"""Regression checks for the isolated Instagram sales service (no live API calls)."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("BOT_TOKEN", "123456:test-token")
os.environ.setdefault("ADMIN_IDS", "1")

import ad_products_runtime  # noqa: F401,E402
import ad_season_campaign_runtime  # noqa: F401,E402
import instagram_sales_runtime as sales  # noqa: E402
from database.models import Base  # noqa: E402
from database.ig_sales_models import IgSalesEvent, IgSalesOrder, IgSalesConversation  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker  # noqa: E402


def test_policy_and_prices():
    offerings = sales.catalog()
    assert offerings["ad_single"]["price"] == "99.00"
    assert offerings["ad_campaign"]["price"] == "299.00"
    assert "numr_campaign" not in offerings
    assert sales.choose_product("Нужна реклама только в телеграм") == "ad_telegram"
    assert "€99.00" in sales.quote_text("ad_single")
    assert "оплатить" not in sales.quote_text("ad_single").lower() or "оформить" in sales.quote_text("ad_single").lower()
    assert sales.parse_invoice_lines("Example BV\nStreet 1, 1234 AB Amsterdam\na@example.com") == (
        "Example BV", "Street 1, 1234 AB Amsterdam", "a@example.com")
    assert sales.parse_invoice_lines("name\naddress\na@a.com") is None
    assert sales.response_window_open(datetime.utcnow() - timedelta(hours=2))
    assert not sales.response_window_open(datetime.utcnow() - timedelta(hours=25))
    assert not sales.meta_signature_is_valid(b"hello", "sha256=invalid", "secret")
    expected = "sha256=" + hmac.new(b"secret", b"hello", hashlib.sha256).hexdigest()
    assert sales.meta_signature_is_valid(b"hello", expected, "secret")
    assert not sales.meta_signature_is_valid(b"hello", expected, "")


async def test_webhook_and_payment_flow():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    # These three tables are all the test service needs.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=[
            IgSalesConversation.__table__, IgSalesEvent.__table__, IgSalesOrder.__table__])

    @asynccontextmanager
    async def sessions():
        async with factory() as session:
            yield session

    class Request:
        def __init__(self, body, signature):
            self.body = body
            self.headers = {"X-Hub-Signature-256": signature}
        async def read(self):
            return self.body

    class FakeBot:
        async def send_message(self, chat, message):
            pass

    env = {
        "IG_SALES_ENABLED": "1",
        "IG_SALES_SEND_ENABLED": "0",
        "IG_SALES_PAYMENTS_ENABLED": "0",
        "IG_SALES_ACCESS_TOKEN": "fake-test-token",
        "IG_SALES_ACCOUNT_ID": "123",
        "IG_SALES_APP_SECRET": "secret",
        "IG_SALES_VERIFY_TOKEN": "verify",
    }
    now_ms = int(datetime.utcnow().timestamp() * 1000)
    event = {
        "object": "instagram",
        "entry": [{"messaging": [{
            "sender": {"id": "customer1"},
            "recipient": {"id": "123"},
            "timestamp": now_ms,
            "message": {"mid": "mid1", "text": "Здравствуйте! Хочу заказать рекламу."},
        }]}],
    }
    body = json.dumps(event).encode()
    signature = "sha256=" + hmac.new(b"secret", body, hashlib.sha256).hexdigest()
    original_get_session = sales.get_session
    original_token = sales.config.ANTHROPIC_API_KEY
    sales.get_session = sessions
    sales.config.ANTHROPIC_API_KEY = ""
    try:
        with patch.dict(os.environ, env):
            bad = await sales.receive_webhook(Request(body, "sha256=abc"))
            assert bad.status == 403
            assert (await sales.receive_webhook(Request(body, signature))).status == 200
            assert (await sales.receive_webhook(Request(body, signature))).status == 200
            async with sessions() as session:
                messages = (await session.scalars(select(IgSalesEvent))).all()
                assert len(messages) == 1
            await sales.process_event(FakeBot(), messages[0])
            async with sessions() as session:
                conv = await session.get(IgSalesConversation, "customer1")
                assert conv.state == "quoted"
                assert conv.product_key == "ad_single"
            # No Mollie API call on quote, and no access when payments are disabled.
            async with sessions() as session:
                order_count = (await session.scalars(select(IgSalesOrder))).all()
                assert order_count == []
            # A customer says "Оформить" twice: only one Mollie payment is created.
            created = []
            original_pay_enabled = sales.payment_enabled
            original_create = sales.create_payment
            async def fake_create_payment(description, metadata, amount):
                created.append((metadata, amount))
                return {"id": "tr_automated", "checkout_url": "https://www.mollie.com/checkout/test"}
            sales.payment_enabled = lambda: True
            sales.create_payment = fake_create_payment
            try:
                async with sessions() as session:
                    conv = await session.get(IgSalesConversation, "customer1")
                first = await sales.create_checkout(conv)
                second = await sales.create_checkout(conv)
                assert "https://www.mollie.com/checkout/test" in first
                assert "https://www.mollie.com/checkout/test" in second
                assert len(created) == 1
                assert created[0][1] == "99.00"
            finally:
                sales.payment_enabled = original_pay_enabled
                sales.create_payment = original_create
            # Simulate a paid order and verify amount/status/duplicate webhook guards.
            async with sessions() as session:
                session.add(IgSalesOrder(id="order1", ig_user_id="customer1", product_key="ad_single",
                        amount="99.00", status="open", payment_id="tr_test123"))
                await session.commit()
            payment = {"status": "paid", "metadata": {"kind": "ig_ad_sale", "order_id": "order1"},
                       "amount": {"value": "98.00", "currency": "EUR"}}
            await sales.on_payment(FakeBot(), "tr_test123", payment)
            async with sessions() as session:
                order = await session.get(IgSalesOrder, "order1")
                assert order.status == "open"
            payment["amount"]["value"] = "99.00"
            await sales.on_payment(FakeBot(), "tr_test123", payment)
            await sales.on_payment(FakeBot(), "tr_test123", payment)
            async with sessions() as session:
                order = await session.get(IgSalesOrder, "order1")
                assert order.status == "paid"
                conv = await session.get(IgSalesConversation, "customer1")
                assert conv.state == "paid"
    finally:
        sales.get_session = original_get_session
        sales.config.ANTHROPIC_API_KEY = original_token
        await engine.dispose()


def main():
    test_policy_and_prices()
    asyncio.run(test_webhook_and_payment_flow())
    print("[OK] Instagram Direct: HMAC + dedupe + pricing + payment verification + invoices input")


if __name__ == "__main__":
    main()
