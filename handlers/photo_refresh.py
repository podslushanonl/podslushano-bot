"""Патч фотографий месячной афиши без дополнительных AI-запросов.

Версия v3 повторно проходит по текущей месячной афише. Для каждой карточки
официальный сайт сначала ищется на Evenementen.nl, а при отсутствии ссылки —
обычным HTML-поиском по названию/городу/году. Claude/Anthropic не используется.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select

from database.db import get_session
from database.models import DiscoveredEvent, Meta
from handlers import evenementen_catalog, events
from utils.event_photo import resolve_official_event_media

log = logging.getLogger(__name__)

PHOTO_VERSION = "official-photo-v3"


async def _official_fetch_page_image(url: str) -> str | None:
    """Не выбираем фото без названия события: месячный refresh сделает это точнее."""
    del url
    return None


def _event_kb(batch: str, idx: int, total: int, ev: DiscoveredEvent) -> InlineKeyboardMarkup:
    """Показывает отдельно официальный сайт и агрегатор-источник."""
    rows: list[list[InlineKeyboardButton]] = []
    source = events._valid_url(ev.source_url)
    official = events._valid_url(ev.link)
    tickets = events._valid_url(ev.ticket_url)
    maps = events._maps_url(ev.venue, ev.city, ev.territory)

    actions: list[InlineKeyboardButton] = []
    if official and official != source:
        actions.append(InlineKeyboardButton(text="🌐 Сайт мероприятия", url=official))
    if source:
        actions.append(InlineKeyboardButton(text="ℹ️ Источник", url=source))
    if actions:
        rows.append(actions)
    if tickets and tickets not in {source, official}:
        rows.append([InlineKeyboardButton(text="🎟 Билеты", url=tickets)])
    if maps:
        rows.append([InlineKeyboardButton(text="📍 Google Maps", url=maps)])
    if total > 1:
        rows.append([
            InlineKeyboardButton(text="◀️", callback_data=f"aev:{batch}:{(idx - 1) % total}"),
            InlineKeyboardButton(text=f"{idx + 1}/{total}", callback_data="aev_noop"),
            InlineKeyboardButton(text="▶️", callback_data=f"aev:{batch}:{(idx + 1) % total}"),
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _refresh_existing_month_photos_once() -> None:
    """Один раз для v3 дозаполняет официальные сайты и реальные фото всего месяца."""
    month = evenementen_catalog._target_month()
    marker_key = f"event-photo-version:{month:%Y-%m}"

    async with get_session() as session:
        marker = await session.get(Meta, marker_key)
        if marker and marker.value == PHOTO_VERSION:
            return
        keys = list(evenementen_catalog._catalog_sections())
        rows = list((await session.scalars(
            select(DiscoveredEvent).where(
                DiscoveredEvent.query_city == "Nederland",
                DiscoveredEvent.radius_km == 999,
                DiscoveredEvent.section_key.in_(keys),
                DiscoveredEvent.source_url.contains("evenementen.nl"),
                DiscoveredEvent.ends_at > datetime.utcnow(),
            ).order_by(DiscoveredEvent.id)
        )).all())

    if not rows:
        # Афиша могла ещё не успеть собраться. Не ставим marker — попробуем позже.
        return

    # Ограничиваем параллелизм: бесплатный fallback делает несколько обычных HTTP-запросов.
    semaphore = asyncio.Semaphore(3)

    async def resolve(row: DiscoveredEvent):
        async with semaphore:
            official, image = await resolve_official_event_media(
                row.source_url,
                row.title,
                row.city or "",
                row.event_date or "",
            )
            return row.id, official, image

    results = await asyncio.gather(*(resolve(row) for row in rows))
    found_sites = 0
    found_images = 0
    unresolved = 0
    async with get_session() as session:
        for row_id, official, image in results:
            row = await session.get(DiscoveredEvent, row_id)
            if not row:
                continue
            # Старое/сомнительное фото удаляем всегда; показываем только новое подтверждённое.
            row.photo_url = image or ""
            if official:
                row.link = official
                found_sites += 1
            else:
                # Не оставляем Evenementen.nl в поле официального сайта.
                if row.link and "evenementen.nl" in row.link.casefold():
                    row.link = ""
            if image:
                found_images += 1
            if not official and not image:
                unresolved += 1

        marker = await session.get(Meta, marker_key)
        if marker:
            marker.value = PHOTO_VERSION
        else:
            session.add(Meta(key=marker_key, value=PHOTO_VERSION))
        await session.commit()

    log.info(
        "Official event photo refresh v3: rows=%d official_sites=%d photos=%d unresolved=%d",
        len(rows), found_sites, found_images, unresolved,
    )


# На первичной месячной записи не подставляем случайные картинки агрегатора.
# Полный v3 refresh после сборки использует название/город/дату и находит медиа точнее.
events.fetch_page_image = _official_fetch_page_image
events._auto_event_kb = _event_kb

_original_catalog_loop = evenementen_catalog.evenementen_catalog_loop


async def _catalog_loop_with_photo_refresh(bot) -> None:
    await asyncio.sleep(4)
    await _refresh_existing_month_photos_once()
    task = asyncio.create_task(_original_catalog_loop(bot))
    # Если месячная афиша создавалась с нуля, даём ей закончить и запускаем v3 ещё раз.
    await asyncio.sleep(120)
    await _refresh_existing_month_photos_once()
    await task


evenementen_catalog.evenementen_catalog_loop = _catalog_loop_with_photo_refresh
