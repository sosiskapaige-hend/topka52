import hashlib
import hmac
import json
import logging
import os
import time
import urllib.parse
from collections import defaultdict
import asyncio

from fastapi import FastAPI, HTTPException, Header, Request, Depends
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from fastapi.staticfiles import StaticFiles

from bot.storage import UserStorage, TicketStorage, WithdrawStorage

logger = logging.getLogger(__name__)

# References to global state (set in main.py)
_storage: UserStorage | None = None
_tickets: TicketStorage | None = None
_withdrawals: WithdrawStorage | None = None
_payments = None


def get_storage() -> UserStorage:
    if not _storage:
        raise HTTPException(status_code=500, detail="Storage not initialized")
    return _storage

def get_tickets() -> TicketStorage:
    if not _tickets:
        raise HTTPException(status_code=500, detail="Tickets not initialized")
    return _tickets

def get_withdrawals() -> WithdrawStorage:
    if not _withdrawals:
        raise HTTPException(status_code=500, detail="Withdrawals not initialized")
    return _withdrawals

def get_payments():
    if not _payments:
        raise HTTPException(status_code=500, detail="Payments not initialized")
    return _payments


# ── Auth ──────────────────────────────────────────────────────────────────────

def validate_init_data(init_data: str, bot_token: str) -> dict:
    try:
        parsed = urllib.parse.parse_qsl(init_data, keep_blank_values=True)
        data_dict = dict(parsed)
        if "hash" not in data_dict:
            raise ValueError("No hash")
        hash_val = data_dict.pop("hash")
        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(data_dict.items()))
        secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        calc_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calc_hash, hash_val):
            raise ValueError("Invalid hash")
        if "user" in data_dict:
            data_dict["user"] = json.loads(data_dict["user"])
        return data_dict
    except Exception as e:
        logger.warning("WebApp auth failed: %s", e)
        raise HTTPException(status_code=401, detail="Unauthorized")

def get_current_user(x_tg_init_data: str = Header(..., alias="X-TG-INIT-DATA")):
    bot_token = os.getenv("BOT_TOKEN")
    if not bot_token:
        raise HTTPException(status_code=500, detail="Bot token not configured")
    auth_data = validate_init_data(x_tg_init_data, bot_token)
    user_info = auth_data.get("user")
    if not user_info:
        raise HTTPException(status_code=401, detail="User data missing")
    return user_info


# ── Rate limiting ─────────────────────────────────────────────────────────────

_rate_store: dict[str, list[float]] = defaultdict(list)

def _check_rate(key: str, limit: int, window: int) -> bool:
    now = time.time()
    hits = _rate_store[key]
    _rate_store[key] = [t for t in hits if now - t < window]
    if len(_rate_store[key]) >= limit:
        return False
    _rate_store[key].append(now)
    return True

def _rate_limit(request: Request, limit: int = 60, window: int = 60):
    ip = request.client.host if request.client else "unknown"
    if not _check_rate(f"ip:{ip}", limit, window):
        raise HTTPException(status_code=429, detail="Too many requests")


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="Quantum WebApp API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://web.telegram.org", "https://topka52.onrender.com"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.mount("/app", StaticFiles(directory="webapp", html=True), name="webapp")


@app.get("/health")
async def health() -> dict:
    return {"ok": True}


# ── Xrocket webhook ───────────────────────────────────────────────────────────

def _xrocket_signature(
    rocket_pay_signature: str | None = Header(None, alias="Rocket-Pay-Signature"),
    legacy_signature: str | None = Header(None, alias="X-XROCKET-SIGNATURE"),
) -> str | None:
    return rocket_pay_signature or legacy_signature


async def _process_xrocket_payload(payload: dict, raw_body: bytes, x_sig: str | None) -> dict:
    try:
        import bot.xrocket_client_prod as xrocket
    except Exception:
        raise HTTPException(status_code=500, detail="Integration error")

    if not xrocket.verify_webhook_signature(raw_body, x_sig):
        raise HTTPException(status_code=401, detail="Invalid signature")

    from bot.payments_service import (
        parse_webhook_invoice_id,
        webhook_indicates_paid,
        try_complete_payment,
        schedule_deposit_notification,
    )

    if not webhook_indicates_paid(payload):
        return {"ok": True, "processed": False, "reason": "not_paid_event"}

    payments = get_payments()
    storage = get_storage()
    invoice_id = parse_webhook_invoice_id(payload)
    if not invoice_id:
        return {"ok": True, "processed": False, "reason": "no_invoice_id"}

    result = await try_complete_payment(payments, storage, invoice_id, external_meta=payload)
    if result:
        schedule_deposit_notification(result)
    return {"ok": True, "processed": bool(result), "invoice_id": invoice_id}


@app.post("/api/xrocket/webhook")
async def xrocket_webhook(request: Request, x_sig: str | None = Depends(_xrocket_signature)):
    body = await request.body()
    try:
        payload = json.loads(body)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    return JSONResponse(await _process_xrocket_payload(payload, body, x_sig))


@app.post("/xrocket/webhook")
async def xrocket_webhook_alt(request: Request, x_sig: str | None = Depends(_xrocket_signature)):
    body = await request.body()
    try:
        payload = json.loads(body)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    return JSONResponse(await _process_xrocket_payload(payload, body, x_sig))


# ── Payment poller (startup) ──────────────────────────────────────────────────

@app.on_event("startup")
async def _restore_pending_bundles():
    """Re-schedule finish tasks for bundles that survived a restart."""
    import main as _main

    async def _wait_and_finish():
        # Wait for ptb_app to be ready
        for _ in range(30):
            if getattr(_main, "ptb_app", None):
                break
            await asyncio.sleep(1)

        storage = _storage
        if not storage:
            return

        from bot.handlers import _finish_bundle_task
        now = time.time()
        try:
            pool = await __import__("bot.db", fromlist=["get_pool"]).get_pool()
            async with pool.acquire() as conn:
                rows = await conn.fetch("SELECT telegram_id, active_bundles FROM users WHERE active_bundles != '[]'")
            for row in rows:
                uid = row["telegram_id"]
                bundles = row["active_bundles"] if isinstance(row["active_bundles"], list) else __import__("json").loads(row["active_bundles"])
                for b in bundles:
                    start = b.get("start_time", now)
                    duration = b.get("duration", 60)
                    remaining = max(0, int(start + duration - now))
                    asyncio.create_task(
                        _finish_bundle_task(_main.ptb_app, remaining, uid, b["id"], b.get("profit", 0))
                    )
                    logger.info("Restored bundle %s for user %s, finishes in %ds", b["id"], uid, remaining)
        except Exception as e:
            logger.error("Failed to restore pending bundles: %s", e)

    asyncio.create_task(_wait_and_finish())


@app.on_event("startup")
async def _start_payment_poller():
    interval = int(os.getenv("XROCKET_POLL_INTERVAL", "60"))
    if os.getenv("ENABLE_XROCKET_POLL", "true").lower() not in ("1", "true", "yes"):
        return

    async def _poll_loop():
        import bot.xrocket_client_prod as xrocket
        from bot.payments_service import invoice_is_paid, try_complete_payment, schedule_deposit_notification
        while True:
            try:
                payments = get_payments()
                storage = get_storage()
                pending = await payments.get_pending_payments()
                for rec in pending:
                    invoice_id = rec.get("invoice_id")
                    if not invoice_id:
                        continue
                    try:
                        info = await xrocket.get_invoice(str(invoice_id))
                        if not invoice_is_paid(info):
                            continue
                        result = await try_complete_payment(
                            payments, storage, str(invoice_id),
                            external_meta=info if isinstance(info, dict) else None,
                        )
                        if result:
                            schedule_deposit_notification(result)
                    except Exception as e:
                        logger.error("Poller error for invoice %s: %s", invoice_id, e)
            except Exception as e:
                logger.error("Xrocket poller loop failed: %s", e)
            await asyncio.sleep(interval)

    asyncio.create_task(_poll_loop())


# ── API endpoints ─────────────────────────────────────────────────────────────

@app.get("/api/me")
async def get_me(
    request: Request,
    user=Depends(get_current_user),
    storage: UserStorage = Depends(get_storage),
):
    _rate_limit(request, limit=60, window=60)
    uid = user["id"]
    record = await storage.get_or_create(uid)
    from bot.constants import (
        DEPOSIT_COMMISSION, DEPOSIT_COMMISSION_PLUS,
        WITHDRAW_COMMISSION, PLUS_OPERATIONS_LIMIT, OPERATIONS_LIMIT,
    )
    commission = DEPOSIT_COMMISSION_PLUS if record.subscription_active else DEPOSIT_COMMISSION
    ops_limit = PLUS_OPERATIONS_LIMIT if record.subscription_active else (record.operations_limit or OPERATIONS_LIMIT)
    return {
        "telegram_id": uid,
        "system_id": record.system_id,
        "first_name": user.get("first_name", ""),
        "last_name": user.get("last_name", ""),
        "username": user.get("username", ""),
        "balance": record.balance,
        "is_admin": record.is_admin,
        "subscription_active": record.subscription_active,
        "subscription_expiry": record.subscription_expiry,
        "operations_done": record.operations_done,
        "operations_limit": ops_limit,
        "is_banned": record.is_banned,
        "deposit_commission": commission,
        "withdraw_commission": WITHDRAW_COMMISSION,
    }


@app.get("/api/bundles")
async def get_bundles(
    request: Request,
    user=Depends(get_current_user),
    storage: UserStorage = Depends(get_storage),
):
    _rate_limit(request, limit=60, window=60)
    uid = user["id"]
    record = await storage.get_or_create(uid)
    from bot.constants import COINS, BUNDLE_CONFIG

    now = time.time()
    active = []
    for b in record.active_bundles:
        start = b.get("start_time", now)
        duration = b.get("duration", 1) or 1
        elapsed = now - start
        progress = min(1.0, elapsed / duration)
        expected = b.get("profit", 0)
        active.append({
            "id": b.get("id", ""),
            "coin": b.get("coin", ""),
            "amount": b.get("amount", 0),
            "start_time": start,
            "duration": duration,
            "expected_profit": expected,
            "current_profit": round(expected * progress, 6),
            "progress": round(progress * 100, 1),
        })

    return {
        "available_coins": [
            {"ticker": c[0], "spread": c[1], "config": BUNDLE_CONFIG[c[0]]}
            for c in COINS
        ],
        "active_bundles": active,
    }


class LaunchRequest(BaseModel):
    coin: str
    amount: float


@app.post("/api/bundles/launch")
async def launch_bundle(
    request: Request,
    req: LaunchRequest,
    user=Depends(get_current_user),
    storage: UserStorage = Depends(get_storage),
):
    _rate_limit(request, limit=10, window=60)
    uid = user["id"]
    record = await storage.get_or_create(uid)

    from bot.constants import BUNDLE_CONFIG, PLUS_OPERATIONS_LIMIT, OPERATIONS_LIMIT
    import math, random, uuid

    if req.coin not in BUNDLE_CONFIG:
        raise HTTPException(status_code=400, detail="Invalid coin")

    ex1, ex2, spread_str, min_u, max_u, p_min, p_max, t_min, t_max = BUNDLE_CONFIG[req.coin]

    if math.isnan(req.amount) or math.isinf(req.amount):
        raise HTTPException(status_code=400, detail="Неверная сумма")
    if req.amount < min_u or req.amount > max_u:
        raise HTTPException(status_code=400, detail=f"Сумма должна быть от {min_u} до {max_u} USDT")
    if record.balance < req.amount:
        raise HTTPException(status_code=400, detail="Недостаточно средств")

    ops_limit = PLUS_OPERATIONS_LIMIT if record.subscription_active else (record.operations_limit or OPERATIONS_LIMIT)
    if record.operations_done >= ops_limit:
        raise HTTPException(status_code=400, detail="Достигнут лимит операций")

    profit = round(req.amount * random.uniform(p_min, p_max) / 100.0, 6)
    duration = random.randint(t_min, t_max)
    bundle_id = str(uuid.uuid4())

    bundle_data = {
        "id": bundle_id,
        "coin": req.coin,
        "ex1": ex1,
        "ex2": ex2,
        "amount": req.amount,
        "spread_str": spread_str,
        "profit": profit,
        "start_time": time.time(),
        "duration": duration,
    }

    await storage.update_user(uid, balance=record.balance - req.amount)
    await storage.add_active_bundle(uid, bundle_data)

    import main
    if hasattr(main, "ptb_app"):
        from bot.handlers import _finish_bundle_task
        asyncio.create_task(_finish_bundle_task(main.ptb_app, duration, uid, bundle_id, profit))

    return {"status": "success"}


@app.get("/api/transactions")
async def get_history(
    request: Request,
    user=Depends(get_current_user),
    storage: UserStorage = Depends(get_storage),
):
    _rate_limit(request, limit=30, window=60)
    uid = user["id"]
    record = await storage.get_or_create(uid)
    return {"history": record.history}


@app.get("/api/referrals")
async def get_referrals(
    request: Request,
    user=Depends(get_current_user),
    storage: UserStorage = Depends(get_storage),
):
    _rate_limit(request, limit=20, window=60)
    uid = user["id"]
    record = await storage.get_or_create(uid)
    return {
        "referral_count": record.referral_count,
        "referral_bonus": record.referral_bonus,
        "link": await storage.get_referral_link(uid),
    }


class SupportRequest(BaseModel):
    message: str


@app.post("/api/support")
async def send_support(
    request: Request,
    req: SupportRequest,
    user=Depends(get_current_user),
    storage: UserStorage = Depends(get_storage),
    tickets: TicketStorage = Depends(get_tickets),
):
    # Per-user rate limit: 1 message per 5 minutes (not IP-based)
    uid = user["id"]
    if not _check_rate(f"support:{uid}", 1, 300):
        raise HTTPException(status_code=429, detail="Пожалуйста, подождите 5 минут перед следующим обращением.")

    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Сообщение не может быть пустым")

    record = await storage.get_or_create(uid)
    now = time.time()
    await storage.update_support_time(uid, now)

    import html
    name = user.get("first_name", "")
    if user.get("last_name"):
        name += f" {user['last_name']}"
    name = html.escape(name.strip())
    username = html.escape(user.get("username", ""))
    uname_str = f"{name} @{username} ({uid})" if username else f"{name} ({uid})"

    ticket_id = await tickets.create_ticket(uid, uname_str, req.message)

    import main
    if hasattr(main, "ptb_app") and main.ptb_app:
        try:
            admins = await storage.get_all_admins()
            escaped_text = html.escape(req.message)
            msg = (
                f"📩 <b>Новое обращение #{ticket_id} (WebApp)</b>\n"
                f"От: {uname_str}\n\n"
                f"{escaped_text}\n\n"
                f"💡 Откройте /panel для ответа"
            )
            for admin_id in admins:
                asyncio.create_task(
                    main.ptb_app.bot.send_message(chat_id=admin_id, text=msg, parse_mode="HTML")
                )
        except Exception as e:
            logger.error("Failed to notify admins about ticket %s: %s", ticket_id, e)

    return {"status": "success", "ticket_id": ticket_id}


class WithdrawRequest(BaseModel):
    amount: float
    address: str


class DepositRequest(BaseModel):
    amount: float


@app.post("/api/deposit/create")
async def create_deposit(
    request: Request,
    req: DepositRequest,
    user=Depends(get_current_user),
    storage: UserStorage = Depends(get_storage),
):
    _rate_limit(request, limit=5, window=60)
    uid = user["id"]
    if req.amount < 1:
        raise HTTPException(status_code=400, detail="Минимальная сумма: 1 USDT")

    record = await storage.get_or_create(uid)
    from bot.constants import DEPOSIT_COMMISSION, DEPOSIT_COMMISSION_PLUS
    commission = DEPOSIT_COMMISSION_PLUS if record.subscription_active else DEPOSIT_COMMISSION
    credited = round(req.amount * (1 - commission), 4)

    try:
        import bot.xrocket_client_prod as xrocket
        from bot.payments_service import extract_invoice_from_create_response
        import json as _json

        payments = get_payments()
        rnd = int.from_bytes(os.urandom(2), "big")
        unique_amount = round(req.amount + (rnd % 199 + 1) / 1000.0, 3)

        payload_meta = _json.dumps(
            {"user_id": uid, "system_id": record.system_id, "amount_requested": req.amount},
            ensure_ascii=False,
        )
        resp = await xrocket.create_invoice(
            unique_amount,
            description=f"Пополнение {req.amount} USDT",
            payload=payload_meta,
            num_payments=1,
        )
        invoice_id, pay_url = extract_invoice_from_create_response(resp)
        if not invoice_id:
            raise RuntimeError("No invoice id from xrocket")

        await payments.create_payment(
            invoice_id=invoice_id,
            user_id=uid,
            amount_requested=req.amount,
            unique_amount=unique_amount,
            currency="USDT",
            payment_url=pay_url,
            metadata={"user_id": uid, "system_id": record.system_id, "amount_requested": req.amount},
        )
        return {
            "ok": True,
            "invoice_id": invoice_id,
            "pay_url": pay_url,
            "amount": unique_amount,
            "credited": credited,
            "commission_pct": int(commission * 100),
        }
    except Exception as e:
        logger.error("Failed to create deposit invoice: %s", e)
        raise HTTPException(status_code=500, detail="Не удалось создать счёт")


@app.post("/api/plus/buy")
async def buy_plus(
    request: Request,
    user=Depends(get_current_user),
    storage: UserStorage = Depends(get_storage),
):
    _rate_limit(request, limit=3, window=60)
    uid = user["id"]
    record = await storage.get_or_create(uid)
    if record.subscription_active:
        raise HTTPException(status_code=400, detail="Подписка уже активна")

    try:
        import bot.xrocket_client_prod as xrocket
        from bot.payments_service import extract_invoice_from_create_response
        from bot.constants import PLUS_SUBSCRIPTION_PRICE
        import json as _json

        payments = get_payments()
        rnd = int.from_bytes(os.urandom(2), "big")
        unique_amount = round(PLUS_SUBSCRIPTION_PRICE + (rnd % 199 + 1) / 1000.0, 3)

        payload_meta = _json.dumps(
            {"user_id": uid, "system_id": record.system_id, "type": "plus_subscription"},
            ensure_ascii=False,
        )
        resp = await xrocket.create_invoice(
            unique_amount,
            description="Quantum+ подписка 30 дней",
            payload=payload_meta,
            num_payments=1,
        )
        invoice_id, pay_url = extract_invoice_from_create_response(resp)
        if not invoice_id:
            raise RuntimeError("No invoice id")

        await payments.create_payment(
            invoice_id=invoice_id,
            user_id=uid,
            amount_requested=PLUS_SUBSCRIPTION_PRICE,
            unique_amount=unique_amount,
            currency="USDT",
            payment_url=pay_url,
            metadata={"user_id": uid, "type": "plus_subscription"},
        )
        return {"ok": True, "invoice_id": invoice_id, "pay_url": pay_url, "amount": unique_amount}
    except Exception as e:
        logger.error("Failed to create plus invoice: %s", e)
        raise HTTPException(status_code=500, detail="Не удалось создать счёт")


@app.post("/api/withdraw")
async def request_withdraw(
    request: Request,
    req: WithdrawRequest,
    user=Depends(get_current_user),
    storage: UserStorage = Depends(get_storage),
    withdrawals: WithdrawStorage = Depends(get_withdrawals),
):
    _rate_limit(request, limit=5, window=60)
    uid = user["id"]
    record = await storage.get_or_create(uid)

    from bot.storage import WITHDRAW_MIN_AMOUNT
    from bot.constants import WITHDRAW_COMMISSION

    if req.amount < WITHDRAW_MIN_AMOUNT:
        raise HTTPException(status_code=400, detail=f"Минимальная сумма вывода: {WITHDRAW_MIN_AMOUNT} USDT")
    if req.amount > record.balance:
        raise HTTPException(status_code=400, detail="Недостаточно средств")
    if len(req.address) < 10:
        raise HTTPException(status_code=400, detail="Неверный адрес кошелька")

    net_amount = round(req.amount * (1 - WITHDRAW_COMMISSION), 4)
    await storage.update_user(uid, balance=record.balance - req.amount)

    import html
    name = user.get("first_name", "")
    if user.get("last_name"):
        name += f" {user['last_name']}"
    name = html.escape(name.strip())
    username = html.escape(user.get("username", ""))
    uname_str = f"{name} @{username} ({uid})" if username else f"{name} ({uid})"

    withdraw_id = await withdrawals.create_withdrawal(
        user_id=uid,
        username=uname_str,
        amount=net_amount,
        address=req.address,
    )

    import main
    if hasattr(main, "ptb_app"):
        admins = await storage.get_all_admins()
        msg = (
            f"💸 <b>Новая заявка на вывод! (WebApp)</b>\n\n"
            f"Пользователь: {uname_str}\n"
            f"Списано: <b>{req.amount:.4f} USDT</b>\n"
            f"К выплате: <b>{net_amount:.4f} USDT</b>\n\n"
            f"Откройте панель администратора для обработки."
        )
        from telegram import InlineKeyboardMarkup, InlineKeyboardButton
        from bot.constants import CB_ADMIN_PANEL
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔧 Админ-панель", callback_data=CB_ADMIN_PANEL)]])
        for admin_id in admins:
            asyncio.create_task(
                main.ptb_app.bot.send_message(chat_id=admin_id, text=msg, parse_mode="HTML", reply_markup=markup)
            )

    return {"status": "success", "withdraw_id": withdraw_id, "net_amount": net_amount}
