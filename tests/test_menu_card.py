"""Карточка меню: разделы открываются от имени пользователя; кнопки команд админ-центра."""
import unittest
from datetime import datetime
from unittest.mock import patch

from aiogram import Bot, Dispatcher, Router
from aiogram.client.session.base import BaseSession
from aiogram.filters import Command
from aiogram.methods import AnswerCallbackQuery, EditMessageText, SendMessage
from aiogram.types import CallbackQuery, Chat, Message, Update, User

import config
from handlers import admin_center, menu


class FakeSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.calls = []

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if isinstance(method, (SendMessage, EditMessageText)):
            return Message(message_id=99, date=datetime.now(), chat=Chat(id=7, type="private"), text="ok")
        return True

    async def stream_content(self, *a, **k):  # pragma: no cover
        yield b""

    async def close(self):
        pass


BOT_USER = User(id=1, is_bot=True, first_name="bot")
HUMAN = User(id=7, is_bot=False, first_name="Анна")


def cb_update(data: str, n: int) -> Update:
    msg = Message(message_id=5, date=datetime.now(), chat=Chat(id=7, type="private"), from_user=BOT_USER, text="card")
    return Update(update_id=n, callback_query=CallbackQuery(id=str(n), from_user=HUMAN, chat_instance="x",
                                                           message=msg, data=data))


class MenuCardTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.session = FakeSession()
        self.bot = Bot("123456:TEST", session=self.session)
        self.seen = []

    async def test_entry_runs_as_user_and_sections_edit_card(self):
        async def share(message, state):
            self.seen.append(message.from_user.id)

        dp = Dispatcher()
        dp.include_router(menu.router)
        with patch.object(menu, "_entries", lambda: {"share": share}):
            await dp.feed_update(self.bot, cb_update("m:go:share", 1))
        self.assertEqual(self.seen, [7])  # не id бота
        await dp.feed_update(self.bot, cb_update("m:biz", 2))
        edits = [c for c in self.session.calls if isinstance(c, EditMessageText)]
        self.assertTrue(edits and "Для бизнеса" in edits[-1].text)
        self.assertTrue(any(isinstance(c, AnswerCallbackQuery) for c in self.session.calls))

    def test_every_card_button_has_entry(self):
        keys = {b.callback_data[5:] for s in ("main", "services", "biz", "more")
                for row in menu.card_kb(s).inline_keyboard for b in row
                if b.callback_data and b.callback_data.startswith("m:go:")}
        self.assertTrue(keys <= set(menu._entries()), keys - set(menu._entries()))

    async def test_admin_command_button_feeds_real_command(self):
        extra = Router()

        @extra.message(Command("channels"))
        async def channels(message: Message):
            self.seen.append((message.from_user.id, message.text, message.chat.id))

        dp = Dispatcher()
        with patch.object(config, "ADMIN_IDS", [7]):
            # фильтры роутера читают ADMIN_IDS при создании — пересобираем на время теста
            r = Router()
            r.callback_query.register(admin_center.run_command, lambda c: c.data.startswith("acrun:"))
            dp.include_router(r)
            dp.include_router(extra)
            await dp.feed_update(self.bot, cb_update("acrun:channels", 3))
        self.assertEqual(self.seen, [(7, "/channels", 7)])


if __name__ == "__main__":
    unittest.main()
