"""Реестр Telegram-каналов, которыми администратор управляет из бота."""
from __future__ import annotations

import re

from aiogram import Bot
from aiogram.enums import ChatType
from sqlalchemy import select

from database.db import get_session
from database.models import AdminChannel


_TME_RE = re.compile(
    r"^(?:https?://)?(?:www\.)?t\.me/(?P<username>[A-Za-z0-9_]{5,})(?:/.*)?$",
    re.IGNORECASE,
)


def normalize_channel_reference(raw: str) -> int | str:
    """Приводит -100..., @username и t.me/username к формату Bot API."""
    value = (raw or "").strip()
    if not value:
        raise ValueError("Пустой канал")

    if re.fullmatch(r"-?\d+", value):
        return int(value)

    match = _TME_RE.fullmatch(value)
    if match:
        return "@" + match.group("username")

    if value.startswith("@") and re.fullmatch(r"@[A-Za-z0-9_]{5,}", value):
        return value

    if re.fullmatch(r"[A-Za-z0-9_]{5,}", value):
        return "@" + value

    raise ValueError("Пришли @username канала, ссылку t.me/username или его id -100…")


async def list_admin_channels() -> list[AdminChannel]:
    async with get_session() as session:
        rows = (
            await session.scalars(
                select(AdminChannel).order_by(AdminChannel.created_at.asc(), AdminChannel.title.asc())
            )
        ).all()
        return list(rows)


async def save_admin_channel(
    chat_id: int,
    title: str,
    username: str | None,
    added_by: int | None,
) -> AdminChannel:
    async with get_session() as session:
        row = await session.get(AdminChannel, chat_id)
        if row is None:
            row = AdminChannel(
                chat_id=chat_id,
                title=title,
                username=username,
                added_by=added_by,
            )
            session.add(row)
        else:
            row.title = title
            row.username = username
            if added_by is not None:
                row.added_by = added_by
        await session.commit()
        await session.refresh(row)
        return row


async def delete_admin_channel(chat_id: int) -> bool:
    async with get_session() as session:
        row = await session.get(AdminChannel, chat_id)
        if row is None:
            return False
        await session.delete(row)
        await session.commit()
        return True


async def get_publishable_channel(bot: Bot, reference: int | str):
    """Возвращает канал, только если бот может публиковать в него."""
    chat = await bot.get_chat(reference)
    if chat.type != ChatType.CHANNEL:
        raise ValueError("Это не Telegram-канал.")

    me = await bot.get_me()
    member = await bot.get_chat_member(chat.id, me.id)
    status = getattr(member.status, "value", str(member.status))
    if status not in {"administrator", "creator"}:
        raise PermissionError("Бот не является администратором этого канала.")

    can_post = getattr(member, "can_post_messages", None)
    if status != "creator" and can_post is False:
        raise PermissionError("У бота нет права «Публиковать сообщения» в этом канале.")

    return chat
