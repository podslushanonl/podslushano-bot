import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace

from utils.webserver import _premium_now


class PremiumNowTest(unittest.TestCase):
    def test_premium_respects_end_date(self):
        now = datetime.utcnow()
        self.assertTrue(_premium_now(SimpleNamespace(is_premium=True, premium_until=None)))
        self.assertTrue(_premium_now(SimpleNamespace(is_premium=True, premium_until=now + timedelta(days=3))))
        self.assertFalse(_premium_now(SimpleNamespace(is_premium=True, premium_until=now - timedelta(minutes=1))))
        self.assertFalse(_premium_now(SimpleNamespace(is_premium=False, premium_until=now + timedelta(days=3))))


if __name__ == "__main__":
    unittest.main()
