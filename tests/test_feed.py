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
from utils import app_api, community, feed, items, realtime, social
from utils.site_api import make_token

PG_URL = os.getenv("TEST_DATABASE_URL", "")


def jpeg_b64(color=(200, 80, 40)) -> str:
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), color).save(buf, "JPEG")
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


class FeedHarness:
    """Тестовый сервер приложения с четырьмя участниками и помощниками запросов (без самих тестов)."""
    url = ""
    mods = (app_api, community, feed, items, realtime, social)

    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_async_engine(self.url or f"sqlite+aiosqlite:///{Path(self.tmp.name) / 't.db'}")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.patches = [patch.object(m, "get_session", self.sessions) for m in self.mods]
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
        for m in self.mods:
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



class FeedBase(FeedHarness):
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
        # битое фото не съело лимит: сразу можно опубликовать нормальный пост
        self.assertEqual((await self.post("/api/app/posts", 1, {"text": "Теперь с текстом"}))[0], 200)

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

    async def test_repost_of_blocked_author_is_hidden(self):
        p = await self.publish(1, "Пост Анны", photos=[jpeg_b64()])
        r = await self.publish(2, "Смотрите", repost_of=p["id"])
        await self.post("/api/app/friends/block", 4, {"user_id": 1})     # Гена заблокировал Анну
        seen = [x for x in (await self.get("/api/app/posts", 4))[1]["posts"] if x["id"] == r["id"]][0]
        self.assertEqual(seen["repost"], {"id": p["id"], "deleted": True})   # текст и фото Анны не утекают
        other = [x for x in (await self.get("/api/app/posts", 3))[1]["posts"] if x["id"] == r["id"]][0]
        self.assertEqual(other["repost"]["text"], "Пост Анны")

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
        # «Рядом» без координат — мой город (Анна и Гена в Utrecht), Вера из Amsterdam не попадает
        self.assertEqual(ids((await self.get("/api/app/posts?scope=near", 1))[1]), [g["id"], a["id"]])
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
        self.assertEqual(prof["posts"], 1)                                   # счётчик публикаций
        wall = (await self.get("/api/app/user/1/posts", 2))[1]["posts"]       # стена — отдельным запросом
        self.assertEqual((wall[0]["likes"], wall[0]["liked"]), (1, True))

    # ------------------------------------------------------------ стена, репост в один тап

    async def test_wall_and_one_tap_repost(self):
        p = await self.publish(1, "Ищу соседей по квартире")
        self.assertEqual((await self.get("/api/app/user/1/posts"))[0], 401)
        st, d = await self.post(f"/api/app/posts/{p['id']}/repost", 2)
        self.assertEqual((st, d["reposts"], d["reposted"], d["post"]["repost"]["id"]), (200, 1, True, p["id"]))
        self.assertEqual((await self.post(f"/api/app/posts/{p['id']}/repost", 2))[0], 409)          # повтор
        self.assertEqual((await self.post(f"/api/app/posts/{p['id']}/repost", 1))[0], 400)          # свой
        wall2 = (await self.get("/api/app/user/2/posts", 3))[1]["posts"]
        self.assertEqual([(x["repost"]["id"], x["author"]["name"]) for x in wall2], [(p["id"], "Борис")])
        self.assertTrue((await self.get("/api/app/posts", 2))[1]["posts"][0]["reposted"])
        self.assertEqual((await self.get("/api/app/user/2", 3))[1]["posts"], 1)
        st, d = await self.post(f"/api/app/posts/{p['id']}/repost", 2, {"on": False})               # убрать
        self.assertEqual((st, d["reposts"], d["reposted"]), (200, 0, False))
        self.assertEqual((await self.get("/api/app/user/2/posts", 3))[1]["posts"], [])
        # блокировка: стену заблокировавшего не видно
        await self.post("/api/app/friends/block", 1, {"user_id": 4})
        self.assertEqual((await self.get("/api/app/user/1/posts", 4))[1]["posts"], [])

    # ------------------------------------------------------------ аватар и статус

    async def test_avatar_and_bio(self):
        st, d = await self.post("/api/app/me/avatar", 1, {"photo": jpeg_b64()})
        self.assertEqual(st, 200)
        url = d["user"]["avatar"]
        self.assertTrue(url.startswith("/api/app/user/1/avatar?v=1"))
        r = await self.c.get(url)
        self.assertEqual(Image.open(io.BytesIO(await r.read())).size, (512, 512))
        p = await self.publish(1, "С новой аватаркой")
        self.assertEqual(p["author"]["avatar"], url)
        self.assertEqual((await self.post("/api/app/me/avatar", 1, {"photo": "data:image/jpeg;base64,eHh4"}))[0], 400)
        st, d = await self.post("/api/app/me", 1, {"bio": "  Люблю   велосипеды  и Utrecht  "})
        self.assertEqual(d["user"]["bio"], "Люблю велосипеды и Utrecht")
        prof = (await self.get("/api/app/user/1", 2))[1]["user"]
        self.assertEqual((prof["bio"], prof["avatar"]), ("Люблю велосипеды и Utrecht", url))
        self.assertEqual((await self.post("/api/app/me", 1, {"bio": "ну ты и сука"}))[0], 400)
        # Рамка, выбранная в приложении: слева красное, справа синее — берём правую половину
        img = Image.new("RGB", (400, 200), (220, 20, 20))
        img.paste((20, 40, 220), (200, 0, 400, 200))
        buf = io.BytesIO()
        img.save(buf, "PNG")
        photo = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
        st, d = await self.post("/api/app/me/avatar", 1, {"photo": photo, "crop": {"x": 0.5, "y": 0, "w": 0.5, "h": 1}})
        av = Image.open(io.BytesIO(await (await self.c.get(d["user"]["avatar"])).read())).convert("RGB")
        self.assertEqual(av.size, (512, 512))
        self.assertGreater(av.getpixel((10, 256))[2], 150)           # синее до самого левого края
        st, d = await self.post("/api/app/me/avatar", 1, {"photo": photo, "crop": {"x": "bad"}})   # негодная рамка — по центру
        av = Image.open(io.BytesIO(await (await self.c.get(d["user"]["avatar"])).read())).convert("RGB")
        self.assertGreater(av.getpixel((10, 256))[0], 150)
        await self.post("/api/app/me/avatar", 1, {"photo": ""})
        self.assertEqual((await self.get("/api/app/user/1", 2))[1]["user"]["avatar"], "")
        self.assertEqual((await self.c.get("/api/app/user/1/avatar?v=1")).status, 404)

    # ------------------------------------------------------------ новости и события: лайк, комментарии, поделиться

    async def test_items(self):
        base = "/api/app/items/news/n-42"
        self.assertEqual((await self.post(base + "/like", 1))[1], {"ok": True, "likes": 1, "liked": True})
        await self.post(base + "/like", 2)
        await self.post(base + "/like", 2)                                          # повтор не удваивает
        self.assertEqual((await self.post(base + "/comments", 2, {"text": "Полезная новость"}))[0], 200)
        st, d = await self.post(base + "/share", 3, {"title": "Новые правила аренды", "url": "https://www.podslushano.nl/n42",
                                                     "img": "javascript:alert(1)", "text": "Важно!"})
        self.assertEqual((st, d["post"]["share"]["title"], d["post"]["share"]["url"], d["post"]["share"]["img"], d["post"]["text"]),
                         (200, "Новые правила аренды", "https://www.podslushano.nl/n42", "", "Важно!"))  # не-http картинка отброшена
        st, d = await self.post("/api/app/items/news/n-43/share", 3, {"title": "Новость", "url": "https://podslushano.nl.evil.com/x",
                                                                      "img": "https://tracker.example/p.gif"})
        self.assertEqual((st, d["post"]["share"]["url"], d["post"]["share"]["img"]), (200, "", ""))   # чужие ссылки — нет
        self.assertEqual((await self.post("/api/app/items/event/ev9/share", 3, {"title": "Концерт", "url": "https://podslushano.nl/e"}))[1]
                         ["post"]["share"]["url"], "")                                              # событие открывается в приложении
        self.assertEqual((await self.post(base + "/share", 3, {"title": "x"}))[0], 409)
        stats = (await self.get("/api/app/items/stats?keys=news:n-42,event:ev1,bad:x", 3))[1]["stats"]
        self.assertEqual(stats["news:n-42"], {"likes": 2, "liked": False, "comments": 1, "shares": 1, "shared": True})
        self.assertEqual(stats["event:ev1"]["likes"], 0)
        self.assertNotIn("bad:x", stats)
        cid = (await self.get(base + "/comments"))[1]["comments"][0]["id"]
        for uid in (1, 3, 4):
            await self.post("/api/app/report", uid, {"kind": "icomment", "id": cid})
        self.assertEqual((await self.get(base + "/comments"))[1]["comments"], [])   # 3 жалобы — скрыт
        self.assertEqual((await self.c.post("/api/app/items/video/x/like", headers=self.h(1))).status, 404)
        wall = (await self.get("/api/app/user/3/posts", 1))[1]["posts"]
        self.assertEqual([p["share"]["key"] for p in wall], ["ev9", "n-43", "n-42"])

    async def test_old_posts_table_gets_new_columns(self):
        async with self.engine.begin() as c:
            await c.exec_driver_sql("DROP TABLE user_posts")
            await c.exec_driver_sql("CREATE TABLE user_posts (id INTEGER PRIMARY KEY, user_id INTEGER, text TEXT, "
                                    "city VARCHAR(80), created_at TIMESTAMP, deleted BOOLEAN, hidden BOOLEAN)")
            await c.exec_driver_sql("INSERT INTO user_posts VALUES (1, 1, 'старый пост', 'Utrecht', "
                                    "'2026-10-01 10:00:00', FALSE, FALSE), (2, 2, 'старый из Berlin', 'Berlin', "
                                    "'2026-10-01 11:00:00', FALSE, FALSE)")
            await c.exec_driver_sql("DROP INDEX IF EXISTS ix_app_users_phone")
            for col in ("bio", "avatar", "avatar_v", "phone"):   # app_users из прошлой версии — без новых колонок
                await c.exec_driver_sql(f"ALTER TABLE app_users DROP COLUMN {col}")
        with patch.object(db, "engine", self.engine):
            await db._migrate()
            await db._migrate()
        async with self.engine.connect() as c:
            ucols = await c.run_sync(lambda x: {i["name"] for i in inspect(x).get_columns("app_users")})
            self.assertTrue({"bio", "avatar", "avatar_v", "phone"} <= ucols)
            uidx = await c.run_sync(lambda x: {i["name"]: i["unique"] for i in inspect(x).get_indexes("app_users")})
            self.assertTrue(uidx.get("ix_app_users_phone"))
            cols = await c.run_sync(lambda x: {i["name"] for i in inspect(x).get_columns("user_posts")})
            idx = await c.run_sync(lambda x: {i["name"] for i in inspect(x).get_indexes("user_posts")})
        self.assertTrue({"country", "repost_of", "photo_count", "share_kind", "share_key", "share_title"} <= cols)
        self.assertTrue({"ix_user_posts_country", "ix_user_posts_repost_of"} <= idx)
        old = (await self.get("/api/app/posts?scope=near&country=Нидерланды"))[1]["posts"]
        self.assertEqual([(x["text"], x["country"], x["photos"], x["likes"]) for x in old], [("старый пост", "Нидерланды", [], 0)])
        de = (await self.get("/api/app/posts?scope=near&country=Германия"))[1]["posts"]   # страна автора, не по умолчанию
        self.assertEqual([x["text"] for x in de], ["старый из Berlin"])


class FeedSqliteTests(FeedBase, unittest.IsolatedAsyncioTestCase):
    pass


@unittest.skipUnless(PG_URL, "TEST_DATABASE_URL не задан")
class FeedPostgresTests(FeedBase, unittest.IsolatedAsyncioTestCase):
    url = PG_URL


if __name__ == "__main__":
    unittest.main()
