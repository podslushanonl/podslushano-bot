"""Focused checks for the Q4 2026 /ads campaign and discount contract."""
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("BOT_TOKEN", "123456:test-token")
os.environ.setdefault("ADMIN_IDS", "1")

import config  # noqa: E402
import ad_products_runtime  # noqa: E402,F401
import ad_season_campaign_runtime as season  # noqa: E402


def test_public_products() -> None:
    single = config.AD_FORMATS["ad_single"]
    telegram = config.AD_FORMATS["ad_telegram"]
    expert = config.AD_FORMATS["ad_expert_live"]

    assert single["options"][0]["price"] == "99.00"
    assert not any("Telegram" in item for item in single["details"])
    assert telegram["options"][0]["price"] == "75.00"
    assert telegram["dates"] == 1
    assert any("7 дней" in item for item in telegram["details"])
    assert expert["options"][0]["price"] == "120.00"
    assert expert["lead_days"] == 7


def test_discount_prices_and_tokens() -> None:
    expected = {
        "ad_single": "73.26",
        "ad_telegram": "55.50",
        "ad_expert_live": "88.80",
        "ad_promotion": "133.20",
        "ad_campaign": "221.26",
    }
    for fmt, price in expected.items():
        option = next(
            item for item in config.AD_FORMATS[fmt]["options"]
            if item["key"] == "q4_26"
        )
        assert option["price"] == price

    token = season._issue_token("Advertiser@Example.com")
    assert season._token_email(token) == "advertiser@example.com"
    assert season._token_email(token + "x") is None

    clean, extracted = season._extract_discount_token(
        "+316123|||SEASON26:" + token + "|||GUIDE64:payload"
    )
    assert extracted == token
    assert clean == "+316123|||GUIDE64:payload"


async def test_discount_checkout_guard() -> None:
    original = season._original_book_and_pay
    original_active = season._campaign_active
    captured = {}

    async def fake_original(fmt, opt, dates, fields):
        captured.update(fmt=fmt, opt=opt, dates=dates, fields=fields)
        return "https://checkout.example", ""

    season._original_book_and_pay = fake_original
    season._campaign_active = lambda: True
    token = season._issue_token("buyer@example.com")
    try:
        checkout, error = await season._book_and_pay_q4(
            "ad_single",
            "q4_26",
            ["2026-12-20"],
            {"phone": "+316|||SEASON26:" + token},
        )
        assert checkout == "https://checkout.example"
        assert not error
        assert captured["fields"]["phone"] == "+316"

        checkout, error = await season._book_and_pay_q4(
            "ad_single",
            "q4_26",
            ["2027-01-05"],
            {"phone": "+316|||SEASON26:" + token},
        )
        assert checkout is None
        assert "31 декабря" in error

        checkout, error = await season._book_and_pay_q4(
            "ad_single", "q4_26", ["2026-12-20"], {"phone": "+316"}
        )
        assert checkout is None
        assert "не подтверждена" in error
    finally:
        season._original_book_and_pay = original
        season._campaign_active = original_active


def main() -> None:
    test_public_products()
    test_discount_prices_and_tokens()
    asyncio.run(test_discount_checkout_guard())
    print("[OK] Ads Q4: products + signed −26% discount + Dec 31 guard")


if __name__ == "__main__":
    main()
