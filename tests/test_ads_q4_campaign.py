"""Focused checks for the Q4 2026 /ads campaign and discount contract."""
import asyncio
import json
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
    assert any("4 Instagram Stories" in item for item in expert["details"])


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

    unsubscribe_token = season._issue_unsubscribe_token("Advertiser@Example.com")
    assert season._unsubscribe_token_email(unsubscribe_token) == "advertiser@example.com"
    assert season._unsubscribe_token_email(unsubscribe_token + "x") is None

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




async def test_checkout_keeps_redesigned_page() -> None:
    """Backend rejections must not send a discounted buyer to legacy /ads."""
    from handlers import ads as ads_handler
    from utils import webserver

    original = ads_handler.book_and_pay
    captured = {}

    async def fake_book(fmt, opt, dates, fields):
        captured.update(fmt=fmt, opt=opt, dates=dates, fields=fields)
        if fmt == "ad_campaign":
            return None, "Укажите рабочий контакт: Instagram, Telegram, сайт, e-mail или телефон."
        return "https://www.mollie.com/checkout/example", ""

    class Request:
        def __init__(self, accept):
            self.headers = {"Accept": accept}

        async def post(self):
            return {
                "fmt": "ad_campaign" if "error" in self.headers["Accept"] else "ad_single",
                "opt": "q4_26",
                "dates": "2026-10-27",
                "email": "buyer@example.com",
                "buyer_name": "Test Buyer",
                "address": "Example Street 1",
                "client_type": "person",
                "terms": "on",
            }

    ads_handler.book_and_pay = fake_book
    try:
        error_request = Request("application/json; error")
        response = await webserver._ads_book(error_request)
        assert response.status == 400
        payload = json.loads(response.text)
        assert not payload["ok"]
        assert "рабочий контакт" in payload["error"]
        assert captured["opt"] == "q4_26"
        assert captured["dates"] == ["2026-10-27"]

        success_request = Request("application/json")
        response = await webserver._ads_book(success_request)
        assert response.status == 200
        payload = json.loads(response.text)
        assert payload == {"ok": True, "checkout_url": "https://www.mollie.com/checkout/example"}
        assert captured["opt"] == "q4_26"

        html_request = Request("text/html; error")
        response = await webserver._ads_book(html_request)
        assert response.status == 400
        assert "Не удалось перейти к оплате" in response.text
        assert "Забронировать дату и формат" not in response.text
    finally:
        ads_handler.book_and_pay = original


def test_new_checkout_script_is_installed() -> None:
    page = (ROOT / "static/ads-site/index.html").read_text(encoding="utf-8")
    script = (ROOT / "static/ads-site/checkout-fix.js").read_text(encoding="utf-8")
    assert 'src="/ads-static/checkout-fix.js"' in page
    assert "event.defaultPrevented" in script
    assert "new FormData(form)" in script
    assert "'Accept': 'application/json'" in script
    assert "showCheckoutError" in script
    assert "payload.checkout_url" in script

def main() -> None:
    test_public_products()
    test_discount_prices_and_tokens()
    asyncio.run(test_discount_checkout_guard())
    asyncio.run(test_checkout_keeps_redesigned_page())
    test_new_checkout_script_is_installed()
    print("[OK] Ads Q4: products + signed −26% discount + unsubscribe + Dec 31 guard")


if __name__ == "__main__":
    main()
