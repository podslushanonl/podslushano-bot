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
from database.models import AdBooking, AdReminderLog, Meta
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
    info = config.AD_FORMATS.get(booking.fmt) or {}
    format_name = html.escape(info.get("name") or booking.fmt)
    delivery_html = (
        "<ul>"
        "<li>если общий размер файлов до 25 МБ — прикрепите их к ответу на это письмо;</li>"
        "<li>если файлов больше или они тяжелее 25 МБ — загрузите оригиналы в "
        "Google Drive, Dropbox или WeTransfer и вставьте ссылку в ответ;</li>"
        "<li>для ссылки включите доступ «всем, у кого есть ссылка», чтобы мы могли "
        "открыть и скачать материалы без запроса разрешения.</li>"
        "</ul>"
    )
    delivery_text = (
        "Как передать материалы:\n"
        "• если общий размер файлов до 25 МБ — прикрепите их к ответу на это письмо;\n"
        "• если файлов больше или они тяжелее 25 МБ — загрузите оригиналы в "
        "Google Drive, Dropbox или WeTransfer и вставьте ссылку в ответ;\n"
        "• для ссылки включите доступ «всем, у кого есть ссылка», чтобы мы могли "
        "открыть и скачать материалы без запроса разрешения."
    )
    if kind == "48h":
        subject = f"Нужны материалы для рекламы {date_label} · бронь №{booking.id}"
        html_body = (
            f"<p>Здравствуйте, {client}!</p>"
            "<p>До запланированного размещения осталось <strong>2 дня "
            "(48 часов)</strong>. Сейчас нам нужен полный комплект материалов, чтобы "
            "успеть подготовить публикацию, адаптировать её под аудиторию и согласовать "
            "содержание до выхода.</p>"
            f"<p><strong>Бронь:</strong> №{booking.id}<br>"
            f"<strong>Формат:</strong> {format_name}<br>"
            f"<strong>Дата размещения:</strong> {date_label}</p>"
            "<p><strong>Что прислать:</strong></p>"
            "<ul><li>фото и видео в исходном качестве, без сжатия;</li>"
            "<li>факты, которые обязательно должны быть в публикации: услуга или "
            "предложение, цена, дата, адрес и другие важные условия;</li>"
            "<li>ссылку, контакт и понятное действие для аудитории;</li>"
            "<li>готовый текст, тезисы или примеры подачи, если они у вас есть.</li></ul>"
            "<p><strong>Куда отправить:</strong> ответьте на это письмо.</p>"
            f"{delivery_html}"
            "<p>Пожалуйста, пришлите всё одним письмом или одной ссылкой. Если часть "
            "материалов будет отправлена позже, укажите это в ответе.</p>"
            f"<p>Podslushano.nl<br><a href=\"mailto:{support}\">{support}</a></p>"
        )
        text_body = (
            f"Здравствуйте, {_client_name(booking)}!\n\n"
            "До запланированного размещения осталось 2 дня (48 часов). Сейчас нам "
            "нужен полный комплект материалов, чтобы успеть подготовить публикацию, "
            "адаптировать её под аудиторию и согласовать содержание до выхода.\n\n"
            f"Бронь: №{booking.id}\nФормат: {info.get('name') or booking.fmt}\n"
            f"Дата размещения: {_date_label(publish_date)}\n\n"
            "Что прислать:\n"
            "• фото и видео в исходном качестве, без сжатия;\n"
            "• факты, которые обязательно должны быть в публикации: услуга или "
            "предложение, цена, дата, адрес и другие важные условия;\n"
            "• ссылку, контакт и понятное действие для аудитории;\n"
            "• готовый текст, тезисы или примеры подачи, если они у вас есть.\n\n"
            "Куда отправить: ответьте на это письмо.\n\n"
            f"{delivery_text}\n\n"
            "Пожалуйста, пришлите всё одним письмом или одной ссылкой. Если часть "
            "материалов будет отправлена позже, укажите это в ответе.\n\n"
            f"Podslushano.nl · {config.SUPPORT_EMAIL or config.COMPANY_EMAIL}"
        )
    elif kind == "24h":
        subject = f"Последний день для материалов · реклама {date_label} · бронь №{booking.id}"
        html_body = (
            f"<p>Здравствуйте, {client}!</p>"
            "<p>До рекламного размещения осталось <strong>24 часа</strong>, а материалы "
            "по брони всё ещё не получены. Сегодня последний день, когда мы можем "
            "принять их без изменения запланированной даты.</p>"
            f"<p><strong>Бронь:</strong> №{booking.id}<br>"
            f"<strong>Формат:</strong> {format_name}<br>"
            f"<strong>Дата размещения:</strong> {date_label}</p>"
            "<p><strong>Что нужно сделать сегодня:</strong> ответьте на это письмо и "
            "пришлите полный комплект — исходные фото или видео, обязательные факты, "
            "ссылку или контакт и желаемое действие для аудитории.</p>"
            f"{delivery_html}"
            "<p>Без полного комплекта мы не сможем подготовить и согласовать публикацию "
            "к запланированному выходу. В таком случае дата может быть перенесена или "
            "размещение на этот день будет пропущено.</p>"
            "<p>Если материалы уже были отправлены другим способом, ответьте на это "
            "письмо и напишите, где именно их найти.</p>"
            f"<p>Podslushano.nl<br><a href=\"mailto:{support}\">{support}</a></p>"
        )
        text_body = (
            f"Здравствуйте, {_client_name(booking)}!\n\n"
            "До рекламного размещения осталось 24 часа, а материалы по брони всё ещё "
            "не получены. Сегодня последний день, когда мы можем принять их без "
            "изменения запланированной даты.\n\n"
            f"Бронь: №{booking.id}\nФормат: {info.get('name') or booking.fmt}\n"
            f"Дата размещения: {_date_label(publish_date)}\n\n"
            "Что нужно сделать сегодня: ответьте на это письмо и пришлите полный "
            "комплект — исходные фото или видео, обязательные факты, ссылку или контакт "
            "и желаемое действие для аудитории.\n\n"
            f"{delivery_text}\n\n"
            "Без полного комплекта мы не сможем подготовить и согласовать публикацию "
            "к запланированному выходу. В таком случае дата может быть перенесена или "
            "размещение на этот день будет пропущено.\n\n"
            "Если материалы уже были отправлены другим способом, ответьте на это "
            "письмо и напишите, где именно их найти.\n\n"
            f"Podslushano.nl · {config.SUPPORT_EMAIL or config.COMPANY_EMAIL}"
        )
    else:
        subject = f"Сегодняшнее размещение приостановлено · бронь №{booking.id}"
        html_body = (
            f"<p>Здравствуйте, {client}!</p>"
            "<p>Сегодня должна была выйти ваша реклама, но к началу подготовки мы не "
            "получили материалы. Поэтому размещение на сегодня <strong>приостановлено</strong> "
            "и не может быть опубликовано без согласованного контента.</p>"
            f"<p><strong>Бронь:</strong> №{booking.id}<br>"
            f"<strong>Формат:</strong> {format_name}<br>"
            f"<strong>Дата:</strong> {date_label}</p>"
            "<p><strong>Что будет дальше:</strong> мы проверим возможность переноса и "
            "отдельно подтвердим новую дату либо сообщим, что размещение на этот день "
            "пропущено.</p>"
            "<p>Чтобы мы могли продолжить работу, ответьте на это письмо и пришлите "
            "полный комплект материалов. Если общий размер превышает 25 МБ, отправьте "
            "ссылку Google Drive, Dropbox или WeTransfer с доступом «всем, у кого есть "
            "ссылка».</p>"
            "<p>Если вы уже отправляли материалы другим способом, укажите в ответе, "
            "где именно их найти.</p>"
            f"<p>Podslushano.nl<br><a href=\"mailto:{support}\">{support}</a></p>"
        )
        text_body = (
            f"Здравствуйте, {_client_name(booking)}!\n\n"
            "Сегодня должна была выйти ваша реклама, но к началу подготовки мы не "
            "получили материалы. Поэтому размещение на сегодня приостановлено и не "
            "может быть опубликовано без согласованного контента.\n\n"
            f"Бронь: №{booking.id}\nФормат: {info.get('name') or booking.fmt}\n"
            f"Дата: {_date_label(publish_date)}\n\n"
            "Что будет дальше: мы проверим возможность переноса и отдельно подтвердим "
            "новую дату либо сообщим, что размещение на этот день пропущено.\n\n"
            "Чтобы мы могли продолжить работу, ответьте на это письмо и пришлите полный "
            "комплект материалов. Если общий размер превышает 25 МБ, отправьте ссылку "
            "Google Drive, Dropbox или WeTransfer с доступом «всем, у кого есть ссылка».\n\n"
            "Если вы уже отправляли материалы другим способом, укажите в ответе, где "
            "именно их найти.\n\n"
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


def _admin_action_key(booking_id: int, publish_date: str) -> str:
    return f"adreminder:admin-action:{booking_id}:{publish_date}"


async def _admin_action_due(booking_id: int, publish_date: str) -> bool:
    async with get_session() as session:
        return await session.get(
            Meta, _admin_action_key(booking_id, publish_date)
        ) is None


async def _mark_admin_action_sent(booking_id: int, publish_date: str) -> None:
    async with get_session() as session:
        await session.merge(Meta(
            key=_admin_action_key(booking_id, publish_date), value="sent"
        ))
        await session.commit()


async def _email_was_sent(booking_id: int, publish_date: str, kind: str) -> bool:
    async with get_session() as session:
        row = await session.scalar(
            select(AdReminderLog).where(
                AdReminderLog.booking_id == booking_id,
                AdReminderLog.publish_date == publish_date,
                AdReminderLog.kind == kind,
            )
        )
        return row is not None and row.status == "sent"


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
) -> bool:
    message = (
        "⚠️ <b>Реклама сегодня, материалов нет</b>\n\n"
        f"Бронь №{booking.id} · {html.escape(_client_name(booking))}\n"
        f"Дата: {publish_date}\nE-mail: {html.escape(booking.email or '—')}\n\n"
        "<b>Клиенту отправлено письмо:</b>\n"
        f"<blockquote>{html.escape(text_body)}</blockquote>\n\n"
        "Выберите, что сделать с размещением."
    )
    keyboard = _day_of_keyboard(booking.id, publish_date)
    delivered = False
    for admin_id in config.ADMIN_IDS:
        try:
            await bot.send_message(admin_id, message, reply_markup=keyboard)
            delivered = True
        except Exception as exc:  # noqa: BLE001
            log.warning("Не удалось уведомить администратора о рекламной брони: %s", exc)
    return delivered


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
            if kind is None:
                continue
            subject, html_body, text_body = _message(booking, publish_date, kind)
            if not await _delivery_due(booking.id, publish_date, kind):
                # После обновления восстановит кнопки и для сегодняшнего письма,
                # которое старая версия уже успела отправить без действий.
                if (
                    kind == "day_of"
                    and await _email_was_sent(booking.id, publish_date, kind)
                    and await _admin_action_due(booking.id, publish_date)
                    and await _notify_day_of_admins(
                        bot, booking, publish_date, text_body
                    )
                ):
                    await _mark_admin_action_sent(booking.id, publish_date)
                continue
            ok, error = await send_email_message(
                booking.email or "", subject, html_body, text_body
            )
            await _save_result(
                booking.id, publish_date, kind, booking.email, ok, error
            )
            if ok:
                sent += 1
                if kind == "day_of":
                    if await _notify_day_of_admins(
                        bot, booking, publish_date, text_body
                    ):
                        await _mark_admin_action_sent(booking.id, publish_date)
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
