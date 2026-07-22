"""Unit + integration tests for Quantum bot.

Run:  python -m pytest tests/ -v
Requires: DATABASE_URL env var pointing to a test Neon/Postgres DB for async tests.
Pure-logic tests run without any DB or asyncpg.
"""
from __future__ import annotations

import sys
import time
import os
import unittest
from unittest.mock import MagicMock, patch

# ── Stub asyncpg so pure-logic tests work without the driver installed ────────
if "asyncpg" not in sys.modules:
    sys.modules["asyncpg"] = MagicMock()

import pytest


# ── Pure-logic tests (no DB needed) ──────────────────────────────────────────

class TestPaymentsServiceLogic(unittest.TestCase):
    def test_invoice_is_paid_status(self):
        from bot.payments_service import invoice_is_paid
        self.assertTrue(invoice_is_paid({"status": "paid"}))
        self.assertTrue(invoice_is_paid({"status": "PAID"}))
        self.assertTrue(invoice_is_paid({"status": "completed"}))
        self.assertFalse(invoice_is_paid({"status": "pending"}))
        self.assertFalse(invoice_is_paid(None))
        self.assertFalse(invoice_is_paid({}))

    def test_invoice_is_paid_paid_field(self):
        from bot.payments_service import invoice_is_paid
        self.assertTrue(invoice_is_paid({"paid": True}))
        self.assertFalse(invoice_is_paid({"paid": False}))
        self.assertFalse(invoice_is_paid({"paid": None}))

    def test_invoice_is_paid_wrapped(self):
        from bot.payments_service import invoice_is_paid
        self.assertTrue(invoice_is_paid({"success": True, "data": {"status": "paid"}}))

    def test_webhook_indicates_paid(self):
        from bot.payments_service import webhook_indicates_paid
        self.assertTrue(webhook_indicates_paid({"type": "invoicePay"}))
        self.assertTrue(webhook_indicates_paid({"type": "invoice.paid"}))
        self.assertTrue(webhook_indicates_paid({"data": {"status": "paid"}}))
        self.assertFalse(webhook_indicates_paid({"type": "other"}))
        self.assertFalse(webhook_indicates_paid({}))

    def test_parse_webhook_invoice_id(self):
        from bot.payments_service import parse_webhook_invoice_id
        self.assertEqual(parse_webhook_invoice_id({"id": "123"}), "123")
        self.assertEqual(parse_webhook_invoice_id({"data": {"id": "456"}}), "456")
        self.assertEqual(parse_webhook_invoice_id({"invoice_id": "789"}), "789")
        self.assertIsNone(parse_webhook_invoice_id({}))

    def test_extract_invoice_from_create_response(self):
        from bot.payments_service import extract_invoice_from_create_response
        inv_id, url = extract_invoice_from_create_response(
            {"success": True, "data": {"id": "abc", "link": "https://pay.xrocket.tg/abc"}}
        )
        self.assertEqual(inv_id, "abc")
        self.assertEqual(url, "https://pay.xrocket.tg/abc")

        inv_id2, url2 = extract_invoice_from_create_response(None)
        self.assertIsNone(inv_id2)
        self.assertIsNone(url2)

    def test_deposit_history_entry(self):
        from bot.payments_service import _deposit_history_entry
        entry = _deposit_history_entry("inv123", 50.0, "USDT")
        self.assertEqual(entry["type"], "deposit")
        self.assertEqual(entry["invoice_id"], "inv123")
        self.assertEqual(entry["amount"], 50.0)
        self.assertEqual(entry["currency"], "USDT")
        self.assertIn("time", entry)


class TestXrocketWebhookSignature(unittest.TestCase):
    def test_verify_no_key_returns_true(self):
        from bot import xrocket_client_prod as xrocket
        with patch.object(xrocket, "XROCKET_API_KEY", None), \
             patch.object(xrocket, "XROCKET_WEBHOOK_SECRET", None):
            self.assertTrue(xrocket.verify_webhook_signature(b"body", None))

    def test_verify_missing_header_returns_false(self):
        import hashlib
        from bot import xrocket_client_prod as xrocket
        key = hashlib.sha256(b"testkey").digest()
        with patch.object(xrocket, "XROCKET_API_KEY", "testkey"), \
             patch.object(xrocket, "XROCKET_WEBHOOK_SECRET", None):
            self.assertFalse(xrocket.verify_webhook_signature(b"body", None))

    def test_verify_correct_signature(self):
        import hashlib, hmac as _hmac
        from bot import xrocket_client_prod as xrocket
        body = b'{"test": 1}'
        key = hashlib.sha256(b"myapikey").digest()
        sig = _hmac.new(key, body, hashlib.sha256).hexdigest()
        with patch.object(xrocket, "XROCKET_API_KEY", "myapikey"), \
             patch.object(xrocket, "XROCKET_WEBHOOK_SECRET", None):
            self.assertTrue(xrocket.verify_webhook_signature(body, sig))

    def test_verify_wrong_signature(self):
        import hashlib
        from bot import xrocket_client_prod as xrocket
        with patch.object(xrocket, "XROCKET_API_KEY", "myapikey"), \
             patch.object(xrocket, "XROCKET_WEBHOOK_SECRET", None):
            self.assertFalse(xrocket.verify_webhook_signature(b"body", "wrongsig"))


class TestWebAppAuth(unittest.TestCase):
    def test_validate_init_data_invalid_hash(self):
        from bot.webapp_api import validate_init_data
        from fastapi import HTTPException
        with self.assertRaises(HTTPException):
            validate_init_data("user=test&hash=badhash", "token")

    def test_validate_init_data_no_hash(self):
        from bot.webapp_api import validate_init_data
        from fastapi import HTTPException
        with self.assertRaises(HTTPException):
            validate_init_data("user=test", "token")


class TestRateLimiter(unittest.TestCase):
    def test_rate_limit_allows_under_limit(self):
        from bot.webapp_api import _check_rate, _rate_store
        _rate_store.clear()
        for _ in range(5):
            self.assertTrue(_check_rate("test_key", 5, 60))

    def test_rate_limit_blocks_over_limit(self):
        from bot.webapp_api import _check_rate, _rate_store
        _rate_store.clear()
        for _ in range(5):
            _check_rate("test_key2", 5, 60)
        self.assertFalse(_check_rate("test_key2", 5, 60))

    def test_rate_limit_resets_after_window(self):
        from bot.webapp_api import _check_rate, _rate_store
        _rate_store["test_key3"] = [time.time() - 61]  # expired hit
        self.assertTrue(_check_rate("test_key3", 1, 60))


class TestStorageHelpers(unittest.TestCase):
    def test_gen_id_length(self):
        from bot.storage import _gen_id
        for _ in range(20):
            sid = _gen_id()
            self.assertEqual(len(sid), 5)
            self.assertTrue(sid.isupper() or sid.isalnum())

    def test_gen_id_uniqueness(self):
        from bot.storage import _gen_id
        ids = {_gen_id() for _ in range(100)}
        # With 36^5 = 60M possibilities, 100 should all be unique
        self.assertEqual(len(ids), 100)


class TestConstantsIntegrity(unittest.TestCase):
    def test_bundle_config_coins_match(self):
        from bot.constants import COINS, BUNDLE_CONFIG
        for ticker, _ in COINS:
            self.assertIn(ticker, BUNDLE_CONFIG, f"{ticker} in COINS but not in BUNDLE_CONFIG")

    def test_bundle_config_values(self):
        from bot.constants import BUNDLE_CONFIG
        for coin, cfg in BUNDLE_CONFIG.items():
            ex1, ex2, spread, min_u, max_u, p_min, p_max, t_min, t_max = cfg
            self.assertGreater(max_u, min_u, f"{coin}: max_u must be > min_u")
            self.assertGreater(p_max, 0, f"{coin}: p_max must be > 0")
            self.assertGreater(t_max, 0, f"{coin}: t_max must be > 0")
            self.assertGreater(min_u, 0, f"{coin}: min_u must be > 0")

    def test_commissions_range(self):
        from bot.constants import DEPOSIT_COMMISSION, DEPOSIT_COMMISSION_PLUS, WITHDRAW_COMMISSION, REFERRAL_COMMISSION
        for name, val in [
            ("DEPOSIT_COMMISSION", DEPOSIT_COMMISSION),
            ("DEPOSIT_COMMISSION_PLUS", DEPOSIT_COMMISSION_PLUS),
            ("WITHDRAW_COMMISSION", WITHDRAW_COMMISSION),
            ("REFERRAL_COMMISSION", REFERRAL_COMMISSION),
        ]:
            self.assertGreater(val, 0, f"{name} must be > 0")
            self.assertLess(val, 1, f"{name} must be < 1")

    def test_referral_commission_is_30_percent(self):
        from bot.constants import REFERRAL_COMMISSION
        self.assertAlmostEqual(REFERRAL_COMMISSION, 0.30)


class TestTextsNoPlaceholderErrors(unittest.TestCase):
    """Ensure all format strings have correct placeholders."""

    def test_bundles_format(self):
        from bot import texts
        result = texts.BUNDLES.format(done=5, limit=100)
        self.assertIn("5", result)
        self.assertIn("100", result)

    def test_wallet_format(self):
        from bot import texts
        result = texts.WALLET.format(user_line="Test User", system_id="ABC12", balance=99.5)
        self.assertIn("99.5", result)
        self.assertIn("ABC12", result)

    def test_referrals_format(self):
        from bot import texts
        result = texts.REFERRALS.format(
            referral_link="https://t.me/bot?start=ref_ABC",
            referral_count=3,
            referral_bonus=15.5,
        )
        self.assertIn("3", result)
        self.assertIn("15.5", result)

    def test_history_card_format(self):
        from bot import texts
        result = texts.HISTORY_CARD.format(
            coin="BTC", ex1="Binance", ex2="Bybit",
            amount=100.0, exit_amount=101.81, spread="1.81%"
        )
        self.assertIn("BTC", result)
        self.assertIn("Binance", result)

    def test_history_finish_notification_format(self):
        from bot import texts
        result = texts.HISTORY_FINISH_NOTIFICATION.format(
            coin="SOL", ex1="OKX", ex2="Huobi",
            amount=100.0, exit_amount=101.09, profit=1.09,
            spread="1.09%", balance=201.09,
        )
        self.assertIn("SOL", result)
        self.assertIn("1.09", result)

    def test_support_success_format(self):
        from bot import texts
        result = texts.SUPPORT_SUCCESS.format(ticket_id="XYZ99")
        self.assertIn("XYZ99", result)

    def test_no_double_newlines_in_short_texts(self):
        from bot import texts
        # Ensure \r\r\n bug is gone — no carriage returns
        for name in dir(texts):
            val = getattr(texts, name)
            if isinstance(val, str):
                self.assertNotIn("\r", val, f"texts.{name} contains \\r")


# ── Async DB tests (skip if no DATABASE_URL) ─────────────────────────────────

DB_AVAILABLE = bool(os.getenv("DATABASE_URL"))


@pytest.mark.asyncio
@pytest.mark.skipif(not DB_AVAILABLE, reason="DATABASE_URL not set")
async def test_db_get_or_create():
    from bot.db import init_pool, close_pool
    from bot.storage import UserStorage
    await init_pool()
    try:
        storage = UserStorage(bot_name="testbot")
        uid = 999999999  # test user
        record = await storage.get_or_create(uid)
        assert record.telegram_id == uid
        assert len(record.system_id) == 5
        # Second call returns same record
        record2 = await storage.get_or_create(uid)
        assert record2.system_id == record.system_id
    finally:
        await close_pool()


@pytest.mark.asyncio
@pytest.mark.skipif(not DB_AVAILABLE, reason="DATABASE_URL not set")
async def test_db_referral_count_only_increments_once():
    """referral_count must increment only on first deposit, not subsequent ones."""
    from bot.db import init_pool, close_pool, get_pool
    from bot.storage import UserStorage
    await init_pool()
    pool = await get_pool()
    try:
        storage = UserStorage(bot_name="testbot")
        referrer_id = 888888881
        referral_id = 888888882

        # Clean up
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM users WHERE telegram_id IN ($1,$2)", referrer_id, referral_id)

        referrer = await storage.get_or_create(referrer_id)
        await storage.register_referral_new_only(referral_id, referrer.system_id)

        # First deposit
        _, bonus1 = await storage.process_deposit(referral_id, 100.0)
        assert bonus1 > 0

        referrer_after1 = await storage.get_or_create(referrer_id)
        assert referrer_after1.referral_count == 1

        # Second deposit — count must NOT increase
        _, bonus2 = await storage.process_deposit(referral_id, 50.0)
        assert bonus2 > 0

        referrer_after2 = await storage.get_or_create(referrer_id)
        assert referrer_after2.referral_count == 1, "referral_count must not increment on 2nd deposit"
        assert referrer_after2.referral_bonus > referrer_after1.referral_bonus, "bonus must accumulate"
    finally:
        await close_pool()


@pytest.mark.asyncio
@pytest.mark.skipif(not DB_AVAILABLE, reason="DATABASE_URL not set")
async def test_db_referral_not_credited_for_existing_user():
    """User who already started bot must not be credited as referral."""
    from bot.db import init_pool, close_pool, get_pool
    from bot.storage import UserStorage
    await init_pool()
    pool = await get_pool()
    try:
        storage = UserStorage(bot_name="testbot")
        referrer_id = 777777771
        existing_id = 777777772

        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM users WHERE telegram_id IN ($1,$2)", referrer_id, existing_id)

        referrer = await storage.get_or_create(referrer_id)
        # existing_id already in DB
        await storage.get_or_create(existing_id)

        # Try to register as referral — must fail
        ok = await storage.register_referral_new_only(existing_id, referrer.system_id)
        assert not ok, "Existing user must not be registered as referral"
    finally:
        await close_pool()


@pytest.mark.asyncio
@pytest.mark.skipif(not DB_AVAILABLE, reason="DATABASE_URL not set")
async def test_db_process_deposit_idempotent_balance():
    """process_deposit must correctly add to balance and total_deposited."""
    from bot.db import init_pool, close_pool, get_pool
    from bot.storage import UserStorage
    await init_pool()
    pool = await get_pool()
    try:
        storage = UserStorage(bot_name="testbot")
        uid = 666666661
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM users WHERE telegram_id=$1", uid)

        await storage.get_or_create(uid)
        record, _ = await storage.process_deposit(uid, 100.0)
        assert abs(record.balance - 100.0) < 0.001
        assert abs(record.total_deposited - 100.0) < 0.001

        record2, _ = await storage.process_deposit(uid, 50.0)
        assert abs(record2.balance - 150.0) < 0.001
        assert abs(record2.total_deposited - 150.0) < 0.001
    finally:
        await close_pool()


@pytest.mark.asyncio
@pytest.mark.skipif(not DB_AVAILABLE, reason="DATABASE_URL not set")
async def test_db_payment_acquire_idempotent():
    """acquire_for_crediting must return None on second call (idempotency)."""
    from bot.db import init_pool, close_pool
    from bot.storage import PaymentStorage, UserStorage
    import time
    await init_pool()
    try:
        payments = PaymentStorage()
        storage = UserStorage()
        uid = 555555551
        invoice_id = f"test_inv_{int(time.time())}"

        from bot.db import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM users WHERE telegram_id=$1", uid)
        await storage.get_or_create(uid)

        await payments.create_payment(
            invoice_id=invoice_id, user_id=uid,
            amount_requested=10.0, unique_amount=10.001,
        )
        rec1 = await payments.acquire_for_crediting(invoice_id)
        assert rec1 is not None

        rec2 = await payments.acquire_for_crediting(invoice_id)
        assert rec2 is None, "Second acquire must return None (already processed)"
    finally:
        await close_pool()


if __name__ == "__main__":
    unittest.main()
