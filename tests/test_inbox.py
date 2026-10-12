"""Инбокс: уведомления админам уходят в группу с темами, ответы на действия админа — нет."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from aiogram.methods import SendMessage
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import config
from database.models import Base
from utils import inbox


class TopicMapTests(unittest.TestCase):
    def test_modules(self):
        self.assertEqual(inbox.topic_for_module("handlers.board"), "board")
        self.assertEqual(inbox.topic_for_module("handlers.afisha"), "afisha")
        self.assertEqual(inbox.topic_for_module("utils.notify"), "submissions")
        self.assertEqual(inbox.topic_for_module("ad_material_reminder_runtime"), "ads")
        self.assertEqual(inbox.topic_for_module("handlers.errors"), "errors")
        self.assertIsNone(inbox.topic_for_module("handlers.anonymous_questions"))
        self.assertEqual(inbox.topic_for_module("handlers.something_new"), "other")


class RedirectTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{Path(self.tmp.name) / 't.db'}")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.patches = [patch.object(inbox, "get_session", async_sessionmaker(self.engine, expire_on_commit=False)),
                        patch.object(config, "ADMIN_IDS", [11, 22])]
        for p in self.patches:
            p.start()
        inbox._chat, inbox._chat_loaded = None, False
        inbox._threads.clear()
        inbox._recent.clear()
        self.bot = SimpleNamespace(create_forum_topic=AsyncMock(return_value=SimpleNamespace(message_thread_id=77)))
        self.sent = []

        async def make_request(bot, method):
            self.sent.append((method.chat_id, getattr(method, "message_thread_id", None), method.text))
            return f"resp{len(self.sent)}"
        self.mr = make_request
        self.mw = inbox.InboxRedirect()

    async def asyncTearDown(self):
        for p in self.patches:
            p.stop()
        inbox._chat, inbox._chat_loaded = None, False
        await self.engine.dispose()
        self.tmp.cleanup()

    async def notify(self, admin_id, text="Новое объявление"):
        return await self.mw(self.mr, self.bot, SendMessage(chat_id=admin_id, text=text))

    async def test_without_inbox_goes_to_dm(self):
        await self.notify(11)
        self.assertEqual(self.sent, [(11, None, "Новое объявление")])

    async def test_redirect_dedup_and_actor(self):
        await inbox._meta_set("inbox_chat", "-1009")
        inbox._chat_loaded = False
        with patch.object(inbox, "_caller_topic", lambda: "board"):
            await self.notify(11)
            await self.notify(22)  # то же уведомление второму админу — в группе уже есть
            self.assertEqual(self.sent, [(-1009, 77, "Новое объявление")])
            self.bot.create_forum_topic.assert_awaited_once()
            self.assertEqual(self.bot.create_forum_topic.await_args.kwargs["name"], inbox.TOPICS["board"])
            token = inbox._actor.set(11)  # админ сам нажал кнопку — ответ ему в личку
            try:
                await self.notify(11, "Готово")
            finally:
                inbox._actor.reset(token)
            self.assertEqual(self.sent[-1], (11, None, "Готово"))
        with patch.object(inbox, "_caller_topic", lambda: None):  # анонимные вопросы остаются в личке
            await self.notify(11, "Анонимный вопрос")
            self.assertEqual(self.sent[-1], (11, None, "Анонимный вопрос"))
        await self.mw(self.mr, self.bot, SendMessage(chat_id=555, text="пользователю"))
        self.assertEqual(self.sent[-1], (555, None, "пользователю"))

    def test_caller_topic_from_real_stack(self):
        self.assertEqual(inbox._caller_topic(), "other")  # вызов из tests.* — раздела нет


if __name__ == "__main__":
    unittest.main()
