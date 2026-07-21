from __future__ import annotations

import json
import logging
import secrets
import string
import threading
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_FILE = DATA_DIR / "users.json"

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
    pending_referrer: str | None = None     # system_id of referrer waiting to be credited
    referral_qualified: bool = False        # True once user deposited 10+ USDT


def _generate_system_id(length: int = 5) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


class UserStorage:
    def __init__(self, path: Path = DATA_FILE, bot_name: str | None = None) -> None:
        self._path = path
        self._users: dict[int, UserRecord] = {}
        self._lock = threading.RLock()
        self._bot_name = bot_name or "quantumcryptobot"
        self._dirty = False
        self._load()
        
        # Start background save loop
        self._save_thread = threading.Thread(target=self._flush_loop, daemon=True)
        self._save_thread.start()

    def _flush_loop(self):
        import time
        while True:
            time.sleep(5)
            if self._dirty:
                with self._lock:
                    if self._dirty:
                        self._perform_save()
                        self._dirty = False

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            content = self._path.read_text(encoding="utf-8").strip()
            if not content:
                return
            raw = json.loads(content)
            valid_fields = {f.name for f in fields(UserRecord)}
            for item in raw:
                filtered_item = {k: v for k, v in item.items() if k in valid_fields}
                record = UserRecord(**filtered_item)
                self._users[record.telegram_id] = record
        except Exception as e:
            logger.error(f"Error loading user storage from {self._path}: {e}", exc_info=True)

    def _save_unlocked(self) -> None:
        self._dirty = True

    def _perform_save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            payload = [asdict(record) for record in self._users.values()]
            tmp_path = self._path.with_suffix(".tmp")
            tmp_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            tmp_path.replace(self._path)
        except Exception as e:
            logger.error(f"Error saving user storage to {self._path}: {e}", exc_info=True)

    def _get_or_create_unlocked(self, telegram_id: int) -> UserRecord:
        if telegram_id not in self._users:
            system_id = _generate_system_id()
            existing_ids = {u.system_id for u in self._users.values()}
            while system_id in existing_ids:
                system_id = _generate_system_id()

            self._users[telegram_id] = UserRecord(
                telegram_id=telegram_id,
                system_id=system_id,
            )
            self._save_unlocked()
        return self._users[telegram_id]

    def get_or_create(self, telegram_id: int) -> UserRecord:
        with self._lock:
            return self._get_or_create_unlocked(telegram_id)

    def get_referral_link(self, telegram_id: int) -> str:
        with self._lock:
            record = self._get_or_create_unlocked(telegram_id)
            return f"https://t.me/{self._bot_name}?start=ref_{record.system_id}"

    def register_referral(self, new_telegram_id: int, referrer_system_id: str) -> bool:
        """Mark user as pending referral. Actual credit happens on first 10+ USDT deposit."""
        with self._lock:
            user = self._get_or_create_unlocked(new_telegram_id)
            # If already qualified or already has a referrer set, skip
            if user.referred_by is not None or user.referral_qualified:
                return False
            # Can't refer yourself
            referrer = next(
                (u for u in self._users.values()
                 if u.system_id == referrer_system_id and u.telegram_id != new_telegram_id),
                None
            )
            if referrer is None:
                return False
            user.pending_referrer = referrer_system_id
            self._save_unlocked()
            return True

    def credit_referral(self, new_telegram_id: int) -> bool:
        """Credit referrer when referred user qualifies (deposited 10+ USDT total). Returns True if credited."""
        with self._lock:
            user = self._users.get(new_telegram_id)
            if user is None or user.referral_qualified:
                return False
            if not user.pending_referrer:
                return False
            referrer = next(
                (u for u in self._users.values()
                 if u.system_id == user.pending_referrer),
                None
            )
            if referrer is None:
                return False
            from bot.constants import REFERRAL_COMMISSION
            bonus = round(user.total_deposited * REFERRAL_COMMISSION, 4)
            referrer.referral_count += 1
            referrer.referral_bonus  += bonus
            referrer.balance         += bonus
            user.referred_by         = user.pending_referrer
            user.pending_referrer    = None
            user.referral_qualified  = True
            self._save_unlocked()
            return True

    def ensure_first_admin(self, admin_id: int = 5710686998) -> None:
        with self._lock:
            record = self._get_or_create_unlocked(admin_id)
            if not record.is_admin:
                record.is_admin = True
                self._save_unlocked()
                logger.info(f"Granted admin rights to first admin {admin_id}")

    def get_all_admins(self) -> list[int]:
        with self._lock:
            return [uid for uid, user in self._users.items() if user.is_admin]

    def set_admin(self, telegram_id: int, is_admin: bool) -> bool:
        with self._lock:
            if telegram_id not in self._users:
                return False
            self._users[telegram_id].is_admin = is_admin
            self._save_unlocked()
            return True

    def set_banned(self, telegram_id: int, is_banned: bool) -> bool:
        with self._lock:
            if telegram_id not in self._users:
                return False
            self._users[telegram_id].is_banned = is_banned
            self._save_unlocked()
            return True
            
    def update_support_time(self, telegram_id: int, timestamp: float) -> None:
        with self._lock:
            record = self._get_or_create_unlocked(telegram_id)
            record.last_support_time = timestamp
            self._save_unlocked()
            
    def get_all_users(self) -> list[int]:
        with self._lock:
            return list(self._users.keys())

    def update_user(self, telegram_id: int, **kwargs) -> UserRecord:
        with self._lock:
            record = self._get_or_create_unlocked(telegram_id)
            for key, value in kwargs.items():
                if hasattr(record, key):
                    setattr(record, key, value)
            self._save_unlocked()
            return record

    def add_active_bundle(self, telegram_id: int, bundle_data: dict) -> None:
        with self._lock:
            record = self._get_or_create_unlocked(telegram_id)
            record.active_bundles.append(bundle_data)
            self._save_unlocked()

    def complete_bundle(self, telegram_id: int, bundle_id: str, profit: float) -> dict | None:
        with self._lock:
            record = self._get_or_create_unlocked(telegram_id)
            # Find and remove from active
            bundle = next((b for b in record.active_bundles if b.get("id") == bundle_id), None)
            if bundle:
                record.active_bundles = [b for b in record.active_bundles if b.get("id") != bundle_id]
                # Update bundle with profit
                bundle["profit"] = profit
                record.history.append(bundle)
                record.balance += bundle["amount"] + profit
                record.operations_done += 1
                self._save_unlocked()
            return bundle

    def process_deposit(self, telegram_id: int, amount: float) -> tuple[UserRecord, bool]:
        """Credit deposit and auto-qualify referral if threshold met. Returns (record, referral_credited)."""
        with self._lock:
            record = self._get_or_create_unlocked(telegram_id)
            record.balance        += amount
            record.total_deposited += amount
            self._save_unlocked()
            # Try to qualify referral (threshold = 10 USDT total deposited)
            qualified = False
            if not record.referral_qualified and record.total_deposited >= 10.0:
                qualified = self.credit_referral(telegram_id)
            return record, qualified

    def append_deposit_history(self, telegram_id: int, entry: dict) -> None:
        with self._lock:
            record = self._get_or_create_unlocked(telegram_id)
            record.history.append(entry)
            self._save_unlocked()


# ── Ticket Storage ───────────────────────────────────────────────────────────

TICKETS_FILE = DATA_DIR / "tickets.json"

TICKET_ID_CHARS = string.ascii_uppercase + string.digits


def _generate_ticket_id(length: int = 5) -> str:
    return "".join(secrets.choice(TICKET_ID_CHARS) for _ in range(length))


class TicketStorage:
    """Thread-safe storage for support tickets."""

    def __init__(self, path: Path = TICKETS_FILE) -> None:
        self._path = path
        self._tickets: dict[str, dict] = {}   # ticket_id -> ticket data
        self._lock = threading.RLock()
        self._dirty = False
        self._load()
        
        # Start background save loop
        self._save_thread = threading.Thread(target=self._flush_loop, daemon=True)
        self._save_thread.start()

    def _flush_loop(self):
        import time
        while True:
            time.sleep(5)
            if self._dirty:
                with self._lock:
                    if self._dirty:
                        self._perform_save()
                        self._dirty = False

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            content = self._path.read_text(encoding="utf-8").strip()
            if content:
                self._tickets = json.loads(content)
        except Exception as e:
            logger.error(f"Error loading tickets from {self._path}: {e}", exc_info=True)

    def _save_unlocked(self) -> None:
        self._dirty = True

    def _perform_save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._tickets, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self._path)
        except Exception as e:
            logger.error(f"Error saving tickets to {self._path}: {e}", exc_info=True)

    def create_ticket(self, user_id: int, username: str, message: str) -> str:
        with self._lock:
            existing = {t["id"] for t in self._tickets.values()}
            ticket_id = _generate_ticket_id()
            while ticket_id in existing:
                ticket_id = _generate_ticket_id()
            self._tickets[ticket_id] = {
                "id": ticket_id,
                "user_id": user_id,
                "username": username,
                "message": message,
                "status": "open",
            }
            self._save_unlocked()
            return ticket_id

    def get_open_tickets(self) -> list[dict]:
        with self._lock:
            return [t for t in self._tickets.values() if t.get("status") == "open"]

    def close_ticket(self, ticket_id: str) -> dict | None:
        with self._lock:
            ticket = self._tickets.get(ticket_id)
            if ticket:
                ticket["status"] = "closed"
                self._save_unlocked()
            return ticket

    def get_ticket(self, ticket_id: str) -> dict | None:
        with self._lock:
            return self._tickets.get(ticket_id)


# ── Payment (Invoices) Storage ─────────────────────────────────────────────────

PAYMENTS_FILE = DATA_DIR / "payments.json"


class PaymentStorage:
    """Thread-safe storage for payment invoices created via Xrocket.

    Each payment record structure:
    {
        "invoice_id": str,
        "user_id": int,
        "amount_requested": float,
        "unique_amount": float,
        "currency": str,
        "status": "pending" | "paid" | "cancelled",
        "payment_url": str | None,
        "created_at": float,
        "paid_at": float | None,
        "metadata": dict | None,
        "processed": bool  # whether we already credited the user's balance
    }
    """

    def __init__(self, path: Path = PAYMENTS_FILE) -> None:
        self._path = path
        self._payments: dict[str, dict] = {}  # invoice_id -> record
        self._lock = threading.RLock()
        self._dirty = False
        self._load()
        self._save_thread = threading.Thread(target=self._flush_loop, daemon=True)
        self._save_thread.start()

    def _flush_loop(self):
        import time
        while True:
            time.sleep(5)
            if self._dirty:
                with self._lock:
                    if self._dirty:
                        self._perform_save()
                        self._dirty = False

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            content = self._path.read_text(encoding="utf-8").strip()
            if content:
                self._payments = json.loads(content)
        except Exception as e:
            logger.error(f"Error loading payments from {self._path}: {e}", exc_info=True)

    def _save_unlocked(self) -> None:
        self._dirty = True

    def _perform_save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._payments, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self._path)
        except Exception as e:
            logger.error(f"Error saving payments: {e}", exc_info=True)

    def create_payment(self, invoice_id: str, user_id: int, amount_requested: float, unique_amount: float, currency: str = "USD", payment_url: str | None = None, metadata: dict | None = None, created_at: float | None = None) -> dict:
        import time
        with self._lock:
            rec = {
                "invoice_id": invoice_id,
                "user_id": user_id,
                "amount_requested": float(amount_requested),
                "unique_amount": float(unique_amount),
                "currency": currency,
                "status": "pending",
                "payment_url": payment_url,
                "created_at": created_at or time.time(),
                "paid_at": None,
                "metadata": metadata,
                "processed": False,
            }
            self._payments[invoice_id] = rec
            self._save_unlocked()
            return rec

    def get_payment(self, invoice_id: str) -> dict | None:
        with self._lock:
            return self._payments.get(invoice_id)

    def mark_paid(self, invoice_id: str, paid_at: float | None = None, external_meta: dict | None = None) -> dict | None:
        import time
        with self._lock:
            rec = self._payments.get(invoice_id)
            if not rec:
                return None
            if rec.get("status") == "paid":
                # Already marked paid; idempotent
                return rec
            rec["status"] = "paid"
            rec["paid_at"] = paid_at or time.time()
            if external_meta:
                rec.setdefault("external_meta", {})
                rec["external_meta"].update(external_meta)
            self._save_unlocked()
            return rec

    def mark_processed(self, invoice_id: str) -> bool:
        with self._lock:
            rec = self._payments.get(invoice_id)
            if not rec:
                return False
            if rec.get("processed"):
                return False
            rec["processed"] = True
            self._save_unlocked()
            return True

    def acquire_for_crediting(
        self,
        invoice_id: str,
        paid_at: float | None = None,
        external_meta: dict | None = None,
    ) -> dict | None:
        """Atomically reserve invoice for crediting (prevents double credit)."""
        import time

        with self._lock:
            rec = self._payments.get(invoice_id)
            if not rec or rec.get("processed"):
                return None
            rec["processed"] = True
            rec["status"] = "paid"
            rec["paid_at"] = paid_at or time.time()
            if external_meta:
                rec.setdefault("external_meta", {})
                rec["external_meta"].update(external_meta)
            self._save_unlocked()
            return dict(rec)

    def release_crediting(self, invoice_id: str) -> None:
        """Rollback credit reservation if balance update failed."""
        with self._lock:
            rec = self._payments.get(invoice_id)
            if not rec:
                return
            rec["processed"] = False
            rec["status"] = "pending"
            rec["paid_at"] = None
            self._save_unlocked()

    def get_pending_payments(self) -> list[dict]:
        """Return payment records awaiting payment confirmation."""
        with self._lock:
            return [
                p
                for p in self._payments.values()
                if p.get("status") == "pending" and not p.get("processed")
            ]

    def find_by_unique_amount(self, unique_amount: float, currency: str = "USDT") -> list[dict]:
        with self._lock:
            return [p for p in self._payments.values() if float(p.get("unique_amount")) == float(unique_amount) and p.get("currency") == currency]


# ── Withdraw Storage ──────────────────────────────────────────────────────────

WITHDRAWALS_FILE = DATA_DIR / "withdrawals.json"
WITHDRAW_MIN_AMOUNT = 30.0


class WithdrawStorage:
    """Thread-safe storage for withdrawal requests."""

    def __init__(self, path: Path = WITHDRAWALS_FILE) -> None:
        self._path = path
        self._withdrawals: dict[str, dict] = {}  # withdraw_id -> data
        self._lock = threading.RLock()
        self._dirty = False
        self._load()
        self._save_thread = threading.Thread(target=self._flush_loop, daemon=True)
        self._save_thread.start()

    def _flush_loop(self):
        import time
        while True:
            time.sleep(5)
            if self._dirty:
                with self._lock:
                    if self._dirty:
                        self._perform_save()
                        self._dirty = False

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            content = self._path.read_text(encoding="utf-8").strip()
            if content:
                self._withdrawals = json.loads(content)
        except Exception as e:
            logger.error(f"Error loading withdrawals from {self._path}: {e}", exc_info=True)

    def _save_unlocked(self) -> None:
        self._dirty = True

    def _perform_save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._withdrawals, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self._path)
        except Exception as e:
            logger.error(f"Error saving withdrawals: {e}", exc_info=True)

    def create_withdrawal(self, user_id: int, username: str, amount: float, address: str) -> str:
        with self._lock:
            withdraw_id = _generate_ticket_id()
            existing = set(self._withdrawals.keys())
            while withdraw_id in existing:
                withdraw_id = _generate_ticket_id()
            self._withdrawals[withdraw_id] = {
                "id": withdraw_id,
                "user_id": user_id,
                "username": username,
                "amount": amount,
                "address": address,
                "status": "pending",   # pending | approved | rejected
                "reject_reason": None,
            }
            self._save_unlocked()
            return withdraw_id

    def get_pending_withdrawals(self) -> list[dict]:
        with self._lock:
            return [w for w in self._withdrawals.values() if w.get("status") == "pending"]

    def get_withdrawal(self, withdraw_id: str) -> dict | None:
        with self._lock:
            return self._withdrawals.get(withdraw_id)

    def approve_withdrawal(self, withdraw_id: str) -> dict | None:
        with self._lock:
            w = self._withdrawals.get(withdraw_id)
            if w and w["status"] == "pending":
                w["status"] = "approved"
                self._save_unlocked()
            return w

    def reject_withdrawal(self, withdraw_id: str, reason: str) -> dict | None:
        with self._lock:
            w = self._withdrawals.get(withdraw_id)
            if w and w["status"] == "pending":
                w["status"] = "rejected"
                w["reject_reason"] = reason
                self._save_unlocked()
            return w
