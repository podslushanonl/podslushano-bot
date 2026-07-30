"""Кнопки AI Sales Manager под рекламными заявками."""
from __future__ import annotations

import html
import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery

import config
from database.db import get_session
from database.models import Submission
from utils.ai_sales import ADS_URL, load_analysis

log = logging.getLogger(__name__)
router = Router()


async def _get_submission(submission_id: int) -> Submission | None:
    async with get_session() as session:
        return await session.get(Submission, submission_id)


def _is_admin(callback: CallbackQuery) -> bool:
    return callback.from_user.id in config.ADMIN_IDS


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
        submission.status = "contacted"
        async with get_session() as session:
            await session.merge(submission)
            await session.commit()
        await callback.answer("✅ Ответ отправлен")
        if callback.message:
            marker = "\n\n— ✅ AI-ответ отправлен клиенту"
            if callback.message.text:
                await callback.message.edit_text(
                    callback.message.text + marker,
                    reply_markup=callback.message.reply_markup,
                )
            elif callback.message.caption:
                await callback.message.edit_caption(
                    callback.message.caption + marker,
                    reply_markup=callback.message.reply_markup,
                )
    except Exception as exc:  # noqa: BLE001
        log.warning("Не удалось отправить AI-ответ по заявке %s: %s", submission_id, exc)
        await callback.answer("Не удалось отправить ответ", show_alert=True)


@router.callback_query(F.data.startswith("aiopen:"))
async def open_ads_page(callback: CallbackQuery) -> None:
    """Служебная callback-заглушка для старых клиентов Telegram."""
    await callback.answer(ADS_URL, show_alert=True)
