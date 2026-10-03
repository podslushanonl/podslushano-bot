"""Regression guard for the mobile /ads language switcher."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("BOT_TOKEN", "123456:test-token")
os.environ.setdefault("ADMIN_IDS", "1")

import ad_ads_cleanup_runtime as cleanup  # noqa: E402


def test_inline_language_switcher_cannot_self_trigger_dom_loop() -> None:
    inline = cleanup._SWITCHER_INLINE
    assert "MutationObserver" not in inline
    assert "if(b.textContent!==v[0])" in inline
    assert "DOMContentLoaded" in inline
    assert "🇷🇺" in inline
    assert "🇳🇱" in inline
    assert "🇬🇧" in inline
