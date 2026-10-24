"""Афиша на сайте из бота: список будущих событий, убрать и вернуть, скрытые события темы в ленте."""
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from database.models import Base, EventListing
from utils import afisha_manage as am
from utils import afisha_site

SITE = [{"key": "galkin", "h": "Максим Галкин", "date": "2099-11-20", "city": "Amsterdam"},
        {"key": "u1", "h": "Старая копия с сайта", "date": "2099-11-02", "city": ""}]


class ManageTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{Path(self.tmp.name) / 't.db'}")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.refresh = AsyncMock(return_value=True)
        self.patches = [patch.object(am, "get_session", self.sessions),
                        patch.object(afisha_site, "get_session", self.sessions),
                        patch.object(am, "site_events", AsyncMock(return_value=SITE)),
                        patch.object(am.wp, "refresh_site", self.refresh)]
        for p in self.patches:
            p.start()
        now = datetime.utcnow()
        async with self.sessions() as s:
            s.add(EventListing(title="Стендап", month_key="2099-11", status="approved", source="admin",
                               starts_at=now + timedelta(days=3), ends_at=now + timedelta(days=3, hours=4)))
            await s.commit()

    async def asyncTearDown(self):
        for p in self.patches:
            p.stop()
        await self.engine.dispose()
        self.tmp.cleanup()

    async def feed(self):
        app = web.Application()
        afisha_site.install_routes(app)
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            return json.loads(await (await client.get("/api/afisha/events")).text())
        finally:
            await client.close()

    async def test_list_merges_bot_and_theme_events(self):
        items = await am.upcoming()
        self.assertEqual([i["key"] for i in items], ["u1", "galkin"])
        self.assertEqual(items[0]["h"], "Стендап")   # своё событие берётся из базы, не с сайта

    async def test_remove_and_restore_theme_event(self):
        galkin = next(i for i in await am.upcoming() if i["key"] == "galkin")
        self.assertTrue(await am.remove(galkin))
        self.assertEqual([i["key"] for i in await am.upcoming()], ["u1"])
        self.assertEqual((await self.feed())["hidden"], ["galkin"])
        self.assertEqual([i["key"] for i in await am.removed()], ["galkin"])
        self.assertTrue(await am.restore("galkin"))
        self.assertEqual((await self.feed())["hidden"], [])
        self.assertEqual(self.refresh.await_count, 2)

    async def test_remove_and_restore_bot_event(self):
        mine = next(i for i in await am.upcoming() if i["key"] == "u1")
        self.assertTrue(await am.remove(mine))
        self.assertEqual((await self.feed())["events"], [])
        self.assertFalse(await am.remove(mine))   # повторно убрать нельзя
        self.assertEqual([i["key"] for i in await am.removed()], ["u1"])
        self.assertTrue(await am.restore("u1"))
        self.assertEqual([e["key"] for e in (await self.feed())["events"]], ["u1"])
        self.assertFalse(await am.restore("u1"))


if __name__ == "__main__":
    unittest.main()
