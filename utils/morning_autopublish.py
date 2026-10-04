"""Fresh, durable morning drafts; publication at 06:00 Europe/Amsterdam.

Use the existing verified research pipeline and configured channel. Preparing
at 05:50 allows time for research. Restart recovery accepts only today's drafts
at most 30 minutes old. An ambiguous Telegram send is held for manual review,
never blindly retried (Bot API has no idempotency key).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, time, timedelta

import config
from utils import editorial_channel as editorial
from utils import editorial_overrides as overrides

PREPARE_AT = time(5, 50)
PUBLISH_AT = time(6, 0)
END_AT = time(7, 0)
MAX_AGE = timedelta(minutes=30)
_lock = asyncio.Lock()


async def _alert(bot, today: str, reason: str) -> None:
    key = f"morning_auto_alert_{today}"
    if await editorial._meta_get(key) == reason[:95]:
        return
    editorial.log.error("Morning autopublish: %s", reason)
    for admin_id in config.ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                "⚠️ Утренний пост на 06:00 по Амстердаму: " + reason,
                parse_mode=None,
            )
        except Exception:
            editorial.log.warning("Morning autopublish admin alert failed")
    await editorial._meta_set(key, reason[:95])


async def _channel_ready(bot) -> bool:
    """Read-only check: require the community channel and explicit post rights."""
    if not config.ANNOUNCE_CHANNEL:
        return False
    chat = await bot.get_chat(config.ANNOUNCE_CHANNEL)
    if getattr(chat.type, "value", chat.type) != "channel" or (chat.username or "").lower() != "podslushanovnl":
        return False
    me = await bot.get_me()
    member = await bot.get_chat_member(chat.id, me.id)
    return getattr(member.status, "value", member.status) == "creator" or bool(getattr(member, "can_post_messages", False))


async def run_morning(bot, now: datetime) -> None:
    # The existing editorial clock returns naive Amsterdam local time. Explicit
    # conversion also handles aware callers regardless of server/user timezone.
    if now.tzinfo is not None:
        now = now.astimezone(editorial.AMSTERDAM).replace(tzinfo=None)
    if not PREPARE_AT <= now.time() < END_AT or _lock.locked():
        return
    async with _lock:
        await _run_locked(bot, now)


async def _run_locked(bot, now: datetime) -> None:
    from handlers.content import _is_paused
    from utils import editorial_budget_photo as budget

    today = now.date().isoformat()
    date_key = "editorial_morning_date"  # shared with the previous scheduler
    if await editorial._meta_get(date_key) == today:
        return
    if await _is_paused():
        await _alert(bot, today, "Публикации приостановлены в контент-центре; пост не отправлен.")
        return
    status_key = f"morning_auto_{today}"
    status = await editorial._meta_get(status_key)
    if status in {"sending", "uncertain", "published"}:
        if status != "published":
            await _alert(bot, today, "Статус отправки неясен. Проверьте канал: повторная отправка остановлена, чтобы не создать дубль.")
        return

    draft_id = f"morning_{today.replace('-', '')}"
    checked_key = f"{draft_id}_checked"
    draft = await editorial._load_draft(draft_id)
    checked_raw = await editorial._meta_get(checked_key)
    try:
        checked = datetime.fromisoformat(checked_raw)
    except ValueError:
        checked = None
    fresh = checked is not None and checked.date() == now.date() and timedelta(0) <= now - checked <= MAX_AGE
    if not draft or not fresh:
        attempts_key = f"morning_auto_attempts_{today}"
        try:
            attempts = int(await editorial._meta_get(attempts_key) or "0")
        except ValueError:
            attempts = 0
        if attempts >= budget.MAX_AUTOMATIC_ATTEMPTS_PER_SLOT:
            return
        if not await editorial._attempt_allowed(f"morning_auto_try_{today}", now, 5):
            return
        await editorial._meta_set(attempts_key, attempts + 1)
        try:
            if not await _channel_ready(bot):
                await _alert(bot, today, "Не подтверждены канал @podslushanovnl или право бота публиковать сообщения.")
                return
            text = await editorial._morning_brief()
            if not text or editorial.MORNING_FOOTER not in text:
                error = await editorial._meta_get("editorial_last_error")
                reason = ("Недостаточно средств на Anthropic API для подготовки текста. Пополните баланс; пост не опубликован."
                          if "credit" in error.lower() else
                          "Не удалось получить проверенную свежую подборку. Непроверенный текст не опубликован.")
                await _alert(bot, today, reason)
                return
            checked = editorial._now()
            if checked.date() != now.date():
                return
            post = overrides._with_reaction_cta("morning", text)
            await editorial._store_draft(draft_id, "morning", post, False)
            await editorial._meta_set(checked_key, checked.isoformat())
            draft = ("morning", post, False)
        except Exception as exc:
            editorial.log.exception("Morning preparation failed")
            await _alert(bot, today, f"Подготовка завершилась ошибкой {type(exc).__name__}; публикации нет.")
            return

    send_now = editorial._now()
    if send_now.date() != now.date() or not PUBLISH_AT <= send_now.time() < END_AT:
        return
    if not timedelta(0) <= send_now - checked <= MAX_AGE:
        return
    if await _is_paused():
        return
    try:
        if not await _channel_ready(bot):
            await _alert(bot, today, "Перед отправкой не подтверждено право публикации в канале.")
            return
    except Exception:
        await _alert(bot, today, "Не удалось проверить доступ к каналу перед отправкой.")
        return
    text = draft[1].replace("{checked_at}", checked.strftime("%H:%M, %d.%m.%Y"))
    rendered = editorial._format_morning_html(text)
    await editorial._meta_set(status_key, "sending")
    try:
        message = await bot.send_message(
            config.ANNOUNCE_CHANNEL, rendered, parse_mode="HTML",
            disable_web_page_preview=True,
        )
        await editorial._meta_set(f"{draft_id}_message", message.message_id)
        await editorial._meta_set(date_key, today)
        await editorial._meta_set(status_key, "published")
        await editorial._meta_set(f"ed_{draft_id}_status", "published")
        await editorial._meta_set("editorial_last_status", "morning_auto_published")
        await editorial._meta_set("editorial_last_error", "")
        editorial.log.info("Morning auto published date=%s message_id=%s checked=%s", today, message.message_id, checked.isoformat())
    except Exception:
        await editorial._meta_set(status_key, "uncertain")
        await _alert(bot, today, "Статус отправки неясен. Проверьте канал: повторная отправка остановлена, чтобы не создать дубль.")
