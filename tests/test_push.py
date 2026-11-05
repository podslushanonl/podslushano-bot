"""Push-уведомления: регистрация устройства с провинцией и рассылка только по своей провинции."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from database.models import AppPushToken, Base
from utils import push


class PushTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{Path(self.tmp.name) / 't.db'}")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.p = patch.object(push, "get_session", self.sessions)
        self.p.start()
        app = web.Application()
        push.install_routes(app)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.p.stop()
        await self.engine.dispose()
        self.tmp.cleanup()

    async def _reg(self, token, province):
        return await self.client.post("/api/app/push/register", json={"token": token, "province": province, "platform": "ios"})

    async def test_register_and_send_by_province(self):
        a, b, c = "ExponentPushToken[aaaaaaaaaaaa]", "ExponentPushToken[bbbbbbbbbbbb]", "ExponentPushToken[cccccccccccc]"
        self.assertEqual((await self._reg(a, "nb")).status, 200)
        await self._reg(b, "nb")
        await self._reg(c, "nh")
        await self._reg(c, "li")                     # сменил провинцию: запись обновилась, не задвоилась
        self.assertEqual((await self._reg("bad", "nb")).status, 400)
        self.assertEqual((await self._reg(a, "xx")).status, 400)
        post = AsyncMock(return_value=[{"status": "ok"}, {"status": "error", "details": {"error": "DeviceNotRegistered"}}])
        with patch.object(push, "_post", post):
            sent, failed = await push.send_to_province("nb", "Афиша", "Новые события", "/afisha")
        self.assertEqual((sent, failed), (1, 1))
        msgs = post.await_args.args[0]
        self.assertEqual({m["to"] for m in msgs}, {a, b})   # Limburg и Noord-Holland не получили
        self.assertEqual(msgs[0]["data"], {"url": "/afisha"})
        async with self.sessions() as s:
            rows = {r.token: r for r in await s.scalars(select(AppPushToken))}
        self.assertFalse(rows[b].active)               # недействительный токен выключен
        self.assertEqual(rows[c].province, "li")
        self.assertEqual(len(rows), 3)

    def test_parse_command(self):
        self.assertEqual(push.parse_command("nb Афиша | Новые события | /afisha"), ("nb", "Афиша", "Новые события", "/afisha"))
        self.assertIsInstance(push.parse_command("xx Заголовок | Текст"), str)
        self.assertIsInstance(push.parse_command("nb только заголовок"), str)
        self.assertIsInstance(push.parse_command("all A | B | https://example.com"), str)


if __name__ == "__main__":
    unittest.main()
