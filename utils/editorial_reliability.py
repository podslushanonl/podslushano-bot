"""Reliability layer for scheduled editorial previews with a hard cost cap."""
from __future__ import annotations

from datetime import time

import config
from utils import editorial_channel as editorial

_RETRY_MINUTES = 15
_ALERT_COOLDOWN_MINUTES = 30
_MAX_ATTEMPTS_PER_SLOT = 2


async def _alert_admins(bot, kind: str, reason: str) -> None:
    now = editorial._now()
    alert_key = f"editorial_{kind}_failure_alert"
    if not await editorial._attempt_allowed(alert_key, now, _ALERT_COOLDOWN_MINUTES):
        return
    labels = {
        "morning": "утренний бриф",
        "event": "пост о мероприятии",
        "curiosity": "познавательный пост",
        "evening": "вечерний пост 21:00",
    }
    text = (
        f"⚠️ Не удалось подготовить {labels.get(kind, kind)}.\n\n"
        f"Этап: {reason}.\n"
        f"Автоматических платных попыток максимум {_MAX_ATTEMPTS_PER_SLOT} на слот.\n\n"
        "Бот не будет бесконечно расходовать API-баланс. /editorialhealth проверяет состояние без платного Anthropic-запроса."
    )
    for admin_id in config.ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, parse_mode=None)
        except Exception as exc:  # noqa: BLE001
            editorial.log.warning("Cannot send editorial failure alert: %s", exc)


async def _attempt_budget_available(date_key: str, now) -> bool:
    today = now.date().isoformat()
    date_meta = f"{date_key}_attempt_date"
    count_meta = f"{date_key}_attempt_count"
    if await editorial._meta_get(date_meta) != today:
        await editorial._meta_set(date_meta, today)
        await editorial._meta_set(count_meta, "0")
    try:
        count = int(await editorial._meta_get(count_meta) or "0")
    except ValueError:
        count = 0
    if count >= _MAX_ATTEMPTS_PER_SLOT:
        return False
    await editorial._meta_set(count_meta, str(count + 1))
    return True


async def _reliable_run_generated(bot, now, kind, date_key, generator, button=False):
    today = now.date().isoformat()
    if await editorial._meta_get(date_key) == today:
        return
    if not await editorial._attempt_allowed(f"{date_key}_try", now, _RETRY_MINUTES):
        return
    if not await _attempt_budget_available(date_key, now):
        return

    try:
        text = await generator()
    except Exception as exc:  # noqa: BLE001
        editorial.log.exception("Scheduled %s generator crashed: %s", kind, exc)
        await _alert_admins(bot, kind, f"генерация текста завершилась ошибкой {type(exc).__name__}")
        return

    if not text:
        editorial.log.warning("Scheduled %s generator returned no verified text", kind)
        await _alert_admins(bot, kind, "не удалось получить проверенный текст через Web Search")
        return

    try:
        delivered = await editorial._send_for_approval(bot, kind, text, button)
    except Exception as exc:  # noqa: BLE001
        editorial.log.exception("Scheduled %s preview delivery crashed: %s", kind, exc)
        await _alert_admins(bot, kind, f"отправка предпросмотра завершилась ошибкой {type(exc).__name__}")
        return

    if not delivered:
        await _alert_admins(bot, kind, "предпросмотр не был доставлен ни одному администратору")
        return

    await editorial._meta_set(date_key, today)
    await editorial._meta_set(f"{date_key}_last_success", now.isoformat(timespec="minutes"))


async def _reliable_run_evening(bot, now):
    if time(21, 0) <= now.time() < time(23, 30):
        await _reliable_run_generated(bot, now, "evening", "editorial_evening_date", editorial._evening_post)


async def _reliable_run_morning(bot, now):
    if time(6, 45) <= now.time() < time(9, 0):
        await _reliable_run_generated(bot, now, "morning", "editorial_morning_date", editorial._morning_brief)


def install_editorial_reliability() -> None:
    editorial._run_generated = _reliable_run_generated
    editorial._run_evening = _reliable_run_evening
    editorial._run_morning = _reliable_run_morning
