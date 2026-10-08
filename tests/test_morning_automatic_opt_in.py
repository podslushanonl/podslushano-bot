"""Safety regression: the daily paid morning slot requires explicit opt-in."""
import asyncio
import os
from datetime import datetime
from unittest.mock import patch

from utils import editorial_budget_photo as budget


def test_morning_automation_is_disabled_by_default():
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("EDITORIAL_MORNING_AUTO_ENABLED", None)
        # No Telegram, database or paid generator may be reached.
        asyncio.run(budget._budgeted_run_morning(None, datetime(2026, 10, 8, 6, 35)))


def test_morning_automation_remains_disabled_with_false_values():
    for value in ("0", "false", "off", "no", ""):
        with patch.dict(os.environ, {"EDITORIAL_MORNING_AUTO_ENABLED": value}):
            asyncio.run(budget._budgeted_run_morning(None, datetime(2026, 10, 8, 6, 35)))


def test_morning_automation_can_only_be_enabled_explicitly():
    # Outside the time window, enabling the feature does not generate anything.
    for value in ("1", "true", "yes", "on"):
        with patch.dict(os.environ, {"EDITORIAL_MORNING_AUTO_ENABLED": value}):
            asyncio.run(budget._budgeted_run_morning(None, datetime(2026, 10, 8, 5, 0)))
