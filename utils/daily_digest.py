"""Ежедневный дайджест «Новости дня»: каждый день в 19:00 (Europe/Amsterdam), до 10 заголовков.

Окно — записи, опубликованные после предыдущего ежедневного дайджеста; если такого нет или он
старше 48 ч, берутся последние 24 часа. Отметка дня — meta daily_digest:last_day (дата в
Амстердаме), дубля за день не будет. Если бот был выключен в 19:00, запуск случится позже тем же
вечером, но не на следующий день.
"""
import asyncio
import logging
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import config
from utils import digest_core as core

log = logging.getLogger(__name__)

AMSTERDAM = ZoneInfo("Europe/Amsterdam")
POST_TIME = time(19, 0)
CHECK_SECONDS = 300
DEFAULT_WINDOW = timedelta(hours=24)
MAX_LOOKBACK = timedelta(hours=48)
LAST_DAY_KEY = "daily_digest:last_day"
LAST_RUN_KEY = "daily_digest:last_run_at"


def enabled() -> bool:
    return core.enabled(config.DAILY_DIGEST_ENABLED)


def window_start(now: datetime, last_run: datetime | None) -> datetime:
    """Начало окна: время прошлого опубликованного дайджеста, но не старше 48 ч."""
    if last_run is None or last_run > now or now - last_run > MAX_LOOKBACK:
        return now - DEFAULT_WINDOW
    return last_run


async def daily_since(now: datetime) -> datetime:
    raw = await core.meta_get(LAST_RUN_KEY)
    return window_start(now, datetime.fromisoformat(raw) if raw else None)


async def mark_done(now: datetime, status: str) -> None:
    """День закрываем при любом исходе. Окно сдвигаем только если дайджест вышел или ушёл на
    проверку: пропущенный запуск не теряет новости — окно растянется на следующий день."""
    await core.meta_set(LAST_DAY_KEY, now.astimezone(AMSTERDAM).date().isoformat())
    if status in ("posted", "drafted"):
        await core.meta_set(LAST_RUN_KEY, now.astimezone(timezone.utc).isoformat())


async def scheduled_pass(bot, now: datetime | None = None) -> None:
    now = now or datetime.now(AMSTERDAM)
    local = now.astimezone(AMSTERDAM)
    if local.time() < POST_TIME:
        return
    if await core.meta_get(LAST_DAY_KEY) == local.date().isoformat():
        return
    result = await core.run(bot, core.DAILY, await daily_since(now))
    if result["status"] == "paused":
        return  # пауза контента: попробуем позже тем же вечером
    await mark_done(now, result["status"])


async def daily_digest_loop(bot) -> None:
    """Фоновая задача: проверяет расписание каждые CHECK_SECONDS секунд."""
    if not enabled():
        log.info("Ежедневный дайджест выключен (DAILY_DIGEST_ENABLED=0 или нет ANTHROPIC/WP_*)")
        return
    await asyncio.sleep(150)
    while True:
        try:
            await scheduled_pass(bot)
        except Exception as e:  # noqa: BLE001
            log.exception("Ежедневный дайджест: ошибка: %s", e)
        await asyncio.sleep(CHECK_SECONDS)

