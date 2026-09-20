"""Черновик первого письма после админской проверки за 3 дня.

На этапе 72h администратор подтверждает, что материалов пока нет. Это действие
НИКОГДА не отправляет письмо клиенту: оно только фиксирует статус и показывает
администратору готовый текст первого (48h) напоминания. Реальная отправка
остаётся отдельным действием на этапе 48h.
"""
from __future__ import annotations

import html
from datetime import date, datetime

from aiogram import F, Router
from aiogram.types import CallbackQuery

import config
import ad_material_admin_gate_runtime as gate
from database.db import get_session
from database.models import AdBooking
from utils.ad_calendar import _client_name, _date_label

router = Router()


def build_48h_preview(booking: AdBooking, publish_date: str) -> str:
    subject, _, text_body = gate._message(booking, publish_date, "48h")
    return (
        "📝 <b>Первое письмо подготовлено</b>\n\n"
        f"Клиент: {html.escape(_client_name(booking))}\n"
        f"Дата выхода: {html.escape(_date_label(publish_date))}\n"
        f"E-mail: {html.escape(booking.email or '—')}\n\n"
        f"<b>Тема письма:</b> {html.escape(subject)}\n\n"
        f"<blockquote>{html.escape(text_body)}</blockquote>\n\n"
        "🔒 <b>Клиенту ничего не отправлено.</b>\n"
        "За 48 часов бот снова спросит, пришли ли материалы. Только после твоего "
        "отдельного подтверждения «Нет — отправить письмо за 48 часов» это письмо уйдёт клиенту."
    )


@router.callback_query(F.data.startswith("adgate:wait:"))
async def confirm_72h_no_materials(callback: CallbackQuery) -> None:
    """Зафиксировать «материалов нет» и показать preview, не отправляя email."""
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("Только для администраторов", show_alert=True)
        return
    try:
        _, _, raw_id, publish_date = callback.data.split(":", 3)
        booking_id = int(raw_id)
        date.fromisoformat(publish_date)
    except (ValueError, IndexError):
        await callback.answer("Некорректная команда", show_alert=True)
        return

    async with get_session() as session:
        booking = await session.get(AdBooking, booking_id)
    if booking is None or booking.status != "paid":
        await callback.answer("Бронь не найдена", show_alert=True)
        return

    await gate._set_date_state(
        booking,
        publish_date,
        "waiting",
        note="За 3 дня администратор подтвердил: материалов пока нет; подготовлен preview первого письма.",
    )

    await callback.answer("Материалов нет — черновик первого письма подготовлен")
    if callback.message:
        try:
            await callback.message.edit_text(
                (callback.message.text or "")
                + "\n\n❌ <b>Материалов пока нет.</b> Первое письмо подготовлено, но клиенту не отправлено.",
                reply_markup=None,
            )
        except Exception:
            pass
        try:
            await callback.message.answer(build_48h_preview(booking, publish_date))
        except Exception:
            # Даже если Telegram не смог показать preview, письмо всё равно не отправляется.
            pass
