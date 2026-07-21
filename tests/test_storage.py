import json
import tempfile
import unittest
from pathlib import Path

from bot.storage import UserStorage, UserRecord


class TestUserStorage(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.file_path = Path(self.temp_dir.name) / "users.json"
        self.storage = UserStorage(path=self.file_path, bot_name="testbot")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_get_or_create(self):
        user = self.storage.get_or_create(123456)
        self.assertEqual(user.telegram_id, 123456)
        self.assertIsNotNone(user.system_id)
        self.assertEqual(len(user.system_id), 5)

    def test_get_referral_link_no_deadlock(self):
        # This function previously deadlocked with threading.Lock()
        link = self.storage.get_referral_link(123456)
        user = self.storage.get_or_create(123456)
        self.assertEqual(link, f"https://t.me/testbot?start=ref_{user.system_id}")

    def test_register_referral(self):
        referrer = self.storage.get_or_create(100)
        ref_id = referrer.system_id

        # Register new user with referrer system_id
        success = self.storage.register_referral(200, ref_id)
        self.assertTrue(success)

        # Check updated counts
        updated_referrer = self.storage.get_or_create(100)
        self.assertEqual(updated_referrer.referral_count, 1)

        new_user = self.storage.get_or_create(200)
        self.assertEqual(new_user.referred_by, ref_id)

        # Re-registering should return False
        again = self.storage.register_referral(200, ref_id)
        self.assertFalse(again)

    def test_corrupted_json_recovery(self):
        # Write corrupted json
        self.file_path.write_text("{invalid json", encoding="utf-8")
        storage = UserStorage(path=self.file_path, bot_name="testbot")
        user = storage.get_or_create(999)
        self.assertEqual(user.telegram_id, 999)

    def test_update_user_no_deadlock(self):
        user = self.storage.update_user(123456, balance=150.5, subscription_active=True)
        self.assertEqual(user.balance, 150.5)
        self.assertTrue(user.subscription_active)


if __name__ == "__main__":
    unittest.main()
