"""Защита от спама и контроль расходов на ИИ.

Два механизма (в памяти процесса, без БД — простого достаточно):
- антифлуд: не больше N сообщений за T секунд от одного пользователя;
- дневной лимит обращений к ИИ на пользователя (защита бюджета).
"""
import time
from collections import defaultdict, deque
from datetime import date

from aiogram import BaseMiddleware
from aiogram.types import Message

import config

# --- Антифлуд ----------------------------------------------------------------
_hits: dict[int, deque] = defaultdict(deque)
_last_warn: dict[int, float] = {}


def allow_message(user_id: int) -> bool:
    """True, если сообщение в пределах лимита частоты; False — если флуд."""
    now = time.monotonic()
    dq = _hits[user_id]
    while dq and now - dq[0] > config.FLOOD_WINDOW:
        dq.popleft()
    if len(dq) >= config.FLOOD_LIMIT:
        return False
    dq.append(now)
    return True


def _should_warn(user_id: int) -> bool:
    """Предупреждаем о флуде не чаще раза в окно, чтобы не спамить в ответ."""
    now = time.monotonic()
    if now - _last_warn.get(user_id, 0) > config.FLOOD_WINDOW:
        _last_warn[user_id] = now
        return True
    return False


# --- Дневной лимит ИИ --------------------------------------------------------
_ai_counts: dict[int, list] = {}  # user_id -> [date, count]


def allow_ai(user_id: int) -> bool:
    """True, если пользователь не превысил дневной лимит обращений к ИИ."""
    limit = config.AI_DAILY_LIMIT
    if limit <= 0:
        return True  # 0 = без лимита
    today = date.today()
    rec = _ai_counts.get(user_id)
    if rec is None or rec[0] != today:
        _ai_counts[user_id] = [today, 0]
        rec = _ai_counts[user_id]
    if rec[1] >= limit:
        return False
    rec[1] += 1
    return True


class ThrottleMiddleware(BaseMiddleware):
    """Притормаживает пользователей, которые шлют сообщения слишком часто."""

    async def __call__(self, handler, event, data):
        user = getattr(event, "from_user", None)
        if user and not allow_message(user.id):
            if isinstance(event, Message) and _should_warn(user.id):
                try:
                    await event.answer(
                        "Секунду 🙏 Слишком много сообщений подряд — чуть помедленнее."
                    )
                except Exception:  # noqa: BLE001
                    pass
            return  # сообщение не передаём дальше
        return await handler(event, data)
