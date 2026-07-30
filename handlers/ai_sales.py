"""AI Sales Manager: ответы, статусы и контроль рекламных заявок."""
from __future__ import annotations

import asyncio
import html
import logging
from datetime import datetime, timedelta

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select

import config
from database.db import get_session
from database.models import Meta, Submission
from utils.ai_sales import ADS_URL, load_analysis
from utils.notify import get_mod_chat

log = logging.getLogger(__name__)
router = Router()

FOLLOW_UP_TEXT = (
    "Добрый день! 👋 Напоминаем о вашей заявке на рекламу. "
    "Выбрать формат, удобную дату и оформить размещение можно здесь:\n\n"
    f"{ADS_URL}\n\n"
    "Если нужна помощь с выбором формата — напишите, с удовольствием подскажем."
)

STATUS_LABELS = {
    "pending": "🆕 Новая",
    "contacted": "📤 Ответ отправлен",
    "awaiting_payment": "⏳ Ожидает оплату",
    "paid": "✅ Оплачено",
    "rejected": "❌ Отказ",
    "closed": "⚫ Закрыто",
}


def _meta_key(submission_id: int, suffix: str) -> str:
    return f"ad:{submission_id}:{suffix}"


async def _get_submission(submission_id: int) -> Submission | None:
    async with get_session() as session:
        return await session.get(Submission, submission_id)


async def _set_meta(submission_id: int, suffix: str, value: str) -> None:
    async with get_session() as session:
        await session.merge(Meta(key=_meta_key(submission_id, suffix), value=value[:100]))
        await session.commit()


async def _get_meta(submission_id: int, suffix: str) -> str | None:
    async with get_session() as session:
        row = await session.get(Meta, _meta_key(submission_id, suffix))
    return row.value if row else None


async def _set_status(submission_id: int, status: str) -> Submission | None:
    async with get_session() as session:
        submission = await session.get(Submission, submission_id)
        if submission is None or submission.type != "ad":
            return None
        submission.status = status
        await session.commit()
        await session.refresh(submission)
    await _set_meta(submission_id, "status_at", datetime.utcnow().isoformat())
    return submission


def _is_admin(callback: CallbackQuery) -> bool:
    return callback.from_user.id in config.ADMIN_IDS


def _status_keyboard(submission_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏳ Ожидает оплату", callback_data=f"aistatus:awaiting_payment:{submission_id}")],
        [
            InlineKeyboardButton(text="✅ Оплачено", callback_data=f"aistatus:paid:{submission_id}"),
            InlineKeyboardButton(text="❌ Отказ", callback_data=f"aistatus:rejected:{submission_id}"),
        ],
        [InlineKeyboardButton(text="🔔 Напомнить клиенту", callback_data=f"aifollow:{submission_id}")],
    ])


async def _append_marker(callback: CallbackQuery, marker: str) -> None:
    if not callback.message:
        return
    try:
        if callback.message.text:
            await callback.message.edit_text(
                callback.message.text + marker,
                reply_markup=callback.message.reply_markup,
            )
        elif callback.message.caption:
            await callback.message.edit_caption(
                caption=callback.message.caption + marker,
                reply_markup=callback.message.reply_markup,
            )
    except Exception:  # сообщение могло уже измениться
        pass


@router.callback_query(F.data.startswith("aisend:"))
async def send_ai_reply(callback: CallbackQuery) -> None:
    """Отправляет клиенту подготовленный ИИ ответ одной кнопкой."""
    if not _is_admin(callback):
        await callback.answer("Только для администраторов", show_alert=True)
        return
    try:
        submission_id = int(callback.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("Некорректная заявка", show_alert=True)
        return

    submission = await _get_submission(submission_id)
    analysis = await load_analysis(submission_id)
    if submission is None or analysis is None:
        await callback.answer("Заявка или AI-анализ не найден", show_alert=True)
        return

    reply = str(analysis.get("reply", "")).strip()
    if not reply:
        await callback.answer("AI не подготовил ответ", show_alert=True)
        return

    try:
        await callback.bot.send_message(
            submission.user_id,
            html.escape(reply),
            disable_web_page_preview=True,
        )
        await _set_status(submission_id, "contacted")
        await _set_meta(submission_id, "contacted_at", datetime.utcnow().isoformat())
        await callback.answer("✅ Ответ отправлен")
        await _append_marker(callback, "\n\n— 📤 Ответ отправлен · ожидаем реакцию клиента")
    except Exception as exc:  # noqa: BLE001
        log.warning("Не удалось отправить AI-ответ по заявке %s: %s", submission_id, exc)
        await callback.answer("Не удалось отправить ответ", show_alert=True)


@router.callback_query(F.data.startswith("aistatus:"))
async def change_lead_status(callback: CallbackQuery) -> None:
    """Меняет этап рекламной заявки прямо из рабочего канала."""
    if not _is_admin(callback):
        await callback.answer("Только для администраторов", show_alert=True)
        return
    try:
        _, status, raw_id = callback.data.split(":", 2)
        submission_id = int(raw_id)
    except (ValueError, IndexError):
        await callback.answer("Некорректная команда", show_alert=True)
        return
    if status not in STATUS_LABELS:
        await callback.answer("Неизвестный статус", show_alert=True)
        return
    submission = await _set_status(submission_id, status)
    if submission is None:
        await callback.answer("Заявка не найдена", show_alert=True)
        return
    label = STATUS_LABELS[status]
    await callback.answer(label)
    await _append_marker(callback, f"\n\n— {label}")


@router.callback_query(F.data.startswith("aifollow:"))
async def send_follow_up(callback: CallbackQuery) -> None:
    """Отправляет клиенту аккуратное напоминание об оформлении рекламы."""
    if not _is_admin(callback):
        await callback.answer("Только для администраторов", show_alert=True)
        return
    try:
        submission_id = int(callback.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("Некорректная заявка", show_alert=True)
        return
    submission = await _get_submission(submission_id)
    if submission is None:
        await callback.answer("Заявка не найдена", show_alert=True)
        return
    try:
        await callback.bot.send_message(
            submission.user_id,
            html.escape(FOLLOW_UP_TEXT),
            disable_web_page_preview=True,
        )
        await _set_status(submission_id, "awaiting_payment")
        await _set_meta(submission_id, "followed_at", datetime.utcnow().isoformat())
        await callback.answer("🔔 Напоминание отправлено")
        await _append_marker(callback, "\n\n— 🔔 Клиенту отправлено напоминание")
    except Exception as exc:  # noqa: BLE001
        log.warning("Не удалось напомнить клиенту по заявке %s: %s", submission_id, exc)
        await callback.answer("Не удалось отправить напоминание", show_alert=True)


@router.callback_query(F.data.startswith("aiopen:"))
async def open_ads_page(callback: CallbackQuery) -> None:
    await callback.answer(ADS_URL, show_alert=True)


async def _notify_admins(bot: Bot, submission: Submission, hours: int) -> None:
    target = await get_mod_chat()
    targets = [target] if target else list(config.ADMIN_IDS)
    author = f"@{submission.username}" if submission.username else f"id {submission.user_id}"
    text = (
        f"🔔 <b>Контроль рекламной заявки №{submission.id}</b>\n\n"
        f"Клиент: {author}\n"
        f"Прошло {hours} часов после отправки ответа, оплата не отмечена.\n\n"
        "Можно напомнить клиенту или изменить статус заявки."
    )
    for chat_id in targets:
        try:
            await bot.send_message(chat_id, text, reply_markup=_status_keyboard(submission.id))
        except Exception as exc:  # noqa: BLE001
            log.warning("Не удалось отправить контроль заявки %s: %s", submission.id, exc)


async def ad_lead_reminder_loop(bot: Bot) -> None:
    """Раз в час напоминает администраторам о лидах без оплаты через 24 и 48 часов."""
    await asyncio.sleep(30)
    while True:
        try:
            async with get_session() as session:
                result = await session.execute(
                    select(Submission).where(
                        Submission.type == "ad",
                        Submission.status.in_(["contacted", "awaiting_payment"]),
                    )
                )
                submissions = list(result.scalars())

            now = datetime.utcnow()
            for submission in submissions:
                raw = await _get_meta(submission.id, "contacted_at")
                if not raw:
                    continue
                try:
                    contacted_at = datetime.fromisoformat(raw)
                except ValueError:
                    continue
                age = now - contacted_at
                for hours in (24, 48):
                    if age < timedelta(hours=hours):
                        continue
                    marker = f"reminder_{hours}h"
                    if await _get_meta(submission.id, marker):
                        continue
                    await _notify_admins(bot, submission, hours)
                    await _set_meta(submission.id, marker, now.isoformat())
        except Exception as exc:  # noqa: BLE001
            log.exception("Ошибка контроля рекламных заявок: %s", exc)
        await asyncio.sleep(3600)
