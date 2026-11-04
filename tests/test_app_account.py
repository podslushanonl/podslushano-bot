"""Удаление аккаунта приложения: личные данные и публикации стираются, вход по старому токену закрыт."""
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from database.models import AppFavorite, AppUser, Base, PostLike, PostPhoto, UserPost
from utils import app_account, app_api, newsletter


class AppAccountTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{Path(self.tmp.name) / 't.db'}")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.mail = AsyncMock(return_value=(True, ""))
        self.patches = [patch.object(app_api, "get_session", self.sessions),
                        patch.object(app_account, "get_session", self.sessions),
                        patch.object(app_api, "send_email_message", self.mail)]
        for p in self.patches:
            p.start()
        newsletter._hits.clear()
        app = web.Application()
        app_api.install_routes(app)
        app_account.install_routes(app)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        for p in self.patches:
            p.stop()
        await self.engine.dispose()
        self.tmp.cleanup()

    async def _login(self, email):
        await self.client.post("/api/app/auth/email", json={"email": email})
        code = re.search(r"\d{6}", self.mail.await_args.args[1]).group(0)
        d = await (await self.client.post("/api/app/auth/verify", json={"email": email, "code": code})).json()
        return d["token"], d["user"]["id"]

    async def test_delete_wipes_data_and_closes_login(self):
        token, uid = await self._login("anna@example.com")
        other_token, other = await self._login("boris@example.com")
        async with self.sessions() as s:
            post = UserPost(user_id=uid, text="привет")
            s.add(post)
            await s.flush()
            s.add_all([PostPhoto(post_id=post.id, idx=0, data=b"x"), PostLike(post_id=post.id, user_id=other),
                       AppFavorite(user_id=uid, key="e1", title="Событие")])
            await s.commit()
        h = {"Authorization": f"Bearer {token}"}
        no = await self.client.post("/api/app/me/delete", json={}, headers=h)
        self.assertEqual(no.status, 400)   # без подтверждения ничего не удаляем
        ok = await self.client.post("/api/app/me/delete", json={"confirm": True}, headers=h)
        self.assertEqual(ok.status, 200)
        async with self.sessions() as s:
            u = await s.get(AppUser, uid)
            self.assertIsNone(u.email)
            self.assertEqual(u.name, app_account.DELETED_NAME)
            for model in (UserPost, PostPhoto, PostLike, AppFavorite):
                self.assertEqual(await s.scalar(select(func.count()).select_from(model)), 0, model.__name__)
            self.assertIsNotNone(await s.get(AppUser, other))
        me = await self.client.get("/api/app/me", headers=h)
        self.assertEqual(me.status, 401)   # старый токен больше не пускает
        other_me = await self.client.get("/api/app/me", headers={"Authorization": f"Bearer {other_token}"})
        self.assertEqual(other_me.status, 200)
        _, new_uid = await self._login("anna@example.com")
        self.assertNotEqual(new_uid, uid)   # та же почта создаёт новый пустой аккаунт


if __name__ == "__main__":
    unittest.main()
