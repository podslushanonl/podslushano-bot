"""Напоминания рекламодателям о материалах перед датой размещения."""
from __future__ import annotations

import asyncio
import html
import logging
from datetime import date, datetime
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select

import config
from database.db import get_session
from database.models import AdBooking, AdReminderLog
from utils.ad_calendar import _booking_dates, _client_name, _date_label
from utils.invoices import send_email_message

log = logging.getLogger(__name__)
_INTERVAL_SECONDS = 30 * 60


def _local_now(now: datetime | None = None) -> datetime:
    timezone = ZoneInfo(config.GOOGLE_CALENDAR_TIMEZONE)
    if now is None:
        return datetime.now(timezone)
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone)
    return now.astimezone(timezone)


def _local_today(now: datetime | None = None) -> date:
    return _local_now(now).date()


def _reminders_open(now: datetime | None = None) -> bool:
    """Не разрешает письмам уходить ночью после смены календарной даты."""
    return _local_now(now).hour >= config.AD_REMINDER_HOUR


def _due_kind(today: date, publish_date: str) -> str | None:
    days = (date.fromisoformat(publish_date) - today).days
    return {2: "48h", 1: "24h", 0: "day_of"}.get(days)


def _message(booking: AdBooking, publish_date: str, kind: str) -> tuple[str, str, str]:
    client = html.escape(_client_name(booking))
    date_label = html.escape(_date_label(publish_date))
    support = html.escape(config.SUPPORT_EMAIL or config.COMPANY_EMAIL)
    if kind == "48h":
        subject = f"Материалы для рекламы · {date_label}"
        lead = "До запланированного размещения осталось 48 часов."
        action = "Пожалуйста, отправьте материалы ответом на это письмо."
    elif kind == "24h":
        subject = f"Последнее напоминание о материалах · {date_label}"
        lead = "До запланированного размещения осталось 24 часа."
        action = "Это последнее напоминание: пожалуйста, отправьте материалы сегодня."
    else:
        subject = f"Материалы не получены · размещение {date_label}"
        lead = "Сегодня запланировано рекламное размещение, но материалы пока не получены."
        action = (
            "Мы не можем подготовить публикацию без материалов. Ответьте на это письмо, "
            "чтобы уточнить статус размещения или согласовать возможные новые даты."
        )
    html_body = (
        f"<p>Здравствуйте, {client}!</p>"
        f"<p>{html.escape(lead)}</p>"
        f"<p><strong>Дата размещения:</strong> {date_label}</p>"
        f"<p>{html.escape(action)}</p>"
        f"<p>Если вы уже всё отправили, просто проигнорируйте письмо.</p>"
        f"<p>Podslushano.nl<br><a href=\"mailto:{support}\">{support}</a></p>"
    )
    text_body = (
        f"Здравствуйте, {_client_name(booking)}!\n\n{lead}\n"
        f"Дата размещения: {_date_label(publish_date)}.\n\n{action}\n\n"
        "Если вы уже всё отправили, просто проигнорируйте письмо.\n\n"
        f"Podslushano.nl · {config.SUPPORT_EMAIL or config.COMPANY_EMAIL}"
    )
    return subject, html_body, text_body


async def _delivery_due(booking_id: int, publish_date: str, kind: str) -> bool:
    async with get_session() as session:
        row = await session.scalar(
            select(AdReminderLog).where(
                AdReminderLog.booking_id == booking_id,
                AdReminderLog.publish_date == publish_date,
                AdReminderLog.kind == kind,
            )
        )
    if row is None:
        return True
    if row.status == "sent":
        return False
    # Ошибки доставки повторяем, но не чаще одного раза в шесть часов.
    last_attempt = row.updated_at or row.created_at
    if last_attempt is None:
        return True
    return (datetime.utcnow() - last_attempt).total_seconds() >= 6 * 60 * 60


async def _save_result(
    booking_id: int,
    publish_date: str,
    kind: str,
    recipient: str | None,
    ok: bool,
    error: str,
) -> None:
    async with get_session() as session:
        row = await session.scalar(
            select(AdReminderLog).where(
                AdReminderLog.booking_id == booking_id,
                AdReminderLog.publish_date == publish_date,
                AdReminderLog.kind == kind,
            )
        )
        if row is None:
            row = AdReminderLog(
                booking_id=booking_id,
                publish_date=publish_date,
                kind=kind,
                status="sent" if ok else "failed",
                recipient=recipient,
                error_text=error or None,
            )
            session.add(row)
        else:
            row.status = "sent" if ok else "failed"
            row.recipient = recipient
            row.error_text = error or None
        await session.commit()


async def _notify_admins(bot: Bot, text: str) -> None:
    for admin_id in config.ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text)
        except Exception as exc:  # noqa: BLE001
            log.warning("Не удалось уведомить администратора о рекламной брони: %s", exc)


def _day_of_keyboard(booking_id: int, publish_date: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="📅 Перенести дату",
            callback_data=f"admove:start:{booking_id}:{publish_date}",
        )],
        [InlineKeyboardButton(
            text="⏭ Пропустить размещение",
            callback_data=f"adskip:ask:{booking_id}:{publish_date}",
        )],
        [InlineKeyboardButton(
            text="✅ Материалы уже получены",
            callback_data=f"admat:received:{booking_id}",
        )],
    ])


async def _notify_day_of_admins(
    bot: Bot,
    booking: AdBooking,
    publish_date: str,
    text_body: str,
) -> None:
    message = (
        "⚠️ <b>Реклама сегодня, материалов нет</b>\n\n"
        f"Бронь №{booking.id} · {html.escape(_client_name(booking))}\n"
        f"Дата: {publish_date}\nE-mail: {html.escape(booking.email or '—')}\n\n"
        "<b>Клиенту отправлено письмо:</b>\n"
        f"<blockquote>{html.escape(text_body)}</blockquote>\n\n"
        "Выберите, что сделать с размещением."
    )
    keyboard = _day_of_keyboard(booking.id, publish_date)
    for admin_id in config.ADMIN_IDS:
        try:
            await bot.send_message(admin_id, message, reply_markup=keyboard)
        except Exception as exc:  # noqa: BLE001
            log.warning("Не удалось уведомить администратора о рекламной брони: %s", exc)


async def process_ad_reminders(bot: Bot, now: datetime | None = None) -> int:
    """Отправляет все напоминания, которые должны уйти сегодня, ровно по одному разу."""
    if not _reminders_open(now):
        return 0
    today = _local_today(now)
    async with get_session() as session:
        bookings = list((await session.scalars(
            select(AdBooking).where(
                AdBooking.status == "paid",
                AdBooking.materials_status != "received",
            )
        )).all())

    sent = 0
    for booking in bookings:
        for publish_date in _booking_dates(booking):
            kind = _due_kind(today, publish_date)
            if kind is None or not await _delivery_due(booking.id, publish_date, kind):
                continue
            subject, html_body, text_body = _message(booking, publish_date, kind)
            ok, error = await send_email_message(
                booking.email or "", subject, html_body, text_body
            )
            await _save_result(
                booking.id, publish_date, kind, booking.email, ok, error
            )
            if ok:
                sent += 1
                if kind == "day_of":
                    await _notify_day_of_admins(
                        bot, booking, publish_date, text_body
                    )
            else:
                await _notify_admins(
                    bot,
                    "❌ <b>Не отправлено напоминание рекламодателю</b>\n\n"
                    f"Бронь №{booking.id} · дата {publish_date} · {kind}\n"
                    f"E-mail: {booking.email or '—'}\nОшибка: {html.escape(error[:700])}",
                )
    return sent


async def ad_reminder_loop(bot: Bot) -> None:
    await asyncio.sleep(30)
    while True:
        try:
            await process_ad_reminders(bot)
        except Exception as exc:  # noqa: BLE001
            log.exception("Ошибка цикла напоминаний рекламодателям: %s", exc)
        await asyncio.sleep(_INTERVAL_SECONDS)
