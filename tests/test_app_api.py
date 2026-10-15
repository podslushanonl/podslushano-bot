"""Аккаунты приложения: вход по коду из письма, через Telegram, профиль и избранное."""
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from database.models import Base
from utils import app_api, newsletter, phone, sms


class AppApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{Path(self.tmp.name) / 't.db'}")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.mail = AsyncMock(return_value=(True, ""))
        self.patches = [patch.object(app_api, "get_session", sessions),
                        patch.object(app_api, "send_email_message", self.mail)]
        for p in self.patches:
            p.start()
        newsletter._hits.clear()
        app = web.Application()
        app_api.install_routes(app)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        for p in self.patches:
            p.stop()
        await self.engine.dispose()
        self.tmp.cleanup()

    async def _code(self, email):
        r = await self.client.post("/api/app/auth/email", json={"email": email})
        self.assertEqual(r.status, 200)
        subject = self.mail.await_args.args[1]
        return re.search(r"\d{6}", subject).group(0)

    async def test_email_login_creates_account_once(self):
        code = await self._code("Anna@Example.com")
        bad = await self.client.post("/api/app/auth/verify", json={"email": "anna@example.com", "code": "000000" if code != "000000" else "111111"})
        self.assertEqual(bad.status, 400)
        ok = await (await self.client.post("/api/app/auth/verify", json={"email": "anna@example.com", "code": code})).json()
        self.assertTrue(ok["token"])
        uid = ok["user"]["id"]
        again = await self.client.post("/api/app/auth/verify", json={"email": "anna@example.com", "code": code})
        self.assertEqual(again.status, 400)  # код одноразовый
        code2 = await self._code("anna@example.com")
        ok2 = await (await self.client.post("/api/app/auth/verify", json={"email": "anna@example.com", "code": code2})).json()
        self.assertEqual(ok2["user"]["id"], uid)  # тот же аккаунт, не новый

    async def test_attempt_limit(self):
        code = await self._code("b@example.com")
        wrong = "123456" if code != "123456" else "654321"
        for _ in range(5):
            await self.client.post("/api/app/auth/verify", json={"email": "b@example.com", "code": wrong})
        r = await self.client.post("/api/app/auth/verify", json={"email": "b@example.com", "code": code})
        self.assertEqual(r.status, 429)

    async def test_parallel_wrong_codes_cannot_bypass_limit(self):
        import asyncio
        code = await self._code("c@example.com")
        wrong = "123456" if code != "123456" else "654321"
        await asyncio.gather(*[self.client.post("/api/app/auth/verify", json={"email": "c@example.com", "code": wrong})
                               for _ in range(20)])
        r = await self.client.post("/api/app/auth/verify", json={"email": "c@example.com", "code": code})
        self.assertEqual(r.status, 429)

    async def test_telegram_login_and_profile(self):
        start = await (await self.client.post("/api/app/auth/tg")).json()
        self.assertIn("applogin_" + start["nonce"], start["url"])
        pending = await (await self.client.get("/api/app/auth/tg", params={"nonce": start["nonce"]})).json()
        self.assertTrue(pending["pending"])
        self.assertTrue(await app_api.confirm_tg(start["nonce"], 42, "Олег"))
        self.assertFalse(await app_api.confirm_tg(start["nonce"], 43, "Чужой"))  # второй раз нельзя
        done = await (await self.client.get("/api/app/auth/tg", params={"nonce": start["nonce"]})).json()
        self.assertEqual(done["user"]["name"], "Олег")
        self.assertTrue(done["user"]["telegram"])
        gone = await self.client.get("/api/app/auth/tg", params={"nonce": start["nonce"]})
        self.assertEqual(gone.status, 410)

        h = {"Authorization": "Bearer " + done["token"]}
        self.assertEqual((await self.client.get("/api/app/me")).status, 401)
        me = await (await self.client.post("/api/app/me", json={"city": "Utrecht"}, headers=h)).json()
        self.assertEqual(me["user"]["city"], "Utrecht")
        await self.client.post("/api/app/favorites", json={"key": "sorokin", "title": "Сорокин"}, headers=h)
        await self.client.post("/api/app/favorites", json={"key": "sorokin", "title": "Сорокин"}, headers=h)
        me = await (await self.client.get("/api/app/me", headers=h)).json()
        self.assertEqual([f["key"] for f in me["favorites"]], ["sorokin"])
        await self.client.post("/api/app/favorites", json={"key": "sorokin", "on": False}, headers=h)
        me = await (await self.client.get("/api/app/me", headers=h)).json()
        self.assertEqual(me["favorites"], [])

    async def test_phone_login(self):
        sent = {}

        async def fake_send(to, code, ttl):
            sent[to] = code
            return True

        # Без канала доставки вход по номеру выключен
        with patch.dict("os.environ", {"TELEGRAM_GATEWAY_TOKEN": "", "OTP_DEBUG": ""}):
            self.assertFalse((await (await self.client.get("/api/app/auth/methods")).json())["phone"])
            r = await self.client.post("/api/app/auth/start", json={"phone": "612345678", "cc": "31"})
            self.assertEqual(r.status, 503)
        with patch.dict("os.environ", {"OTP_DEBUG": "1"}), patch.object(sms, "send_code", fake_send):
            self.assertTrue((await (await self.client.get("/api/app/auth/methods")).json())["phone"])
            bad = await self.client.post("/api/app/auth/start", json={"phone": "201234567", "cc": "31"})   # стационарный
            self.assertEqual(bad.status, 400)
            d = await (await self.client.post("/api/app/auth/start", json={"phone": "06 12 34 56 78", "cc": "31"})).json()
            self.assertEqual((d["kind"], d["to"]), ("phone", "+31612345678"))
            wrong = await self.client.post("/api/app/auth/check", json={"phone": "+31612345678", "code": "1"})
            self.assertEqual(wrong.status, 400)
            ok = await (await self.client.post("/api/app/auth/check", json={"phone": "+31612345678",
                                                                            "code": sent["+31612345678"]})).json()
            self.assertEqual(ok["user"]["phone"], "+31612345678")
            # Тот же номер в другом виде — тот же аккаунт
            await self.client.post("/api/app/auth/start", json={"phone": "0031 6 1234 5678"})
            again = await (await self.client.post("/api/app/auth/check", json={"phone": "612345678", "cc": "31",
                                                                               "code": sent["+31612345678"]})).json()
            self.assertEqual(again["user"]["id"], ok["user"]["id"])
        # Новый адрес работает и для почты
        await self.client.post("/api/app/auth/start", json={"email": "Vera@Example.com"})
        code = re.search(r"\d{6}", self.mail.await_args.args[1]).group(0)
        mail = await (await self.client.post("/api/app/auth/check", json={"email": "vera@example.com", "code": code})).json()
        self.assertEqual(mail["user"]["email"], "vera@example.com")
        self.assertNotEqual(mail["user"]["id"], ok["user"]["id"])

    def test_phone_normalize(self):
        n = phone.normalize
        self.assertEqual(n("06-12345678", "31"), "+31612345678")
        self.assertEqual(n("+49 151 23456789"), "+4915123456789")
        self.assertEqual(n("0470 12 34 56", "32"), "+32470123456")
        self.assertEqual(n("+380 67 123 45 67"), "+380671234567")
        self.assertEqual(n("067 123 45 67", "380"), "+380671234567")
        for bad in [("030 1234567", "49"), ("612345678", "1"), ("61234567", "31"), ("+7 912 345 67 89", ""), ("", "31")]:
            self.assertIsNone(n(*bad), bad)


if __name__ == "__main__":
    unittest.main()
