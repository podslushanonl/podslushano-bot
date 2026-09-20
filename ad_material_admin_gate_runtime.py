"""Админ-подтверждение перед каждым письмом о рекламных материалах.

Главный источник истины — администратор: материалы могут прийти в Telegram,
Instagram, WhatsApp, Gmail или другим способом. Gmail остаётся полезной
подсказкой, но сам по себе не принимает решение об отправке/остановке писем.

Сценарий:
- за 3 дня: спросить админа, есть ли материалы; клиенту ничего не отправлять;
- за 48 часов: если вопрос ещё актуален, спросить админа и только по кнопке
  «материалов нет» отправить первое письмо;
- за 24 часа: повторить проверку и только по подтверждению отправить второе;
- в день выхода: повторить проверку и только по подтверждению отправить
  финальное письмо без обещания автоматического переноса.

Если администратор не отвечает, клиентское письмо НЕ отправляется.
"""
from __future__ import annotations

import html
from datetime import date, datetime

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select

import config
import ad_material_reminder_runtime as smart
from database.db import get_session
from database.models import AdBooking, Meta
from handlers import ad_sales_pipeline as sales_handlers
from utils import ad_reminders
from utils import ad_sales_pipeline as sales_utils
from utils.ad_calendar import _booking_dates, _client_name, _date_label

router = Router()

_DATE_STATE_PREFIX = "admatdate:"
_GATE_NOTICE_PREFIX = "adgate:notice:"
_ALLOWED_STATES = {"waiting", "discussion", "partial", "received", "preparing"}
_SILENT_STATES = {"discussion", "partial", "received", "preparing", "scheduled", "published", "completed"}


def _stage_for_days(days: int) -> str | None:
    return {3: "72h_check", 2: "48h", 1: "24h", 0: "day_of"}.get(days)


def _date_state_key(booking_id: int, publish_date: str) -> str:
    return f"{_DATE_STATE_PREFIX}{booking_id}:{publish_date}"


def _notice_key(booking_id: int, publish_date: str, stage: str) -> str:
    return f"{_GATE_NOTICE_PREFIX}{booking_id}:{publish_date}:{stage}"


async def _date_state(booking_id: int, publish_date: str) -> str | None:
    async with get_session() as session:
        row = await session.get(Meta, _date_state_key(booking_id, publish_date))
        return (row.value or "").strip() if row else None


async def _set_date_state(
    booking: AdBooking,
    publish_date: str,
    state: str,
    *,
    note: str | None = None,
) -> None:
    if state not in _ALLOWED_STATES:
        raise ValueError(f"unsupported material state: {state}")
    async with get_session() as session:
        await session.merge(Meta(key=_date_state_key(booking.id, publish_date), value=state))
        await session.commit()

    # Для одиночной рекламы сохраняем старый общий статус тоже: его показывают CRM
    # и карточки администратора. Для многодатных пакетов состояние хранится по дате,
    # чтобы материалы первого выхода не отключали проверки для остальных выходов.
    if len(_booking_dates(booking)) == 1:
        await smart._set_material_state(booking.id, state, note=note)


async def _effective_state(booking: AdBooking, publish_date: str) -> str:
    per_date = await _date_state(booking.id, publish_date)
    if per_date:
        return per_date
    # Явный общий статус, выставленный администратором через CRM, остаётся валидным.
    return (booking.materials_status or "waiting").strip() or "waiting"


async def _notice_due(booking_id: int, publish_date: str, stage: str) -> bool:
    async with get_session() as session:
        return await session.get(Meta, _notice_key(booking_id, publish_date, stage)) is None


async def _mark_notice(booking_id: int, publish_date: str, stage: str) -> None:
    async with get_session() as session:
        await session.merge(Meta(
            key=_notice_key(booking_id, publish_date, stage),
            value=datetime.utcnow().isoformat(timespec="seconds"),
        ))
        await session.commit()


def _message(booking: AdBooking, publish_date: str, kind: str) -> tuple[str, str, str]:
    """Клиентские письма: коротко, понятно и без обещаний, которых мы не давали."""
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
        f"<p><strong>Формат:</strong> {format_name}<br>"
        f"<strong>Дата:</strong> {date_label}</p>"
    )
    details_text = f"Формат: {format_raw}\nДата: {date_raw}"
    delivery_html = (
        "<p>Материалы можно прислать там, где мы уже общаемся — в Telegram, Instagram "
        "или WhatsApp — либо ответом на это письмо. Фото и видео лучше отправлять в "
        "исходном качестве. Для больших файлов подойдёт открытая ссылка на Google Drive, "
        "Dropbox или WeTransfer.</p>"
    )
    delivery_text = (
        "Материалы можно прислать там, где мы уже общаемся — в Telegram, Instagram "
        "или WhatsApp — либо ответом на это письмо. Фото и видео лучше отправлять в "
        "исходном качестве. Для больших файлов подойдёт открытая ссылка на Google Drive, "
        "Dropbox или WeTransfer."
    )

    if kind == "48h":
        subject = f"Материалы для рекламы {date_raw} · Podslushano.nl"
        html_body = (
            f"<p>Здравствуйте, {client}!</p>"
            f"<p>Через <strong>48 часов</strong> у вас запланирован рекламный выход в "
            "Podslushano.nl, а материалы для подготовки публикации мы пока не получили.</p>"
            f"{details_html}"
            "<p>Пожалуйста, пришлите исходные фото/видео, основные факты и условия, а также "
            "ссылку или контакт, который должен быть в рекламе. Это нужно, чтобы мы успели "
            "подготовить и согласовать публикацию до выхода.</p>"
            f"{delivery_html}"
            "<p>Если вы уже отправили материалы после нашего последнего контакта, это письмо "
            "можно просто проигнорировать.</p>"
            f"<p>Podslushano.nl<br><a href=\"mailto:{support}\">{support}</a></p>"
        )
        text_body = (
            f"Здравствуйте, {client_raw}!\n\n"
            "Через 48 часов у вас запланирован рекламный выход в Podslushano.nl, а материалы "
            "для подготовки публикации мы пока не получили.\n\n"
            f"{details_text}\n\n"
            "Пожалуйста, пришлите исходные фото/видео, основные факты и условия, а также "
            "ссылку или контакт, который должен быть в рекламе. Это нужно, чтобы мы успели "
            "подготовить и согласовать публикацию до выхода.\n\n"
            f"{delivery_text}\n\n"
            "Если вы уже отправили материалы после нашего последнего контакта, это письмо "
            "можно просто проигнорировать.\n\n"
            f"Podslushano.nl · {support_raw}"
        )
    elif kind == "24h":
        subject = f"Материалы для завтрашней рекламы · Podslushano.nl"
        html_body = (
            f"<p>Здравствуйте, {client}!</p>"
            f"<p>До запланированного рекламного выхода осталось <strong>24 часа</strong>. "
            "Материалы для публикации мы пока не получили.</p>"
            f"{details_html}"
            "<p>Если реклама должна выйти в запланированную дату, пожалуйста, пришлите полный "
            "комплект материалов сегодня. Нам нужны исходные фото/видео, важные факты и "
            "условия, а также нужная ссылка или контакт.</p>"
            f"{delivery_html}"
            "<p>Если материалы уже отправлены, это письмо можно проигнорировать.</p>"
            f"<p>Podslushano.nl<br><a href=\"mailto:{support}\">{support}</a></p>"
        )
        text_body = (
            f"Здравствуйте, {client_raw}!\n\n"
            "До запланированного рекламного выхода осталось 24 часа. Материалы для "
            "публикации мы пока не получили.\n\n"
            f"{details_text}\n\n"
            "Если реклама должна выйти в запланированную дату, пожалуйста, пришлите полный "
            "комплект материалов сегодня. Нам нужны исходные фото/видео, важные факты и "
            "условия, а также нужная ссылка или контакт.\n\n"
            f"{delivery_text}\n\n"
            "Если материалы уже отправлены, это письмо можно проигнорировать.\n\n"
            f"Podslushano.nl · {support_raw}"
        )
    else:
        subject = f"Реклама на сегодня: нужны дальнейшие действия · Podslushano.nl"
        html_body = (
            f"<p>Здравствуйте, {client}!</p>"
            f"<p>Сегодня у вас запланирован рекламный выход в Podslushano.nl, но к моменту "
            "подготовки мы не получили материалы. Без согласованного контента публикация "
            "сегодня выйти не может.</p>"
            f"{details_html}"
            "<p>Пожалуйста, свяжитесь с нами и пришлите материалы, чтобы согласовать дальнейшие "
            "действия. Если перенос на другую дату возможен, мы предложим доступные варианты. "
            "Новая дата не назначается автоматически и зависит от свободных рекламных слотов.</p>"
            f"{delivery_html}"
            "<p>Если материалы уже были переданы другим способом, просто сообщите нам, где их найти.</p>"
            f"<p>Podslushano.nl<br><a href=\"mailto:{support}\">{support}</a></p>"
        )
        text_body = (
            f"Здравствуйте, {client_raw}!\n\n"
            "Сегодня у вас запланирован рекламный выход в Podslushano.nl, но к моменту "
            "подготовки мы не получили материалы. Без согласованного контента публикация "
            "сегодня выйти не может.\n\n"
            f"{details_text}\n\n"
            "Пожалуйста, свяжитесь с нами и пришлите материалы, чтобы согласовать дальнейшие "
            "действия. Если перенос на другую дату возможен, мы предложим доступные варианты. "
            "Новая дата не назначается автоматически и зависит от свободных рекламных слотов.\n\n"
            f"{delivery_text}\n\n"
            "Если материалы уже были переданы другим способом, просто сообщите нам, где их найти.\n\n"
            f"Podslushano.nl · {support_raw}"
        )
    return subject, html_body, text_body


def _gmail_hint(mailbox: smart.MailboxResult) -> str:
    if not mailbox.available:
        return "Gmail: проверить автоматически не удалось. Это не влияет на решение — проверь остальные каналы."
    if mailbox.state == "received":
        return "Gmail: найдено письмо с вложением или ссылкой на материалы. Проверь — возможно, материалы уже получены."
    if mailbox.state == "discussion":
        return "Gmail: найден ответ клиента, но вложение или ссылка на материалы не обнаружены."
    return "Gmail: новых ответов/материалов от этого e-mail не найдено."


def _keyboard(booking_id: int, publish_date: str, stage: str) -> InlineKeyboardMarkup:
    common = [
        [
            InlineKeyboardButton(
                text="✅ Материалы получены",
                callback_data=f"adgate:state:received:{booking_id}:{publish_date}:{stage}",
            ),
            InlineKeyboardButton(
                text="💬 Уже обсуждаем",
                callback_data=f"adgate:state:discussion:{booking_id}:{publish_date}:{stage}",
            ),
        ],
        [InlineKeyboardButton(
            text="📎 Часть материалов получена",
            callback_data=f"adgate:state:partial:{booking_id}:{publish_date}:{stage}",
        )],
    ]
    if stage == "72h_check":
        common.append([InlineKeyboardButton(
            text="❌ Пока материалов нет",
            callback_data=f"adgate:wait:{booking_id}:{publish_date}",
        )])
    else:
        label = {
            "48h": "📤 Нет — отправить письмо за 48 часов",
            "24h": "📤 Нет — отправить письмо за 24 часа",
            "day_of": "📤 Нет — отправить финальное письмо",
        }[stage]
        common.append([InlineKeyboardButton(
            text=label,
            callback_data=f"adgate:send:{booking_id}:{publish_date}:{stage}",
        )])
    return InlineKeyboardMarkup(inline_keyboard=common)


async def _notify_admin_gate(
    bot,
    booking: AdBooking,
    publish_date: str,
    stage: str,
    mailbox: smart.MailboxResult,
) -> bool:
    if not await _notice_due(booking.id, publish_date, stage):
        return False

    title = {
        "72h_check": "🧾 <b>Реклама через 3 дня — проверь материалы</b>",
        "48h": "⏰ <b>Реклама через 48 часов — отправлять напоминание?</b>",
        "24h": "⏰ <b>Реклама завтра — материалы уже есть?</b>",
        "day_of": "⚠️ <b>Реклама сегодня — финальная проверка материалов</b>",
    }[stage]
    action = (
        "Клиенту сейчас ничего не отправляется. Отметь фактическую ситуацию по всем каналам: "
        "Telegram, Instagram, WhatsApp, e-mail и ссылкам."
        if stage == "72h_check"
        else "Письмо клиенту уйдёт только если ты сам нажмёшь кнопку «Нет — отправить». "
             "Без твоего подтверждения бот ничего не отправит."
    )
    text = (
        f"{title}\n\n"
        f"Бронь №{booking.id} · {html.escape(_client_name(booking))}\n"
        f"Дата выхода: {html.escape(_date_label(publish_date))}\n"
        f"E-mail: {html.escape(booking.email or '—')}\n\n"
        f"{html.escape(_gmail_hint(mailbox))}\n\n"
        f"{action}"
    )
    delivered = False
    for admin_id in config.ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                text,
                reply_markup=_keyboard(booking.id, publish_date, stage),
            )
            delivered = True
        except Exception:
            pass
    if delivered:
        await _mark_notice(booking.id, publish_date, stage)
    return delivered


async def process_ad_reminders(bot, now: datetime | None = None) -> int:
    """Никогда не отправляет клиентские письма сам: только запрашивает решение админа."""
    if not ad_reminders._reminders_open(now):
        return 0
    today = ad_reminders._local_today(now)
    async with get_session() as session:
        bookings = list((await session.scalars(
            select(AdBooking).where(AdBooking.status == "paid")
        )).all())

    prompts = 0
    for booking in bookings:
        for publish_date in _booking_dates(booking):
            days = (date.fromisoformat(publish_date) - today).days
            stage = _stage_for_days(days)
            if stage is None:
                continue
            state = await _effective_state(booking, publish_date)
            if state in _SILENT_STATES:
                continue
            mailbox = await smart._mailbox_check(booking)
            if await _notify_admin_gate(bot, booking, publish_date, stage, mailbox):
                prompts += 1
    return prompts


@router.callback_query(F.data.startswith("adgate:state:"))
async def set_gate_state(callback: CallbackQuery) -> None:
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("Только для администраторов", show_alert=True)
        return
    try:
        _, _, state, raw_id, publish_date, stage = callback.data.split(":", 5)
        booking_id = int(raw_id)
        date.fromisoformat(publish_date)
    except (ValueError, IndexError):
        await callback.answer("Некорректная команда", show_alert=True)
        return
    if state not in {"received", "discussion", "partial"}:
        await callback.answer("Неизвестный статус", show_alert=True)
        return
    async with get_session() as session:
        booking = await session.get(AdBooking, booking_id)
    if booking is None or booking.status != "paid":
        await callback.answer("Бронь не найдена", show_alert=True)
        return
    label = {
        "received": "Материалы получены",
        "discussion": "Уже обсуждаем материалы",
        "partial": "Часть материалов получена",
    }[state]
    await _set_date_state(
        booking,
        publish_date,
        state,
        note=f"Администратор: {label} · {datetime.utcnow():%Y-%m-%d %H:%M} UTC",
    )
    await callback.answer(label)
    if callback.message:
        try:
            await callback.message.edit_text(
                (callback.message.text or "") + f"\n\n✅ <b>{html.escape(label)}</b>. Автоматические письма по этой дате отключены.",
                reply_markup=None,
            )
        except Exception:
            pass


@router.callback_query(F.data.startswith("adgate:wait:"))
async def confirm_still_waiting(callback: CallbackQuery) -> None:
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
    await _set_date_state(
        booking,
        publish_date,
        "waiting",
        note="За 3 дня администратор подтвердил: материалов пока нет.",
    )
    await callback.answer("Зафиксировано: материалов пока нет")
    if callback.message:
        try:
            await callback.message.edit_text(
                (callback.message.text or "")
                + "\n\n❌ <b>Материалов пока нет.</b> Клиенту ничего не отправлено. "
                  "За 48 часов до выхода бот спросит ещё раз перед первым письмом.",
                reply_markup=None,
            )
        except Exception:
            pass


@router.callback_query(F.data.startswith("adgate:send:"))
async def send_after_admin_confirmation(callback: CallbackQuery) -> None:
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("Только для администраторов", show_alert=True)
        return
    try:
        _, _, raw_id, publish_date, kind = callback.data.split(":", 4)
        booking_id = int(raw_id)
        date.fromisoformat(publish_date)
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
    current = await _effective_state(booking, publish_date)
    if current in _SILENT_STATES:
        await callback.answer("Письмо не нужно: материалы уже отмечены", show_alert=True)
        return

    await _set_date_state(
        booking,
        publish_date,
        "waiting",
        note=f"Администратор подтвердил отсутствие материалов перед письмом {kind}.",
    )
    ok, payload = await smart._send_one(booking, publish_date, kind)
    if not ok:
        await callback.answer(
            "Это письмо уже отправлялось" if payload == "already-sent" else "Не удалось отправить письмо",
            show_alert=True,
        )
        return

    await callback.answer("Письмо отправлено")
    extra = (
        " Клиенту не обещан автоматический перенос: сначала нужно отдельно согласовать дальнейшие действия."
        if kind == "day_of" else ""
    )
    if callback.message:
        try:
            await callback.message.edit_text(
                (callback.message.text or "")
                + f"\n\n📤 <b>Подтверждено: материалов нет. Письмо {html.escape(kind)} отправлено.</b>{extra}",
                reply_markup=None,
            )
        except Exception:
            pass


def install() -> None:
    if getattr(ad_reminders, "_admin_gated_material_reminders_installed", False):
        return

    # Разговор сам по себе больше не считается доказательством получения материалов.
    # Решение принимает администратор, потому что основная переписка может идти вне бота.
    sales_utils.record_message = smart._original_record_message
    sales_handlers.record_message = smart._original_record_message

    # Новая копия писем и новый scheduler полностью заменяют автоматическую цепочку.
    smart._message = _message
    ad_reminders._message = _message
    ad_reminders.process_ad_reminders = process_ad_reminders
    ad_reminders._admin_gated_material_reminders_installed = True


install()
