"""Афиша с сайта: проверка анкеты, заявка с постером → оплата, лента одобренных событий."""
import io
import json
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import config
from database.models import Base, EventListing
from utils import afisha_manage, afisha_site

TODAY = date(2026, 10, 12)
GOOD = {"title": "Вечер стендапа", "description": "Русскоязычный стендап в центре города, два часа шуток.",
        "date": "2026-10-20", "time": "19:30", "city": "Amsterdam", "venue": "Comedy Café",
        "link": "tickets.example.nl/stand", "email": "Org@Example.nl", "category": "стендап"}


def poster() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (800, 1000), (200, 80, 40)).save(buf, "PNG")
    return buf.getvalue()


class ValidateTests(unittest.TestCase):
    def test_good(self):
        d, err = afisha_site.validate(GOOD, TODAY)
        self.assertEqual(err, "")
        self.assertEqual(d["link"], "https://tickets.example.nl/stand")
        self.assertEqual(d["invoice_email"], "org@example.nl")
        self.assertEqual(d["month_key"], "2026-10")
        self.assertEqual(d["event_date"], "20.10.2026")
        self.assertFalse(d["is_nationwide"])

    def test_errors(self):
        for patch_, msg in [({"date": "2026-10-01"}, "прошла"), ({"email": "nope"}, "почту"),
                            ({"title": ""}, "название"), ({"city": "", "online": ""}, "город"),
                            ({"end": "2026-10-19"}, "окончания"), ({"time": "25:00"}, "время")]:
            d, err = afisha_site.validate({**GOOD, **patch_}, TODAY)
            self.assertIsNone(d)
            self.assertIn(msg, err)

    def test_online_and_unknown_category(self):
        d, _ = afisha_site.validate({**GOOD, "city": "", "online": "1", "category": "что-то"}, TODAY)
        self.assertTrue(d["is_nationwide"])
        self.assertEqual(d["category"], "другое")


class SubmitAndFeedTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{Path(self.tmp.name) / 't.db'}")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.pay = AsyncMock(return_value={"id": "tr_1", "checkout_url": "https://pay.example/1"})
        self.patches = [patch.object(afisha_site, "get_session", self.sessions),
                        patch.object(afisha_manage, "get_session", self.sessions),
                        patch.object(afisha_site, "create_payment", self.pay),
                        patch.object(afisha_site, "POSTER_DIR", self.tmp.name),
                        patch.object(afisha_site, "validate", lambda f: ValidateTests_validate(f)),
                        patch.object(config, "payments_enabled", lambda: True)]
        for p in self.patches:
            p.start()
        app = web.Application()
        afisha_site.install_routes(app)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        for p in self.patches:
            p.stop()
        await self.engine.dispose()
        self.tmp.cleanup()

    async def post(self, fields, img=b""):
        form = aiohttp.FormData(default_to_multipart=True)
        for k, v in fields.items():
            form.add_field(k, v)
        if img:
            form.add_field("poster", img, filename="p.png", content_type="image/png")
        r = await self.client.post("/api/afisha/submit", data=form)
        return r.status, json.loads(await r.text())

    async def test_submit_creates_unpaid_listing_and_payment(self):
        status, body = await self.post(GOOD, poster())
        self.assertEqual(status, 200, body)
        self.assertEqual(body["checkout_url"], "https://pay.example/1")
        meta = self.pay.await_args.args[1]
        self.assertEqual(meta["kind"], "afisha")
        self.assertEqual(self.pay.await_args.args[2], config.AFISHA_PRICE)
        async with self.sessions() as s:
            ev = (await s.scalars(select(EventListing))).one()
        self.assertEqual((ev.status, ev.source, ev.payment_id, ev.venue), ("awaiting_payment", "site", "tr_1", "Comedy Café"))
        self.assertTrue(Path(afisha_site.poster_path(ev.id)).exists())

    async def test_submit_needs_poster(self):
        status, body = await self.post(GOOD)
        self.assertEqual(status, 400)
        self.assertIn("постер", body["error"])

    async def test_poster_public_only_when_approved(self):
        status, _ = await self.post(GOOD, poster())
        self.assertEqual(status, 200)
        r = await self.client.get("/ev-photo/1")
        self.assertEqual(r.status, 404)
        async with self.sessions() as s:
            ev = await s.get(EventListing, 1)
            ev.status = "approved"
            await s.commit()
        r = await self.client.get("/ev-photo/1")
        self.assertEqual((r.status, r.content_type), (200, "image/jpeg"))

    async def test_large_poster_passes_body_limit(self):
        app = web.Application(client_max_size=10 * 1024 * 1024)
        afisha_site.install_routes(app)
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            big = poster() + b"\0" * (3 * 1024 * 1024)  # 3 МБ: больше стандартного лимита aiohttp
            form = aiohttp.FormData(default_to_multipart=True)
            for k, v in GOOD.items():
                form.add_field(k, v)
            form.add_field("poster", big, filename="p.png", content_type="image/png")
            r = await client.post("/api/afisha/submit", data=form)
            self.assertEqual(r.status, 200, await r.text())
        finally:
            await client.close()

    async def test_feed_shows_only_approved_upcoming(self):
        now = datetime.utcnow()
        async with self.sessions() as s:
            s.add_all([
                EventListing(title="Да", month_key="2026-10", status="approved", starts_at=now + timedelta(days=2),
                             ends_at=now + timedelta(days=2, hours=3), city="Utrecht", event_time="20:00", category="концерт"),
                EventListing(title="Не оплачено", month_key="2026-10", status="awaiting_payment",
                             starts_at=now + timedelta(days=2), ends_at=now + timedelta(days=3)),
                EventListing(title="Прошло", month_key="2026-10", status="approved",
                             starts_at=now - timedelta(days=3), ends_at=now - timedelta(days=2)),
            ])
            await s.commit()
        r = await self.client.get("/api/afisha/events")
        body = json.loads(await r.text())
        items = body["events"]
        self.assertEqual(body["hidden"], [])
        self.assertEqual([i["h"] for i in items], ["Да"])
        self.assertEqual((items[0]["city"], items[0]["time"], items[0]["cat"]), ("Utrecht", "20:00", "концерт"))
        self.assertTrue(items[0]["key"].startswith("u"))


_real_validate = afisha_site.validate


def ValidateTests_validate(fields):
    return _real_validate(fields, TODAY)


if __name__ == "__main__":
    unittest.main()
