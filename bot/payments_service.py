"""Xrocket payment completion: idempotent balance credit and user notification."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from bot.storage import PaymentStorage, UserStorage

logger = logging.getLogger(__name__)

PAID_STATUSES = frozenset({"paid", "completed", "success"})


def unwrap_xrocket_data(resp: dict | None) -> dict | None:
    if not resp or not isinstance(resp, dict):
        return None
    if resp.get("success") is True and isinstance(resp.get("data"), dict):
        return resp["data"]
    return resp


def extract_invoice_from_create_response(resp: dict | None) -> tuple[str | None, str | None]:
    inv = unwrap_xrocket_data(resp) or resp
    if not isinstance(inv, dict):
        return None, None
    raw_id = inv.get("id")
    invoice_id = str(raw_id) if raw_id is not None else None
    pay_url = inv.get("link") or inv.get("payment_url") or inv.get("pay_url")
    return invoice_id, pay_url


def invoice_is_paid(info: dict | None) -> bool:
    inv = unwrap_xrocket_data(info) or info
    if not isinstance(inv, dict):
        return False
    status = inv.get("status")
    if status and str(status).lower() in PAID_STATUSES:
        return True
    paid_at = inv.get("paid")
    return paid_at not in (None, "", False)


def parse_webhook_invoice_id(payload: dict) -> str | None:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    if not isinstance(data, dict):
        data = payload
    raw_id = (
        data.get("id")
        or payload.get("invoice_id")
        or payload.get("id")
        or (payload.get("payload") or {}).get("invoiceId")
    )
    if raw_id is None:
        return None
    return str(raw_id)


def webhook_indicates_paid(payload: dict) -> bool:
    event_type = str(payload.get("type") or payload.get("event") or "").lower()
    if event_type in ("invoicepay", "invoice.paid", "invoice_paid"):
        return True
    data = payload.get("data")
    if isinstance(data, dict):
        st = data.get("status")
        if st and str(st).lower() in PAID_STATUSES:
            return True
        if data.get("paid"):
            return True
        payment = data.get("payment")
        if isinstance(payment, dict) and payment.get("paid"):
            return True
    status = payload.get("status")
    return bool(status and str(status).lower() in PAID_STATUSES)


def _deposit_history_entry(invoice_id: str, amount: float, currency: str) -> dict:
    import time

    return {
        "type": "deposit",
        "invoice_id": invoice_id,
        "amount": amount,
        "currency": currency,
        "time": time.time(),
    }


def try_complete_payment(
    payments: PaymentStorage,
    storage: UserStorage,
    invoice_id: str,
    external_meta: dict | Any | None = None,
) -> dict | None:
    """Credit user balance once for invoice_id. Returns summary dict or None if skipped."""
    meta = external_meta if isinstance(external_meta, dict) else None
    rec = payments.acquire_for_crediting(invoice_id, external_meta=meta)
    if not rec:
        return None

    user_id = int(rec["user_id"])
    amt = float(rec.get("amount_requested", 0.0))
    currency = rec.get("currency") or "USDT"

    try:
        record, _referral = storage.process_deposit(user_id, amt)
        storage.append_deposit_history(user_id, _deposit_history_entry(invoice_id, amt, currency))
    except Exception:
        payments.release_crediting(invoice_id)
        raise

    return {
        "user_id": user_id,
        "amount": amt,
        "currency": currency,
        "balance": record.balance,
        "invoice_id": invoice_id,
    }


async def notify_deposit_success(result: dict) -> None:
    if not result:
        return
    text = (
        f"✅ <b>Баланс пополнен!</b>\n\n"
        f"Зачислено: <b>+{result['amount']:.2f} {result['currency']}</b>\n"
        f"Текущий баланс: <b>{result['balance']:.4f} {result['currency']}</b>"
    )
    from telegram import InlineKeyboardMarkup, InlineKeyboardButton
    from bot.constants import CB_WALLET
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("💼 Кошелёк", callback_data=CB_WALLET)]])
    try:
        import main
        if hasattr(main, "ptb_app") and main.ptb_app:
            await main.ptb_app.bot.send_message(
                chat_id=result["user_id"],
                text=text,
                parse_mode="HTML",
                reply_markup=keyboard,
            )
    except Exception as e:
        logger.error("Failed to notify user %s about deposit: %s", result.get("user_id"), e)


def schedule_deposit_notification(result: dict | None) -> None:
    if not result:
        return
    try:
        asyncio.get_running_loop().create_task(notify_deposit_success(result))
    except RuntimeError:
        asyncio.run(notify_deposit_success(result))
