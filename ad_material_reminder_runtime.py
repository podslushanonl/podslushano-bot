"""Умные напоминания рекламодателям о материалах.

Цель: письмо 48h/24h/day_of — это не календарная рассылка сама по себе, а
только способ получить ЕЩЁ НЕ ПОЛУЧЕННЫЕ материалы. Любой признак живого
обсуждения, частично/полностью полученных материалов или начавшейся подготовки
останавливает клиентские напоминания.

Дополнительно модуль умеет перед отправкой проверить почтовый ящик:
1) Gmail API — если задан GOOGLE_GMAIL_OAUTH_REFRESH_TOKEN (client id/secret
   переиспользуются от Google Calendar OAuth);
2) Gmail IMAP — если заданы GMAIL_ADDRESS + GMAIL_APP_PASSWORD.

Если доступ к inbox не настроен, действует fail-safe: бот может отправить первое
письмо, но НЕ шлёт второе/третье вслепую. Вместо этого просит администратора
подтвердить, что материалы всё ещё не пришли.
"""
from __future__ import annotations

import asyncio
import base64
import email as email_lib
import html
import imaplib
import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import aiohttp
from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select

import config
from database.ad_sales_models import AdConversationMessage, AdSalesPipeline
from database.db import get_session
from database.models import AdBooking, AdReminderLog, Meta
from handlers import ad_sales_pipeline as sales_handlers
from handlers import ads
from utils import ad_reminders
from utils import ad_sales_pipeline as sales_utils
from utils.ad_calendar import _booking_dates, _client_name, _date_label
from utils.invoices import send_email_message

log = logging.getLogger(__name__)
router = Router()

WAITING = "waiting"
SILENT_MATERIAL_STATES = {
    "discussion", "partial", "received", "preparing", "scheduled", "published", "completed",
}
SILENT_PRODUCTION_STATES = {
    "materials_discussion", "materials_partial", "materials_received",
    "preparing", "scheduled", "published", "completed",
}
PRODUCTION_BY_MATERIAL_STATE = {
    "waiting": "waiting_materials",
    "discussion": "materials_discussion",
    "partial": "materials_partial",
    "received": "materials_received",
    "preparing": "preparing",
}
MATERIAL_STATE_LABELS = {
    "waiting": "📥 Ждём материалы",
    "discussion": "💬 Материалы обсуждаем",
    "partial": "📎 Часть материалов получена",
    "received": "📦 Материалы получены",
    "preparing": "🛠 Материал в подготовке",
}
_LINK_RE = re.compile(
    r"(?:drive\.google\.com|docs\.google\.com|dropbox\.com|wetransfer\.com|we\.tl|"
    r"onedrive\.live\.com|1drv\.ms|icloud\.com|mega\.nz)",
    re.I,
)


@dataclass
class MailboxResult:
    available: bool
    state: str | None = None  # discussion | received | None
    detail: str = ""


def _smart_production_labels() -> None:
    # Preserve the dict object because handlers imported it by reference.
    sales_utils.PRODUCTION_LABELS.clear()
    sales_utils.PRODUCTION_LABELS.update({
        "waiting_materials": "📥 Ждём материалы",
        "materials_discussion": "💬 Обсуждаем материалы",
        "materials_partial": "📎 Часть материалов получена",
        "materials_received": "📦 Материалы получены",
        "preparing": "🛠 Готовим материал",
        "scheduled": "🗓 Запланировано",
        "published": "🚀 Опубликовано",
        "completed": "🏁 Завершено",
    })
    # После оплаты рекламный диалог не должен «исчезать»: ответ клиента может
    # означать, что материалы уже присланы/обсуждаются.
    sales_utils.ACTIVE_SALES.add("paid")


def _materials_keyboard(booking_id: int, received: bool = False) -> InlineKeyboardMarkup:
    if received:
        return InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text="↩️ Снова ждём материалы",
                callback_data=f"admstate:waiting:{booking_id}",
            )
        ]])
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="💬 Обсуждаем", callback_data=f"admstate:discussion:{booking_id}"
            ),
            InlineKeyboardButton(
                text="📎 Часть получена", callback_data=f"admstate:partial:{booking_id}"
            ),
        ],
        [
            InlineKeyboardButton(
                text="✅ Материалы получены", callback_data=f"admstate:received:{booking_id}"
            ),
            InlineKeyboardButton(
                text="🛠 В подготовке", callback_data=f"admstate:preparing:{booking_id}"
            ),
        ],
    ])


def _state_keyboard(booking_id: int, current: str) -> InlineKeyboardMarkup:
    if current == "waiting":
        return _materials_keyboard(booking_id)
    rows = [[InlineKeyboardButton(
        text="↩️ Снова ждём материалы",
        callback_data=f"admstate:waiting:{booking_id}",
    )]]
    if current not in {"received", "preparing"}:
        rows.append([InlineKeyboardButton(
            text="✅ Материалы получены",
            callback_data=f"admstate:received:{booking_id}",
        )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _set_material_state(
    booking_id: int,
    state: str,
    *,
    note: str | None = None,
) -> bool:
    if state not in MATERIAL_STATE_LABELS:
        return False
    async with get_session() as session:
        booking = await session.get(AdBooking, booking_id)
        if booking is None:
            return False
        booking.materials_status = state
        pipeline = await session.scalar(
            select(AdSalesPipeline).where(AdSalesPipeline.ad_booking_id == booking_id)
        )
        if pipeline is not None:
            pipeline.production_status = PRODUCTION_BY_MATERIAL_STATE[state]
            if note:
                pipeline.materials_note = note[:2000]
        await session.commit()
    return True


async def _mark_discussion_from_conversation(submission_id: int, note: str) -> None:
    async with get_session() as session:
        pipeline = await session.scalar(
            select(AdSalesPipeline).where(AdSalesPipeline.submission_id == submission_id)
        )
        if pipeline is None or pipeline.ad_booking_id is None:
            return
        booking = await session.get(AdBooking, pipeline.ad_booking_id)
        if booking is None or booking.status != "paid":
            return
        if booking.materials_status == WAITING:
            booking.materials_status = "discussion"
        if pipeline.production_status in {"not_started", "waiting_materials"}:
            pipeline.production_status = "materials_discussion"
        pipeline.materials_note = note[:2000]
        await session.commit()


# Existing handlers imported record_message directly, so patch both references.
_original_record_message = sales_utils.record_message


async def _smart_record_message(
    submission_id: int,
    user_id: int,
    role: str,
    text: str,
    *,
    kind: str = "inbound",
    telegram_message_id: int | None = None,
) -> None:
    await _original_record_message(
        submission_id,
        user_id,
        role,
        text,
        kind=kind,
        telegram_message_id=telegram_message_id,
    )
    if role in {"client", "manager"} and kind in {"inbound", "outbound"}:
        await _mark_discussion_from_conversation(
            submission_id,
            f"Живой рекламный диалог после оплаты · {role} · {datetime.utcnow():%Y-%m-%d %H:%M} UTC",
        )


def _message(booking: AdBooking, publish_date: str, kind: str) -> tuple[str, str, str]:
    """Короткие письма: одно действие, без бюрократии и ложных утверждений."""
    client_raw = _client_name(booking)
    client = html.escape(client_raw)
    date_raw = _date_label(publish_date)
    date_label = html.escape(date_raw)
    info = config.AD_FORMATS.get(booking.fmt) or {}
    format_raw = info.get("name") or booking.fmt
    format_name = html.escape(format_raw)
    support_raw = config.SUPPORT_EMAIL or config.COMPANY_EMAIL
    support = html.escape(support_raw)

    details_html = (
        f"<p><strong>Размещение:</strong> {format_name}<br>"
        f"<strong>Дата:</strong> {date_label}<br>"
        f"<strong>Бронь:</strong> №{booking.id}</p>"
    )
    details_text = (
        f"Размещение: {format_raw}\nДата: {date_raw}\nБронь: №{booking.id}"
    )
    send_html = (
        "<p>Можно просто ответить на это письмо. Фото и видео лучше прислать в исходном "
        "качестве; если файлов много или они тяжелее 25 МБ — одной ссылкой на Google Drive, "
        "Dropbox или WeTransfer с открытым доступом по ссылке.</p>"
    )
    send_text = (
        "Можно просто ответить на это письмо. Фото и видео лучше прислать в исходном "
        "качестве; если файлов много или они тяжелее 25 МБ — одной ссылкой на Google Drive, "
        "Dropbox или WeTransfer с открытым доступом по ссылке."
    )

    if kind == "48h":
        subject = f"Материалы для рекламы {date_raw} · Podslushano.nl"
        html_body = (
            f"<p>Здравствуйте, {client}!</p>"
            f"<p>Напоминаем о рекламном выходе <strong>{date_label}</strong>. Если материалы "
            "ещё не отправляли, пришлите, пожалуйста, всё необходимое для подготовки: "
            "исходные фото/видео, ключевые факты и условия, нужную ссылку или контакт.</p>"
            f"{details_html}{send_html}"
            "<p>Если материалы уже у нас или мы уже обсуждаем их с вами, ничего дополнительно "
            "отправлять не нужно.</p>"
            f"<p>Podslushano.nl<br><a href=\"mailto:{support}\">{support}</a></p>"
        )
        text_body = (
            f"Здравствуйте, {client_raw}!\n\n"
            f"Напоминаем о рекламном выходе {date_raw}. Если материалы ещё не отправляли, "
            "пришлите всё необходимое для подготовки: исходные фото/видео, ключевые факты "
            "и условия, нужную ссылку или контакт.\n\n"
            f"{details_text}\n\n{send_text}\n\n"
            "Если материалы уже у нас или мы уже обсуждаем их с вами, ничего дополнительно "
            "отправлять не нужно.\n\n"
            f"Podslushano.nl · {support_raw}"
        )
    elif kind == "24h":
        subject = f"Напоминание о материалах · реклама {date_raw}"
        html_body = (
            f"<p>Здравствуйте, {client}!</p>"
            "<p>Пишем, потому что по этой брони у нас пока нет отметки о полученных или "
            "обсуждаемых материалах. До выхода рекламы остался один день.</p>"
            f"{details_html}"
            "<p>Если материалы ещё не отправляли, пришлите их сегодня: фото/видео, основные "
            "факты и условия, а также нужную ссылку или контакт.</p>"
            f"{send_html}"
            "<p>Если вы уже отправили материалы другим способом, достаточно ответить, где "
            "их найти — после этого автоматические напоминания остановятся.</p>"
            f"<p>Podslushano.nl<br><a href=\"mailto:{support}\">{support}</a></p>"
        )
        text_body = (
            f"Здравствуйте, {client_raw}!\n\n"
            "Пишем, потому что по этой брони у нас пока нет отметки о полученных или "
            "обсуждаемых материалах. До выхода рекламы остался один день.\n\n"
            f"{details_text}\n\n"
            "Если материалы ещё не отправляли, пришлите их сегодня: фото/видео, основные "
            "факты и условия, а также нужную ссылку или контакт.\n\n"
            f"{send_text}\n\n"
            "Если вы уже отправили материалы другим способом, достаточно ответить, где "
            "их найти — после этого автоматические напоминания остановятся.\n\n"
            f"Podslushano.nl · {support_raw}"
        )
    else:
        subject = f"Материалы для сегодняшней рекламы · бронь №{booking.id}"
        html_body = (
            f"<p>Здравствуйте, {client}!</p>"
            f"<p>Сегодня запланирован рекламный выход <strong>{date_label}</strong>, но по "
            "брони всё ещё нет подтверждения, что материалы получены или находятся в работе.</p>"
            f"{details_html}"
            "<p>Если размещение остаётся актуальным, ответьте на это письмо и пришлите "
            "материалы либо напишите, где вы их уже отправили. Мы отдельно согласуем дальнейшие "
            "действия по сегодняшнему выходу.</p>"
            "<p>Это письмо само по себе не отменяет и не переносит размещение.</p>"
            f"<p>Podslushano.nl<br><a href=\"mailto:{support}\">{support}</a></p>"
        )
        text_body = (
            f"Здравствуйте, {client_raw}!\n\n"
            f"Сегодня запланирован рекламный выход {date_raw}, но по брони всё ещё нет "
            "подтверждения, что материалы получены или находятся в работе.\n\n"
            f"{details_text}\n\n"
            "Если размещение остаётся актуальным, ответьте на это письмо и пришлите материалы "
            "либо напишите, где вы их уже отправили. Мы отдельно согласуем дальнейшие действия "
            "по сегодняшнему выходу.\n\n"
            "Это письмо само по себе не отменяет и не переносит размещение.\n\n"
            f"Podslushano.nl · {support_raw}"
        )
    return subject, html_body, text_body


def _message_has_materials(msg) -> bool:
    body_chunks: list[str] = []
    for part in msg.walk():
        filename = part.get_filename()
        disposition = (part.get("Content-Disposition") or "").lower()
        if filename or "attachment" in disposition:
            return True
        if part.get_content_maintype() == "text" and "attachment" not in disposition:
            payload = part.get_payload(decode=True)
            if payload:
                charset = part.get_content_charset() or "utf-8"
                try:
                    body_chunks.append(payload.decode(charset, errors="replace"))
                except LookupError:
                    body_chunks.append(payload.decode("utf-8", errors="replace"))
    return bool(_LINK_RE.search("\n".join(body_chunks)))


def _imap_mailbox_check(client_email: str, since: datetime) -> MailboxResult:
    address = (config.GMAIL_ADDRESS or "").strip()
    password = (config.GMAIL_APP_PASSWORD or "").strip()
    if not (address and password):
        return MailboxResult(False, detail="Gmail IMAP не настроен")
    conn = None
    try:
        conn = imaplib.IMAP4_SSL("imap.gmail.com", 993, timeout=12)
        conn.login(address, password)
        status, _ = conn.select("INBOX", readonly=True)
        if status != "OK":
            return MailboxResult(False, detail="не удалось открыть Gmail INBOX")
        since_token = since.strftime("%d-%b-%Y")
        status, data = conn.search(None, "FROM", f'"{client_email}"', "SINCE", since_token)
        if status != "OK":
            return MailboxResult(False, detail="ошибка поиска Gmail IMAP")
        ids = (data[0] or b"").split()[-12:]
        found_reply = False
        for msg_id in reversed(ids):
            status, raw = conn.fetch(msg_id, "(BODY.PEEK[])")
            if status != "OK" or not raw:
                continue
            blob = next((item[1] for item in raw if isinstance(item, tuple) and len(item) > 1), None)
            if not blob:
                continue
            msg = email_lib.message_from_bytes(blob)
            try:
                sent_at = parsedate_to_datetime(msg.get("Date"))
                if sent_at is not None:
                    if sent_at.tzinfo is None:
                        sent_at = sent_at.replace(tzinfo=timezone.utc)
                    threshold = since.replace(tzinfo=timezone.utc) if since.tzinfo is None else since.astimezone(timezone.utc)
                    if sent_at.astimezone(timezone.utc) < threshold - timedelta(hours=2):
                        continue
            except Exception:
                pass
            found_reply = True
            if _message_has_materials(msg):
                return MailboxResult(True, "received", "Gmail: письмо с вложением/ссылкой")
        if found_reply:
            return MailboxResult(True, "discussion", "Gmail: найден ответ рекламодателя")
        return MailboxResult(True, None, "Gmail: новых ответов нет")
    except Exception as exc:  # noqa: BLE001
        log.warning("Не удалось проверить Gmail IMAP: %s", exc)
        return MailboxResult(False, detail=f"Gmail IMAP: {exc}")
    finally:
        if conn is not None:
            try:
                conn.logout()
            except Exception:
                pass


def _gmail_payload_text(payload: dict) -> tuple[bool, str]:
    """Return (has_attachment, decoded_text) from Gmail API payload tree."""
    has_attachment = False
    chunks: list[str] = []
    stack = [payload]
    while stack:
        part = stack.pop()
        stack.extend(part.get("parts") or [])
        filename = (part.get("filename") or "").strip()
        body = part.get("body") or {}
        if filename or body.get("attachmentId"):
            has_attachment = True
        data = body.get("data")
        mime = (part.get("mimeType") or "").lower()
        if data and mime.startswith("text/"):
            try:
                padding = "=" * (-len(data) % 4)
                chunks.append(base64.urlsafe_b64decode(data + padding).decode("utf-8", errors="replace"))
            except Exception:
                pass
    return has_attachment, "\n".join(chunks)


async def _gmail_api_mailbox_check(client_email: str, since: datetime) -> MailboxResult:
    refresh_token = os.getenv("GOOGLE_GMAIL_OAUTH_REFRESH_TOKEN", "").strip()
    client_id = os.getenv("GOOGLE_CALENDAR_OAUTH_CLIENT_ID", "").strip()
    client_secret = os.getenv("GOOGLE_CALENDAR_OAUTH_CLIENT_SECRET", "").strip()
    if not (refresh_token and client_id and client_secret):
        return MailboxResult(False, detail="Gmail API OAuth не настроен")
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
            async with session.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
            ) as response:
                if response.status >= 300:
                    return MailboxResult(False, detail=f"Gmail OAuth HTTP {response.status}")
                token = (await response.json()).get("access_token")
            if not token:
                return MailboxResult(False, detail="Gmail OAuth не вернул access token")
            headers = {"Authorization": f"Bearer {token}"}
            threshold = since if since.tzinfo else since.replace(tzinfo=timezone.utc)
            query = f"from:{client_email} after:{int(threshold.timestamp())}"
            async with session.get(
                "https://gmail.googleapis.com/gmail/v1/users/me/messages",
                headers=headers,
                params={"q": query, "maxResults": 10},
            ) as response:
                if response.status >= 300:
                    return MailboxResult(False, detail=f"Gmail API HTTP {response.status}")
                messages = (await response.json()).get("messages") or []
            found_reply = False
            for item in messages:
                async with session.get(
                    f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{item['id']}",
                    headers=headers,
                    params={"format": "full"},
                ) as response:
                    if response.status >= 300:
                        continue
                    data = await response.json()
                found_reply = True
                has_attachment, text = _gmail_payload_text(data.get("payload") or {})
                if has_attachment or _LINK_RE.search(text or ""):
                    return MailboxResult(True, "received", "Gmail API: материалы найдены")
            if found_reply:
                return MailboxResult(True, "discussion", "Gmail API: найден ответ рекламодателя")
            return MailboxResult(True, None, "Gmail API: новых ответов нет")
    except Exception as exc:  # noqa: BLE001
        log.warning("Не удалось проверить Gmail API: %s", exc)
        return MailboxResult(False, detail=f"Gmail API: {exc}")


async def _mailbox_check(booking: AdBooking) -> MailboxResult:
    if not booking.email:
        return MailboxResult(False, detail="у брони нет e-mail")
    api = await _gmail_api_mailbox_check(booking.email, booking.created_at or datetime.utcnow())
    if api.available:
        return api
    imap = await asyncio.to_thread(
        _imap_mailbox_check, booking.email, booking.created_at or datetime.utcnow()
    )
    if imap.available:
        return imap
    return MailboxResult(False, detail=f"{api.detail}; {imap.detail}")


async def _pipeline_suppression(booking: AdBooking) -> str | None:
    if booking.materials_status in SILENT_MATERIAL_STATES:
        return booking.materials_status
    async with get_session() as session:
        pipeline = await session.scalar(
            select(AdSalesPipeline).where(AdSalesPipeline.ad_booking_id == booking.id)
        )
        if pipeline is None:
            return None
        if pipeline.production_status in SILENT_PRODUCTION_STATES:
            mapped = {
                "materials_discussion": "discussion",
                "materials_partial": "partial",
                "materials_received": "received",
                "preparing": "preparing",
                "scheduled": "scheduled",
                "published": "published",
                "completed": "completed",
            }.get(pipeline.production_status, "discussion")
            db_booking = await session.get(AdBooking, booking.id)
            if db_booking and db_booking.materials_status == WAITING:
                db_booking.materials_status = mapped
                await session.commit()
            return mapped

        since = pipeline.paid_at or booking.created_at or datetime.utcnow()
        activity = await session.scalar(
            select(AdConversationMessage)
            .where(
                AdConversationMessage.submission_id == pipeline.submission_id,
                AdConversationMessage.role.in_(("client", "manager")),
                AdConversationMessage.kind.in_(("inbound", "outbound")),
                AdConversationMessage.created_at >= since,
            )
            .order_by(AdConversationMessage.id.desc())
        )
        if activity is not None:
            db_booking = await session.get(AdBooking, booking.id)
            if db_booking:
                db_booking.materials_status = "discussion"
            pipeline.production_status = "materials_discussion"
            pipeline.materials_note = "Есть живой диалог после оплаты — автоматические письма остановлены."
            await session.commit()
            return "discussion"
    return None


async def _any_reminder_sent(booking_id: int) -> bool:
    async with get_session() as session:
        row = await session.scalar(
            select(AdReminderLog.id)
            .where(AdReminderLog.booking_id == booking_id, AdReminderLog.status == "sent")
            .limit(1)
        )
        return row is not None


def _review_key(booking_id: int, publish_date: str, kind: str) -> str:
    return f"adrem:review:{booking_id}:{publish_date}:{kind}"


async def _review_notice_due(booking_id: int, publish_date: str, kind: str) -> bool:
    async with get_session() as session:
        return await session.get(Meta, _review_key(booking_id, publish_date, kind)) is None


async def _mark_review_notice(booking_id: int, publish_date: str, kind: str) -> None:
    async with get_session() as session:
        await session.merge(Meta(
            key=_review_key(booking_id, publish_date, kind),
            value="sent",
        ))
        await session.commit()


async def _notify_review_needed(bot, booking: AdBooking, publish_date: str, kind: str, reason: str) -> None:
    if not await _review_notice_due(booking.id, publish_date, kind):
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="💬 Уже обсуждаем", callback_data=f"admstate:discussion:{booking.id}"
            ),
            InlineKeyboardButton(
                text="📎 Часть получена", callback_data=f"admstate:partial:{booking.id}"
            ),
        ],
        [InlineKeyboardButton(
            text="✅ Материалы получены", callback_data=f"admstate:received:{booking.id}"
        )],
        [InlineKeyboardButton(
            text="📤 Всё ещё ждём — отправить письмо",
            callback_data=f"admsend:{booking.id}:{publish_date}:{kind}",
        )],
    ])
    text = (
        "🛡 <b>Повторное письмо клиенту не отправлено</b>\n\n"
        f"Бронь №{booking.id} · {html.escape(_client_name(booking))}\n"
        f"Дата: {html.escape(_date_label(publish_date))}\n"
        f"E-mail: {html.escape(booking.email or '—')}\n\n"
        "Ранее клиенту уже уходило напоминание, но бот сейчас не может надёжно проверить "
        f"входящие письма ({html.escape(reason[:450])}). Поэтому он не спамит вслепую.\n\n"
        "Если материалов действительно ещё нет — нажмите последнюю кнопку."
    )
    for admin_id in config.ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, reply_markup=kb)
        except Exception as exc:  # noqa: BLE001
            log.warning("Не удалось запросить проверку материалов у админа: %s", exc)
    await _mark_review_notice(booking.id, publish_date, kind)


async def _send_one(booking: AdBooking, publish_date: str, kind: str) -> tuple[bool, str]:
    if not await ad_reminders._delivery_due(booking.id, publish_date, kind):
        return False, "already-sent"
    subject, html_body, text_body = _message(booking, publish_date, kind)
    ok, error = await send_email_message(booking.email or "", subject, html_body, text_body)
    await ad_reminders._save_result(
        booking.id, publish_date, kind, booking.email, ok, error
    )
    return ok, text_body if ok else error


async def process_ad_reminders(bot, now: datetime | None = None) -> int:
    """Send only genuinely-needed material reminders, never a blind sequence."""
    if not ad_reminders._reminders_open(now):
        return 0
    today = ad_reminders._local_today(now)
    async with get_session() as session:
        bookings = list((await session.scalars(
            select(AdBooking).where(AdBooking.status == "paid")
        )).all())

    sent = 0
    for booking in bookings:
        due = [
            (publish_date, ad_reminders._due_kind(today, publish_date))
            for publish_date in _booking_dates(booking)
        ]
        due = [(publish_date, kind) for publish_date, kind in due if kind is not None]
        if not due:
            continue

        if await _pipeline_suppression(booking):
            continue

        mailbox = await _mailbox_check(booking)
        if mailbox.state:
            await _set_material_state(
                booking.id,
                mailbox.state,
                note=f"Автоматически по почте: {mailbox.detail}",
            )
            log.info(
                "Бронь #%s: напоминания остановлены по почтовой активности (%s)",
                booking.id, mailbox.detail,
            )
            continue

        had_previous = await _any_reminder_sent(booking.id)
        for publish_date, kind in due:
            if not await ad_reminders._delivery_due(booking.id, publish_date, kind):
                continue
            # Без видимости inbox максимум одно автоматическое письмо на бронь.
            # Дальше решение подтверждает админ — это безопаснее, чем спамить.
            if not mailbox.available and had_previous:
                await _notify_review_needed(
                    bot, booking, publish_date, kind, mailbox.detail or "inbox недоступен"
                )
                continue
            ok, payload = await _send_one(booking, publish_date, kind)
            if ok:
                sent += 1
                had_previous = True
                if kind == "day_of":
                    if await ad_reminders._notify_day_of_admins(
                        bot, booking, publish_date, payload
                    ):
                        await ad_reminders._mark_admin_action_sent(booking.id, publish_date)
            elif payload != "already-sent":
                await ad_reminders._notify_admins(
                    bot,
                    "❌ <b>Не отправлено напоминание рекламодателю</b>\n\n"
                    f"Бронь №{booking.id} · дата {publish_date} · {kind}\n"
                    f"E-mail: {html.escape(booking.email or '—')}\n"
                    f"Ошибка: {html.escape(str(payload)[:700])}",
                )
    return sent


@router.callback_query(F.data.startswith("admstate:"))
async def set_material_state_callback(callback: CallbackQuery) -> None:
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("Только для администраторов", show_alert=True)
        return
    try:
        _, state, raw_id = callback.data.split(":", 2)
        booking_id = int(raw_id)
    except (ValueError, IndexError):
        await callback.answer("Некорректная бронь", show_alert=True)
        return
    if state not in MATERIAL_STATE_LABELS:
        await callback.answer("Неизвестный статус", show_alert=True)
        return
    ok = await _set_material_state(
        booking_id,
        state,
        note=f"Статус установлен администратором · {datetime.utcnow():%Y-%m-%d %H:%M} UTC",
    )
    if not ok:
        await callback.answer("Бронь не найдена", show_alert=True)
        return
    await callback.answer(MATERIAL_STATE_LABELS[state])
    if callback.message:
        try:
            await callback.message.edit_reply_markup(
                reply_markup=_state_keyboard(booking_id, state)
            )
        except Exception:
            pass


@router.callback_query(F.data.startswith("admsend:"))
async def send_confirmed_reminder(callback: CallbackQuery) -> None:
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("Только для администраторов", show_alert=True)
        return
    try:
        _, raw_id, publish_date, kind = callback.data.split(":", 3)
        booking_id = int(raw_id)
        datetime.strptime(publish_date, "%Y-%m-%d")
    except (ValueError, IndexError):
        await callback.answer("Некорректная команда", show_alert=True)
        return
    if kind not in {"48h", "24h", "day_of"}:
        await callback.answer("Некорректный тип письма", show_alert=True)
        return
    async with get_session() as session:
        booking = await session.get(AdBooking, booking_id)
    if booking is None or booking.status != "paid":
        await callback.answer("Бронь не найдена", show_alert=True)
        return
    suppression = await _pipeline_suppression(booking)
    if suppression:
        await callback.answer("Письмо не нужно: материалы уже в работе", show_alert=True)
        return
    await _set_material_state(booking_id, "waiting", note="Администратор подтвердил: материалов всё ещё нет.")
    ok, payload = await _send_one(booking, publish_date, kind)
    if ok:
        await callback.answer("Письмо отправлено")
        if callback.message:
            try:
                await callback.message.edit_text(
                    (callback.message.text or "") + "\n\n✅ Администратор подтвердил: материалы не пришли. Письмо отправлено.",
                    reply_markup=None,
                )
            except Exception:
                pass
    else:
        await callback.answer(
            "Это письмо уже отправлялось" if payload == "already-sent" else "Не удалось отправить",
            show_alert=True,
        )


def install() -> None:
    if getattr(ad_reminders, "_smart_material_reminders_installed", False):
        return
    _smart_production_labels()
    # Paid booking admin card gets richer material-state controls.
    ads._materials_keyboard = _materials_keyboard
    # Rewrite reminder copy and the scheduler guard itself.
    ad_reminders._message = _message
    ad_reminders.process_ad_reminders = process_ad_reminders
    # Post-payment Telegram conversation is a suppression signal too.
    sales_utils.record_message = _smart_record_message
    sales_handlers.record_message = _smart_record_message
    ad_reminders._smart_material_reminders_installed = True


install()
