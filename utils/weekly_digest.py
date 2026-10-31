"""Недельный дайджест: понедельник 09:00 (Europe/Amsterdam), последние 7 дней, до 20 заголовков.

Отметка «неделя обработана» — meta weekly_digest:last_week (ISO-неделя): после перезапуска
пост не повторяется. Если бот был выключен в 09:00, запуск случится позже в тот же понедельник,
но не в другие дни. Отбор и тестовый режим — в utils.digest_core.
"""
import asyncio
import logging
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import config
from utils import digest_core as core

log = logging.getLogger(__name__)

AMSTERDAM = ZoneInfo("Europe/Amsterdam")
WEEKDAY = 0  # понедельник
POST_TIME = time(9, 0)
CHECK_SECONDS = 300
WINDOW = timedelta(days=7)
LAST_WEEK_KEY = "weekly_digest:last_week"


def enabled() -> bool:
    return core.enabled(config.WEEKLY_DIGEST_ENABLED)


def iso_week(now: datetime) -> str:
    year, week, _ = now.astimezone(AMSTERDAM).isocalendar()
    return f"{year}-W{week:02d}"


def is_due_time(now: datetime) -> bool:
    local = now.astimezone(AMSTERDAM)
    return local.weekday() == WEEKDAY and local.time() >= POST_TIME


async def mark_done(now: datetime) -> None:
    await core.meta_set(LAST_WEEK_KEY, iso_week(now))


async def scheduled_pass(bot, now: datetime | None = None) -> None:
    now = now or datetime.now(AMSTERDAM)
    if not is_due_time(now):
        return
    if await core.meta_get(LAST_WEEK_KEY) == iso_week(now):
        return
    result = await core.run(bot, core.WEEKLY, now - WINDOW)
    if result["status"] == "paused":
        return  # пауза контента: попробуем позже в тот же понедельник
    await mark_done(now)


async def weekly_digest_loop(bot) -> None:
    """Фоновая задача: проверяет расписание каждые CHECK_SECONDS секунд."""
    if not enabled():
        log.info("Недельный дайджест выключен (WEEKLY_DIGEST_ENABLED=0 или нет ANTHROPIC/WP_*)")
        return
    await asyncio.sleep(120)
    while True:
        try:
            await scheduled_pass(bot)
        except Exception as e:  # noqa: BLE001
            log.exception("Недельный дайджест: ошибка: %s", e)
        await asyncio.sleep(CHECK_SECONDS)

