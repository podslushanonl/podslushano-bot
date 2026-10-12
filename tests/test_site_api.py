"""Site API: donations (one-off and monthly), business cabinet, scheduled gift cards."""
import json
import tempfile
import time
import unittest
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import config
from database.models import AlloWebSale, Base, Meta, Specialist, SpecialistEdit
from utils import allo_v2, site_api


class Req:
    def __init__(self, data=None, query=None, headers=None, bot=None):
        self.data = data or {}
        self.query = query or {}
        self.headers = {"Origin": "https://www.podslushano.nl", **(headers or {})}
        self.content_length = 100
        self.app = {"bot": bot}
        self.method = "GET"

    async def json(self):
        return self.data


def body(resp):
    return json.loads(resp.text)


class TokenTests(unittest.TestCase):
    def test_roundtrip_tamper_expiry_kind(self):
        t = site_api.make_token({"k": "cab", "e": "a@b.nl"}, 60)
        self.assertEqual(site_api.read_token(t, "cab")["e"], "a@b.nl")
        self.assertIsNone(site_api.read_token(t, "login"))
        raw, sig = t.split(".")
        self.assertIsNone(site_api.read_token(raw + "x." + sig, "cab"))
        old = site_api.make_token({"k": "cab"}, -1)
        self.assertIsNone(site_api.read_token(old, "cab"))


class SiteApiDbTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{Path(self.tmp.name) / 't.db'}")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.orig = (site_api.get_session, site_api.send_email_message, site_api.create_payment, site_api._mollie,
                     allo_v2.get_session, allo_v2.send_email_message, allo_v2.create_payment)
        site_api.get_session = self.sessions
        allo_v2.get_session = self.sessions
        self.mail = AsyncMock(return_value=(True, ""))
        site_api.send_email_message = self.mail
        allo_v2.send_email_message = self.mail
        self.created = []

        async def create_payment(description, metadata, amount, method=None, redirect_url=None):
            self.created.append((description, metadata, amount, redirect_url))
            return {"id": "tr_x", "checkout_url": "https://mollie.test/pay"}

        site_api.create_payment = create_payment
        self.calls = []

        async def mollie(method, path, body=None):
            self.calls.append((method, path, body))
            if path == "/customers":
                return {"id": "cst_1"}
            if path == "/payments":
                return {"id": "tr_first", "_links": {"checkout": {"href": "https://mollie.test/first"}}}
            if path.endswith("/subscriptions"):
                return {"id": "sub_1"}
            return {}

        site_api._mollie = mollie
        self.cfg = patch.multiple(config, SITE_URL="https://www.podslushano.nl", WEBHOOK_BASE_URL="https://bot.test")
        self.cfg.start()
        self.pay = patch.object(config, "payments_enabled", return_value=True)
        self.pay.start()
        async with self.sessions() as s:
            s.add_all([
                Specialist(name="Мастер маникюра", category="маникюр", city="Утрехт", province="Utrecht",
                           description="Маникюр", contact="+31 6 1234 5678", status="active",
                           source="self", invoice_email="owner@example.com", plan="year"),
                Specialist(name="Чужая карточка", category="юрист", city="Гаага", province="Zuid-Holland",
                           description="Юрист", contact="x", status="active", source="self",
                           invoice_email="other@example.com", plan="year"),
                Specialist(name="Из бота", category="психолог", city="", province="", description="Психолог",
                           contact="y", status="active", source="self", submitter_user_id=777, plan="month"),
            ])
            await s.commit()

    async def asyncTearDown(self):
        (site_api.get_session, site_api.send_email_message, site_api.create_payment, site_api._mollie,
         allo_v2.get_session, allo_v2.send_email_message, allo_v2.create_payment) = self.orig
        self.cfg.stop()
        self.pay.stop()
        await self.engine.dispose()
        self.tmp.cleanup()

    def session_for(self, **kw):
        return {"X-Cabinet": site_api.make_token({"k": "cab", **kw}, 600)}

    # ---- donations
    async def test_one_off_donation(self):
        r = await site_api.donate(Req({"amount_cents": 700, "monthly": False}))
        self.assertTrue(body(r)["ok"])
        desc, meta, amount, redirect = self.created[0]
        self.assertEqual((meta["kind"], meta["monthly"], amount), ("donation", False, "7.00"))
        self.assertEqual(redirect, "https://www.podslushano.nl/?donation=thanks")

    async def test_monthly_needs_email_then_creates_first_payment(self):
        r = await site_api.donate(Req({"amount_cents": 700, "monthly": True}))
        self.assertEqual(r.status, 400)
        r = await site_api.donate(Req({"amount_cents": 700, "monthly": True, "email": "D@Example.com"}))
        self.assertEqual(body(r)["checkout_url"], "https://mollie.test/first")
        pay = [c for c in self.calls if c[1] == "/payments"][0][2]
        self.assertEqual(pay["sequenceType"], "first")
        self.assertEqual(pay["customerId"], "cst_1")
        self.assertEqual(pay["metadata"]["email"], "d@example.com")

    async def test_subscription_created_once_with_cancel_link(self):
        payment = {"status": "paid", "amount": {"value": "7.00"},
                   "metadata": {"kind": "donation", "monthly": True, "customer_id": "cst_1", "amount": "7.00", "email": "d@example.com"}}
        await site_api.on_donation_payment("tr_first", payment)
        await site_api.on_donation_payment("tr_first", payment)
        subs = [c for c in self.calls if c[1].endswith("/subscriptions")]
        self.assertEqual(len(subs), 1)
        self.assertEqual(subs[0][2]["interval"], "1 month")
        self.assertEqual(self.mail.await_count, 1)
        self.assertIn("/api/donate/cancel?t=", self.mail.await_args.args[2])

    async def test_cancel_needs_post(self):
        t = site_api.make_token({"k": "don", "c": "cst_1", "s": "sub_1"}, 600)
        r = await site_api.donate_cancel(Req(query={"t": t}))
        self.assertIn("Отменить ежемесячный вклад?", r.text)
        self.assertFalse([c for c in self.calls if c[0] == "DELETE"])
        req = Req(query={"t": t})
        req.method = "POST"
        r = await site_api.donate_cancel(req)
        self.assertIn("Вклад отменён", r.text)
        self.assertEqual([c[:2] for c in self.calls if c[0] == "DELETE"], [("DELETE", "/customers/cst_1/subscriptions/sub_1")])

    # ---- cabinet
    async def test_login_only_mails_known_owner(self):
        await site_api.cabinet_login(Req({"email": "nobody@example.com"}))
        self.assertEqual(self.mail.await_count, 0)
        r = await site_api.cabinet_login(Req({"email": "Owner@Example.com"}))
        self.assertTrue(body(r)["ok"])
        link = self.mail.await_args.args[3].split("Войти: ")[1].split()[0]
        self.assertIn(link.replace("&", "&amp;"), self.mail.await_args.args[2])  # та же ссылка в кнопке письма
        token = link.split("?t=")[1]
        r = await site_api.cabinet_session(Req(query={"t": token}))
        sess = body(r)["session"]
        r = await site_api.cabinet_cards(Req(headers={"X-Cabinet": sess}))
        names = [c["name"] for c in body(r)["cards"]]
        self.assertEqual(names, ["Мастер маникюра"])

    async def test_telegram_owner_and_foreign_card(self):
        h = self.session_for(u=777)
        r = await site_api.cabinet_cards(Req(headers=h))
        self.assertEqual([c["name"] for c in body(r)["cards"]], ["Из бота"])
        r = await site_api.cabinet_color(Req({"id": 2, "color": "red"}, headers=h))
        self.assertEqual(r.status, 400)

    async def test_edit_goes_to_moderation_and_colour_applies(self):
        h = self.session_for(e="owner@example.com")
        with patch("handlers.cabinet._notify_admins_edit", AsyncMock()) as notify:
            r = await site_api.cabinet_edit(Req({"id": 1, "field": "description", "value": "Новый текст карточки"}, headers=h, bot=object()))
        self.assertTrue(body(r)["moderation"])
        notify.assert_awaited()
        r = await site_api.cabinet_edit(Req({"id": 1, "field": "description", "value": "Привіт"}, headers=h))
        self.assertEqual(r.status, 400)
        await site_api.cabinet_color(Req({"id": 1, "color": "blue"}, headers=h))
        async with self.sessions() as s:
            sp = await s.get(Specialist, 1)
            edits = (await s.scalars(select(SpecialistEdit))).all()
        self.assertEqual(sp.card_color, "blue")
        self.assertEqual(sp.description, "Маникюр")
        self.assertEqual([e.field for e in edits], ["description"])

    async def test_hide_delete_renew(self):
        h = self.session_for(e="owner@example.com")
        r = await site_api.cabinet_visibility(Req({"id": 1, "hidden": True}, headers=h))
        self.assertEqual(body(r)["status"], "hidden")
        r = await site_api.cabinet_renew(Req({"id": 1, "plan": "year"}, headers=h))
        self.assertEqual(body(r)["checkout_url"], "https://mollie.test/pay")
        self.assertEqual(self.created[-1][1]["kind"], "renew")
        self.assertEqual(self.created[-1][3], "https://www.podslushano.nl/cabinet/?paid=1")
        await site_api.cabinet_delete(Req({"id": 1}, headers=h))
        r = await site_api.cabinet_cards(Req(headers=h))
        self.assertEqual(body(r)["cards"], [])

    # ---- scheduled gift
    async def test_scheduled_gift_waits_for_its_day(self):
        today = allo_v2._ams_now().date()
        self.assertIsNone(allo_v2._parse_send_on(today.isoformat()))
        later = (today + timedelta(days=3)).isoformat()
        self.assertEqual(allo_v2._parse_send_on(later), later)
        self.assertFalse(allo_v2._gift_due(later))
        self.assertTrue(allo_v2._gift_due((today - timedelta(days=1)).isoformat()))
        async with self.sessions() as s:
            s.add(AlloWebSale(token="t" * 30, kind="gift", buyer_name="Оля", buyer_email="o@example.com",
                              recipient_name="Аня", recipient_email="a@example.com", gross_cents=5000,
                              amount_cents=5000, status="paid", send_on=later))
            await s.commit()
        await allo_v2._deliver_sale(1)
        async with self.sessions() as s:
            sale = await s.get(AlloWebSale, 1)
        self.assertEqual(sale.email_state, "pending")


if __name__ == "__main__":
    unittest.main()
