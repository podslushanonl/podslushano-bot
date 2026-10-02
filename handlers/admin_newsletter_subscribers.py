"""Список подписчиков рекламной рассылки в Админ-центре."""
from __future__ import annotations

import html

from aiogram import F
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import func, select

from database.db import get_session
from handlers import admin_center

_PAGE_SIZE = 12


def _source_label(source: str | None) -> str:
    if source == "ads_q4_2026":
        return "Страница /ads"
    return html.escape((source or "—").strip() or "—")


def _keyboard(page: int, total: int) -> InlineKeyboardMarkup:
    total_pages = max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE)
    page = min(max(page, 0), total_pages - 1)
    rows: list[list[InlineKeyboardButton]] = []

    pager: list[InlineKeyboardButton] = []
    if page > 0:
        pager.append(
            InlineKeyboardButton(
                text="← Назад", callback_data=f"ac:adsubs:{page - 1}"
            )
        )
    if page + 1 < total_pages:
        pager.append(
            InlineKeyboardButton(
                text="Дальше →", callback_data=f"ac:adsubs:{page + 1}"
            )
        )
    if pager:
        rows.append(pager)

    rows.append(
        [InlineKeyboardButton(text="↻ Обновить", callback_data=f"ac:adsubs:{page}")]
    )
    rows.append(
        [InlineKeyboardButton(text="🏠 Админ-центр", callback_data="ac:home")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _page(page: int = 0) -> tuple[str, int, int]:
    # Импорт локальный: ad_season_campaign_runtime сам импортирует handlers,
    # поэтому на старте бота здесь нельзя создавать circular import.
    from ad_season_campaign_runtime import AdsNewsletterSubscriber

    async with get_session() as session:
        total = await session.scalar(
            select(func.count(AdsNewsletterSubscriber.id))
        ) or 0
        active = await session.scalar(
            select(func.count(AdsNewsletterSubscriber.id)).where(
                AdsNewsletterSubscriber.is_active.is_(True)
            )
        ) or 0

        total_pages = max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE)
        page = min(max(page, 0), total_pages - 1)
        offset = page * _PAGE_SIZE
        rows = (
            await session.scalars(
                select(AdsNewsletterSubscriber)
                .order_by(
                    AdsNewsletterSubscriber.consent_at.desc(),
                    AdsNewsletterSubscriber.id.desc(),
                )
                .offset(offset)
                .limit(_PAGE_SIZE)
            )
        ).all()

    inactive = max(total - active, 0)
    lines = [
        "📨 <b>Подписчики рекламной рассылки</b>",
        "",
        f"Всего: <b>{total}</b> · активных: <b>{active}</b> · отписались: <b>{inactive}</b>",
    ]

    if not rows:
        lines.extend(["", "Пока подписчиков нет."])
        return "\n".join(lines), total, page

    lines.append("")
    for index, row in enumerate(rows, start=offset + 1):
        email = html.escape(row.email or "—")
        subscribed = row.consent_at.strftime("%d.%m.%Y") if row.consent_at else "—"
        source = _source_label(row.source)
        status = "🟢 активна" if row.is_active else "⚪ отписался"
        lines.extend(
            [
                f"<b>{index}.</b> <code>{email}</code>",
                f"📅 {subscribed} · 🌐 {source} · {status}",
                "",
            ]
        )

    if total_pages > 1:
        lines.append(f"Страница {page + 1} из {total_pages}")
    return "\n".join(lines).rstrip(), total, page


async def show_subscribers(callback: CallbackQuery) -> None:
    page = 0
    parts = (callback.data or "").split(":")
    if len(parts) >= 3:
        try:
            page = max(int(parts[2]), 0)
        except ValueError:
            page = 0

    text, total, page = await _page(page)
    await admin_center._show(callback.message, text, _keyboard(page, total))
    await callback.answer()


def _install_home_button() -> None:
    current = admin_center._home_kb
    if getattr(current, "_newsletter_subscribers_wrapper", False):
        return

    def home_with_newsletter() -> InlineKeyboardMarkup:
        markup = current()
        rows = [list(row) for row in markup.inline_keyboard]
        if not any(
            button.callback_data == "ac:adsubs"
            for row in rows
            for button in row
        ):
            insert_at = max(len(rows) - 2, 0)
            rows.insert(
                insert_at,
                [
                    InlineKeyboardButton(
                        text="📨 Подписчики рассылки", callback_data="ac:adsubs"
                    )
                ],
            )
        return InlineKeyboardMarkup(inline_keyboard=rows)

    home_with_newsletter._newsletter_subscribers_wrapper = True  # type: ignore[attr-defined]
    admin_center._home_kb = home_with_newsletter


_install_home_button()
admin_center.router.callback_query.register(show_subscribers, F.data.startswith("ac:adsubs"))
