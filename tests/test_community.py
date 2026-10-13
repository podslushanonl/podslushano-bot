"""Сообщество приложения: чаты, посты, правила, фильтры, жалобы и модерация."""
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from database.models import AppUser, Base
from utils import app_api, community
from utils.site_api import make_token


class CommunityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{Path(self.tmp.name) / 't.db'}")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.patches = [patch.object(app_api, "get_session", self.sessions), patch.object(community, "get_session", self.sessions)]
        for p in self.patches:
            p.start()
        community._hits.clear()
        old = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=10)
        async with self.sessions() as s:
            s.add_all([AppUser(id=1, email="a@x.nl", name="Анна", city="Utrecht", created_at=old),
                       AppUser(id=2, email="b@x.nl", name="Борис", created_at=old),
                       AppUser(id=3, email="c@x.nl", name="", created_at=old),
                       AppUser(id=4, email="d@x.nl", name="Дина"), AppUser(id=5, email="e@x.nl", name="Ева", created_at=old)])
            await s.commit()
        app = web.Application()
        community.install_routes(app)
        self.c = TestClient(TestServer(app))
        await self.c.start_server()

    async def asyncTearDown(self):
        await self.c.close()
        for p in self.patches:
            p.stop()
        await self.engine.dispose()
        self.tmp.cleanup()

    def h(self, uid):
        return {"Authorization": "Bearer " + make_token({"k": "app", "u": uid}, 3600)}

    async def post(self, path, uid, **body):
        return await self.c.post(path, json=body, headers=self.h(uid) if uid else {})

    async def test_rooms_seeded(self):
        d = await (await self.c.get("/api/app/rooms")).json()
        self.assertIn("amsterdam", [r["slug"] for r in d["rooms"]])

    async def test_write_requires_login_name_rules(self):
        url = "/api/app/rooms/utrecht/messages"
        self.assertEqual((await self.post(url, None, text="привет")).status, 401)
        self.assertEqual((await self.post(url, 3, text="привет")).status, 409)   # без имени
        self.assertEqual((await self.post(url, 1, text="привет")).status, 428)   # правила
        await self.post("/api/app/rules", 1)
        r = await self.post(url, 1, text="Привет всем из Utrecht!")
        self.assertEqual(r.status, 200)
        d = await (await self.c.get(url, headers=self.h(2))).json()
        self.assertEqual([m["text"] for m in d["messages"]], ["Привет всем из Utrecht!"])
        self.assertFalse(d["messages"][0]["mine"])
        after = await (await self.c.get(url + f"?after={d['messages'][0]['id']}")).json()
        self.assertEqual(after["messages"], [])

    async def test_filters_and_rate_limit(self):
        url = "/api/app/rooms/nl/messages"
        for uid in (1, 4):
            await self.post("/api/app/rules", uid)
        bad = await (await self.post(url, 1, text="ну ты и сука")).json()
        self.assertIn("мата", bad["error"])
        link_new = await self.post(url, 4, text="заходите на example.com")
        self.assertEqual(link_new.status, 400)  # новый аккаунт: ссылки нельзя
        self.assertEqual((await self.post(url, 1, text="заходите на example.com")).status, 200)
        self.assertEqual((await self.post(url, 1, text="и ещё раз")).status, 429)

    async def test_reports_autohide_moderation_ban_and_block(self):
        for uid in (1, 2, 3, 4, 5):
            await self.post("/api/app/rules", uid)
        p = await (await self.post("/api/app/posts", 1, text="Продаю велосипед в Utrecht")).json()
        pid = p["post"]["id"]
        self.assertEqual(p["post"]["city"], "Utrecht")
        await self.post("/api/app/report", 2, kind="post", id=pid)
        await self.post("/api/app/report", 2, kind="post", id=pid)  # повтор не считается
        feed = await (await self.c.get("/api/app/posts")).json()
        self.assertEqual(len(feed["posts"]), 1)
        await self.post("/api/app/report", 4, kind="post", id=pid)
        await self.post("/api/app/report", 5, kind="post", id=pid)
        feed = await (await self.c.get("/api/app/posts")).json()
        self.assertEqual(feed["posts"], [])  # 3 жалобы от разных людей — скрыт
        async with self.sessions() as s:
            from sqlalchemy import select
            from database.models import ContentReport
            rid = (await s.execute(select(ContentReport.id))).scalars().first()
        self.assertIn("снова видно", await community.moderate(rid, "keep"))
        self.assertEqual(len((await (await self.c.get("/api/app/posts")).json())["posts"]), 1)
        self.assertIn("заблокирован", await community.moderate(rid, "ban1"))
        r = await self.post("/api/app/posts", 1, text="Я снова тут")
        self.assertEqual(r.status, 403)

        p2 = await (await self.post("/api/app/posts", 2, text="Ищу няню в Rotterdam")).json()
        await self.post("/api/app/block", 4, user_id=2)
        mine = await (await self.c.get("/api/app/posts", headers=self.h(4))).json()
        self.assertNotIn(p2["post"]["id"], [x["id"] for x in mine["posts"]])
        self.assertEqual((await self.post("/api/app/delete", 4, kind="post", id=p2["post"]["id"])).status, 403)
        self.assertEqual((await self.post("/api/app/delete", 2, kind="post", id=p2["post"]["id"])).status, 200)


if __name__ == "__main__":
    unittest.main()
