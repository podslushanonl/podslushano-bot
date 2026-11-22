"""End-to-end admin reply flow with SQLite and a recording Telegram transport."""
import asyncio
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aiogram import Bot, Dispatcher, Router
from aiogram.client.session.base import BaseSession
from aiogram.exceptions import TelegramForbiddenError
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, Message, MessageEntity, Update, User
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import config
from database.models import Base, Meta
from database.anonymous_questions import AnonymousAnswer, AnonymousQuestion
from handlers import anonymous_questions as aq, anonymous_replies as ar
from utils import users

ADMIN = 111
CHANNEL = -1001234567890
WORK = -1009999999999


class Transport(BaseSession):
    def __init__(self):
        super().__init__()
        self.calls = []
        self.posts = []
        self.failure = None
        self.permissions = True

    async def close(self):
        pass

    async def stream_content(self, *args, **kwargs):
        yield b""

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        name = method.__api_method__
        if name == "getChat":
            cid = int(method.chat_id)
            return SimpleNamespace(id=cid, type="channel" if cid != -1007 else "supergroup",
                                   title="ЧАСТНЫЙ СЛУЧАЙ" if cid == CHANNEL else "Other", username=None)
        if name == "getChatMember":
            return SimpleNamespace(status="administrator", can_post_messages=self.permissions)
        if name in {"sendMessage", "editMessageText"}:
            if method.chat_id < 0:
                assert method.chat_id == CHANNEL, "Never publish to the work channel"
                if self.failure == "forbidden":
                    raise TelegramForbiddenError(method=method, message="No permission")
                if self.failure == "network":
                    raise TimeoutError("Delivery may have happened")
                self.posts.append(method)
            return Message(message_id=len(self.calls), date=datetime.now(timezone.utc),
                           chat={"id": method.chat_id, "type": "channel" if method.chat_id < 0 else "private"}, text=method.text)
        return True

    def publish_button(self):
        for method in reversed(self.calls):
            markup = getattr(method, "reply_markup", None)
            if markup:
                for row in markup.inline_keyboard:
                    for button in row:
                        if (button.callback_data or "").startswith("alexpub:publish:"):
                            return button.callback_data
        raise AssertionError("No publication preview")


async def main():
    with tempfile.TemporaryDirectory() as tmp:
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp}/test.db")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        transport = Transport()
        bot = Bot("123456:TEST_TOKEN", session=transport)
        dp = Dispatcher()
        dp.message.middleware(users.RegisterUserMiddleware())
        dp.callback_query.middleware(users.RegisterUserMiddleware())
        dp.include_router(ar.router)
        dp.include_router(aq.router)
        navigation = Router()

        @navigation.message(CommandStart())
        async def menu(message, state):
            await state.clear()
            await message.answer("Menu")

        dp.include_router(navigation)
        sequence = 0

        async def send(text, uid=ADMIN, entities=None):
            nonlocal sequence
            sequence += 1
            msg = Message(message_id=sequence, date=datetime.now(timezone.utc),
                          chat={"id": uid, "type": "private"},
                          from_user=User(id=uid, is_bot=False, first_name="Admin"),
                          text=text, entities=entities)
            await dp.feed_update(bot, Update(update_id=sequence, message=msg))

        async def click(payload, uid=ADMIN, chat_id=None):
            nonlocal sequence
            sequence += 1
            msg = Message(message_id=sequence, date=datetime.now(timezone.utc),
                          chat={"id": chat_id or uid, "type": "supergroup" if chat_id else "private"}, text="Question")
            cb = CallbackQuery(id=str(sequence), from_user=User(id=uid, is_bot=False, first_name="Test"),
                               chat_instance="test", message=msg, data=payload)
            await dp.feed_update(bot, Update(update_id=sequence, callback_query=cb))

        async def draft_status(qid):
            async with sessions() as db:
                return (await db.get(AnonymousAnswer, qid)).status

        with patch.object(aq, "get_session", sessions), patch.object(ar, "get_session", sessions), \
             patch.object(users, "get_session", sessions), patch.object(config, "ADMIN_IDS", [ADMIN]), \
             patch.object(config, "ANNOUNCE_CHANNEL", str(WORK)):
            async with sessions() as db:
                for i in range(1, 5):
                    db.add(AnonymousQuestion(id=i, sender_hash="anonymous", text=f"Вопрос {i} <приватный>?", status="pending"))
                await db.commit()
            await click("alexq:reply:1", uid=222)
            assert await ar._channel_id() is None
            await click("alexq:reply:1")
            await send(str(WORK))
            assert "рабочий канал" in transport.calls[-1].text
            await send("-1007")
            assert "не чат" in transport.calls[-1].text
            transport.permissions = False
            await send(str(CHANNEL))
            assert "нет права" in transport.calls[-1].text
            transport.permissions = True
            await send(str(CHANNEL))
            assert await ar._channel_id() is None, "Must confirm destination first"
            await click("alexpub:connect")
            assert await ar._channel_id() == CHANNEL
            assert await dp.fsm.get_context(bot=bot, chat_id=ADMIN, user_id=ADMIN).get_state() == ar.ReplyForm.answer.state
            await send("Привет, это мой ответ 🤍", entities=[MessageEntity(type="bold", offset=0, length=6)])
            preview = transport.publish_button()
            assert not transport.posts, "Writing an answer never publishes"
            assert "<b>Привет</b>" in transport.calls[-1].text
            assert "&lt;приватный&gt;" in transport.calls[-1].text
            await click(preview, uid=222)
            assert not transport.posts
            await click("alexpub:edit:1")
            await click(preview)
            assert not transport.posts, "Old preview cannot publish during editing"
            await send("😀" * 2100)
            assert "не помещается" in transport.calls[-1].text
            await send("Исправленный ответ")
            cancelled = transport.publish_button()
            # Simulate losing FSM data after restart before cancelling this preview.
            await dp.fsm.get_context(bot=bot, chat_id=ADMIN, user_id=ADMIN).clear()
            await click(cancelled.replace("alexpub:publish:", "alexpub:cancel:"))
            await click(cancelled)
            assert not transport.posts, "Cancel invalidates publication button"
            await click("alexq:reply:1")
            preview = transport.publish_button()
            transport.permissions = False
            await click(preview)
            assert not transport.posts, "Recheck permissions at publication"
            transport.permissions = True
            await asyncio.gather(click(preview), click(preview))
            assert len(transport.posts) == 1, "Double-click publishes only once"
            assert "Исправленный ответ" in transport.posts[0].text
            assert await draft_status(1) == "published"
            async with sessions() as db:
                assert (await db.get(AnonymousQuestion, 1)).status == "published"
                assert (await db.get(AnonymousAnswer, 1)).message_id
            await click(preview)
            assert len(transport.posts) == 1
            for action in ["answer", "skip", "block"]:
                await click(f"alexq:{action}:1")
                async with sessions() as db:
                    assert (await db.get(AnonymousQuestion, 1)).status == "published"
            await click("alexq:reply:2", chat_id=-100777)
            assert "личный чат" in transport.calls[-1].text

            # Definite Telegram rejection remains retryable.
            await click("alexq:reply:2")
            await send("Второй ответ")
            preview = transport.publish_button()
            transport.failure = "forbidden"
            await click(preview)
            assert await draft_status(2) == "draft"
            transport.failure = None
            await click("alexq:reply:2")
            await click(transport.publish_button())
            assert await draft_status(2) == "published"
            assert len(transport.posts) == 2

            # Ambiguous delivery is never retried automatically or by old buttons.
            await click("alexq:reply:3")
            await send("Третий ответ")
            preview = transport.publish_button()
            transport.failure = "network"
            await click(preview)
            assert await draft_status(3) == "uncertain"
            transport.failure = None
            await click(preview)
            await click("alexq:reply:3")
            assert len(transport.posts) == 2

            # Commands escape the reply form without becoming answers.
            await click("alexq:reply:4")
            await send("/alexquestions")
            assert await dp.fsm.get_context(bot=bot, chat_id=ADMIN, user_id=ADMIN).get_state() is None
            async with sessions() as db:
                assert await db.get(AnonymousAnswer, 4) is None
            await click("alexq:reply:4")
            await send("Сохранённый черновик")
            old_preview = transport.publish_button()
            # Changing the bound channel makes this preview unusable.
            async with sessions() as db:
                (await db.get(Meta, ar.CHANNEL_KEY)).value = str(-1008888888888)
                await db.commit()
            await click(old_preview)
            assert len(transport.posts) == 2
            assert await draft_status(4) == "draft"
        await dp.storage.close()
        await bot.session.close()
        await engine.dispose()
    print("anonymous reply flow: OK")


if __name__ == "__main__":
    asyncio.run(main())
