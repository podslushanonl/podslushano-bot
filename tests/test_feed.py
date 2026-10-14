"""Живая лента приложения: фото, лайки, комментарии, репосты, «Друзья» и «Рядом».

На SQLite всегда; с TEST_DATABASE_URL — ещё и на PostgreSQL.
"""
import base64
import io
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from PIL import Image
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from database import db
from database.models import AppUser, Base, Friendship, FriendStatus
from utils import app_api, community, feed, realtime, social
from utils.site_api import make_token

PG_URL = os.getenv("TEST_DATABASE_URL", "")


def jpeg_b64(color=(200, 80, 40)) -> str:
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), color).save(buf, "JPEG")
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


class FeedBase:
    url = ""

    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_async_engine(self.url or f"sqlite+aiosqlite:///{Path(self.tmp.name) / 't.db'}")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.patches = [patch.object(m, "get_session", self.sessions) for m in (app_api, community, feed, realtime, social)]
        for p in self.patches:
            p.start()
        community._hits.clear()
        old = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=10)
        async with self.sessions() as s:
            s.add_all([
                AppUser(id=1, email="a@x.nl", name="Анна", city="Utrecht", created_at=old, rules_at=old),
                AppUser(id=2, email="b@x.nl", name="Борис", city="Berlin", country="Германия", created_at=old, rules_at=old),
                AppUser(id=3, email="v@x.nl", name="Вера", city="Amsterdam", created_at=old, rules_at=old),
                AppUser(id=4, email="g@x.nl", name="Гена", city="Utrecht", created_at=old, rules_at=old),
            ])
            await s.flush()
            s.add(Friendship(user_id=1, friend_id=3, status=FriendStatus.ACCEPTED))
            await s.commit()
        app = web.Application()
        for m in (app_api, community, feed, realtime, social):
            m.install_routes(app)
        self.c = TestClient(TestServer(app))
        await self.c.start_server()

    async def asyncTearDown(self):
        await self.c.close()
        for p in self.patches:
            p.stop()
        if self.url:
            async with self.engine.begin() as conn:
                await conn.run_sync(Base.metadata.drop_all)
        await self.engine.dispose()
        self.tmp.cleanup()

    def h(self, uid):
        return {"Authorization": "Bearer " + make_token({"k": "app", "u": uid}, 3600)} if uid else {}

    async def post(self, path, uid, body=None):
        r = await self.c.post(path, json=body or {}, headers=self.h(uid))
        return r.status, await r.json()

    async def get(self, path, uid=None):
        r = await self.c.get(path, headers=self.h(uid))
        return r.status, await r.json()

    async def publish(self, uid, text="", **kw):
        community._hits.clear()   # лимит «раз в минуту» в тестах не мешает
        st, d = await self.post("/api/app/posts", uid, {"text": text, **kw})
        self.assertEqual(st, 200, d)
        return d["post"]

    # ------------------------------------------------------------ фото

    async def test_post_with_photos(self):
        p = await self.publish(1, "Закат над Utrecht", photos=[jpeg_b64(), jpeg_b64((10, 10, 200))])
        self.assertEqual((p["photos"], p["country"], p["city"]),
                         ([f"/api/app/posts/{p['id']}/photo/0", f"/api/app/posts/{p['id']}/photo/1"], "Нидерланды", "Utrecht"))
        r = await self.c.get(p["photos"][1])
        self.assertEqual((r.status, r.headers["Content-Type"]), (200, "image/jpeg"))
        self.assertEqual(Image.open(io.BytesIO(await r.read())).size, (40, 30))
        self.assertEqual((await self.c.get(f"/api/app/posts/{p['id']}/photo/5")).status, 404)
        only_photo = await self.publish(1, photos=[jpeg_b64()])   # можно без текста
        self.assertEqual(only_photo["text"], "")
        st, d = await self.post("/api/app/posts", 1, {"text": "", "photos": []})
        self.assertEqual(st, 400)
        community._hits.clear()
        st, d = await self.post("/api/app/posts", 1, {"text": "x", "photos": ["data:image/jpeg;base64,bm90IGEgcGljdHVyZQ=="]})
        self.assertEqual(st, 400)

    # ------------------------------------------------------------ лайки

    async def test_likes(self):
        p = await self.publish(1, "Первый пост")
        url = f"/api/app/posts/{p['id']}/like"
        self.assertEqual((await self.post(url, None))[0], 401)
        self.assertEqual((await self.post(url, 2, {"on": True}))[1], {"ok": True, "likes": 1, "liked": True})
        self.assertEqual((await self.post(url, 2, {"on": True}))[1]["likes"], 1)     # повтор не удваивает
        self.assertEqual((await self.post(url, 3, {"on": True}))[1]["likes"], 2)
        self.assertEqual((await self.post(url, 2, {"on": False}))[1], {"ok": True, "likes": 1, "liked": False})
        feed_ = (await self.get("/api/app/posts", 3))[1]["posts"][0]
        self.assertEqual((feed_["likes"], feed_["liked"]), (1, True))

    async def test_like_pushes_to_author(self):
        p = await self.publish(1, "Пост")
        ws = await self.c.ws_connect(f"/api/app/ws?token={make_token({'k': 'app', 'u': 1}, 3600)}")
        await self.post(f"/api/app/posts/{p['id']}/like", 2, {"on": True})
        e = await ws.receive_json(timeout=3)
        self.assertEqual((e["type"], e["event"], e["post"], e["user"]["name"]), ("post", "like", p["id"], "Борис"))
        await ws.close()

    # ------------------------------------------------------------ комментарии

    async def test_comments(self):
        p = await self.publish(1, "Где купить гречку?")
        url = f"/api/app/posts/{p['id']}/comments"
        st, d = await self.post(url, 2, {"text": "В Amazing Oriental"})
        self.assertEqual((st, d["comment"]["author"]["name"], d["comment"]["mine"]), (200, "Борис", True))
        cid = d["comment"]["id"]
        self.assertEqual((await self.post(url, 3, {"text": "ну ты и сука"}))[0], 400)   # фильтр мата
        community._hits.clear()
        await self.post(url, 3, {"text": "И в Lidl бывает"})
        detail = (await self.get(f"/api/app/posts/{p['id']}", 1))[1]
        self.assertEqual(([c["text"] for c in detail["comments"]], detail["post"]["comments"]),
                         (["В Amazing Oriental", "И в Lidl бывает"], 2))
        # удалить свой, нельзя чужой
        self.assertEqual((await self.post("/api/app/delete", 3, {"kind": "comment", "id": cid}))[0], 403)
        self.assertEqual((await self.post("/api/app/delete", 2, {"kind": "comment", "id": cid}))[0], 200)
        self.assertEqual(len((await self.get(url))[1]["comments"]), 1)
        # 3 жалобы — комментарий скрыт
        cid2 = (await self.get(url))[1]["comments"][0]["id"]
        for uid in (1, 2, 4):
            await self.post("/api/app/report", uid, {"kind": "comment", "id": cid2})
        self.assertEqual((await self.get(url))[1]["comments"], [])

    # ------------------------------------------------------------ репосты

    async def test_reposts(self):
        p = await self.publish(1, "Ищу соседей по квартире", photos=[jpeg_b64()])
        self.assertEqual((await self.post("/api/app/posts", 1, {"repost_of": p["id"]}))[0], 400)   # свой
        r = await self.publish(2, "Кому интересно?", repost_of=p["id"])
        self.assertEqual((r["repost"]["id"], r["repost"]["author"]["name"], r["repost"]["photos"]),
                         (p["id"], "Анна", p["photos"]))
        community._hits.clear()
        self.assertEqual((await self.post("/api/app/posts", 2, {"repost_of": p["id"]}))[0], 409)   # повтор
        rr = await self.publish(3, repost_of=r["id"])            # репост репоста → оригинал
        self.assertEqual(rr["repost"]["id"], p["id"])
        self.assertEqual((await self.get(f"/api/app/posts/{p['id']}"))[1]["post"]["reposts"], 2)
        await self.post("/api/app/delete", 1, {"kind": "post", "id": p["id"]})
        mine = [x for x in (await self.get("/api/app/posts"))[1]["posts"] if x["id"] == r["id"]][0]
        self.assertEqual(mine["repost"], {"id": p["id"], "deleted": True})

    # ------------------------------------------------------------ виды ленты

    async def test_scopes(self):
        a = await self.publish(1, "Анна из Utrecht")
        b = await self.publish(2, "Борис из Berlin")
        v = await self.publish(3, "Вера из Amsterdam")
        g = await self.publish(4, "Гена из Utrecht")
        ids = lambda d: [x["id"] for x in d["posts"]]  # noqa: E731
        self.assertEqual(ids((await self.get("/api/app/posts?scope=all", 1))[1]), [g["id"], v["id"], b["id"], a["id"]])
        self.assertEqual(ids((await self.get("/api/app/posts?scope=friends", 1))[1]), [v["id"], a["id"]])
        self.assertEqual((await self.get("/api/app/posts?scope=friends"))[0], 401)
        self.assertEqual(ids((await self.get("/api/app/posts?scope=near", 1))[1]), [g["id"], v["id"], a["id"]])
        self.assertEqual(ids((await self.get("/api/app/posts?scope=near", 2))[1]), [b["id"]])
        self.assertEqual(ids((await self.get("/api/app/posts?scope=near&city=Utrecht", 1))[1]), [g["id"], a["id"]])
        self.assertEqual(ids((await self.get("/api/app/posts?scope=near&country=Германия"))[1]), [b["id"]])
        self.assertEqual((await self.get("/api/app/posts?scope=near&country=Germany"))[0], 400)
        # блокировка в обе стороны прячет посты
        await self.post("/api/app/friends/block", 4, {"user_id": 1})
        self.assertNotIn(g["id"], ids((await self.get("/api/app/posts", 1))[1]))
        self.assertNotIn(a["id"], ids((await self.get("/api/app/posts", 4))[1]))
        self.assertEqual((await self.get(f"/api/app/posts/{a['id']}", 4))[0], 404)

    async def test_paging(self):
        made = []
        for i in range(feed.PAGE + 3):
            made.append((await self.publish(1, f"Пост {i}"))["id"])
        first = (await self.get("/api/app/posts"))[1]
        self.assertEqual((len(first["posts"]), first["more"]), (feed.PAGE, True))
        rest = (await self.get(f"/api/app/posts?before={first['posts'][-1]['id']}"))[1]
        self.assertEqual(([x["id"] for x in rest["posts"]], rest["more"]), (made[:3][::-1], False))

    async def test_profile_posts_have_counters(self):
        p = await self.publish(1, "Привет")
        await self.post(f"/api/app/posts/{p['id']}/like", 2, {"on": True})
        prof = (await self.get("/api/app/user/1", 2))[1]
        self.assertEqual((prof["posts"][0]["likes"], prof["posts"][0]["liked"]), (1, True))

    async def test_old_posts_table_gets_new_columns(self):
        async with self.engine.begin() as c:
            await c.exec_driver_sql("DROP TABLE user_posts")
            await c.exec_driver_sql("CREATE TABLE user_posts (id INTEGER PRIMARY KEY, user_id INTEGER, text TEXT, "
                                    "city VARCHAR(80), created_at TIMESTAMP, deleted BOOLEAN, hidden BOOLEAN)")
            await c.exec_driver_sql("INSERT INTO user_posts VALUES (1, 1, 'старый пост', 'Utrecht', "
                                    "'2026-10-01 10:00:00', FALSE, FALSE)")
        with patch.object(db, "engine", self.engine):
            await db._migrate()
            await db._migrate()
        async with self.engine.connect() as c:
            cols = await c.run_sync(lambda x: {i["name"] for i in inspect(x).get_columns("user_posts")})
            idx = await c.run_sync(lambda x: {i["name"] for i in inspect(x).get_indexes("user_posts")})
        self.assertTrue({"country", "repost_of", "photo_count"} <= cols)
        self.assertTrue({"ix_user_posts_country", "ix_user_posts_repost_of"} <= idx)
        old = (await self.get("/api/app/posts?scope=near&country=Нидерланды"))[1]["posts"][0]
        self.assertEqual((old["text"], old["country"], old["photos"], old["likes"]), ("старый пост", "Нидерланды", [], 0))


class FeedSqliteTests(FeedBase, unittest.IsolatedAsyncioTestCase):
    pass


@unittest.skipUnless(PG_URL, "TEST_DATABASE_URL не задан")
class FeedPostgresTests(FeedBase, unittest.IsolatedAsyncioTestCase):
    url = PG_URL


if __name__ == "__main__":
    unittest.main()
