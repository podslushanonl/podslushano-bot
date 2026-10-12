"""Инбокс администратора: все уведомления бота — в одну группу с темами, а не в личку.

Как подключить: добавить бота в закрытую супергруппу с включёнными темами (права
администратора: управление темами), написать там /inbox. Отключить: /inbox off.

Как работает. Уведомления по всему коду шлются админам в личку (циклы по
ADMIN_IDS). Middleware сессии бота перехватывает такие отправки и переносит их в
группу, в тему по разделу (предложка, объявления, афиша, оплаты специалистов…).
Не трогает:
- ответы на действие самого админа (он нажал кнопку или ввёл команду в личке —
  ответ остаётся у него в личке);
- разделы, где ответ админа идёт через анкету только в личке (анонимные вопросы).
Одинаковое уведомление для нескольких админов попадает в группу один раз.
Пока инбокс не подключён, всё работает как раньше.
"""
from __future__ import annotations

import contextvars
import hashlib
import logging
import os
import sys
import time

from aiogram import BaseMiddleware, F, Router
from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.methods import (
    CopyMessage, ForwardMessage, SendAnimation, SendAudio, SendDocument, SendMediaGroup,
    SendMessage, SendPhoto, SendVideo, SendVoice,
)
from aiogram.types import Message

import config
from database.db import get_session
from database.models import Meta

log = logging.getLogger(__name__)
router = Router()

# Тема → (название, эмодзи-иконка для понятности в списке тем)
TOPICS = {
    "submissions": "📨 Предложка",
    "support": "✉️ Связь с нами",
    "board": "📋 Объявления",
    "afisha": "📅 Афиша",
    "specialists": "💼 Специалисты и оплаты",
    "ads": "📢 Реклама",
    "allo": "🚶 allowalks",
    "content": "📰 Контент и новости",
    "errors": "⚠️ Ошибки",
    "other": "🗂 Прочее",
}
# Модуль, откуда пришло уведомление → тема. None — оставить в личке.
_MODULE_TOPIC = [
    ("handlers.anonymous_", None),
    ("handlers.submissions", "submissions"), ("handlers.stories", "submissions"),
    ("handlers.moderation", "submissions"), ("utils.notify", "submissions"),
    ("handlers.chat", "submissions"), ("utils.video_submissions", "submissions"),
    ("handlers.support", "support"),
    ("handlers.board", "board"),
    ("handlers.afisha", "afisha"), ("handlers.events", "afisha"), ("handlers.evenementen", "afisha"),
    ("utils.afisha_site", "afisha"),
    ("handlers.selfadd", "specialists"), ("handlers.cabinet", "specialists"), ("handlers.contacts", "specialists"),
    ("utils.site_api", "specialists"), ("handlers.invoice_admin", "specialists"), ("utils.invoices", "specialists"),
    ("handlers.allo", "allo"), ("utils.allo", "allo"),
    ("handlers.ads", "ads"), ("handlers.ad_", "ads"), ("handlers.ai_sales", "ads"), ("utils.ad_", "ads"),
    ("utils.ai_sales", "ads"), ("ad_", "ads"), ("instagram_sales_runtime", "ads"),
    ("utils.editorial", "content"), ("handlers.content", "content"), ("utils.site_news", "content"),
    ("handlers.digest", "content"), ("handlers.spotlight", "content"), ("handlers.photo_refresh", "content"),
    ("utils.authors_web", "content"), ("handlers.guides", "content"),
    ("handlers.errors", "errors"), ("bot", "errors"),
]
_SEND = (SendMessage, SendPhoto, SendVideo, SendDocument, SendAnimation, SendAudio, SendVoice,
         SendMediaGroup, CopyMessage, ForwardMessage)
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_actor: contextvars.ContextVar[int | None] = contextvars.ContextVar("inbox_actor", default=None)
_chat: int | None = None
_chat_loaded = False
_threads: dict[str, int] = {}
_recent: dict[str, tuple[float, object]] = {}


async def _meta(key: str) -> str | None:
    async with get_session() as session:
        row = await session.get(Meta, key)
        return row.value if row and row.value else None


async def _meta_set(key: str, value: str | None) -> None:
    async with get_session() as session:
        row = await session.get(Meta, key)
        if value is None:
            if row:
                await session.delete(row)
        else:
            await session.merge(Meta(key=key, value=value))
        await session.commit()


async def inbox_chat() -> int | None:
    global _chat, _chat_loaded
    if not _chat_loaded:
        raw = await _meta("inbox_chat")
        _chat = int(raw) if raw and raw.lstrip("-").isdigit() else None
        _chat_loaded = True
    return _chat


def topic_for_module(module: str) -> str | None:
    for prefix, topic in _MODULE_TOPIC:
        if module == prefix or module.startswith(prefix):
            return topic
    return "other"


def _caller_topic() -> str | None:
    """Раздел по модулю, из которого бот отправляет уведомление."""
    f = sys._getframe(2)
    while f:
        path = os.path.abspath(f.f_code.co_filename)
        if path.startswith(_ROOT) and "site-packages" not in path and not path.endswith(("inbox.py",)):
            rel = os.path.relpath(path, _ROOT)[:-3].replace(os.sep, ".")
            return topic_for_module(rel)
        f = f.f_back
    return "other"


async def _thread(bot, chat_id: int, topic: str) -> int | None:
    if topic in _threads:
        return _threads[topic]
    raw = await _meta(f"inbox_topic:{topic}")
    if raw and raw.isdigit():
        _threads[topic] = int(raw)
        return _threads[topic]
    try:
        created = await bot.create_forum_topic(chat_id, name=TOPICS.get(topic, TOPICS["other"]))
    except Exception as e:  # noqa: BLE001 — без темы уйдёт в «General»
        log.warning("Инбокс: тема %s не создана: %s", topic, e)
        return None
    _threads[topic] = created.message_thread_id
    await _meta_set(f"inbox_topic:{topic}", str(created.message_thread_id))
    return _threads[topic]


def _fingerprint(method) -> str:
    parts = [type(method).__name__]
    for name in ("text", "caption", "photo", "video", "document", "from_chat_id", "message_id"):
        v = getattr(method, name, None)
        if v is not None:
            parts.append(f"{name}={getattr(v, 'filename', None) or v}")
    rm = getattr(method, "reply_markup", None)
    if rm is not None:
        parts.append(rm.model_dump_json() if hasattr(rm, "model_dump_json") else str(rm))
    return hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()


class InboxRedirect(BaseRequestMiddleware):
    async def __call__(self, make_request, bot, method):
        if isinstance(method, _SEND):
            chat_id = getattr(method, "chat_id", None)
            if isinstance(chat_id, int) and chat_id in config.ADMIN_IDS and chat_id != _actor.get():
                target = await inbox_chat()
                topic = _caller_topic() if target else None
                if target and topic:
                    key = _fingerprint(method)
                    now = time.monotonic()
                    for k in [k for k, (t, _) in _recent.items() if now - t > 30]:
                        _recent.pop(k, None)
                    if key in _recent:  # то же уведомление другому админу — в группе уже есть
                        return _recent[key][1]
                    method.chat_id = target
                    thread = await _thread(bot, target, topic)
                    if thread:
                        method.message_thread_id = thread
                    resp = await make_request(bot, method)
                    _recent[key] = (now, resp)
                    return resp
        return await make_request(bot, method)


class ActorMiddleware(BaseMiddleware):
    """Запоминает, кто сейчас действует: ответы ему самому не уводим в группу."""

    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        token = _actor.set(user.id if user else None)
        try:
            return await handler(event, data)
        finally:
            _actor.reset(token)


def install(bot, dp) -> None:
    bot.session.middleware(InboxRedirect())
    dp.update.outer_middleware(ActorMiddleware())


@router.message(Command("inbox"), F.from_user.id.in_(config.ADMIN_IDS))
async def cmd_inbox(message: Message) -> None:
    global _chat, _chat_loaded
    arg = (message.text or "").split(maxsplit=1)[1:] or [""]
    if arg[0].strip().lower() == "off":
        await _meta_set("inbox_chat", None)
        _chat, _chat_loaded = None, True
        await message.answer("Инбокс отключён: уведомления снова приходят в личку.", parse_mode=None)
        return
    if message.chat.type != ChatType.SUPERGROUP or not getattr(message.chat, "is_forum", False):
        await message.answer(
            "Напишите /inbox в закрытой группе с включёнными темами. Боту нужны права администратора "
            "с управлением темами.", parse_mode=None)
        return
    try:
        topic = await message.bot.create_forum_topic(message.chat.id, name=TOPICS["other"])
    except Exception as e:  # noqa: BLE001
        await message.answer(f"Не получилось создать тему ({type(e).__name__}). Дайте боту право "
                             "управлять темами и повторите /inbox.", parse_mode=None)
        return
    for key in TOPICS:
        await _meta_set(f"inbox_topic:{key}", None)
    _threads.clear()
    _threads["other"] = topic.message_thread_id
    await _meta_set("inbox_topic:other", str(topic.message_thread_id))
    await _meta_set("inbox_chat", str(message.chat.id))
    await _meta_set("mod_chat", None)  # заявки предложки тоже пойдут в инбокс, в свою тему
    _chat, _chat_loaded = message.chat.id, True
    await message.answer(
        "Готово. Уведомления бота теперь приходят сюда, каждое в свою тему: "
        + ", ".join(TOPICS.values()) + ". Темы создаются при первом уведомлении. "
        "Ответы на ваши команды остаются в личке. Отключить: /inbox off", parse_mode=None)
