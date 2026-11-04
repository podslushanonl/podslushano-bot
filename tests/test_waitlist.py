"""Лист ожидания свечи: запись в один шаг с согласием, письмо с отпиской, число для баннера."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from database.models import Base, Meta
from utils import waitlist as wl


class WaitlistTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{Path(self.tmp.name) / 't.db'}")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.mail = AsyncMock(return_value=(True, ""))
        self.patches = [patch.object(wl, "get_session", self.sessions), patch.object(wl, "send_email_message", self.mail)]
        for p in self.patches:
            p.start()
        wl._hits.clear()
        app = web.Application()
        wl.install_routes(app)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        for p in self.patches:
            p.stop()
        await self.engine.dispose()
        self.tmp.cleanup()

    async def stats(self):
        return json.loads(await (await self.client.get("/api/waitlist/candle")).text())

    async def test_join_in_one_step_with_unsubscribe(self):
        r = await self.client.post("/api/waitlist/candle/join", json={"email": "a@b.nl"})
        self.assertEqual(r.status, 400)                              # без галочки согласия не записываем
        r = await self.client.post("/api/waitlist/candle/join", json={"email": "A@B.nl", "consent": "1"})
        j = json.loads(await r.text())
        self.assertEqual((j["ok"], j["already"], j["position"], j["count"]), (True, False, 1, 1))
        self.assertEqual(await self.stats(), {"count": 1, "stock": 24, "buy": ""})   # сразу в списке
        subject, html, text = self.mail.await_args.args[1:4]
        self.assertIn("Вы в листе ожидания", subject)
        self.assertNotIn("confirm", html)
        self.assertIn("Отписаться", html)
        self.assertIn("/api/waitlist/unsubscribe?t=", text)
        r = await self.client.post("/api/waitlist/candle/join", json={"email": "a@b.nl", "consent": "1"})
        self.assertTrue(json.loads(await r.text())["already"])
        self.assertEqual(self.mail.await_count, 1)                   # второе письмо не шлём
        link = text[text.index("/api/waitlist/unsubscribe?t="):].split()[0]
        await self.client.post(link)
        self.assertEqual((await self.stats())["count"], 0)

    async def test_mail_failure_still_keeps_place(self):
        self.mail.return_value = (False, "resend down")
        r = await self.client.post("/api/waitlist/candle/join", json={"email": "c@d.nl", "consent": "on"})
        self.assertEqual(r.status, 200)
        self.assertEqual((await self.stats())["count"], 1)

    async def test_buy_link(self):
        async with self.sessions() as s:
            s.add(Meta(key="waitlist_open_url:candle", value="https://soulofsol.example/buy"))
            await s.commit()
        self.assertEqual((await self.stats())["buy"], "https://soulofsol.example/buy")

    async def test_unknown_campaign(self):
        self.assertEqual((await self.client.get("/api/waitlist/nope")).status, 404)


if __name__ == "__main__":
    unittest.main()
