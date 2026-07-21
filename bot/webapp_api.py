import hashlib
import hmac
import json
import logging
import os
import urllib.parse
from contextlib import asynccontextmanager
import asyncio

from fastapi import FastAPI, HTTPException, Header, Request, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from fastapi.staticfiles import StaticFiles

from bot.storage import UserStorage, TicketStorage, WithdrawStorage

logger = logging.getLogger(__name__)

# References to global state (will be set in main.py)
_storage: UserStorage | None = None
_tickets: TicketStorage | None = None
_withdrawals: WithdrawStorage | None = None
_payments = None  # type: ignore  # PaymentStorage will be set by main

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


def validate_init_data(init_data: str, bot_token: str) -> dict:
    """Validate Telegram WebApp initData."""
    try:
        parsed = urllib.parse.parse_qsl(init_data)
        data_dict = dict(parsed)
        if 'hash' not in data_dict:
            raise ValueError("No hash provided")
            
        hash_val = data_dict.pop('hash')
        sorted_items = sorted(data_dict.items(), key=lambda x: x[0])
        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted_items)
        
        secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        calc_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        
        if calc_hash != hash_val:
            raise ValueError("Invalid hash")
            
        # Parse user field which is a JSON string
        if 'user' in data_dict:
            data_dict['user'] = json.loads(data_dict['user'])
            
        return data_dict
    except Exception as e:
        logger.warning(f"WebApp auth failed: {e}")
        raise HTTPException(status_code=401, detail="Unauthorized")

def get_current_user(x_tg_init_data: str = Header(..., alias="X-TG-INIT-DATA")):
    bot_token = os.getenv("BOT_TOKEN")
    if not bot_token:
        raise HTTPException(status_code=500, detail="Bot token not configured")
    auth_data = validate_init_data(x_tg_init_data, bot_token)
    user_info = auth_data.get('user')
    if not user_info:
        raise HTTPException(status_code=401, detail="User data missing")
    return user_info


app = FastAPI(title="Quantum WebApp API")

# Mount static files at root
app.mount("/app", StaticFiles(directory="webapp", html=True), name="webapp")


@app.get("/health")
async def health() -> dict:
    return {"ok": True}


# Xrocket webhook endpoint (payment notifications)
from fastapi import Header


def _xrocket_signature(
    rocket_pay_signature: str | None = Header(None, alias="Rocket-Pay-Signature"),
    legacy_signature: str | None = Header(None, alias="X-XROCKET-SIGNATURE"),
) -> str | None:
    return rocket_pay_signature or legacy_signature


async def _process_xrocket_payload(payload: dict, raw_body: bytes, x_sig: str | None) -> dict:
    """Core processing for Xrocket webhook payload. Returns dict with processed flag."""
    try:
        import bot.xrocket_client_prod as xrocket
    except Exception:
        logger.error("xrocket helper not available")
        raise HTTPException(status_code=500, detail="Integration error")

    if not xrocket.verify_webhook_signature(raw_body, x_sig):
        raise HTTPException(status_code=401, detail="Invalid signature")

    logger.info("Received Xrocket webhook: %s", payload)

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

    result = try_complete_payment(payments, storage, invoice_id, external_meta=payload)
    if result:
        schedule_deposit_notification(result)
    return {"ok": True, "processed": bool(result), "invoice_id": invoice_id}


@app.post("/api/xrocket/webhook")
async def xrocket_webhook(request: Request, x_sig: str | None = Depends(_xrocket_signature)):
    """Receive webhook notifications from Xrocket and process payments."""
    body = await request.body()
    try:
        payload = json.loads(body)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    result = await _process_xrocket_payload(payload, body, x_sig)
    return JSONResponse(result)


@app.post("/xrocket/webhook")
async def xrocket_webhook_alt(request: Request, x_sig: str | None = Depends(_xrocket_signature)):
    """Compatibility endpoint for Xrocket webhook at /xrocket/webhook"""
    body = await request.body()
    try:
        payload = json.loads(body)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    result = await _process_xrocket_payload(payload, body, x_sig)
    return JSONResponse(result)


@app.post("/api/internal/create-test-invoice")
async def create_test_invoice(request: Request):
    """Create a test invoice record locally (no external API call) for E2E testing.

    Body JSON: {"user_id": <int>, "amount": <number>}
    Returns the created local invoice record (invoice_id, payment_url).
    """
    body = await request.json()
    user_id = body.get("user_id")
    amount = body.get("amount")
    if not user_id or not amount:
        raise HTTPException(status_code=400, detail="user_id and amount are required")
    try:
        payments = get_payments()
    except HTTPException:
        raise HTTPException(status_code=500, detail="Payments storage not initialized")
    import uuid, time
    # create a unique fractional part
    cents = (int(uuid.uuid4().int % 199) + 1) / 1000.0
    unique_amount = round(float(amount) + cents, 3)
    invoice_id = str(uuid.uuid4())
    payment_url = f"https://example.com/pay/{invoice_id}"
    payments.create_payment(invoice_id=invoice_id, user_id=int(user_id), amount_requested=float(amount), unique_amount=unique_amount, currency="USD", payment_url=payment_url, metadata={"test": True})
    return JSONResponse({"ok": True, "invoice_id": invoice_id, "payment_url": payment_url, "unique_amount": unique_amount})

@app.on_event("startup")
async def _start_payment_poller():
    """Start background polling task to check pending Xrocket invoices periodically.

    This is a fallback when webhooks are not delivered. Interval controlled by XROCKET_POLL_INTERVAL (seconds).
    """
    interval = int(os.getenv("XROCKET_POLL_INTERVAL", "60"))
    enabled = os.getenv("ENABLE_XROCKET_POLL", "true").lower() in ("1", "true", "yes")
    if not enabled:
        logger.info("Xrocket polling disabled via ENABLE_XROCKET_POLL env")
        return

    async def _poll_loop():
        import bot.xrocket_client_prod as xrocket
        from bot.payments_service import (
            invoice_is_paid,
            try_complete_payment,
            schedule_deposit_notification,
        )
        while True:
            try:
                payments = None
                try:
                    payments = get_payments()
                except HTTPException:
                    await asyncio.sleep(1)
                    continue
                pending = payments.get_pending_payments()
                if not pending:
                    await asyncio.sleep(interval)
                    continue
                storage = get_storage()
                for rec in pending:
                    invoice_id = rec.get("invoice_id")
                    try:
                        if not invoice_id:
                            continue
                        info = await xrocket.get_invoice(str(invoice_id))
                        if not invoice_is_paid(info):
                            continue
                        result = try_complete_payment(
                            payments, storage, str(invoice_id), external_meta=info if isinstance(info, dict) else None
                        )
                        if result:
                            schedule_deposit_notification(result)
                    except Exception as e:
                        logger.error("Error polling invoice %s: %s", invoice_id, e, exc_info=True)
                await asyncio.sleep(interval)
            except Exception as e:
                logger.error("Xrocket poller loop failed: %s", e, exc_info=True)
                await asyncio.sleep(interval)

    asyncio.create_task(_poll_loop())


@app.get("/api/me")
async def get_me(user=Depends(get_current_user), storage: UserStorage = Depends(get_storage)):
    uid = user['id']
    record = storage.get_or_create(uid)
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
        "operations_limit": record.operations_limit,
        "is_banned": record.is_banned
    }

@app.get("/api/bundles")
async def get_bundles(user=Depends(get_current_user), storage: UserStorage = Depends(get_storage)):
    uid = user['id']
    record = storage.get_or_create(uid)
    
    from bot.constants import COINS, BUNDLE_CONFIG
    
    # Process active bundles to calculate current profit dynamically
    import time
    active = []
    for b in record.active_bundles:
        elapsed = time.time() - b["start_time"]
        progress = min(1.0, elapsed / b["duration"])
        profit = b["profit"] * progress
        active.append({
            "coin": b["coin"],
            "amount": b["amount"],
            "start_time": b["start_time"],
            "duration": b["duration"],
            "expected_profit": b["profit"],
            "current_profit": profit,
            "progress": progress * 100
        })
        
    return {
        "available_coins": [{"ticker": c[0], "spread": c[1], "config": BUNDLE_CONFIG[c[0]]} for c in COINS],
        "active_bundles": active
    }

class LaunchRequest(BaseModel):
    coin: str
    amount: float

@app.post("/api/bundles/launch")
async def launch_bundle(req: LaunchRequest, user=Depends(get_current_user), storage: UserStorage = Depends(get_storage)):
    uid = user['id']
    record = storage.get_or_create(uid)
    
    from bot.constants import BUNDLE_CONFIG
    if req.coin not in BUNDLE_CONFIG:
        raise HTTPException(status_code=400, detail="Invalid coin")
        
    cfg = BUNDLE_CONFIG[req.coin]
    ex1, ex2, spread_str, min_u, max_u, p_min, p_max, t_min, t_max = cfg
    
    import math
    if math.isnan(req.amount) or math.isinf(req.amount):
        raise HTTPException(status_code=400, detail="Неверная сумма")
        
    if req.amount < min_u or req.amount > max_u:
        raise HTTPException(status_code=400, detail=f"Сумма должна быть от {min_u} до {max_u} USDT")
        
    if record.balance < req.amount:
        raise HTTPException(status_code=400, detail="Недостаточно средств")
        
    if record.operations_done >= record.operations_limit:
        raise HTTPException(status_code=400, detail="Достигнут лимит операций")
        
    limit = record.total_deposited * 3
    total_profit = sum(b.get("profit", 0) for b in record.history)
    if (total_profit >= limit and limit > 0) or limit == 0:
        raise HTTPException(status_code=400, detail="Достигнут лимит прибыли. Пополните баланс.")
        
    import random
    import uuid
    import asyncio
    
    profit_percent = random.uniform(p_min, p_max) / 100.0
    profit = req.amount * profit_percent
    duration = random.randint(t_min, t_max)
    bundle_id = str(uuid.uuid4())
    
    bundle_data = {
        "id": bundle_id,
        "coin": req.coin,
        "ex1": ex1,
        "ex2": ex2,
        "amount": req.amount,
        "spread_str": spread_str,
        "profit": 0,
        "start_time": __import__('time').time(),
        "duration": duration
    }
    
    storage.update_user(uid, balance=record.balance - req.amount)
    storage.add_active_bundle(uid, bundle_data)
    
    import main
    if hasattr(main, "ptb_app"):
        from bot.handlers import _finish_bundle_task
        asyncio.create_task(_finish_bundle_task(
            main.ptb_app, duration, uid, bundle_id, profit
        ))
        
    return {"status": "success"}

@app.get("/api/transactions")
async def get_history(user=Depends(get_current_user), storage: UserStorage = Depends(get_storage)):
    uid = user['id']
    record = storage.get_or_create(uid)
    return {"history": record.history}

@app.get("/api/referrals")
async def get_referrals(user=Depends(get_current_user), storage: UserStorage = Depends(get_storage)):
    uid = user['id']
    record = storage.get_or_create(uid)
    return {
        "referral_count": record.referral_count,
        "referral_bonus": record.referral_bonus,
        "link": storage.get_referral_link(uid)
    }

class SupportRequest(BaseModel):
    message: str

@app.post("/api/support")
async def send_support(req: SupportRequest, user=Depends(get_current_user), storage: UserStorage = Depends(get_storage), tickets: TicketStorage = Depends(get_tickets)):
    uid = user['id']
    import time
    now = time.time()
    
    # Rate limit check (5 min)
    record = storage.get_or_create(uid)
    if record.last_support_time and now - record.last_support_time < 300:
        raise HTTPException(status_code=429, detail="Пожалуйста, подождите 5 минут перед следующим обращением.")
        
    storage.update_support_time(uid, now)
    
    import html
    name = user.get("first_name", "")
    if user.get("last_name"): name += f" {user['last_name']}"
    name = html.escape(name.strip())
    username = html.escape(user.get("username", ""))
    uname_str = f"{name} @{username} ({uid})" if username else f"{name} ({uid})"
    
    ticket_id = tickets.create_ticket(uid, uname_str, req.message)
    
    # Notify admins via ptb_app if available
    import main
    if hasattr(main, "ptb_app"):
        app_ptb = main.ptb_app
        admins = storage.get_all_admins()
        escaped_text = html.escape(req.message)
        msg = (
            f"📩 <b>Новое обращение #{ticket_id} (WebApp)</b>\n"
            f"От: {uname_str}\n\n"
            f"{escaped_text}\n\n"
            f"💡 Откройте /panel для ответа"
        )
        import asyncio
        for admin_id in admins:
            asyncio.create_task(app_ptb.bot.send_message(chat_id=admin_id, text=msg, parse_mode="HTML"))
            
    return {"status": "success", "ticket_id": ticket_id}


class WithdrawRequest(BaseModel):
    amount: float
    address: str

@app.post("/api/withdraw")
async def request_withdraw(req: WithdrawRequest, user=Depends(get_current_user), storage: UserStorage = Depends(get_storage), withdrawals: WithdrawStorage = Depends(get_withdrawals)):
    uid = user['id']
    record = storage.get_or_create(uid)
    
    from bot.storage import WITHDRAW_MIN_AMOUNT
    if req.amount < WITHDRAW_MIN_AMOUNT:
        raise HTTPException(status_code=400, detail=f"Минимальная сумма вывода: {WITHDRAW_MIN_AMOUNT} USDT")
        
    if req.amount > record.balance:
        raise HTTPException(status_code=400, detail="Недостаточно средств")
        
    import html
    name = user.get("first_name", "")
    if user.get("last_name"): name += f" {user['last_name']}"
    name = html.escape(name.strip())
    username = html.escape(user.get("username", ""))
    uname_str = f"{name} @{username} ({uid})" if username else f"{name} ({uid})"
    
    withdraw_id = withdrawals.create_withdrawal(
        user_id=uid,
        username=uname_str,
        amount=req.amount,
        address=req.address
    )
    
    import main
    if hasattr(main, "ptb_app"):
        app_ptb = main.ptb_app
        admins = storage.get_all_admins()
        msg = (
            f"💸 <b>Новая заявка на вывод! (WebApp)</b>\n\n"
            f"Пользователь: {uname_str}\n"
            f"Сумма: <b>{req.amount:.4f} USDT</b>\n\n"
            f"Откройте панель администратора для обработки."
        )
        import asyncio
        for admin_id in admins:
            from telegram import InlineKeyboardMarkup, InlineKeyboardButton
            from bot.constants import CB_ADMIN_PANEL
            markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔧 Админ-панель", callback_data=CB_ADMIN_PANEL)]])
            asyncio.create_task(app_ptb.bot.send_message(chat_id=admin_id, text=msg, parse_mode="HTML", reply_markup=markup))
            
    return {"status": "success", "withdraw_id": withdraw_id}
