"""Личные сообщения приложения: только друзьям; диалоги по объявлениям, живое соединение, прочитано, блокировки, жалобы."""
import asyncio
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from database.models import AppUser, Base, Friendship, FriendStatus, Listing
from utils import app_api, community, dm, realtime, social
from utils.site_api import make_token


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, reply_markup=None, **kw):
        self.sent.append((chat_id, text, reply_markup))
        return SimpleNamespace(message_id=len(self.sent))


class DmTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{Path(self.tmp.name) / 't.db'}")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.patches = [patch.object(m, "get_session", self.sessions) for m in (app_api, community, dm, realtime, social)] + [
            patch.object(dm.config, "ADMIN_IDS", [999]),
            patch.object(dm.config, "WEBHOOK_BASE_URL", "https://bot.example"),
        ]
        for p in self.patches:
            p.start()
        community._hits.clear()
        old = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=10)
        later = datetime.utcnow() + timedelta(days=20)
        async with self.sessions() as s:
            s.add_all([
                AppUser(id=1, email="s@x.nl", name="Сергей", tg_id=555, created_at=old, rules_at=old),
                AppUser(id=2, email="b@x.nl", name="Борис", created_at=old, rules_at=old),
                AppUser(id=3, email="n@x.nl", name="Нина", created_at=old),
                AppUser(id=4, email="o@x.nl", name="Олег", created_at=old, rules_at=old),
                Listing(id=10, category="goods", title="Коляска Bugaboo", description="d", contact="Telegram: @s_nl",
                        status="approved", expires_at=later, app_user_id=1, submitter_user_id=555),
                Listing(id=11, category="goods", title="Из бота", description="d", contact="Telegram: @x_nl",
                        status="approved", expires_at=later, submitter_user_id=777),
                Listing(id=12, category="goods", title="На проверке", description="d", status="pending", app_user_id=1),
                # Сергей и Борис — друзья; Олег (4) с Сергеем не дружит
                Friendship(user_id=2, friend_id=1, status=FriendStatus.ACCEPTED),
            ])
            await s.commit()
        self.bot = FakeBot()
        app = web.Application()
        app["bot"] = self.bot
        dm.install_routes(app)
        realtime.install_routes(app)
        community.install_routes(app)
        self.c = TestClient(TestServer(app))
        await self.c.start_server()

    async def asyncTearDown(self):
        await self.c.close()
        for p in self.patches:
            p.stop()
        await self.engine.dispose()
        self.tmp.cleanup()

    def tok(self, uid):
        return make_token({"k": "app", "u": uid}, 3600)

    def h(self, uid):
        return {"Authorization": "Bearer " + self.tok(uid)} if uid else {}

    async def post(self, path, uid, body=None):
        return await self.c.post(path, json=body or {}, headers=self.h(uid))

    async def get(self, path, uid=None):
        return await self.c.get(path, headers=self.h(uid))

    async def start(self, uid=2, listing=10):
        r = await self.post("/api/app/dm/start", uid, {"listing_id": listing})
        return r.status, await r.json()

    async def test_start_rules(self):
        self.assertEqual((await self.start(None))[0], 401)
        self.assertEqual((await self.start(3))[0], 428)          # правила не приняты
        self.assertEqual((await self.start(2, 11))[0], 409)      # автор не в приложении
        self.assertEqual((await self.start(2, 12))[0], 404)      # не опубликовано
        self.assertEqual((await self.start(1, 10))[0], 400)      # своё объявление
        st, d = await self.start(4)                               # не друзья — писать нельзя
        self.assertEqual((st, d["error"]), (403, social.NOT_FRIENDS))
        st, d = await self.start()
        self.assertEqual(st, 200)
        self.assertEqual((await self.start())[1]["id"], d["id"])  # тот же диалог
        # пустой диалог в списке не показывается
        self.assertEqual((await (await self.get("/api/app/dm", 2)).json())["items"], [])

    async def test_send_read_unread_and_nudge(self):
        cid = (await self.start())[1]["id"]
        url = f"/api/app/dm/{cid}"
        r = await (await self.post(url, 2, {"text": "Здравствуйте! Ещё актуально?"})).json()
        self.assertTrue(r["message"]["mine"])
        await self.post(url, 2, {"text": "Могу забрать сегодня"})
        # продавца нет в приложении → одно напоминание в Telegram, не на каждое сообщение
        nudges = [x for x in self.bot.sent if x[0] == 555]
        self.assertEqual(len(nudges), 1)
        self.assertIn("Коляска Bugaboo", nudges[0][1])
        self.assertEqual(nudges[0][2].inline_keyboard[0][0].url, f"https://bot.example/app/dm/{cid}")

        lst = await (await self.get("/api/app/dm", 1)).json()
        self.assertEqual((lst["unread"], lst["items"][0]["peer"]["name"], lst["items"][0]["listing"]["title"]), (2, "Борис", "Коляска Bugaboo"))
        seller = await (await self.get(url, 1)).json()
        self.assertEqual([m["mine"] for m in seller["messages"]], [False, False])
        self.assertFalse((await (await self.get(url, 2)).json())["messages"][0]["read"])
        await self.post(f"{url}/read", 1)
        self.assertEqual((await (await self.get("/api/app/dm", 1)).json())["unread"], 0)
        self.assertTrue((await (await self.get(url, 2)).json())["messages"][-1]["read"])
        # посторонний диалог не видит
        self.assertEqual((await self.get(url, 4)).status, 404)
        self.assertEqual((await self.post(url, 4, {"text": "привет"})).status, 404)

    async def test_filters_block_and_report(self):
        cid = (await self.start())[1]["id"]
        url = f"/api/app/dm/{cid}"
        self.assertEqual((await self.post(url, 2, {"text": "ну ты и сука"})).status, 400)
        self.assertEqual((await self.post("/api/app/block", 1, {"user_id": 2})).status, 200)
        self.assertEqual((await self.post(url, 2, {"text": "Почему молчите?"})).status, 403)
        self.assertEqual((await self.start(2, 10))[0], 403)
        self.assertEqual((await self.post(f"{url}/report", 1)).status, 200)
        report = [x for x in self.bot.sent if x[0] == 999]
        self.assertEqual(len(report), 1)
        self.assertIn("Жалоба на личную переписку", report[0][1])
        self.assertEqual(report[0][2].inline_keyboard[0][1].callback_data, "dmban:x:2")
        await self.post(f"{url}/report", 1)   # повтор за сутки не дублируется
        self.assertEqual(len([x for x in self.bot.sent if x[0] == 999]), 1)

    async def recv(self, ws, kind):
        while True:
            m = await asyncio.wait_for(ws.receive_json(), 3)
            if m["type"] == kind:
                return m

    async def test_realtime_dm_typing_and_rooms(self):
        self.assertEqual((await self.c.get("/api/app/ws?token=bad")).status, 401)
        cid = (await self.start())[1]["id"]
        seller = await self.c.ws_connect(f"/api/app/ws?token={self.tok(1)}")
        buyer = await self.c.ws_connect(f"/api/app/ws?token={self.tok(2)}")
        await asyncio.sleep(0.05)
        self.assertTrue(realtime.online(1))
        await self.post(f"/api/app/dm/{cid}", 2, {"text": "Привет!"})
        e = await self.recv(seller, "dm")
        self.assertEqual((e["conv"], e["message"]["text"], e["message"]["mine"]), (cid, "Привет!", False))
        self.assertEqual([x for x in self.bot.sent if x[0] == 555], [])   # в сети — без напоминания
        await buyer.send_json({"type": "typing", "conv": cid})
        self.assertEqual((await self.recv(seller, "typing"))["conv"], cid)
        await self.post(f"/api/app/dm/{cid}/read", 1)
        self.assertEqual((await self.recv(buyer, "read"))["conv"], cid)
        # городской чат: новые сообщения приходят подписанным
        await seller.send_json({"type": "join", "room": "amsterdam"})
        await asyncio.sleep(0.05)
        r = await self.post("/api/app/rooms/amsterdam/messages", 2, {"text": "Всем привет из Amsterdam"})
        self.assertEqual(r.status, 200, await r.text())
        e = await self.recv(seller, "room")
        self.assertEqual((e["slug"], e["message"]["text"], e["message"]["author"]["name"]), ("amsterdam", "Всем привет из Amsterdam", "Борис"))
        await seller.close()
        await buyer.close()
        await asyncio.sleep(0.05)
        self.assertFalse(realtime.online(1))


if __name__ == "__main__":
    unittest.main()
