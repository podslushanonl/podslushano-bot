"""Продолжение рекламных диалогов, история, производство и сверка оплат."""
from __future__ import annotations

import asyncio
import html
import logging

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

import config
from database.ad_sales_models import AdSalesPipeline
from database.db import get_session
from database.models import Submission
from utils.ad_sales_pipeline import (
    PRODUCTION_LABELS,
    active_ad_submission,
    conversation_history,
    ensure_pipeline,
    generate_sales_reply,
    latest_ai_suggestion,
    notify_new_client_message,
    production_keyboard,
    reconcile_paid_bookings,
    record_message,
)

log = logging.getLogger(__name__)
router = Router()


def _is_admin(callback: CallbackQuery) -> bool:
    return callback.from_user.id in config.ADMIN_IDS


@router.message(F.chat.type == ChatType.PRIVATE, F.text)
async def capture_ad_client_reply(message: Message) -> None:
    """Перехватывает ответ клиента, пока у него открыт рекламный лид."""
    if message.from_user is None or message.from_user.id in config.ADMIN_IDS:
        return
    submission = await active_ad_submission(message.from_user.id)
    if submission is None:
        return
    text = (message.text or "").strip()
    if not text:
        return
    await ensure_pipeline(submission)
    await record_message(
        submission.id,
        submission.user_id,
        "client",
        text,
        kind="inbound",
        telegram_message_id=message.message_id,
    )
    suggestion = await generate_sales_reply(submission, text)
    await notify_new_client_message(message.bot, submission, text, suggestion)
    await message.answer(
        "Спасибо, сообщение передано менеджеру 🙌 Мы вернёмся с ответом в этом чате."
    )


@router.callback_query(F.data.startswith("aicontsend:"))
async def send_continuation(callback: CallbackQuery) -> None:
    """Отправляет последнее AI-предложение клиенту только после подтверждения админа."""
    if not _is_admin(callback):
        await callback.answer("Только для администраторов", show_alert=True)
        return
    try:
        submission_id = int(callback.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("Некорректная заявка", show_alert=True)
        return
    async with get_session() as session:
        submission = await session.get(Submission, submission_id)
    suggestion = await latest_ai_suggestion(submission_id)
    if submission is None or suggestion is None:
        await callback.answer("Ответ не найден", show_alert=True)
        return
    try:
        sent = await callback.bot.send_message(
            submission.user_id,
            html.escape(suggestion.text),
            disable_web_page_preview=True,
        )
        await record_message(
            submission.id,
            submission.user_id,
            "manager",
            suggestion.text,
            kind="outbound",
            telegram_message_id=sent.message_id,
        )
        await callback.answer("✅ Ответ отправлен")
        if callback.message:
            await callback.message.edit_reply_markup(reply_markup=None)
    except Exception as exc:  # noqa: BLE001
        log.warning("Не удалось отправить продолжение рекламного диалога: %s", exc)
        await callback.answer("Не удалось отправить", show_alert=True)


@router.callback_query(F.data.startswith("aihistory:"))
async def show_history(callback: CallbackQuery) -> None:
    if not _is_admin(callback):
        await callback.answer("Только для администраторов", show_alert=True)
        return
    try:
        submission_id = int(callback.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer()
        return
    rows = await conversation_history(submission_id, 30)
    if not rows:
        await callback.answer("История пока пустая", show_alert=True)
        return
    labels = {"client": "👤 Клиент", "manager": "🧑‍💼 Менеджер", "ai": "🤖 AI", "system": "⚙️ Система"}
    chunks = [f"<b>История рекламной заявки №{submission_id}</b>"]
    for row in rows:
        chunks.append(f"\n{labels.get(row.role, row.role)}:\n{html.escape(row.text[:900])}")
    text = "\n".join(chunks)
    await callback.message.answer(text[:4000])
    await callback.answer()


@router.callback_query(F.data.startswith("aiprod:"))
async def change_production_stage(callback: CallbackQuery) -> None:
    if not _is_admin(callback):
        await callback.answer("Только для администраторов", show_alert=True)
        return
    try:
        _, stage, raw_id = callback.data.split(":", 2)
        submission_id = int(raw_id)
    except (ValueError, IndexError):
        await callback.answer("Некорректная команда", show_alert=True)
        return
    if stage not in PRODUCTION_LABELS:
        await callback.answer("Неизвестный этап", show_alert=True)
        return
    async with get_session() as session:
        pipeline = await session.scalar(
            select(AdSalesPipeline).where(AdSalesPipeline.submission_id == submission_id)
        )
        submission = await session.get(Submission, submission_id)
        if pipeline is None or submission is None:
            await callback.answer("Заявка не найдена", show_alert=True)
            return
        pipeline.production_status = stage
        if stage == "completed":
            pipeline.sales_status = "closed"
            submission.status = "closed"
        await session.commit()
    label = PRODUCTION_LABELS[stage]
    await record_message(submission_id, submission.user_id, "system", label, kind="production")
    await callback.answer(label)
    if callback.message:
        try:
            base = callback.message.text or callback.message.caption or ""
            marker = f"\n\n— {label}"
            if callback.message.text:
                await callback.message.edit_text(base + marker, reply_markup=production_keyboard(submission_id))
            elif callback.message.caption:
                await callback.message.edit_caption(caption=base + marker, reply_markup=production_keyboard(submission_id))
        except Exception:
            pass


async def ad_payment_reconciliation_loop(bot: Bot) -> None:
    """Раз в 10 минут ищет новые оплаченные рекламные брони."""
    await asyncio.sleep(45)
    while True:
        try:
            await reconcile_paid_bookings(bot)
        except Exception as exc:  # noqa: BLE001
            log.exception("Ошибка автоматической сверки рекламных оплат: %s", exc)
        await asyncio.sleep(600)
