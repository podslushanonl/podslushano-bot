"""Соцсеть приложения: открытые профили, дружба, ЛС только друзьям, общий чат для всех, страны, миграция.

Обычно гоняется на SQLite. Если задан TEST_DATABASE_URL (postgresql+asyncpg://…), те же проверки
дополнительно идут на PostgreSQL — так CI проверяет готовность к переезду базы.
"""
import asyncio
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from sqlalchemy import func, inspect, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from database import db
from database.models import AdminChannel, AppUser, Base, ChatRoom, Country, Friendship, FriendStatus
from utils import app_api, community, dm, realtime, social
from utils.site_api import make_token

PG_URL = os.getenv("TEST_DATABASE_URL", "")


class SocialBase:
    url = ""

    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        url = self.url or f"sqlite+aiosqlite:///{Path(self.tmp.name) / 't.db'}"
        self.engine = create_async_engine(url)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.patches = [patch.object(m, "get_session", self.sessions) for m in (app_api, community, dm, realtime, social)]
        for p in self.patches:
            p.start()
        community._hits.clear()
        community._rooms_synced.clear()
        old = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=10)
        async with self.sessions() as s:
            s.add_all([
                AppUser(id=1, email="a@x.nl", name="Анна", city="Utrecht", created_at=old, rules_at=old),
                AppUser(id=2, email="b@x.nl", name="Борис", city="Berlin", country="Германия", created_at=old, rules_at=old),
                AppUser(id=3, email="v@x.nl", name="Вера", city="Gent", country=Country.BE, created_at=old, rules_at=old),
                AppUser(id=4, email="g@x.nl", name="Гена", created_at=old, rules_at=old),
            ])
            await s.commit()
        app = web.Application()
        app["bot"] = None
        for m in (app_api, community, dm, realtime, social):
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

    def tok(self, uid):
        return make_token({"k": "app", "u": uid}, 3600)

    async def post(self, path, uid, body=None):
        r = await self.c.post(path, json=body or {}, headers={"Authorization": "Bearer " + self.tok(uid)} if uid else {})
        return r.status, await r.json()

    async def get(self, path, uid=None):
        r = await self.c.get(path, headers={"Authorization": "Bearer " + self.tok(uid)} if uid else {})
        return r.status, await r.json()

    async def rel(self, me, other):
        return (await self.get(f"/api/app/user/{other}", me))[1]["relation"]

    # ------------------------------------------------------------ 1. профили открыты всем вошедшим

    async def test_profile_open_to_any_signed_in_user(self):
        self.assertEqual((await self.get("/api/app/user/2"))[0], 401)
        st, d = await self.get("/api/app/user/2", 3)          # Вера не дружит с Борисом — профиль всё равно виден
        self.assertEqual(st, 200)
        self.assertEqual((d["user"]["name"], d["user"]["country"], d["relation"], d["can_message"]),
                         ("Борис", "Германия", "none", False))
        self.assertEqual((await self.get("/api/app/user/999", 3))[0], 404)
        self.assertEqual(await self.rel(1, 1), "self")

    # ------------------------------------------------------------ 2. дружба

    async def test_friend_request_accept_remove(self):
        self.assertEqual((await self.post("/api/app/friends/request", 1, {"user_id": 2}))[1]["relation"], "outgoing")
        self.assertEqual(await self.rel(2, 1), "incoming")
        lists = (await self.get("/api/app/friends", 2))[1]
        self.assertEqual([u["name"] for u in lists["incoming"]], ["Анна"])
        self.assertEqual((await self.post("/api/app/friends/accept", 2, {"user_id": 1}))[1]["relation"], "friends")
        st, d = await self.get("/api/app/user/2", 1)
        self.assertEqual((d["relation"], d["can_message"], d["friends"]), ("friends", True, 1))
        # встречная заявка сразу делает друзьями
        await self.post("/api/app/friends/request", 3, {"user_id": 4})
        self.assertEqual((await self.post("/api/app/friends/request", 4, {"user_id": 3}))[1]["relation"], "friends")
        # удалить из друзей
        self.assertEqual((await self.post("/api/app/friends/remove", 1, {"user_id": 2}))[1]["relation"], "none")
        self.assertEqual(await self.rel(2, 1), "none")
        self.assertEqual((await self.post("/api/app/friends/request", 1, {"user_id": 1}))[0], 400)
        self.assertEqual((await self.post("/api/app/friends/accept", 1, {"user_id": 3}))[0], 404)

    async def test_block_status_in_friendship(self):
        await self.post("/api/app/friends/request", 1, {"user_id": 2})
        await self.post("/api/app/friends/accept", 2, {"user_id": 1})
        self.assertEqual((await self.post("/api/app/friends/block", 1, {"user_id": 2}))[1]["relation"], "blocked")
        async with self.sessions() as s:
            rows = list((await s.execute(select(Friendship))).scalars())
        self.assertEqual([(r.user_id, r.friend_id, r.status) for r in rows], [(1, 2, FriendStatus.BLOCKED)])
        self.assertEqual(await self.rel(2, 1), "unavailable")
        self.assertEqual((await self.post("/api/app/friends/request", 2, {"user_id": 1}))[0], 403)
        self.assertEqual((await self.get("/api/app/friends", 1))[1]["blocked"][0]["name"], "Борис")
        self.assertEqual((await self.post("/api/app/friends/unblock", 1, {"user_id": 2}))[1]["relation"], "none")

    async def test_friendship_pair_index(self):
        idx = {i.name: ([c.name for c in i.columns], i.unique) for i in Friendship.__table__.indexes}
        self.assertEqual(idx["ix_friendship_pair"], (["user_id", "friend_id"], True))

    async def test_one_row_per_pair_even_for_reciprocal_requests(self):
        from sqlalchemy.exc import IntegrityError
        async with self.sessions() as s:
            s.add(Friendship(user_id=1, friend_id=2, status=FriendStatus.PENDING))
            await s.commit()
            s.add(Friendship(user_id=2, friend_id=1, status=FriendStatus.PENDING))
            with self.assertRaises(IntegrityError):
                await s.commit()
            await s.rollback()
            # встречные блокировки — две записи, это можно
            s.add_all([Friendship(user_id=3, friend_id=4, status=FriendStatus.BLOCKED),
                       Friendship(user_id=4, friend_id=3, status=FriendStatus.BLOCKED)])
            await s.commit()
        # гонка: заявка 2→1 не увидела встречную (устаревшее чтение) — сервер принимает встречную, а не падает
        with patch.object(social, "_rows", AsyncMock(return_value=[])):
            st, d = await self.post("/api/app/friends/request", 2, {"user_id": 1})
        self.assertEqual((st, d["relation"]), (200, "friends"))
        lists = (await self.get("/api/app/friends", 2))[1]
        self.assertEqual(([u["id"] for u in lists["friends"]], lists["incoming"], lists["outgoing"]), ([1], [], []))

    # ------------------------------------------------------------ 2. ЛС только между друзьями

    async def test_dm_requires_accepted_friendship(self):
        st, d = await self.post("/api/app/dm/start", 1, {"user_id": 2})
        self.assertEqual((st, d["error"]), (403, social.NOT_FRIENDS))
        await self.post("/api/app/friends/request", 1, {"user_id": 2})
        self.assertEqual((await self.post("/api/app/dm/start", 1, {"user_id": 2}))[0], 403)   # заявка ещё не принята
        await self.post("/api/app/friends/accept", 2, {"user_id": 1})
        st, d = await self.post("/api/app/dm/start", 1, {"user_id": 2})
        self.assertEqual(st, 200)
        cid = d["id"]
        self.assertEqual((await self.post("/api/app/dm/start", 2, {"user_id": 1}))[1]["id"], cid)   # один диалог на пару
        self.assertEqual((await self.post(f"/api/app/dm/{cid}", 1, {"text": "Привет!"}))[0], 200)
        self.assertTrue((await self.get(f"/api/app/dm/{cid}", 2))[1]["conversation"]["can_write"])
        # удалили из друзей — история видна, писать нельзя
        await self.post("/api/app/friends/remove", 2, {"user_id": 1})
        st, d = await self.post(f"/api/app/dm/{cid}", 1, {"text": "Ты тут?"})
        self.assertEqual((st, d["error"]), (403, social.NOT_FRIENDS))
        conv = (await self.get(f"/api/app/dm/{cid}", 1))[1]
        self.assertEqual((len(conv["messages"]), conv["conversation"]["can_write"]), (1, False))

    # ------------------------------------------------------------ 3. общий чат открыт всем

    async def test_global_chat_over_websocket_without_friendship(self):
        st, d = await self.get("/api/app/rooms")
        rooms = {r["slug"]: r for r in d["rooms"]}
        self.assertEqual((rooms["all"]["title"], rooms["all"]["country"]), ("Общий чат", ""))
        self.assertEqual((rooms["berlin"]["country"], rooms["gent"]["country"], rooms["amsterdam"]["country"]),
                         ("Германия", "Бельгия", "Нидерланды"))
        anna = await self.c.ws_connect(f"/api/app/ws?token={self.tok(1)}")
        vera = await self.c.ws_connect(f"/api/app/ws?token={self.tok(3)}")
        await anna.send_json({"type": "join", "room": "all"})
        await asyncio.sleep(0.05)
        await vera.send_json({"type": "say", "room": "all", "text": "Всем привет из Gent!", "ref": "r1"})
        said = await self._recv(vera, "said")
        self.assertEqual((said["ok"], said["ref"]), (True, "r1"))
        got = await self._recv(anna, "room")
        self.assertEqual((got["slug"], got["message"]["author"]["name"]), ("all", "Вера"))
        await vera.send_json({"type": "say", "room": "nope", "text": "x"})
        self.assertEqual((await self._recv(vera, "said"))["status"], 404)
        # тот же чат по HTTP — тоже без дружбы
        self.assertEqual((await self.post("/api/app/rooms/all/messages", 2, {"text": "Hallo aus Berlin"}))[0], 200)
        await anna.close()
        await vera.close()

    async def _recv(self, ws, kind):
        while True:
            m = await asyncio.wait_for(ws.receive_json(), 3)
            if m["type"] == kind:
                return m

    # ------------------------------------------------------------ 4. страны

    async def test_country_validated(self):
        st, d = await self.post("/api/app/me", 4, {"country": "Бельгия", "city": "Antwerpen"})
        self.assertEqual((st, d["user"]["country"]), (200, "Бельгия"))
        for bad in ("Belgium", "BE", "Франция", ""):
            self.assertEqual((await self.post("/api/app/me", 4, {"country": bad}))[0], 400, bad)
        with self.assertRaises(ValueError):
            AppUser(name="x", country="Germany")
        self.assertEqual([c.value for c in Country], ["Нидерланды", "Германия", "Бельгия"])

    async def test_search_people(self):
        st, d = await self.get("/api/app/users?q=Бор", 1)
        self.assertEqual([(u["name"], u["relation"]) for u in d["users"]], [("Борис", "none")])
        self.assertEqual((await self.get("/api/app/users?q=а&country=Германия", 1))[1]["users"], [])   # слишком коротко
        self.assertEqual((await self.get("/api/app/users?q=Вер&country=Франция", 1))[0], 400)


class SocialSqliteTests(SocialBase, unittest.IsolatedAsyncioTestCase):
    pass


@unittest.skipUnless(PG_URL, "TEST_DATABASE_URL не задан")
class SocialPostgresTests(SocialBase, unittest.IsolatedAsyncioTestCase):
    url = PG_URL


@unittest.skipUnless(PG_URL, "TEST_DATABASE_URL не задан")
class MigrationScriptTests(unittest.IsolatedAsyncioTestCase):
    """scripts/sqlite_to_postgres.py: копирует данные, сохраняет id, двигает счётчики, не пишет в непустую базу."""

    async def test_copy_sqlite_to_postgres(self):
        from scripts import sqlite_to_postgres as mig
        tmp = tempfile.TemporaryDirectory()
        path = str(Path(tmp.name) / "bot.db")
        src = create_async_engine(f"sqlite+aiosqlite:///{path}")
        async with src.begin() as c:
            await c.run_sync(Base.metadata.create_all)
        async with async_sessionmaker(src)() as s:
            s.add_all([AppUser(id=7, name="Анна", country="Бельгия"), AppUser(id=8, name="Борис"),
                       AdminChannel(chat_id=-1004454718646, title="Канал", added_by=1)])   # отрицательный id
            await s.flush()
            s.add(Friendship(user_id=7, friend_id=8, status=FriendStatus.ACCEPTED))
            await s.commit()
        await src.dispose()
        async with create_async_engine(PG_URL).begin() as c:
            await c.run_sync(Base.metadata.drop_all)
        before = Path(path).read_bytes()
        self.assertEqual(await mig.run(path, PG_URL, dry_run=True, force=False), 0)   # проверка без записи
        self.assertEqual(Path(path).read_bytes(), before)                               # SQLite не тронут
        probe = create_async_engine(PG_URL)
        async with probe.connect() as c:
            self.assertNotIn("app_users", await c.run_sync(lambda x: inspect(x).get_table_names()))   # в PG пусто
        await probe.dispose()
        self.assertEqual(await mig.run(path, PG_URL, dry_run=False, force=True), 0)
        self.assertEqual(await mig.run(path, PG_URL, dry_run=False, force=False), 3)   # второй раз — не затирает
        dst = create_async_engine(PG_URL)
        async with async_sessionmaker(dst)() as s:
            self.assertEqual((await s.get(AppUser, 7)).country, Country.BE)
            s.add(AppUser(name="Новый"))
            await s.commit()
            self.assertEqual(await s.scalar(select(func.max(AppUser.id))), 9)   # счётчик id сдвинут
        async with dst.begin() as c:
            await c.run_sync(Base.metadata.drop_all)
        await dst.dispose()
        tmp.cleanup()


    async def test_bot_imports_sqlite_on_first_start(self):
        """SQLITE_IMPORT=1: init_db сам переносит данные один раз; без флага и на SQLite ничего не делает."""
        tmp = tempfile.TemporaryDirectory()
        path = str(Path(tmp.name) / "bot.db")
        src = create_async_engine(f"sqlite+aiosqlite:///{path}")
        async with src.begin() as c:
            await c.run_sync(Base.metadata.create_all)
        async with async_sessionmaker(src)() as s:
            s.add(AppUser(id=11, name="Ира", country="Германия"))
            await s.commit()
        await src.dispose()
        dst = create_async_engine(PG_URL)
        async with dst.begin() as c:
            await c.run_sync(Base.metadata.drop_all)
        with patch.multiple(db.config, DB_URL=PG_URL, DB_PATH=path), patch.object(db, "engine", dst), \
                patch.object(db, "async_session", async_sessionmaker(dst, expire_on_commit=False)), \
                patch.dict(os.environ, {"SQLITE_IMPORT": "1"}):
            await db._import_sqlite_once()
            async with async_sessionmaker(dst)() as s:
                s.add(AppUser(id=12, name="Новая"))      # бот уже работает на PostgreSQL
                await s.commit()
            await db._import_sqlite_once()                # перезапуск — второй раз не переносит
        async with async_sessionmaker(dst)() as s:
            self.assertEqual(sorted((await s.execute(select(AppUser.id))).scalars()), [11, 12])
            self.assertTrue(await s.get(db.Meta, db.SQLITE_IMPORTED_KEY))
        async with dst.begin() as c:
            await c.run_sync(Base.metadata.drop_all)
        await dst.dispose()
        tmp.cleanup()


    async def test_dirty_sqlite_rows(self):
        """Нулевые символы вычищаются; строки с битыми значениями (например, датой) пропускаются
        и пишутся в pg_import_skipped.jsonl, а не роняют перенос."""
        from scripts import sqlite_to_postgres as mig
        tmp = tempfile.TemporaryDirectory()
        path = str(Path(tmp.name) / "bot.db")
        src = create_async_engine(f"sqlite+aiosqlite:///{path}")
        async with src.begin() as c:
            await c.run_sync(Base.metadata.create_all)
            for row in [(1, "Ан\x00на", "2026-01-01 10:00:00"), (2, "Битая дата", "вчера"), (3, "Олег", "2026-01-02 10:00:00")]:
                await c.exec_driver_sql("INSERT INTO app_users (id, name, city, country, created_at) "
                                        "VALUES (?, ?, '', 'Нидерланды', ?)", row)
        await src.dispose()
        dst = create_async_engine(PG_URL)
        async with dst.begin() as c:
            await c.run_sync(Base.metadata.drop_all)
        with patch.object(mig.config, "DB_PATH", path):
            self.assertEqual(await mig.run(path, PG_URL, dry_run=False, force=False), 0)
        async with async_sessionmaker(dst)() as s:
            users = {u.id: u.name for u in (await s.execute(select(AppUser))).scalars()}
            self.assertEqual(users, {1: "Анна", 3: "Олег"})
        log = (Path(tmp.name) / "pg_import_skipped.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual([(json.loads(x)["table"], json.loads(x)["row"]["id"]) for x in log], [("app_users", 2)])
        async with dst.begin() as c:
            await c.run_sync(Base.metadata.drop_all)
        await dst.dispose()
        tmp.cleanup()

    async def test_import_refuses_non_empty_postgres_unless_forced(self):
        tmp = tempfile.TemporaryDirectory()
        path = str(Path(tmp.name) / "bot.db")
        src = create_async_engine(f"sqlite+aiosqlite:///{path}")
        async with src.begin() as c:
            await c.run_sync(Base.metadata.create_all)
        async with async_sessionmaker(src)() as s:
            s.add(AppUser(id=21, name="Из SQLite"))
            await s.commit()
        await src.dispose()
        dst = create_async_engine(PG_URL)
        async with dst.begin() as c:
            await c.run_sync(Base.metadata.drop_all)
            await c.run_sync(Base.metadata.create_all)
        async with async_sessionmaker(dst)() as s:
            s.add(AppUser(id=99, name="Успел появиться в пустой базе"))
            await s.commit()
        common = dict(DB_URL=PG_URL, DB_PATH=path)
        with patch.multiple(db.config, **common), patch.object(db, "engine", dst), \
                patch.object(db, "async_session", async_sessionmaker(dst, expire_on_commit=False)):
            with patch.dict(os.environ, {"SQLITE_IMPORT": "1"}), self.assertRaises(RuntimeError):
                await db._import_sqlite_once()       # молча работать на неполной базе нельзя
            with patch.dict(os.environ, {"SQLITE_IMPORT": "force"}):
                await db._import_sqlite_once()
        async with async_sessionmaker(dst)() as s:
            self.assertEqual(sorted((await s.execute(select(AppUser.id))).scalars()), [21])
        async with dst.begin() as c:
            await c.run_sync(Base.metadata.drop_all)
        await dst.dispose()
        tmp.cleanup()


    async def test_repair_long_meta_keys(self):
        """После первого переноса: meta.key расширяется до 255, длинные ключи дозагружаются из SQLite,
        обрезки удаляются — один раз."""
        import sqlite3
        tmp = tempfile.TemporaryDirectory()
        path = str(Path(tmp.name) / "bot.db")
        long1, long2 = "seen:" + "x" * 60 + "a", "seen:" + "x" * 60 + "b"
        with sqlite3.connect(path) as c:
            c.execute("CREATE TABLE meta (key VARCHAR(50) PRIMARY KEY, value TEXT)")
            c.executemany("INSERT INTO meta VALUES (?, ?)", [(long1, "1"), (long2, "2"), ("seed_version", "10")])
        dst = create_async_engine(PG_URL)
        async with dst.begin() as c:
            await c.run_sync(Base.metadata.drop_all)
            await c.exec_driver_sql("DROP TABLE IF EXISTS meta")
            await c.exec_driver_sql("CREATE TABLE meta (key VARCHAR(50) PRIMARY KEY, value TEXT)")
            await c.exec_driver_sql(f"INSERT INTO meta VALUES ('{db.SQLITE_IMPORTED_KEY}', 'x'), ('{long1[:50]}', '1')")
        with patch.multiple(db.config, DB_URL=PG_URL, DB_PATH=path), patch.object(db, "engine", dst), \
                patch.object(db, "async_session", async_sessionmaker(dst, expire_on_commit=False)):
            await db._widen_meta_key()
            await db._repair_long_meta_keys_once()
            await db._repair_long_meta_keys_once()   # второй раз ничего не делает
        async with dst.connect() as c:
            keys = dict((await c.exec_driver_sql("SELECT key, value FROM meta")).all())
        self.assertEqual(keys, {db.SQLITE_IMPORTED_KEY: "x", long1: "1", long2: "2", db.META_KEYS_REPAIRED: "2"})
        async with dst.begin() as c:
            await c.exec_driver_sql("DROP TABLE meta")
        await dst.dispose()
        tmp.cleanup()


class LegacyMigrationTests(unittest.IsolatedAsyncioTestCase):
    """Старая база SQLite: колонки country нет, страны комнат кодом NL, блокировки в user_blocks."""

    async def test_migrate_existing_sqlite(self):
        tmp = tempfile.TemporaryDirectory()
        engine = create_async_engine(f"sqlite+aiosqlite:///{Path(tmp.name) / 'old.db'}")
        async with engine.begin() as c:
            await c.exec_driver_sql("CREATE TABLE app_users (id INTEGER PRIMARY KEY, email VARCHAR(200), tg_id BIGINT, "
                                    "name VARCHAR(80), city VARCHAR(80), created_at DATETIME, last_seen DATETIME)")
            await c.exec_driver_sql("CREATE TABLE chat_rooms (id INTEGER PRIMARY KEY, slug VARCHAR(40), title VARCHAR(80), "
                                    "kind VARCHAR(10), country VARCHAR(2), sort INTEGER, active BOOLEAN)")
            await c.exec_driver_sql("CREATE TABLE user_blocks (id INTEGER PRIMARY KEY, user_id INTEGER, blocked_id INTEGER)")
            await c.exec_driver_sql("INSERT INTO app_users (id, name, city) VALUES (1, 'Анна', ''), (2, 'Борис', '')")
            await c.exec_driver_sql("INSERT INTO chat_rooms VALUES (1, 'amsterdam', 'Amsterdam', 'city', 'NL', 1, 1)")
            await c.exec_driver_sql("INSERT INTO user_blocks VALUES (1, 1, 2), (2, 1, 2), (3, 2, 77)")
        with patch.object(db, "engine", engine):
            async with engine.begin() as c:
                await c.run_sync(Base.metadata.create_all)
            await db._migrate()
            await db._migrate()   # повторный запуск ничего не ломает
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as s:
            self.assertEqual((await s.get(AppUser, 1)).country, Country.NL)
            self.assertEqual((await s.get(ChatRoom, 1)).country, Country.NL)
            rows = list((await s.execute(select(Friendship))).scalars())
            self.assertEqual([(r.user_id, r.friend_id, r.status) for r in rows], [(1, 2, FriendStatus.BLOCKED)])
            tables = {r[0] for r in (await s.execute(text("SELECT name FROM sqlite_master WHERE type='table'")))}
        self.assertIn("user_blocks_migrated", tables)
        self.assertNotIn("user_blocks", tables)
        await engine.dispose()
        tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
