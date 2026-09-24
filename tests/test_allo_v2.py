"""Real database tests for the no-plugin Allo checkout state transitions."""
import asyncio
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from database.models import AlloWebCode, AlloWebSale, Base
from utils import allo_v2


class Request:
    def __init__(self, data=None):
        self.data = data or {}
        self.headers = {}
        self.content_length = 100
        self.match_info = {}

    async def json(self):
        return self.data


class AlloV2Tests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "content").mkdir()
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{self.root / 'test.db'}")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.orig = (allo_v2.get_session, allo_v2.ROOT, allo_v2.create_payment,
                     allo_v2.send_email_message, allo_v2.get_payment)
        allo_v2.get_session = self.sessions
        allo_v2.ROOT = self.root
        self.payments = []

        async def create_payment(_description, metadata, amount):
            self.payments.append((metadata, amount))
            return {"id": "tr_" + str(len(self.payments)), "checkout_url": "https://mollie.test/checkout"}

        allo_v2.create_payment = create_payment
        allo_v2.send_email_message = AsyncMock(return_value=(True, ""))
        os.environ["ALLO_CODE_ENCRYPTION_KEY"] = "test-encryption-secret"
        self.start = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
        self.event = {
            "key": "city-test", "starts_at": self.start, "status": "published",
            "category": "city", "title": "Тестовый город", "place": "Test",
            "meeting": "Test Centraal, главный вход", "duration": "11:00–16:00",
            "intro": "День в городе", "route": ["Станция", "Старый город"],
            "included": ["Кофе"], "extra": ["Поезд"],
            "price_cents": 4900, "capacity": 1,
            "photos": [{"url": f"https://example.org/{i}.jpg", "alt": f"Фото {i}"} for i in range(3)],
        }
        self.write_events([self.event])
        (self.root / "content" / "allo_settings.json").write_text('{"gift_amounts_eur":[50]}')

    async def asyncTearDown(self):
        (allo_v2.get_session, allo_v2.ROOT, allo_v2.create_payment,
         allo_v2.send_email_message, allo_v2.get_payment) = self.orig
        await self.engine.dispose()
        self.tmp.cleanup()
        os.environ.pop("ALLO_CODE_ENCRYPTION_KEY", None)

    def write_events(self, events):
        (self.root / "content" / "allo_events.json").write_text(json.dumps(events, ensure_ascii=False))

    @staticmethod
    def data(response):
        return json.loads(response.text)

    async def test_event_capacity_cannot_exceed_eight(self):
        self.event["capacity"] = 9
        self.write_events([self.event])
        self.assertEqual(allo_v2._events(), [])
        self.event["capacity"] = 8
        self.write_events([self.event])
        self.assertEqual(len(allo_v2._events()), 1)

    async def test_server_sets_price_and_reserves_last_seat(self):
        request = Request({"event_key": "city-test", "name": "Алекс", "email": "alex@example.org",
                           "amount_cents": 0, "agreed": True})
        first = await allo_v2.book(request)
        self.assertEqual(first.status, 200)
        self.assertEqual(self.payments[0][1], "49.00")
        second = await allo_v2.book(request)
        self.assertEqual(second.status, 409)
        meta = self.payments[0][0]
        await allo_v2.on_payment("tr_1", {"id": "tr_1", "status": "paid", "metadata": meta,
                                          "amount": {"currency": "EUR", "value": "49.00"}})
        await allo_v2.on_payment("tr_1", {"id": "tr_1", "status": "paid", "metadata": meta,
                                          "amount": {"currency": "EUR", "value": "49.00"}})
        self.assertEqual(allo_v2.send_email_message.await_count, 1)
        async with self.sessions() as session:
            sale = await session.get(AlloWebSale, meta["sale_id"])
            self.assertEqual(sale.status, "paid")

    async def test_same_email_cannot_hold_a_second_seat(self):
        self.event["capacity"] = 2
        self.write_events([self.event])
        request = Request({"event_key": "city-test", "name": "Алекс",
                           "email": "alex@example.org", "agreed": True})
        first = await allo_v2.book(request)
        second = await allo_v2.book(request)
        self.assertEqual(first.status, 200)
        self.assertEqual(second.status, 409)
        self.assertEqual(len(self.payments), 1)
        other = await allo_v2.book(Request({"event_key": "city-test", "name": "Друг",
                                           "email": "friend@example.org", "agreed": True}))
        self.assertEqual(other.status, 200)

    async def test_payment_after_walk_start_does_not_confirm_a_seat(self):
        request = Request({"event_key": "city-test", "name": "Алекс",
                           "email": "alex@example.org", "agreed": True})
        await allo_v2.book(request)
        meta = self.payments[0][0]
        async with self.sessions() as session:
            sale = await session.get(AlloWebSale, meta["sale_id"])
            sale.event_starts_at = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
            await session.commit()
        await allo_v2.on_payment("tr_1", {"id": "tr_1", "status": "paid",
                                          "metadata": meta,
                                          "amount": {"currency": "EUR", "value": "49.00"}})
        async with self.sessions() as session:
            sale = await session.get(AlloWebSale, meta["sale_id"])
            self.assertEqual(sale.status, "refund_requested")
        self.assertEqual(allo_v2.send_email_message.await_count, 0)

    async def test_pass_works_only_for_city_or_nature(self):
        async with self.sessions() as session:
            session.add(AlloWebCode(code_hash=allo_v2._hash_code("ALLO-PASS-TEST"),
                                    kind="pass", owner_email="alex@example.org", total_uses=1))
            await session.commit()
        request = Request({"event_key": "city-test", "name": "Алекс", "email": "alex@example.org",
                           "code": "ALLO-PASS-TEST", "agreed": True})
        result = await allo_v2.book(request)
        self.assertEqual(self.data(result)["status"], "paid")
        self.assertFalse(self.payments)
        async with self.sessions() as session:
            code = await session.scalar(select(AlloWebCode))
            self.assertEqual(await allo_v2._code_available(session, code), 0)

    async def test_gift_issued_once_after_paid(self):
        request = Request({"name": "Алекс", "email": "alex@example.org",
                           "recipient_name": "Друг", "recipient_email": "friend@example.org",
                           "amount_cents": 5000, "agreed": True})
        result = await allo_v2.buy_gift(request)
        self.assertEqual(result.status, 200)
        meta = self.payments[0][0]
        payment = {"id": "tr_1", "status": "paid", "metadata": meta,
                   "amount": {"currency": "EUR", "value": "50.00"}}
        await allo_v2.on_payment("tr_1", payment)
        await allo_v2.on_payment("tr_1", payment)
        async with self.sessions() as session:
            count = await session.scalar(select(func.count()).select_from(AlloWebCode))
            code = await session.scalar(select(AlloWebCode))
        self.assertEqual(count, 1)
        self.assertEqual(code.value_cents, 5000)
        self.assertEqual(allo_v2.send_email_message.await_count, 1)

    async def test_gift_balance_keeps_unspent_amount(self):
        async with self.sessions() as session:
            session.add(AlloWebCode(code_hash=allo_v2._hash_code("ALLO-GIFT-TEST"),
                                    kind="gift", owner_email="friend@example.org",
                                    value_cents=5000))
            await session.commit()
        request = Request({"event_key": "city-test", "name": "Друг",
                           "email": "friend@example.org", "code": "ALLO-GIFT-TEST",
                           "agreed": True})
        response = await allo_v2.book(request)
        self.assertEqual(self.data(response)["status"], "paid")
        async with self.sessions() as session:
            code = await session.scalar(select(AlloWebCode))
            self.assertEqual(await allo_v2._code_available(session, code), 100)

    async def test_reconcile_recovers_missed_webhook(self):
        request = Request({"event_key": "city-test", "name": "Алекс",
                           "email": "alex@example.org", "agreed": True})
        await allo_v2.book(request)
        meta = self.payments[0][0]
        allo_v2.get_payment = AsyncMock(return_value={
            "id": "tr_1", "status": "paid", "metadata": meta,
            "amount": {"currency": "EUR", "value": "49.00"}})
        await allo_v2.reconcile_once()
        async with self.sessions() as session:
            sale = await session.get(AlloWebSale, meta["sale_id"])
            self.assertEqual(sale.status, "paid")

    async def test_paid_order_keeps_original_meeting_after_catalog_changes(self):
        request = Request({"event_key": "city-test", "name": "Алекс",
                           "email": "alex@example.org", "agreed": True})
        await allo_v2.book(request)
        meta = self.payments[0][0]
        self.write_events([])
        await allo_v2.on_payment("tr_1", {"id": "tr_1", "status": "paid",
                                          "metadata": meta,
                                          "amount": {"currency": "EUR", "value": "49.00"}})
        async with self.sessions() as session:
            sale = await session.get(AlloWebSale, meta["sale_id"])
            self.assertEqual(sale.status, "paid")
            self.assertEqual(sale.event_meeting, "Test Centraal, главный вход")
        self.assertIn("Test Centraal", allo_v2.send_email_message.call_args.args[2])


if __name__ == "__main__":
    unittest.main()
