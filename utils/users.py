"""Учёт пользователей бота (для рассылок) через мидлварь.

Запоминаем каждого, кто пишет боту или жмёт кнопки. В памяти держим кэш уже
сохранённых id, чтобы не дёргать базу на каждое сообщение.
"""
import logging

from aiogram import BaseMiddleware

from database.db import get_session
from database.models import BotUser

log = logging.getLogger(__name__)

_known: set[int] = set()


async def remember_user(user) -> None:
    if user is None or getattr(user, "is_bot", False):
        return
    if user.id in _known:
        return
    _known.add(user.id)
    try:
        async with get_session() as session:
            existing = await session.get(BotUser, user.id)
            if existing is None:
                session.add(
                    BotUser(user_id=user.id, username=user.username, first_name=user.first_name)
                )
            else:
                existing.username = user.username
                existing.first_name = user.first_name
                existing.is_blocked = False  # снова активен — раз пишет
            await session.commit()
    except Exception as e:  # noqa: BLE001 — учёт не должен мешать работе
        log.warning("Не удалось сохранить пользователя %s: %s", getattr(user, "id", "?"), e)


class RegisterUserMiddleware(BaseMiddleware):
    """Сохраняет любого пользователя, который взаимодействует с ботом."""

    async def __call__(self, handler, event, data):
        await remember_user(getattr(event, "from_user", None))
        return await handler(event, data)
