"""Checks for Contact Guide checkout staying on /ads and using Mollie directly."""
import asyncio
import inspect
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("BOT_TOKEN", "123456:test-token")
os.environ.setdefault("ADMIN_IDS", "1")

import config  # noqa: E402
import ad_contact_guide_web_runtime as guide  # noqa: E402
from utils import payments  # noqa: E402


class FakeRequest:
    def __init__(self, data):
        self._data = data
        self.query = {}

    async def post(self):
        return self._data


def valid_form(**overrides):
    data = {
        "plan": "year",
        "name": "Example Legal",
        "category": "юрист",
        "online": "1",
        "city": "",
        "description": "Юридическая помощь предпринимателям и частным клиентам в Нидерландах.",
        "contact": "https://example.com",
        "email": "buyer@example.com",
        "terms": "1",
        "token": "signed-token",
    }
    data.update(overrides)
    return data


def test_discount_prices() -> None:
    assert guide._discount_price("9.99") == "7.39"
    assert guide._discount_price("99.00") == "73.26"
    assert guide._discount_price("19.99") == "14.79"
    assert guide._discount_price("109.00") == "80.66"
    assert guide._discount_price("199.00") == "147.26"


def test_frontend_uses_web_checkout_and_gift_states() -> None:
    js = (ROOT / "static" / "ads-site" / "q4-contact-guide.js").read_text(encoding="utf-8")
    cleanup_js = (ROOT / "static" / "ads-site" / "q4-cleanup.js").read_text(encoding="utf-8")
    css = (ROOT / "static" / "ads-site" / "q4-cleanup.css").read_text(encoding="utf-8")
    assert "/ads/contact-guide/checkout" in js
    assert "guideCheckoutShell" in js
    assert "Перейти к оплате Mollie" in js
    assert "tokenEmail" in js
    assert "У вас подарок" in cleanup_js
    assert ".gift-fab.unlocked" in css
    assert "activeGiftGlow" in css


def test_mollie_redirect_keeps_web_purchase_on_ads() -> None:
    source = inspect.getsource(payments.create_payment)
    assert 'metadata.get("source") == "ads_page"' in source
    assert "/ads/contact-guide/success?sid=" in source


async def test_discounted_checkout_uses_exact_mollie_amount() -> None:
    real_payments_enabled = config.payments_enabled
    real_entitlement = guide._season_entitlement
    real_session = guide.get_session
    real_create_payment = guide.selfadd.create_payment
    captured = {}
    stored = {"specialist": None}

    async def fake_entitlement(email, token):
        captured["entitlement"] = (email, token)
        return email == "buyer@example.com" and token == "signed-token"

    class FakeDb:
        def add(self, specialist):
            stored["specialist"] = specialist

        async def commit(self):
            return None

        async def refresh(self, specialist):
            specialist.id = 321

        async def get(self, _model, sid):
            assert sid == 321
            return stored["specialist"]

    class FakeContext:
        async def __aenter__(self):
            return FakeDb()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    async def fake_payment(description, metadata, amount, method=None):
        captured.update(description=description, metadata=metadata, amount=amount, method=method)
        return {"id": "tr_test", "checkout_url": "https://mollie.test/checkout"}

    config.payments_enabled = lambda: True
    guide._season_entitlement = fake_entitlement
    guide.get_session = lambda: FakeContext()
    guide.selfadd.create_payment = fake_payment
    try:
        response = await guide.contact_guide_checkout(FakeRequest(valid_form()))
        payload = json.loads(response.text)
        assert response.status == 200
        assert payload["ok"] is True
        assert payload["checkout_url"] == "https://mollie.test/checkout"
        assert payload["amount"] == "73.26"
        assert payload["discount"] == 26
        assert captured["amount"] == "73.26"
        assert captured["metadata"]["source"] == "ads_page"
        assert captured["metadata"]["kind"] == "new"
        assert captured["metadata"]["plan"] == "year"
        assert captured["metadata"]["discount"] == "q4_26"
        assert stored["specialist"].payment_id == "tr_test"
        assert stored["specialist"].submitter_user_id is None
    finally:
        config.payments_enabled = real_payments_enabled
        guide._season_entitlement = real_entitlement
        guide.get_session = real_session
        guide.selfadd.create_payment = real_create_payment


async def test_invalid_discount_token_does_not_fall_back_to_full_price() -> None:
    real_payments_enabled = config.payments_enabled
    real_entitlement = guide._season_entitlement
    real_session = guide.get_session
    real_create_payment = guide.selfadd.create_payment
    called = {"payment": False, "db": False}

    async def fake_entitlement(_email, _token):
        return False

    class NeverContext:
        async def __aenter__(self):
            called["db"] = True
            raise AssertionError("database must not be touched for invalid discount token")

        async def __aexit__(self, exc_type, exc, tb):
            return False

    async def fake_payment(*_args, **_kwargs):
        called["payment"] = True
        raise AssertionError("Mollie must not be called for invalid discount token")

    config.payments_enabled = lambda: True
    guide._season_entitlement = fake_entitlement
    guide.get_session = lambda: NeverContext()
    guide.selfadd.create_payment = fake_payment
    try:
        response = await guide.contact_guide_checkout(
            FakeRequest(valid_form(token="bad-token"))
        )
        payload = json.loads(response.text)
        assert response.status == 403
        assert payload["ok"] is False
        assert "Скидка −26% не подтверждена" in payload["error"]
        assert called == {"payment": False, "db": False}
    finally:
        config.payments_enabled = real_payments_enabled
        guide._season_entitlement = real_entitlement
        guide.get_session = real_session
        guide.selfadd.create_payment = real_create_payment


def main() -> None:
    test_discount_prices()
    test_frontend_uses_web_checkout_and_gift_states()
    test_mollie_redirect_keeps_web_purchase_on_ads()
    asyncio.run(test_discounted_checkout_uses_exact_mollie_amount())
    asyncio.run(test_invalid_discount_token_does_not_fall_back_to_full_price())
    print("[OK] Contact Guide: direct /ads form + exact −26% + Mollie web return")


if __name__ == "__main__":
    main()
