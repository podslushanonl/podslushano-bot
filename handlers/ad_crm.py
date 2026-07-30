"""Мини-CRM рекламных заявок для администраторов."""
from __future__ import annotations

import html
from collections import Counter
from datetime import datetime, timedelta

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import func, select

import config
from database.db import get_session
from database.models import Meta, Submission

router = Router()
PAGE_SIZE = 5
ACTIVE_STATUSES = ("pending", "contacted", "awaiting_payment")
STATUS_LABELS = {
    "pending": "🆕 Новая",
    "contacted": "📤 Ответ отправлен",
    "awaiting_payment": "⏳ Ожидает оплату",
    "paid": "✅ Оплачено",
    "rejected": "❌ Отказ",
    "closed": "⚫ Закрыто",
}
FILTER_LABELS = {
    "active": "Активные",
    "pending": "Новые",
    "contacted": "Ответ отправлен",
    "awaiting_payment": "Ожидают оплату",
    "paid": "Оплачено",
    "rejected": "Отказы",
    "all": "Все",
}


def _is_admin(user_id: int) -> bool:
    return user_id in config.ADMIN_IDS


def _lead_keyboard(submission_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✍️ Ответить", callback_data=f"subreply:{submission_id}")],
        [
            InlineKeyboardButton(text="⏳ Ждём оплату", callback_data=f"aistatus:awaiting_payment:{submission_id}"),
            InlineKeyboardButton(text="✅ Оплачено", callback_data=f"aistatus:paid:{submission_id}"),
        ],
        [
            InlineKeyboardButton(text="🔔 Напомнить", callback_data=f"aifollow:{submission_id}"),
            InlineKeyboardButton(text="❌ Отказ", callback_data=f"aistatus:rejected:{submission_id}"),
        ],
    ])


def _filters_keyboard(current: str, page: int, total_pages: int) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text=("• " if current == "active" else "") + "Активные", callback_data="adcrm:active:0"),
            InlineKeyboardButton(text=("• " if current == "awaiting_payment" else "") + "Ждут оплату", callback_data="adcrm:awaiting_payment:0"),
        ],
        [
            InlineKeyboardButton(text=("• " if current == "paid" else "") + "Оплачено", callback_data="adcrm:paid:0"),
            InlineKeyboardButton(text=("• " if current == "all" else "") + "Все", callback_data="adcrm:all:0"),
        ],
    ]
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="←", callback_data=f"adcrm:{current}:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{max(total_pages, 1)}", callback_data="adcrmnoop"))
    if page + 1 < total_pages:
        nav.append(InlineKeyboardButton(text="→", callback_data=f"adcrm:{current}:{page + 1}"))
    rows.append(nav)
    rows.append([InlineKeyboardButton(text="📊 Статистика", callback_data="adcrmstats")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _query_leads(filter_name: str, page: int) -> tuple[list[Submission], int]:
    conditions = [Submission.type == "ad"]
    if filter_name == "active":
        conditions.append(Submission.status.in_(ACTIVE_STATUSES))
    elif filter_name != "all":
        conditions.append(Submission.status == filter_name)

    async with get_session() as session:
        count_result = await session.execute(select(func.count(Submission.id)).where(*conditions))
        total = int(count_result.scalar() or 0)
        result = await session.execute(
            select(Submission)
            .where(*conditions)
            .order_by(Submission.created_at.desc(), Submission.id.desc())
            .offset(page * PAGE_SIZE)
            .limit(PAGE_SIZE)
        )
        leads = list(result.scalars())
    return leads, total


async def _meta_values(submission_id: int) -> dict[str, str]:
    prefix = f"ad:{submission_id}:"
    async with get_session() as session:
        result = await session.execute(select(Meta).where(Meta.key.like(f"{prefix}%")))
        rows = list(result.scalars())
    return {row.key.removeprefix(prefix): row.value for row in rows}


def _format_dt(value: str | None) -> str | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return dt.strftime("%d.%m %H:%M")


async def _lead_text(submission: Submission) -> str:
    meta = await _meta_values(submission.id)
    author = f"@{submission.username}" if submission.username else f"id {submission.user_id}"
    lines = [
        f"<b>Заявка №{submission.id}</b> · {STATUS_LABELS.get(submission.status, submission.status)}",
        f"👤 {html.escape(author)}",
        f"📅 {submission.created_at.strftime('%d.%m.%Y %H:%M') if submission.created_at else '—'}",
    ]
    contacted = _format_dt(meta.get("contacted_at"))
    followed = _format_dt(meta.get("followed_at"))
    if contacted:
        lines.append(f"📤 Первый ответ: {contacted}")
    if followed:
        lines.append(f"🔔 Последний follow-up: {followed}")
    if submission.text:
        text = submission.text.strip()
        if len(text) > 700:
            text = text[:697] + "…"
        lines.extend(["", html.escape(text)])
    return "\n".join(lines)


async def _render_dashboard(message: Message, filter_name: str = "active", page: int = 0) -> None:
    leads, total = await _query_leads(filter_name, page)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = min(page, total_pages - 1)
    if not leads and page > 0:
        leads, total = await _query_leads(filter_name, 0)
        page = 0

    title = FILTER_LABELS.get(filter_name, filter_name)
    await message.answer(
        f"📋 <b>CRM рекламы · {title}</b>\nНайдено заявок: <b>{total}</b>",
        reply_markup=_filters_keyboard(filter_name, page, total_pages),
    )
    if not leads:
        await message.answer("В этом разделе пока нет заявок.")
        return
    for lead in leads:
        await message.answer(await _lead_text(lead), reply_markup=_lead_keyboard(lead.id))


@router.message(Command("adleads"))
async def ad_leads(message: Message) -> None:
    if message.from_user is None or not _is_admin(message.from_user.id):
        return
    await _render_dashboard(message)


@router.message(Command("adstats"))
async def ad_stats_command(message: Message) -> None:
    if message.from_user is None or not _is_admin(message.from_user.id):
        return
    await message.answer(await _stats_text())


@router.callback_query(F.data.startswith("adcrm:"))
async def ad_crm_filter(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Только для администраторов", show_alert=True)
        return
    try:
        _, filter_name, raw_page = callback.data.split(":", 2)
        page = max(0, int(raw_page))
    except (ValueError, IndexError):
        await callback.answer("Некорректная команда", show_alert=True)
        return
    if filter_name not in FILTER_LABELS:
        await callback.answer("Неизвестный фильтр", show_alert=True)
        return
    await callback.answer()
    await _render_dashboard(callback.message, filter_name, page)


@router.callback_query(F.data == "adcrmnoop")
async def ad_crm_noop(callback: CallbackQuery) -> None:
    await callback.answer()


async def _stats_text() -> str:
    now = datetime.utcnow()
    month_start = datetime(now.year, now.month, 1)
    week_start = now - timedelta(days=7)
    async with get_session() as session:
        result = await session.execute(select(Submission).where(Submission.type == "ad"))
        leads = list(result.scalars())

    counts = Counter(lead.status for lead in leads)
    month = [lead for lead in leads if lead.created_at and lead.created_at >= month_start]
    week = [lead for lead in leads if lead.created_at and lead.created_at >= week_start]
    paid = counts.get("paid", 0)
    decided = paid + counts.get("rejected", 0) + counts.get("closed", 0)
    conversion = round(paid / decided * 100) if decided else 0
    return (
        "📊 <b>Статистика рекламы</b>\n\n"
        f"Всего заявок: <b>{len(leads)}</b>\n"
        f"За 7 дней: <b>{len(week)}</b>\n"
        f"За текущий месяц: <b>{len(month)}</b>\n\n"
        f"🆕 Новые: <b>{counts.get('pending', 0)}</b>\n"
        f"📤 Ответ отправлен: <b>{counts.get('contacted', 0)}</b>\n"
        f"⏳ Ожидают оплату: <b>{counts.get('awaiting_payment', 0)}</b>\n"
        f"✅ Оплачено: <b>{paid}</b>\n"
        f"❌ Отказ: <b>{counts.get('rejected', 0)}</b>\n\n"
        f"Конверсия среди закрытых решений: <b>{conversion}%</b>"
    )


@router.callback_query(F.data == "adcrmstats")
async def ad_crm_stats(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Только для администраторов", show_alert=True)
        return
    await callback.answer()
    await callback.message.answer(await _stats_text())
