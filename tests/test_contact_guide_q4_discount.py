"""Focused checks for Contact Guide participation in the Q4 −26% campaign."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("BOT_TOKEN", "123456:test-token")
os.environ.setdefault("ADMIN_IDS", "1")

import config  # noqa: E402
import ad_products_runtime  # noqa: E402,F401
import ad_contact_guide_campaign_runtime as guide_campaign  # noqa: E402


def main() -> None:
    expert = config.AD_FORMATS["ad_expert_live"]
    assert expert["lead_days"] == 7
    assert any("4 Instagram Stories" in item for item in expert["details"])

    expected = {
        "9.99": "7.39",
        "99.00": "73.26",
        "19.99": "14.79",
        "109.00": "80.66",
        "199.00": "147.26",
    }
    for base, discounted in expected.items():
        assert guide_campaign.contact_guide_discount_price(base) == discounted

    print("[OK] Contact Guide Q4: expert stories + all Guide prices −26%")


if __name__ == "__main__":
    main()
