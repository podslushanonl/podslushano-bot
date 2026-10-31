"""Админ-команды и кнопки дайджестов.

/digest_now — недельный дайджест сейчас; /daily_now — «Новости дня» сейчас (оба уважают
тестовый режим); /digest_reset_test — сброс счётчиков тестовых запусков. Кнопки
«✅ Опубликовать» / «❌ Пропустить» стоят под черновиками тестового режима.
"""
from datetime import datetime

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

import config
from utils import daily_digest as daily
from utils import digest_core as core
from utils import weekly_digest as weekly

router = Router()
ADMIN = F.from_user.id.in_(config.ADMIN_IDS)

_STATUS_TEXT = {
    "posted": "Опубликовано в канал.",
    "drafted": "Черновик отправлен админам — выберите действие кнопкой.",
    "skipped": "Пропущено: мало подходящих новостей.",
    "paused": "Публикация на паузе — дайджест не собран.",
    "error": "Ошибка, подробности отправлены админам.",
}


@router.message(Command("digest_now"), F.chat.type == ChatType.PRIVATE, ADMIN)
async def digest_now(message: Message) -> None:
    if not weekly.enabled():
        await message.answer("Недельный дайджест выключен: нужны WEEKLY_DIGEST_ENABLED, ANTHROPIC_API_KEY и WP_*.")
        return
    now = datetime.now(weekly.AMSTERDAM)
    await message.answer("Собираю недельный дайджест…")
    result = await core.run(message.bot, core.WEEKLY, now - weekly.WINDOW)
    if result["status"] in ("posted", "drafted"):
        await weekly.mark_done(now)  # ручной запуск закрывает неделю — без дубля в понедельник
    await message.answer(_STATUS_TEXT.get(result["status"], result["status"]))


@router.message(Command("daily_now"), F.chat.type == ChatType.PRIVATE, ADMIN)
async def daily_now(message: Message) -> None:
    if not daily.enabled():
        await message.answer("Ежедневный дайджест выключен: нужны DAILY_DIGEST_ENABLED, ANTHROPIC_API_KEY и WP_*.")
        return
    now = datetime.now(daily.AMSTERDAM)
    await message.answer("Собираю «Новости дня»…")
    result = await core.run(message.bot, core.DAILY, await daily.daily_since(now))
    await daily.mark_done(now, result["status"])
    await message.answer(_STATUS_TEXT.get(result["status"], result["status"]))


@router.message(Command("digest_reset_test"), F.chat.type == ChatType.PRIVATE, ADMIN)
async def digest_reset_test(message: Message) -> None:
    await core.reset_tests()
    await message.answer("Счётчики сброшены: снова по 2 тестовых запуска на рубрику.")


@router.callback_query(F.data.startswith("dg:"), ADMIN)
async def digest_action(callback: CallbackQuery) -> None:
    parts = (callback.data or "").split(":", 2)
    if len(parts) != 3:
        await callback.answer()
        return
    _, action, draft_id = parts
    if action == "pub":
        text = await core.approve(callback.bot, draft_id)
    elif action == "skip":
        text = await core.skip(draft_id)
    else:
        text = "Неизвестное действие."
    await callback.answer(text)
    if callback.message:
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:  # noqa: BLE001 — кнопки могли уже исчезнуть
            pass

