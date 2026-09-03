"""Напоминания рекламодателям о материалах перед датой размещения."""
from __future__ import annotations

import asyncio
import html
import logging
from datetime import date, datetime
from zoneinfo import ZoneInfo

from aiogram import Bot
from sqlalchemy import select

import config
from database.db import get_session
from database.models import AdBooking, AdReminderLog
from utils.ad_calendar import _booking_dates, _client_name, _date_label
from utils.invoices import send_email_message

log = logging.getLogger(__name__)
_INTERVAL_SECONDS = 30 * 60


def _local_today(now: datetime | None = None) -> date:
    timezone = ZoneInfo(config.GOOGLE_CALENDAR_TIMEZONE)
    if now is None:
        return datetime.now(timezone).date()
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone).date()
    return now.astimezone(timezone).date()


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


async def process_ad_reminders(bot: Bot, now: datetime | None = None) -> int:
    """Отправляет все напоминания, которые должны уйти сегодня, ровно по одному разу."""
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
                    await _notify_admins(
                        bot,
                        "⚠️ <b>Реклама сегодня, материалов нет</b>\n\n"
                        f"Бронь №{booking.id} · {_client_name(booking)}\n"
                        f"Дата: {publish_date}\nE-mail: {booking.email or '—'}\n\n"
                        "Клиенту отправлено письмо. Нужно решить: перенос даты или пропуск размещения.",
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
