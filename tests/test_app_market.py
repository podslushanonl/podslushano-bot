"""Премиум 5: барахолка приложения без Telegram, закрытый аккаунт, активные сессии, город поста.

На SQLite всегда; с TEST_DATABASE_URL — ещё и на PostgreSQL.
"""
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from database.models import AppUser, Base, Friendship, FriendStatus, MarketItem
from tests.test_feed import jpeg_b64
from utils import app_api, app_market, community, dm, feed, items, realtime, social
from utils.site_api import make_token

PG_URL = os.getenv("TEST_DATABASE_URL", "")
MODS = (app_api, app_market, community, dm, feed, items, realtime, social)


class Base5:
    url = ""

    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_async_engine(self.url or f"sqlite+aiosqlite:///{Path(self.tmp.name) / 't.db'}")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.patches = [patch.object(m, "get_session", self.sessions) for m in MODS]
        for p in self.patches:
            p.start()
        community._hits.clear()
        old = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=10)
        async with self.sessions() as s:
            s.add_all([
                AppUser(id=1, email="a@x.nl", name="Анна", city="Utrecht", created_at=old, rules_at=old),
                AppUser(id=2, email="b@x.nl", name="Борис", city="Amsterdam", created_at=old, rules_at=old),
                AppUser(id=3, email="v@x.nl", name="Вера", city="Amsterdam", created_at=old, rules_at=old),
                AppUser(id=4, email="g@x.nl", name="Гена", city="Utrecht", created_at=old, rules_at=old),
            ])
            await s.flush()
            s.add(Friendship(user_id=1, friend_id=3, status=FriendStatus.ACCEPTED))
            await s.commit()
        app = web.Application()
        for m in MODS:
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

    def h(self, who):
        tok = who if isinstance(who, str) else make_token({"k": "app", "u": who}, 3600) if who else ""
        return {"Authorization": "Bearer " + tok} if tok else {}

    async def post(self, path, who, body=None, headers=None):
        r = await self.c.post(path, json=body or {}, headers=self.h(who) | (headers or {}))
        return r.status, await r.json()

    async def get(self, path, who=None):
        r = await self.c.get(path, headers=self.h(who))
        return r.status, await r.json()

    def item(self, **kw):
        return {"category": "tech", "title": "iPhone 13", "description": "Отличное состояние, с коробкой",
                "price": "450", "city": "Amsterdam"} | kw

    # ------------------------------------------------------------ барахолка

    async def test_market_create_browse_photos_and_edit(self):
        st, d = await self.post("/api/app/market", 1, self.item(photos=[jpeg_b64(), jpeg_b64((0, 90, 200))]))
        self.assertEqual((st, d["status"]), (200, "active"))
        iid = d["id"]
        st, d = await self.get("/api/app/market?cat=tech&city=Amsterdam")
        self.assertEqual(st, 200)
        self.assertEqual([x["title"] for x in d["items"]], ["iPhone 13"])
        self.assertEqual(d["items"][0]["price"], "€450")
        self.assertEqual([c["key"] for c in d["categories"]], ["wardrobe", "home", "tech", "sport", "tickets", "housing", "services", "free"])
        self.assertEqual(d["cities"], ["Amsterdam", "Rotterdam", "Den Haag", "Eindhoven"])
        self.assertEqual((await self.get("/api/app/market?cat=wardrobe"))[1]["items"], [])
        self.assertEqual((await self.get("/api/app/market?q=iphone"))[1]["items"][0]["id"], iid)
        st, d = await self.get(f"/api/app/market/{iid}", 2)
        it = d["item"]
        self.assertEqual((it["seller"]["name"], len(it["photos"]), it["chat"], it["mine"]), ("Анна", 2, True, False))
        r = await self.c.get(it["photos"][1])
        self.assertEqual((r.status, r.content_type), (200, "image/jpeg"))
        # правка: второе фото становится первым, первое убираем, цена — договорная
        st, d = await self.post("/api/app/market", 1, self.item(id=iid, price="", photos=["keep:1", jpeg_b64((10, 10, 10))]))
        self.assertEqual(st, 200)
        it = (await self.get(f"/api/app/market/{iid}", 1))[1]["item"]
        self.assertEqual((it["price"], len(it["photos"])), ("Договорная", 2))
        # чужое не изменить
        self.assertEqual((await self.post("/api/app/market", 2, self.item(id=iid)))[0], 404)
        # бесплатно
        st, d = await self.post("/api/app/market", 2, self.item(category="free", price="99", title="Куртка"))
        self.assertEqual((await self.get(f"/api/app/market/{d['id']}"))[1]["item"]["price"], "Бесплатно")

    async def test_market_validation_and_limits(self):
        for bad, err in ((self.item(category="goods"), "категорию"), (self.item(title="ab"), "Название"),
                         (self.item(description="мало"), "Опишите"), (self.item(price="12345678"), "цену"),
                         (self.item(city=""), "город")):
            st, d = await self.post("/api/app/market", 1, bad)
            self.assertEqual(st, 400)
            self.assertIn(err, d["error"])
        self.assertEqual((await self.post("/api/app/market", None, self.item()))[0], 401)
        self.assertEqual((await self.post("/api/app/market", 1, self.item()))[0], 200)
        self.assertEqual((await self.post("/api/app/market", 1, self.item()))[0], 429)   # не чаще раза в минуту

    async def test_market_close_and_report_hides(self):
        iid = (await self.post("/api/app/market", 1, self.item()))[1]["id"]
        for uid in (2, 3):
            self.assertEqual((await self.post(f"/api/app/market/{iid}/report", uid, {"reason": "scam"}))[0], 200)
        self.assertEqual((await self.post(f"/api/app/market/{iid}/report", 2))[0], 200)   # повторная жалоба не считается
        self.assertEqual(len((await self.get("/api/app/market"))[1]["items"]), 1)
        await self.post(f"/api/app/market/{iid}/report", 4)
        self.assertEqual((await self.get("/api/app/market"))[1]["items"], [])
        self.assertEqual((await self.get(f"/api/app/market/{iid}", 2))[0], 404)
        self.assertEqual((await self.get(f"/api/app/market/{iid}", 1))[1]["item"]["status"], "hidden")
        community._hits.clear()
        iid2 = (await self.post("/api/app/market", 2, self.item()))[1]["id"]
        self.assertEqual((await self.post(f"/api/app/market/{iid2}/close", 1))[0], 404)
        self.assertEqual((await self.post(f"/api/app/market/{iid2}/close", 2))[0], 200)
        self.assertEqual((await self.get(f"/api/app/market/{iid2}", 3))[0], 404)
        self.assertEqual([x["status"] for x in (await self.get("/api/app/market/my", 2))[1]["items"]], ["closed"])

    async def test_market_expired_not_listed(self):
        async with self.sessions() as s:
            s.add(MarketItem(user_id=1, category="home", title="Старое", description="давно", city="Amsterdam",
                             expires_at=datetime.utcnow() - timedelta(days=1)))
            await s.commit()
        self.assertEqual((await self.get("/api/app/market"))[1]["items"], [])

    async def test_dm_about_item(self):
        iid = (await self.post("/api/app/market", 1, self.item()))[1]["id"]
        st, d = await self.post("/api/app/dm/start", 4, {"item_id": iid})   # не друзья — по объявлению можно
        self.assertEqual(st, 200)
        self.assertEqual((await self.post(f"/api/app/dm/{d['id']}", 4, {"text": "Ещё продаёте?"}))[0], 200)
        lst = (await self.get("/api/app/dm", 1))[1]
        self.assertEqual(lst["items"][0]["listing"]["title"], "iPhone 13")
        self.assertEqual((await self.post("/api/app/dm/start", 1, {"item_id": iid}))[0], 400)   # своё

    # ------------------------------------------------------------ закрытый аккаунт

    async def test_private_account(self):
        st, d = await self.post("/api/app/posts", 1, {"text": "Пост Анны"})
        self.assertEqual(st, 200)
        st, d = await self.post("/api/app/me", 1, {"is_private": True})
        self.assertTrue(d["user"]["is_private"])
        pid = (await self.get("/api/app/posts?scope=all", 1))[1]["posts"][0]["id"]
        # не друг (Борис): профиль с заглушкой, стена пустая, поста нет в ленте и по ссылке
        st, d = await self.get("/api/app/user/1", 2)
        self.assertEqual((d["private"], d["locked"], d["posts"]), (True, True, 1))
        st, d = await self.get("/api/app/user/1/posts", 2)
        self.assertEqual((d["posts"], d["locked"]), ([], True))
        self.assertEqual((await self.get("/api/app/posts?scope=all", 2))[1]["posts"], [])
        self.assertEqual((await self.get(f"/api/app/posts/{pid}", 2))[0], 404)
        # друг (Вера) видит всё
        st, d = await self.get("/api/app/user/1", 3)
        self.assertEqual((d["locked"], d["posts"]), (False, 1))
        self.assertEqual(len((await self.get("/api/app/user/1/posts", 3))[1]["posts"]), 1)
        self.assertEqual(len((await self.get("/api/app/posts?scope=all", 3))[1]["posts"]), 1)
        # и сама Анна
        self.assertFalse((await self.get("/api/app/user/1", 1))[1]["locked"])
        # открыли аккаунт — снова видно всем
        await self.post("/api/app/me", 1, {"is_private": False})
        self.assertEqual(len((await self.get("/api/app/posts?scope=all", 2))[1]["posts"]), 1)

    async def test_post_city(self):
        st, d = await self.post("/api/app/posts", 1, {"text": "Где лучший кофе?", "city": "Den Haag"})
        self.assertEqual(d["post"]["city"], "Den Haag")
        community._hits.clear()
        st, d = await self.post("/api/app/posts", 2, {"text": "Без города"})
        self.assertEqual(d["post"]["city"], "Amsterdam")

    # ------------------------------------------------------------ активные сессии

    async def test_sessions_list_and_revoke(self):
        tokens = []
        for ua in ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0) Safari/604.1", "Mozilla/5.0 (Windows NT 10.0) Chrome/130.0"):
            with patch.object(app_api, "secrets") as sec:
                sec.randbelow.return_value = 123456
                sec.token_hex.side_effect = lambda n, _ua=ua: ("a" if "iPhone" in _ua else "b") * 32
                with patch.object(app_api, "send_email_message", return_value=(True, "")):
                    self.assertEqual((await self.post("/api/app/auth/start", None, {"email": "a@x.nl"}, {"User-Agent": ua}))[0], 200)
                st, d = await self.post("/api/app/auth/check", None, {"email": "a@x.nl", "code": "123456"}, {"User-Agent": ua})
            self.assertEqual(st, 200, d)
            tokens.append(d["token"])
        phone, pc = tokens
        st, d = await self.get("/api/app/me/sessions", phone)
        self.assertEqual([(x["device"], x["current"]) for x in d["items"]], [("iPhone · Safari", True), ("Windows · Chrome", False)])
        # нельзя завершить своё; завершаем ПК — его токен больше не пускает
        self.assertEqual((await self.post("/api/app/me/sessions/revoke", phone, {"id": "a" * 32}))[0], 400)
        self.assertEqual((await self.post("/api/app/me/sessions/revoke", phone, {"id": "b" * 32}))[0], 200)
        self.assertEqual((await self.get("/api/app/me", pc))[0], 401)
        self.assertEqual((await self.get("/api/app/me", phone))[0], 200)
        # выход на телефоне завершает сеанс на сервере
        await self.post("/api/app/auth/logout", phone)
        self.assertEqual((await self.get("/api/app/me", phone))[0], 401)

    async def test_legacy_token_reset_by_end_others(self):
        legacy = make_token({"k": "app", "u": 1}, app_api.TOKEN_DAYS * 86400 - 60)
        other = make_token({"k": "app", "u": 1}, app_api.TOKEN_DAYS * 86400 - 120)
        st, d = await self.get("/api/app/me/sessions", legacy)
        self.assertEqual((st, d["legacy"]), (200, True))
        st, d = await self.post("/api/app/me/sessions/revoke", legacy, {"others": True})
        self.assertTrue(d["token"])   # этому устройству — новый токен с сеансом
        self.assertEqual((await self.get("/api/app/me", other))[0], 401)
        self.assertEqual((await self.get("/api/app/me", d["token"]))[0], 200)


class SqliteTests(Base5, unittest.IsolatedAsyncioTestCase):
    pass


@unittest.skipUnless(PG_URL, "TEST_DATABASE_URL не задан")
class PostgresTests(Base5, unittest.IsolatedAsyncioTestCase):
    url = PG_URL
