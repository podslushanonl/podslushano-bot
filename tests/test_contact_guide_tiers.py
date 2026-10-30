"""КонтактGuide с сайта: тарифы «Стандарт»/«Премиум», контакты по полям, фото премиума,
разбор Instagram из ссылки и напоминание о посте в канале для премиума."""
import io
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import ad_contact_guide_web_runtime as guide
import config
from database.models import Base, Meta, Specialist
from handlers import spotlight
from utils import specialist_photo
from utils.contact_links import parse_contact_links

DESC = "Бухгалтерия и налоги для ZZP и частных лиц, консультации на русском языке."


class Req:
    def __init__(self, data):
        self.data, self.query = data, {}

    async def post(self):
        return self.data


def form(**kw):
    d = {"plan": "year", "name": "TaxNavigator", "category": "бухгалтер", "online": "1", "city": "",
         "description": DESC, "email": "a@b.nl", "terms": "1"}
    d.update(kw)
    return d


def jpeg():
    buf = io.BytesIO()
    Image.new("RGB", (400, 400), (200, 90, 40)).save(buf, "PNG")
    return SimpleNamespace(file=io.BytesIO(buf.getvalue()), filename="p.png")


class CheckoutTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{Path(self.tmp.name) / 't.db'}")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.pay = AsyncMock(return_value={"id": "tr_1", "checkout_url": "https://pay/1"})
        self.patches = [patch.object(guide, "get_session", self.sessions), patch.object(spotlight, "get_session", self.sessions),
                        patch.object(guide.selfadd, "create_payment", self.pay),
                        patch.object(config, "payments_enabled", lambda: True),
                        patch.object(specialist_photo, "PHOTO_DIR", self.tmp.name)]
        for p in self.patches:
            p.start()

    async def asyncTearDown(self):
        for p in self.patches:
            p.stop()
        await self.engine.dispose()
        self.tmp.cleanup()

    async def post(self, **kw):
        r = await guide.contact_guide_checkout(Req(form(**kw)))
        return r.status, json.loads(r.text)

    async def spec(self):
        async with self.sessions() as s:
            return (await s.scalars(select(Specialist))).one()

    async def test_instagram_link_becomes_handle(self):
        status, body = await self.post(phone="+31681179002",
                                       instagram="https://www.instagram.com/tax_navigator_advice?igsh=x")
        self.assertEqual(status, 200, body)
        sp = await self.spec()
        self.assertEqual(sp.contact, "Телефон: +31681179002 · Instagram: @tax_navigator_advice")
        self.assertIn({"type": "instagram", "label": "📷 Instagram", "url": "https://instagram.com/tax_navigator_advice"},
                      parse_contact_links(sp.contact))

    async def test_standard_limits(self):
        status, body = await self.post(phone="+31681179002", instagram="@a_b", website="https://x.nl")
        self.assertEqual(status, 400)
        self.assertIn("до 2 контактов", body["error"])
        status, body = await self.post(phone="+31681179002", description=DESC * 5)
        self.assertEqual(status, 400)
        self.assertIn("до 300", body["error"])
        status, body = await self.post(telegram="https://t.me/x")
        self.assertEqual(status, 400)
        self.assertIn("Telegram", body["error"])
        self.pay.assert_not_awaited()

    async def test_premium_gets_long_text_all_contacts_and_photo(self):
        status, body = await self.post(plan="year_premium", description=DESC * 5, phone="+31681179002",
                                       whatsapp="+31681179002", instagram="@a_b", telegram="@tax_nav_bot",
                                       website="x.nl", public_email="info@x.nl", photo=jpeg())
        self.assertEqual(status, 200, body)
        sp = await self.spec()
        self.assertTrue(sp.is_premium)
        self.assertEqual(sp.contact.count(" · "), 5)
        self.assertTrue(specialist_photo.exists(sp.id))
        from utils.webserver import _photo_url
        self.assertTrue(_photo_url(sp).endswith(f"/sp-photo/{sp.id}"))

    async def test_photo_ignored_for_standard_and_old_form_still_works(self):
        status, _ = await self.post(contact="https://example.com", photo=jpeg())
        self.assertEqual(status, 200)
        sp = await self.spec()
        self.assertEqual(sp.contact, "https://example.com")
        self.assertFalse(specialist_photo.exists(sp.id))

    async def test_premium_due_for_channel_post(self):
        today = date(2026, 10, 30)
        async with self.sessions() as s:
            s.add_all([Specialist(name="A", category="юрист", city="", province="", status="active", is_premium=True),
                       Specialist(name="B", category="юрист", city="", province="", status="active", is_premium=True),
                       Specialist(name="C", category="юрист", city="", province="", status="active", is_premium=False)])
            await s.commit()
            ids = {x.name: x.id for x in (await s.scalars(select(Specialist))).all()}
            s.add(Meta(key=f"spotlight_channel:{ids['A']}", value=(today - timedelta(days=5)).isoformat()))
            await s.commit()
        self.assertEqual([x.name for x in await spotlight.premium_due(today)], ["B"])
        self.assertEqual(sorted(x.name for x in await spotlight.premium_due(today + timedelta(days=30))), ["A", "B"])


class LinkTests(unittest.TestCase):
    def test_old_cards_with_profile_links(self):
        links = parse_contact_links("+31 6 8117 9002 · instagram: @https://www.instagram.com/tax_navigator_advice?cpl=1")
        self.assertEqual(links[0]["url"], "https://instagram.com/tax_navigator_advice")
        self.assertEqual(parse_contact_links("telegram: @https://t.me/KOVA_Executive")[0]["url"], "https://t.me/KOVA_Executive")
        self.assertEqual(parse_contact_links("instagram: @fancy_beauty_space")[0]["url"], "https://instagram.com/fancy_beauty_space")


if __name__ == "__main__":
    unittest.main()
