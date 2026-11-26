"""Signed HTTP intake and durable send receipts, isolated from production state."""
import asyncio
import importlib.util
import json
import os
import tempfile
import time
import types
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendMessage
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from sqlalchemy import String
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Meta(Base):
    __tablename__ = "meta"
    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    value: Mapped[str] = mapped_column(String(100))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DealsIntakeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_async_engine("sqlite+aiosqlite:///" + self.tmp.name + "/state.db")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.session = async_sessionmaker(self.engine, expire_on_commit=False)

        async def meta_set(key, value):
            async with self.session() as session:
                session.add(Meta(key=key, value=value[:100]))
                try:
                    await session.commit()
                    return True
                except IntegrityError:
                    await session.rollback()
                    return False

        self.cid = "-1001234567890"
        self.wp = AsyncMock(return_value={"chat": self.cid})
        modules = {
            "config": types.SimpleNamespace(ADMIN_IDS=[]),
            "database.db": types.SimpleNamespace(get_session=self.session),
            "database.models": types.SimpleNamespace(Meta=Meta),
            "utils.deals_bridge": types.SimpleNamespace(wp_call=self.wp),
            "utils.site_api": types.SimpleNamespace(_meta_set=meta_set),
        }
        root = Path(__file__).resolve().parents[1]
        with patch.dict("sys.modules", modules):
            self.editorial = load("editorial_intake_test", root / "utils/deals_editorial.py")
            modules["utils.deals_editorial"] = self.editorial
            with patch.dict("sys.modules", modules):
                self.intake = load("deals_intake_test", root / "utils/deals_intake.py")
        # target_status imports the bridge lazily, so retain its stub for this test.
        self.module_patch = patch.dict("sys.modules", {"utils.deals_bridge": modules["utils.deals_bridge"]})
        self.module_patch.start()
        self.bot = AsyncMock()
        self.bot.id = 42
        self.bot.get_chat.return_value = types.SimpleNamespace(type="channel")
        self.bot.get_chat_member.return_value = types.SimpleNamespace(can_post_messages=True)
        self.bot.send_message.return_value = types.SimpleNamespace(message_id=101)
        self.bot.send_photo.return_value = types.SimpleNamespace(message_id=102)
        self.key = Ed25519PrivateKey.generate()
        self.env = patch.dict(os.environ, {
            "DEALS_EDITORIAL_PUBLIC_KEY": self.key.public_key().public_bytes_raw().hex(),
            "DEALS_EDITORIAL_ACTIVE_UNTIL": (datetime.now(ZoneInfo("UTC")) + timedelta(days=1)).isoformat(),
        })
        self.env.start()
        app = web.Application()
        app["bot"] = self.bot
        self.intake.install_routes(app)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()
        now = datetime.now(ZoneInfo("Europe/Amsterdam"))
        self.batch = {"channel_id": self.cid, "silent": True, "checked_at": now.isoformat(), "posts": [{
            "id": now.date().isoformat() + "-real-offer", "html": "<b>Verified offer</b>",
            "buttons": [{"label": "Offer", "url": "https://example.com/offer"}],
            "publish_before": now.replace(hour=23, minute=59, second=59).isoformat(),
        }]}

    async def asyncTearDown(self):
        await self.client.close()
        self.env.stop()
        self.module_patch.stop()
        await self.engine.dispose()
        self.tmp.cleanup()

    def headers(self, method, path, body=b"", stamp=None, key=None):
        stamp = str(int(time.time())) if stamp is None else stamp
        signature = (key or self.key).sign(self.intake.signing_message(stamp, method, path, body)).hex()
        return {"X-Editorial-Timestamp": stamp, "X-Editorial-Signature": signature}

    async def post(self, batch=None, **kw):
        body = json.dumps(batch or self.batch).encode()
        headers = self.headers("POST", self.intake.BASE, body, **kw)
        return await self.client.post(self.intake.BASE, data=body, headers=headers)

    async def test_auth_rejects_unsigned_tampered_expired_and_wrong_key(self):
        response = await self.client.post(self.intake.BASE, json=self.batch)
        self.assertEqual(response.status, 401)
        for opts in [{"stamp": str(int(time.time()) - 301)}, {"key": Ed25519PrivateKey.generate()}]:
            self.assertEqual((await self.post(**opts)).status, 401)
        body = json.dumps(self.batch).encode()
        response = await self.client.post(self.intake.BASE, data=body + b" ",
            headers=self.headers("POST", self.intake.BASE, body))
        self.assertEqual(response.status, 401)
        self.bot.send_message.assert_not_awaited()

    async def test_expired_pilot_fails_closed(self):
        with patch.dict(os.environ, {"DEALS_EDITORIAL_ACTIVE_UNTIL": "2020-01-01T00:00:00+00:00"}):
            self.assertEqual((await self.post()).status, 401)

    async def test_dry_run_and_target_scope(self):
        self.batch["dry_run"] = True
        self.assertEqual((await self.post()).status, 200)
        self.bot.send_message.assert_not_awaited()
        self.batch["channel_id"] = "-1009999999999"
        self.assertEqual((await self.post()).status, 503)
        self.bot.send_message.assert_not_awaited()

    async def test_photo_text_receipts_and_restart_dedup(self):
        photo = dict(self.batch["posts"][0], id=self.batch["posts"][0]["id"] + "-photo",
            photo_url="https://example.com/item.jpg")
        self.batch["posts"].append(photo)
        first = await (await self.post()).json()
        self.assertTrue(first["ok"])
        self.assertEqual(first["sent"], 2)
        self.assertEqual({r["message_id"] for r in first["receipts"]}, {101, 102})
        # Remove the process lock to simulate a fresh worker using the same disk.
        self.editorial._lock = asyncio.Lock()
        second = await (await self.post()).json()
        self.assertTrue(second["ok"])
        self.assertEqual(second["skipped"], 2)
        self.bot.send_message.assert_awaited_once()
        self.bot.send_photo.assert_awaited_once()
        self.assertTrue(self.bot.send_photo.call_args.kwargs["disable_notification"])
        response = await self.client.get(self.intake.BASE + "/status",
            headers=self.headers("GET", self.intake.BASE + "/status"))
        self.assertEqual(len((await response.json())["recent"]), 2)

    async def test_timeout_cannot_duplicate_and_definite_rejection_can_retry(self):
        self.bot.send_message.side_effect = TimeoutError()
        first = await (await self.post()).json()
        self.assertFalse(first["ok"])
        self.assertEqual(first["receipts"][0]["state"], "delivery_unknown")
        self.bot.send_message.side_effect = None
        await self.post()
        self.assertEqual(self.bot.send_message.await_count, 1)
        self.batch["posts"][0]["id"] += "-rejected"
        self.bot.send_message.side_effect = TelegramBadRequest(method=SendMessage(chat_id=1, text="test"), message="rejected")
        self.assertEqual((await (await self.post()).json())["failed"], 1)
        self.bot.send_message.side_effect = None
        self.assertTrue((await (await self.post()).json())["ok"])

    async def test_changed_id_content_and_stale_research_rejected(self):
        await self.post()
        self.batch["posts"][0]["html"] = "changed"
        self.assertEqual((await self.post()).status, 400)
        self.bot.send_message.assert_awaited_once()
        self.batch["checked_at"] = (datetime.now(ZoneInfo("UTC")) - timedelta(hours=2)).isoformat()
        self.assertEqual((await self.post()).status, 400)

    async def test_concurrent_submissions_send_once(self):
        responses = await asyncio.gather(self.post(), self.post())
        results = [await response.json() for response in responses]
        self.assertTrue(all(r["ok"] for r in results))
        self.assertEqual(sum(r["sent"] for r in results), 1)
        self.bot.send_message.assert_awaited_once()

    async def test_wrong_date_and_oversized_body_are_not_sent(self):
        self.batch["posts"][0]["id"] = "2020-01-01-expired"
        self.assertEqual((await self.post()).status, 400)
        response = await self.client.post(self.intake.BASE, data=b"x" * 65001)
        self.assertEqual(response.status, 413)
        self.bot.send_message.assert_not_awaited()

    async def correct(self, payload):
        body = json.dumps(payload).encode()
        return await self.client.post(self.intake.BASE + "/buttons", data=body,
            headers=self.headers("POST", self.intake.BASE + "/buttons", body))

    async def test_button_correction_requires_receipt_and_preserves_post(self):
        payload = {"channel_id": self.cid, "checked_at": self.batch["checked_at"], "updates": [{
            "id": self.batch["posts"][0]["id"],
            "buttons": [{"label": "Official catalogue", "url": "https://example.com/catalogue"}]}]}
        self.assertEqual((await self.correct(payload)).status, 409)
        self.bot.edit_message_reply_markup.assert_not_awaited()
        await self.post()
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
        self.bot.edit_message_reply_markup.return_value = types.SimpleNamespace(reply_markup=
            InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Official catalogue", url="https://example.com/catalogue")]]))
        payload["dry_run"] = True
        self.assertEqual((await (await self.correct(payload)).json())["state"], "validated_not_edited")
        self.bot.edit_message_reply_markup.assert_not_awaited()
        payload["dry_run"] = False
        result = await (await self.correct(payload)).json()
        self.assertTrue(result["ok"])
        self.assertEqual(result["edited"], 1)
        self.assertEqual(self.bot.edit_message_reply_markup.call_args.kwargs["message_id"], 101)
        self.assertEqual(self.bot.edit_message_reply_markup.call_args.kwargs["chat_id"], int(self.cid))
        self.bot.send_message.assert_awaited_once()
        self.bot.send_photo.assert_not_awaited()
        payload["channel_id"] = "-1009999999999"
        self.assertEqual((await self.correct(payload)).status, 503)
        self.bot.edit_message_reply_markup.assert_awaited_once()

    async def test_ambiguous_send_cannot_be_edited(self):
        self.bot.send_message.side_effect = TimeoutError()
        await self.post()
        payload = {"channel_id": self.cid, "checked_at": self.batch["checked_at"], "updates": [{
            "id": self.batch["posts"][0]["id"], "buttons": [{"label": "Official", "url": "https://example.com/"}]}]}
        self.assertEqual((await self.correct(payload)).status, 409)
        self.bot.edit_message_reply_markup.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
