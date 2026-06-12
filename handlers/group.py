"""Поведение бота в группе обсуждений (комментарии под постами канала).

Бот добавлен в linked-группу обсуждений. Здесь он НЕ ведёт меню и НЕ отвечает
на каждое сообщение — только когда к нему прямо обратился живой подписчик:
упомянул @бота или ответил на его сообщение. Авто-пересылки постов из канала
и сообщения от имени канала полностью игнорируются.
"""
import logging

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.types import Message

from utils.ai import ai_enabled, ai_reply

log = logging.getLogger(__name__)

router = Router()
# Этот роутер работает ТОЛЬКО в группах и супергруппах
router.message.filter(F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))


@router.message()
async def group_message(message: Message) -> None:
    """Отвечаем в группе только на прямое обращение к боту."""
    # 1) Игнорируем авто-пересылки постов канала и сообщения от имени канала
    if message.is_automatic_forward or message.sender_chat is not None:
        return
    # 2) Игнорируем не-людей и других ботов (чтобы не зациклиться)
    if message.from_user is None or message.from_user.is_bot:
        return

    text = message.text or message.caption
    if not text:
        return

    me = await message.bot.me()
    username = (me.username or "").lower()
    mentioned = bool(username) and f"@{username}" in text.lower()
    replied_to_bot = (
        message.reply_to_message is not None
        and message.reply_to_message.from_user is not None
        and message.reply_to_message.from_user.id == me.id
    )

    # 3) Если к боту НЕ обращались — молчим (это главное правило в группе)
    if not (mentioned or replied_to_bot):
        return

    if not ai_enabled():
        return

    # Убираем упоминание из текста вопроса
    question = text
    if mentioned and me.username:
        question = question.replace(f"@{me.username}", "").strip()
    question = question.strip() or "Привет!"

    await message.bot.send_chat_action(message.chat.id, action="typing")
    reply = await ai_reply(question)
    if reply:
        # Отвечаем реплаем на сообщение подписчика, без меню-клавиатуры
        await message.reply(reply, parse_mode=None)
