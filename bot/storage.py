"""Async PostgreSQL-backed storage (Neon via asyncpg).

Public API is identical to the old JSON-based storage so handlers need
minimal changes — just add `await` before every storage call.
"""
from __future__ import annotations

import json
import logging
import secrets
import string
import time
from dataclasses import dataclass, field

from bot.db import get_pool

logger = logging.getLogger(__name__)

WITHDRAW_MIN_AMOUNT = 30.0

# ── helpers ───────────────────────────────────────────────────────────────────

_ID_CHARS = string.ascii_uppercase + string.digits


def _gen_id(length: int = 5) -> str:
    return "".join(secrets.choice(_ID_CHARS) for _ in range(length))


# ── UserRecord dataclass (in-memory view) ─────────────────────────────────────

@dataclass
class UserRecord:
    telegram_id: int
    system_id: str
    balance: float = 0.0
    total_deposited: float = 0.0
    operations_done: int = 0
    operations_limit: int = 100
    subscription_active: bool = False
    subscription_expiry: str | None = None
    referral_count: int = 0
    referral_bonus: float = 0.0
    referred_by: str | None = None
    active_bundles: list[dict] = field(default_factory=list)
    history: list[dict] = field(default_factory=list)
    is_admin: bool = False
    is_banned: bool = False
    last_support_time: float = 0.0
    pending_referrer: str | None = None
    referral_qualified: bool = False


def _row_to_user(row) -> UserRecord:
    return UserRecord(
        telegram_id=row["telegram_id"],
        system_id=row["system_id"],
        balance=row["balance"],
        total_deposited=row["total_deposited"],
        operations_done=row["operations_done"],
        operations_limit=row["operations_limit"],
        subscription_active=row["subscription_active"],
        subscription_expiry=row["subscription_expiry"],
        referral_count=row["referral_count"],
        referral_bonus=row["referral_bonus"],
        referred_by=row["referred_by"],
        active_bundles=json.loads(row["active_bundles"]) if isinstance(row["active_bundles"], str) else (row["active_bundles"] or []),
        history=json.loads(row["history"]) if isinstance(row["history"], str) else (row["history"] or []),
        is_admin=row["is_admin"],
        is_banned=row["is_banned"],
        last_support_time=row["last_support_time"] or 0.0,
        pending_referrer=row["pending_referrer"],
        referral_qualified=row["referral_qualified"],
    )


# ── UserStorage ───────────────────────────────────────────────────────────────

class UserStorage:
    def __init__(self, bot_name: str | None = None) -> None:
        self._bot_name = bot_name or "QuantumARBcrypto_bot"

    async def get_or_create(self, telegram_id: int) -> UserRecord:
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM users WHERE telegram_id=$1", telegram_id)
            if row:
                return _row_to_user(row)
            # Generate unique system_id
            while True:
                sid = _gen_id()
                exists = await conn.fetchval("SELECT 1 FROM users WHERE system_id=$1", sid)
                if not exists:
                    break
            row = await conn.fetchrow(
                """INSERT INTO users (telegram_id, system_id) VALUES ($1, $2)
                   ON CONFLICT (telegram_id) DO UPDATE SET telegram_id=EXCLUDED.telegram_id
                   RETURNING *""",
                telegram_id, sid,
            )
            return _row_to_user(row)

    async def get_referral_link(self, telegram_id: int) -> str:
        record = await self.get_or_create(telegram_id)
        return f"https://t.me/{self._bot_name}?start=ref_{record.system_id}"

    async def register_referral_new_only(self, new_telegram_id: int, referrer_system_id: str) -> bool:
        """Register referral only if user doesn't exist yet (first-time /start via ref link)."""
        pool = await get_pool()
        async with pool.acquire() as conn:
            exists = await conn.fetchval("SELECT 1 FROM users WHERE telegram_id=$1", new_telegram_id)
            if exists:
                return False  # user already started bot before — don't credit
            referrer = await conn.fetchrow(
                "SELECT telegram_id FROM users WHERE system_id=$1 AND telegram_id!=$2",
                referrer_system_id, new_telegram_id,
            )
            if not referrer:
                return False
            # Create user with pending_referrer set atomically
            while True:
                sid = _gen_id()
                sid_exists = await conn.fetchval("SELECT 1 FROM users WHERE system_id=$1", sid)
                if not sid_exists:
                    break
            await conn.execute(
                """INSERT INTO users (telegram_id, system_id, pending_referrer)
                   VALUES ($1, $2, $3)
                   ON CONFLICT (telegram_id) DO NOTHING""",
                new_telegram_id, sid, referrer_system_id,
            )
            return True

    async def register_referral(self, new_telegram_id: int, referrer_system_id: str) -> bool:
        pool = await get_pool()
        async with pool.acquire() as conn:
            user = await conn.fetchrow("SELECT * FROM users WHERE telegram_id=$1", new_telegram_id)
            if not user or user["referral_qualified"] or user["referred_by"]:
                return False
            referrer = await conn.fetchrow(
                "SELECT telegram_id FROM users WHERE system_id=$1 AND telegram_id!=$2",
                referrer_system_id, new_telegram_id,
            )
            if not referrer:
                return False
            await conn.execute(
                "UPDATE users SET pending_referrer=$1 WHERE telegram_id=$2",
                referrer_system_id, new_telegram_id,
            )
            return True

    async def force_credit_referral(self, new_telegram_id: int, referrer_system_id: str) -> bool:
        """Admin-triggered: set pending_referrer and immediately credit bonus."""
        pool = await get_pool()
        async with pool.acquire() as conn:
            user = await conn.fetchrow("SELECT * FROM users WHERE telegram_id=$1", new_telegram_id)
            if not user or user["referral_qualified"]:
                return False
            referrer = await conn.fetchrow(
                "SELECT * FROM users WHERE system_id=$1 AND telegram_id!=$2",
                referrer_system_id, new_telegram_id,
            )
            if not referrer:
                return False
            await conn.execute(
                "UPDATE users SET pending_referrer=$1 WHERE telegram_id=$2",
                referrer_system_id, new_telegram_id,
            )
        return await self.credit_referral(new_telegram_id)

    async def credit_referral(self, new_telegram_id: int, deposit_amount: float | None = None) -> bool:
        from bot.constants import REFERRAL_COMMISSION
        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                user = await conn.fetchrow("SELECT * FROM users WHERE telegram_id=$1", new_telegram_id)
                if not user or not user["pending_referrer"]:
                    return False
                referrer = await conn.fetchrow(
                    "SELECT * FROM users WHERE system_id=$1", user["pending_referrer"]
                )
                if not referrer:
                    return False
                bonus = round((deposit_amount if deposit_amount is not None else user["total_deposited"]) * REFERRAL_COMMISSION, 4)
                await conn.execute(
                    """UPDATE users SET referral_count=referral_count+1,
                       referral_bonus=referral_bonus+$1, balance=balance+$1
                       WHERE telegram_id=$2""",
                    bonus, referrer["telegram_id"],
                )
                # Add referral bonus to referrer's history
                import time as _time
                history = referrer["history"] if isinstance(referrer["history"], list) else json.loads(referrer["history"] or "[]")
                history.append({
                    "type": "referral_bonus",
                    "amount": bonus,
                    "from_user": new_telegram_id,
                    "time": _time.time(),
                })
                await conn.execute(
                    "UPDATE users SET history=$1 WHERE telegram_id=$2",
                    json.dumps(history), referrer["telegram_id"],
                )
                # On first deposit: mark qualified and set referred_by, but KEEP pending_referrer
                # so future deposits also trigger the bonus
                if not user["referral_qualified"]:
                    await conn.execute(
                        """UPDATE users SET referred_by=$1, referral_qualified=TRUE
                           WHERE telegram_id=$2""",
                        user["pending_referrer"], new_telegram_id,
                    )
                return True

    async def ensure_first_admin(self, admin_id: int = 5710686998) -> None:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO users (telegram_id, system_id, is_admin)
                   VALUES ($1, $2, TRUE)
                   ON CONFLICT (telegram_id) DO UPDATE SET is_admin=TRUE""",
                admin_id, _gen_id(),
            )

    async def get_all_admins(self) -> list[int]:
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT telegram_id FROM users WHERE is_admin=TRUE")
            return [r["telegram_id"] for r in rows]

    async def set_admin(self, telegram_id: int, is_admin: bool) -> bool:
        pool = await get_pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE users SET is_admin=$1 WHERE telegram_id=$2", is_admin, telegram_id
            )
            return result != "UPDATE 0"

    async def set_banned(self, telegram_id: int, is_banned: bool) -> bool:
        pool = await get_pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE users SET is_banned=$1 WHERE telegram_id=$2", is_banned, telegram_id
            )
            return result != "UPDATE 0"

    async def update_support_time(self, telegram_id: int, timestamp: float) -> None:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE users SET last_support_time=$1 WHERE telegram_id=$2", timestamp, telegram_id
            )

    async def get_all_users(self) -> list[int]:
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT telegram_id FROM users")
            return [r["telegram_id"] for r in rows]

    async def update_user(self, telegram_id: int, **kwargs) -> UserRecord:
        if not kwargs:
            return await self.get_or_create(telegram_id)
        pool = await get_pool()
        # Build SET clause
        allowed = {
            "balance", "total_deposited", "operations_done", "operations_limit",
            "subscription_active", "subscription_expiry", "referral_count",
            "referral_bonus", "referred_by", "is_admin", "is_banned",
            "last_support_time", "pending_referrer", "referral_qualified",
        }
        sets, vals = [], []
        for k, v in kwargs.items():
            if k in allowed:
                sets.append(f"{k}=${len(vals)+1}")
                vals.append(v)
        if not sets:
            return await self.get_or_create(telegram_id)
        vals.append(telegram_id)
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                f"UPDATE users SET {', '.join(sets)} WHERE telegram_id=${len(vals)} RETURNING *",
                *vals,
            )
            return _row_to_user(row)

    async def add_active_bundle(self, telegram_id: int, bundle_data: dict) -> None:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """UPDATE users SET active_bundles = active_bundles || $1::jsonb
                   WHERE telegram_id=$2""",
                json.dumps([bundle_data]), telegram_id,
            )

    async def complete_bundle(self, telegram_id: int, bundle_id: str, profit: float) -> dict | None:
        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow("SELECT * FROM users WHERE telegram_id=$1 FOR UPDATE", telegram_id)
                if not row:
                    return None
                bundles = json.loads(row["active_bundles"]) if isinstance(row["active_bundles"], str) else (row["active_bundles"] or [])
                bundle = next((b for b in bundles if b.get("id") == bundle_id), None)
                if not bundle:
                    return None
                bundle["profit"] = profit
                new_active = [b for b in bundles if b.get("id") != bundle_id]
                history = json.loads(row["history"]) if isinstance(row["history"], str) else (row["history"] or [])
                history.append(bundle)
                await conn.execute(
                    """UPDATE users SET active_bundles=$1, history=$2,
                       balance=balance+$3, operations_done=operations_done+1
                       WHERE telegram_id=$4""",
                    json.dumps(new_active), json.dumps(history),
                    bundle["amount"] + profit, telegram_id,
                )
                return bundle

    async def process_deposit(self, telegram_id: int, amount: float) -> tuple[UserRecord, bool]:
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """UPDATE users SET balance=balance+$1, total_deposited=total_deposited+$1,
                   operations_done=0
                   WHERE telegram_id=$2 RETURNING *""",
                amount, telegram_id,
            )
            record = _row_to_user(row)
        qualified = False
        if record.pending_referrer:
            qualified = await self.credit_referral(telegram_id, deposit_amount=amount)
        return record, qualified

    async def append_deposit_history(self, telegram_id: int, entry: dict) -> None:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE users SET history = history || $1::jsonb WHERE telegram_id=$2",
                json.dumps([entry]), telegram_id,
            )


# ── TicketStorage ─────────────────────────────────────────────────────────────

class TicketStorage:
    async def create_ticket(self, user_id: int, username: str, message: str) -> str:
        pool = await get_pool()
        async with pool.acquire() as conn:
            while True:
                tid = _gen_id()
                exists = await conn.fetchval("SELECT 1 FROM tickets WHERE ticket_id=$1", tid)
                if not exists:
                    break
            await conn.execute(
                "INSERT INTO tickets (ticket_id, user_id, username, message) VALUES ($1,$2,$3,$4)",
                tid, user_id, username, message,
            )
            return tid

    async def get_open_tickets(self) -> list[dict]:
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM tickets WHERE status='open'")
            return [dict(r) for r in rows]

    async def close_ticket(self, ticket_id: str) -> dict | None:
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "UPDATE tickets SET status='closed' WHERE ticket_id=$1 RETURNING *", ticket_id
            )
            return dict(row) if row else None

    async def get_ticket(self, ticket_id: str) -> dict | None:
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM tickets WHERE ticket_id=$1", ticket_id)
            return dict(row) if row else None


# ── PaymentStorage ────────────────────────────────────────────────────────────

class PaymentStorage:
    async def create_payment(
        self,
        invoice_id: str,
        user_id: int,
        amount_requested: float,
        unique_amount: float,
        currency: str = "USDT",
        payment_url: str | None = None,
        metadata: dict | None = None,
        created_at: float | None = None,
    ) -> dict:
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO payments
                   (invoice_id, user_id, amount_requested, unique_amount, currency,
                    payment_url, metadata, created_at)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8) RETURNING *""",
                invoice_id, user_id, float(amount_requested), float(unique_amount),
                currency, payment_url,
                json.dumps(metadata) if metadata else None,
                created_at or time.time(),
            )
            return dict(row)

    async def get_payment(self, invoice_id: str) -> dict | None:
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM payments WHERE invoice_id=$1", invoice_id)
            return dict(row) if row else None

    async def acquire_for_crediting(
        self,
        invoice_id: str,
        paid_at: float | None = None,
        external_meta: dict | None = None,
    ) -> dict | None:
        """Atomically mark invoice as processed. Returns record or None if already processed."""
        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    "SELECT * FROM payments WHERE invoice_id=$1 FOR UPDATE", invoice_id
                )
                if not row or row["processed"]:
                    return None
                row = await conn.fetchrow(
                    """UPDATE payments SET processed=TRUE, status='paid', paid_at=$1,
                       external_meta=$2 WHERE invoice_id=$3 RETURNING *""",
                    paid_at or time.time(),
                    json.dumps(external_meta) if external_meta else None,
                    invoice_id,
                )
                return dict(row)

    async def release_crediting(self, invoice_id: str) -> None:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE payments SET processed=FALSE, status='pending', paid_at=NULL WHERE invoice_id=$1",
                invoice_id,
            )

    async def get_pending_payments(self) -> list[dict]:
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM payments WHERE status='pending' AND processed=FALSE"
            )
            return [dict(r) for r in rows]

    async def find_by_unique_amount(self, unique_amount: float, currency: str = "USDT") -> list[dict]:
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM payments WHERE unique_amount=$1 AND currency=$2",
                unique_amount, currency,
            )
            return [dict(r) for r in rows]


# ── WithdrawStorage ───────────────────────────────────────────────────────────

class WithdrawStorage:
    async def create_withdrawal(
        self,
        user_id: int,
        username: str,
        amount: float,
        address: str,
        amount_requested: float | None = None,
    ) -> str:
        pool = await get_pool()
        async with pool.acquire() as conn:
            while True:
                wid = _gen_id()
                exists = await conn.fetchval("SELECT 1 FROM withdrawals WHERE withdraw_id=$1", wid)
                if not exists:
                    break
            await conn.execute(
                "INSERT INTO withdrawals (withdraw_id, user_id, username, amount, amount_requested, address) VALUES ($1,$2,$3,$4,$5,$6)",
                wid, user_id, username, amount, amount_requested if amount_requested is not None else amount, address,
            )
            return wid

    async def get_pending_withdrawals(self) -> list[dict]:
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM withdrawals WHERE status='pending'")
            return [dict(r) for r in rows]

    async def get_withdrawal(self, withdraw_id: str) -> dict | None:
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM withdrawals WHERE withdraw_id=$1", withdraw_id)
            return dict(row) if row else None

    async def approve_withdrawal(self, withdraw_id: str) -> dict | None:
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "UPDATE withdrawals SET status='approved' WHERE withdraw_id=$1 AND status='pending' RETURNING *",
                withdraw_id,
            )
            return dict(row) if row else None

    async def reject_withdrawal(self, withdraw_id: str, reason: str) -> dict | None:
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "UPDATE withdrawals SET status='rejected', reject_reason=$1 WHERE withdraw_id=$2 AND status='pending' RETURNING *",
                reason, withdraw_id,
            )
            return dict(row) if row else None

