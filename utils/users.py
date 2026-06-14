"""Учёт пользователей бота (для рассылок и статистики) через мидлварь.

Запоминаем каждого, кто пишет боту или жмёт кнопки, и обновляем время последней
активности (last_seen). В памяти держим время последней записи по каждому id,
чтобы не дёргать базу на каждое сообщение (обновляем не чаще раза в 5 минут).
"""
import logging
from datetime import datetime, timedelta

from aiogram import BaseMiddleware

from database.db import get_session
from database.models import BotUser

log = logging.getLogger(__name__)

# id -> когда мы в последний раз записали активность в БД (для троттлинга)
_last_write: dict[int, datetime] = {}
# Не чаще, чем раз в 5 минут на пользователя — достаточно для «когда заходил»
_MIN_INTERVAL = timedelta(minutes=5)


async def remember_user(user) -> None:
    if user is None or getattr(user, "is_bot", False):
        return
    now = datetime.utcnow()
    prev = _last_write.get(user.id)
    if prev is not None and now - prev < _MIN_INTERVAL:
        return  # недавно уже записали — не трогаем БД лишний раз
    _last_write[user.id] = now
    try:
        async with get_session() as session:
            existing = await session.get(BotUser, user.id)
            if existing is None:
                session.add(
                    BotUser(
                        user_id=user.id,
                        username=user.username,
                        first_name=user.first_name,
                        last_seen=now,
                    )
                )
            else:
                existing.username = user.username
                existing.first_name = user.first_name
                existing.is_blocked = False  # снова активен — раз пишет
                existing.last_seen = now
            await session.commit()
    except Exception as e:  # noqa: BLE001 — учёт не должен мешать работе
        log.warning("Не удалось сохранить пользователя %s: %s", getattr(user, "id", "?"), e)


class RegisterUserMiddleware(BaseMiddleware):
    """Сохраняет любого пользователя, который взаимодействует с ботом."""

    async def __call__(self, handler, event, data):
        await remember_user(getattr(event, "from_user", None))
        return await handler(event, data)
