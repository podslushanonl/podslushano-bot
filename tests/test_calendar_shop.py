"""Календарь Nederland 2027: форма заказа, оплата, привязка в боте, ICS и напоминания."""
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from aiohttp import web
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import calendar_shop_runtime as shop
import config
from calendar_print import core
from database.models import Base


FORM = {
    "title": "Календарь семьи Ивановых", "region": "M",
    "buyer_name": "Анна Иванова", "street": "Damrak 1", "postcode": "1012ab", "city": "Amsterdam",
    "email": "Anna@Example.com", "phone": "", "consent": "1",
    "d_0": "3", "m_0": "2", "label_0": "ДР Маши", "kind_0": "bday",
    "d_1": "21", "m_1": "11", "label_1": "5 лет в NL", "kind_1": "date",
}


class CoreTests(unittest.TestCase):
    def test_clean_order_limits_and_validates(self):
        raw = {"region": "x", "dates": [{"m": 2, "d": 30, "label": "нет такой даты"}]
               + [{"m": 1, "d": i, "label": f"Дата {i}"} for i in range(1, 25)]}
        o = core.clean_order(raw)
        self.assertEqual(o["region"], "")
        self.assertEqual(len(o["dates"]), core.MAX_PERSONAL_DATES)

    def test_ics_contains_personal_yearly_birthday(self):
        ics = core.build_ics({"region": "M", "dates": [{"m": 2, "d": 3, "label": "ДР Маши", "kind": "bday"}]})
        self.assertTrue(ics.startswith("BEGIN:VCALENDAR"))
        self.assertIn("SUMMARY:🎂 ДР Маши", ics)
        self.assertIn("RRULE:FREQ=YEARLY", ics)
        self.assertIn("Koningsdag", ics)
        self.assertNotIn("· Zuid", ics)  # только каникулы своего региона
        self.assertEqual(ics.count("BEGIN:VEVENT"), ics.count("END:VEVENT"))

    def test_reminders(self):
        o = {"dates": [{"m": 2, "d": 3, "label": "ДР Маши", "kind": "bday"}]}
        keys = [k for k, _ in core.reminders_for(o, dt.date(2027, 1, 25))]
        self.assertTrue(any(k.startswith("dead:2-1") for k in keys))
        texts = [t for _, t in core.reminders_for(o, dt.date(2027, 2, 3))]
        self.assertIn("🎂 Сегодня: ДР Маши", texts)
        self.assertTrue(core.reminders_for({}, dt.date(2027, 4, 26)))  # завтра Koningsdag

    def test_print_html_has_personal_cover_and_qr(self):
        h = core.build_html({"code": "ABC234", "title": "Календарь семьи Ивановых",
                             "dates": [{"m": 2, "d": 3, "label": "ДР Маши", "kind": "bday"}]})
        self.assertIn("Календарь семьи Ивановых", h)
        self.assertIn("ДР Маши", h)
        self.assertIn("Календарь № ABC234", h)
        self.assertEqual(h.count('class="page'), 14)


class FormTests(unittest.TestCase):
    def test_valid_form(self):
        fields, err = shop.parse_form(FORM)
        self.assertIsNone(err)
        self.assertEqual(fields["postcode"], "1012 AB")
        self.assertEqual(fields["email"], "anna@example.com")
        self.assertEqual(len(fields["order"]["dates"]), 2)

    def test_errors(self):
        self.assertIsNotNone(shop.parse_form({**FORM, "postcode": "12"})[1])
        self.assertIsNotNone(shop.parse_form({**FORM, "consent": ""})[1])
        self.assertIsNotNone(shop.parse_form({**FORM, "d_0": "31", "m_0": "2"})[1])


class FlowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{Path(self.tmp.name) / 't.db'}")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.p = [patch.object(shop, "get_session", self.sessions),
                  patch.multiple(config, WEBHOOK_BASE_URL="https://bot.test", BOT_URL="https://t.me/podslushano_nl_bot", ADMIN_IDS=[1]),
                  patch.object(config, "payments_enabled", return_value=True)]
        for x in self.p:
            x.start()

    async def asyncTearDown(self):
        for x in self.p:
            x.stop()
        await self.engine.dispose()
        self.tmp.cleanup()

    async def _order(self):
        created = []

        async def create_payment(description, metadata, amount, method=None, redirect_url=None):
            created.append((metadata, amount, redirect_url))
            return {"id": "tr_cal", "checkout_url": "https://mollie.test/pay"}

        class Req:
            async def post(self):
                return FORM
        with patch("utils.payments.create_payment", create_payment):
            with self.assertRaises(web.HTTPSeeOther) as r:
                await shop.create_order(Req())
        self.assertEqual(r.exception.location, "https://mollie.test/pay")
        self.assertEqual(created[0][0]["kind"], "calendar")
        self.assertEqual(created[0][1], "30.00")
        async with self.sessions() as s:
            return await s.scalar(select(shop.CalendarOrder))

    async def test_order_pay_bind_and_feed(self):
        row = await self._order()
        self.assertEqual(row.status, "new")
        self.assertEqual(row.region, "M")
        bot = SimpleNamespace(send_message=AsyncMock(), send_document=AsyncMock())
        with patch.object(shop, "_notify_admins", AsyncMock()) as notify:
            await shop.on_payment(bot, "tr_cal", {"status": "paid", "metadata": {"kind": "calendar", "code": row.code}})
            await shop.asyncio.sleep(0)
        notify.assert_called_once()
        async with self.sessions() as s:
            row = await s.get(shop.CalendarOrder, row.id)
        self.assertEqual(row.status, "paid")

        msg = SimpleNamespace(from_user=SimpleNamespace(id=42), answer=AsyncMock())
        await shop.handle_start(msg, row.code.lower())
        text = msg.answer.call_args.args[0]
        self.assertIn("подключён", text)
        async with self.sessions() as s:
            self.assertEqual((await s.get(shop.CalendarOrder, row.id)).tg_user_id, 42)

        req = SimpleNamespace(match_info={"token": row.token})
        resp = await shop.ics_feed(req)
        self.assertIn("ДР Маши", resp.body.decode())

        bot2 = SimpleNamespace(send_message=AsyncMock())
        n = await shop._send_reminders(bot2, dt.date(2027, 2, 3))
        self.assertGreaterEqual(n, 1)
        again = await shop._send_reminders(bot2, dt.date(2027, 2, 3))
        self.assertEqual(again, 0)  # без дублей

    async def test_unpaid_order_is_not_exposed(self):
        row = await self._order()
        msg = SimpleNamespace(from_user=SimpleNamespace(id=1), answer=AsyncMock())
        await shop.handle_start(msg, row.code)
        self.assertIn("Не нашёл", msg.answer.call_args.args[0])
        with self.assertRaises(web.HTTPNotFound):
            await shop.ics_feed(SimpleNamespace(match_info={"token": row.token}))

    async def test_admin_text(self):
        row = await self._order()
        text = shop._admin_text(row)
        self.assertIn("1012 AB Amsterdam", text)
        self.assertIn("ДР Маши", text)


if __name__ == "__main__":
    unittest.main()
