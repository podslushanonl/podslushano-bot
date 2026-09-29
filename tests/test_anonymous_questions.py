"""Минимальные regression-checks приватности/маршрутизации ask_alex."""
import os
import sys
from pathlib import Path
import asyncio
import tempfile
from datetime import datetime, timezone
from unittest.mock import patch

from aiogram import Bot, Dispatcher, Router
from aiogram.client.session.base import BaseSession
from aiogram.filters import CommandStart
from aiogram.types import Message, Update, User, CallbackQuery
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database.models import Base, BotUser
from database.anonymous_questions import AnonymousQuestion
from handlers import anonymous_questions as aq
from utils import users

import config
from handlers.anonymous_questions import (
    _callback_question_id,
    question_target_chat_id,
    sender_hash,
)


def main() -> None:
    original_token = config.BOT_TOKEN
    original_admins = list(config.ADMIN_IDS)
    original_target = os.environ.get("ALEX_QUESTIONS_CHAT_ID")
    try:
        config.BOT_TOKEN = "test-secret-token"
        config.ADMIN_IDS[:] = [111]

        first = sender_hash(123456789)
        second = sender_hash(123456789)
        other = sender_hash(987654321)
        assert first == second
        assert first != other
        assert len(first) == 64
        assert "123456789" not in first

        os.environ.pop("ALEX_QUESTIONS_CHAT_ID", None)
        assert question_target_chat_id() == 111
        os.environ["ALEX_QUESTIONS_CHAT_ID"] = "-1001234567890"
        assert question_target_chat_id() == -1001234567890

        assert _callback_question_id("alexq:answer:42") == 42
        assert _callback_question_id("alexq:skip:not-a-number") is None
        assert _callback_question_id(None) is None
    finally:
        config.BOT_TOKEN = original_token
        config.ADMIN_IDS[:] = original_admins
        if original_target is None:
            os.environ.pop("ALEX_QUESTIONS_CHAT_ID", None)
        else:
            os.environ["ALEX_QUESTIONS_CHAT_ID"] = original_target

    asyncio.run(check_flow())
    print("anonymous questions checks: OK")



class TelegramSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.sent = []
        self.fail_admin = False

    async def close(self):
        pass

    async def stream_content(self, *args, **kwargs):
        yield b""

    async def make_request(self, bot, method, timeout=None):
        self.sent.append(method)
        if self.fail_admin and method.__api_method__ == "sendMessage" and method.chat_id == 111:
            raise RuntimeError("Simulated delivery failure")
        if method.__api_method__ in {"sendMessage", "editMessageText"}:
            return Message(message_id=len(self.sent), date=datetime.now(timezone.utc),
                           chat={"id": method.chat_id, "type": "private"}, text=method.text)
        return True


async def check_flow():
    with tempfile.TemporaryDirectory() as tmp:
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp}/test.db")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        telegram = TelegramSession()
        bot = Bot("123456:TEST_TOKEN", session=telegram)
        dp = Dispatcher()
        dp.message.middleware(users.RegisterUserMiddleware())
        dp.callback_query.middleware(users.RegisterUserMiddleware())
        dp.include_router(aq.router)
        navigation = Router()

        @navigation.message(CommandStart())
        async def normal_start(message, state):
            await state.clear()
            await message.answer("Regular menu")

        dp.include_router(navigation)
        sequence = 0

        async def send(text, uid=222):
            nonlocal sequence
            sequence += 1
            message = Message(message_id=sequence, date=datetime.now(timezone.utc),
                              chat={"id": uid, "type": "private"},
                              from_user=User(id=uid, is_bot=False, first_name="Private", username="private_name"),
                              text=text)
            await dp.feed_update(bot, Update(update_id=sequence, message=message))

        async def click(data, uid=111):
            nonlocal sequence
            sequence += 1
            message = Message(message_id=sequence, date=datetime.now(timezone.utc),
                              chat={"id": uid, "type": "private"}, text="Question")
            query = CallbackQuery(id=str(sequence), from_user=User(id=uid, is_bot=False, first_name="Test"),
                                  chat_instance="test", message=message, data=data)
            await dp.feed_update(bot, Update(update_id=sequence, callback_query=query))

        old_known = set(users._known)
        users._known.clear()
        try:
            with patch.object(aq, "get_session", sessions), patch.object(users, "get_session", sessions), \
                 patch.object(config, "ADMIN_IDS", [111]), patch.object(config, "BOT_TOKEN", "test-secret"), \
                 patch.dict(os.environ, {"ALEX_QUESTIONS_CHAT_ID": "111"}):
                await send("/start ask_alex")
                await send("Первый анонимный вопрос?")
                async with sessions() as db:
                    assert await db.get(BotUser, 222) is None
                    questions = (await db.scalars(select(AnonymousQuestion))).all()
                    assert len(questions) == 1
                    assert questions[0].text == "Первый анонимный вопрос?"
                admin_messages = [m for m in telegram.sent if getattr(m, "chat_id", None) == 111]
                assert len(admin_messages) == 1
                assert "private_name" not in admin_messages[0].text
                assert "Private" not in admin_messages[0].text
                await click("alexq:answer:1", uid=222)
                async with sessions() as db:
                    assert (await db.get(AnonymousQuestion, 1)).status == "pending"
                await click("alexq:answer:1")
                async with sessions() as db:
                    assert (await db.get(AnonymousQuestion, 1)).status == "selected"

                await send("/start ask_alex", uid=333)
                telegram.fail_admin = True
                await send("Вопрос при сбое доставки?", uid=333)
                assert "Уведомление пока не доставлено" in telegram.sent[-1].text
                telegram.fail_admin = False
                await send("/alexquestions", uid=111)
                assert "Вопрос при сбое доставки?" in telegram.sent[-1].text
                buttons = telegram.sent[-1].reply_markup.inline_keyboard
                assert any(b.callback_data == "alexq:open:2" for row in buttons for b in row)
                await click("alexq:open:2")
                await click("alexq:skip:2")
                async with sessions() as db:
                    assert (await db.get(AnonymousQuestion, 2)).status == "skipped"
                    assert await db.get(BotUser, 333) is None

                await send("/start ask_alex", uid=444)
                await send("😀" * 2000, uid=444)
                assert "слишком длинный" in telegram.sent[-1].text
                await click("alexq:cancel", uid=444)
                await click("alexq:new", uid=444)
                await send("Ещё один вопрос?", uid=444)
                await click("alexq:block:3")
                await click("alexq:new", uid=444)
                await send("Заблокированный вопрос?", uid=444)
                assert "недоступна" in telegram.sent[-1].text
                async with sessions() as db:
                    assert await db.get(BotUser, 444) is None

                await send("/start ask_alex", uid=555)
                await send("/start", uid=555)
                assert telegram.sent[-1].text == "Regular menu"
                state = dp.fsm.get_context(bot=bot, chat_id=555, user_id=555)
                assert await state.get_state() is None
                async with sessions() as db:
                    assert await db.get(BotUser, 555) is not None
                    assert len((await db.scalars(select(AnonymousQuestion))).all()) == 3
                await send("/start ask_alex", uid=111)
                await send("/alexquestions", uid=111)
                assert "Новые:" in telegram.sent[-1].text
        finally:
            users._known.clear()
            users._known.update(old_known)
            await dp.storage.close()
            await bot.session.close()
            await engine.dispose()


if __name__ == "__main__":
    main()
