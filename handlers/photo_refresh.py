"""Патч фотографий месячной афиши без дополнительных AI-запросов.

При первом запуске версии v2 существующие карточки Evenementen.nl получают
официальный сайт и фотографию с этого сайта обычными HTTP-запросами. Результат
сохраняется в БД и повторно на каждом restart не пересчитывается.
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

PHOTO_VERSION = "official-photo-v2"


async def _official_fetch_page_image(url: str) -> str | None:
    """Замена старого fetch_page_image для будущих месячных сборок."""
    _, image = await resolve_official_event_media(url, "")
    return image or None


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
    """Один раз заменяет уже сохранённые рекламные/случайные картинки сентября."""
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
        # Афиша могла ещё не успеть собраться. Не ставим marker — попробуем после сборки.
        return

    semaphore = asyncio.Semaphore(4)

    async def resolve(row: DiscoveredEvent):
        async with semaphore:
            official, image = await resolve_official_event_media(row.source_url, row.title)
            return row.id, official, image

    results = await asyncio.gather(*(resolve(row) for row in rows))
    found_sites = 0
    found_images = 0
    async with get_session() as session:
        for row_id, official, image in results:
            row = await session.get(DiscoveredEvent, row_id)
            if not row:
                continue
            # Неправильную старую картинку удаляем в любом случае.
            row.photo_url = image or ""
            if official:
                row.link = official
                found_sites += 1
            if image:
                found_images += 1
        marker = await session.get(Meta, marker_key)
        if marker:
            marker.value = PHOTO_VERSION
        else:
            session.add(Meta(key=marker_key, value=PHOTO_VERSION))
        await session.commit()

    log.info(
        "Official event photo refresh: rows=%d official_sites=%d photos=%d",
        len(rows), found_sites, found_images,
    )


# Будущие карточки также получают фото через официальный сайт, а не через баннер
# агрегатора. Это обычные HTTP-запросы и они не расходуют Anthropic API.
events.fetch_page_image = _official_fetch_page_image
events._auto_event_kb = _event_kb

_original_catalog_loop = evenementen_catalog.evenementen_catalog_loop


async def _catalog_loop_with_photo_refresh(bot) -> None:
    # При уже готовой месячной афише сначала исправляем фото. Если базы ещё нет,
    # обычный monthly loop её соберёт; после него попробуем refresh ещё раз.
    await asyncio.sleep(4)
    await _refresh_existing_month_photos_once()
    task = asyncio.create_task(_original_catalog_loop(bot))
    await asyncio.sleep(90)
    await _refresh_existing_month_photos_once()
    await task


evenementen_catalog.evenementen_catalog_loop = _catalog_loop_with_photo_refresh
