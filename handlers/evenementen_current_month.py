"""Current-month policy for the cached evenementen.nl agenda.

/afisha always shows the current calendar month. The monthly cache is now built
directly from evenementen.nl, without Anthropic/Claude, so the agenda does not
depend on AI credits and does not generate AI API costs.
"""
from __future__ import annotations

import asyncio
import html as html_lib
import logging
from datetime import date, datetime

from sqlalchemy import delete, select

from database.db import get_session
from database.models import DiscoveredEvent
from handlers import evenementen_catalog as base
from handlers import events
from handlers.evenementen_direct_source import build_current_month_once

log = logging.getLogger(__name__)


def _current_month() -> date:
    today = datetime.now(base.TZ).date()
    return date(today.year, today.month, 1)


def _sections_for(month: date) -> dict[str, tuple[str, str]]:
    last = base._target_month_end(month)
    sections: dict[str, tuple[str, str]] = {}
    for short, slug, label in base.SITE_CATEGORIES:
        key = f"m{month:%y%m}_{short}"
        title = f"📅 {base.MONTH_NAMES[month.month]} · {label.split(' ', 1)[1]}"
        marker = f"evenementen|{slug}|{month.isoformat()}|{last.isoformat()}|{label}"
        sections[key] = (title, marker)
    return sections


def _current_sections() -> dict[str, tuple[str, str]]:
    return _sections_for(_current_month())


async def _purge_keep_current_and_next() -> None:
    """Drop stale/legacy rows but preserve current and next month's cache."""
    current = _current_month()
    next_month = base._add_months(current, 1)
    keep_keys = [*_sections_for(current), *_sections_for(next_month)]
    now = datetime.utcnow()
    async with get_session() as session:
        await session.execute(
            delete(DiscoveredEvent).where(
                (DiscoveredEvent.source_url == "")
                | (~DiscoveredEvent.source_url.contains(base.SOURCE_DOMAIN))
                | (~DiscoveredEvent.section_key.in_(keep_keys))
                | (DiscoveredEvent.ends_at < now)
            )
        )
        await session.commit()


async def show_current_catalog_section(message, section_key: str, uid: int) -> None:
    """Open one current-month section without any AI request on user click."""
    del uid
    if section_key not in events.AFISHA_SECTIONS:
        await message.answer("Этот раздел уже относится к старой афише. Открой /afisha заново.")
        return
    cached = await events._auto_batch("Nederland", 999, section_key)
    if not cached:
        await message.answer(
            "Афиша текущего месяца сейчас обновляется напрямую с evenementen.nl. "
            "Попробуй открыть этот раздел ещё раз через несколько секунд.",
            reply_markup=events.main_menu(),
        )
        return
    batch, rows = cached
    await message.answer(
        f"🎭 <b>{html_lib.escape(events.AFISHA_SECTIONS[section_key][0])}</b>\n"
        f"Мероприятий: <b>{len(rows)}</b>. Листай кнопками под карточкой 👇",
        reply_markup=events.main_menu(),
    )
    await events._show_auto_card(message, batch, 0)


async def show_current_cached_afisha(
    message,
    city: str,
    radius_km: int,
    uid: int,
    *,
    section_key: str = "nearby",
    section_label: str = "",
) -> None:
    """Personalised view from the current-month shared cache, without AI calls."""
    del uid, section_label
    if section_key != "nearby":
        await show_current_catalog_section(message, section_key, 0)
        return

    canonical = base.CITY_TO_PROVINCE.get((city or "").casefold(), (city, ""))[0]
    nearby = base.cities_within_radius(canonical, radius_km, limit=16)
    keys = list(events.AFISHA_SECTIONS)
    now = datetime.utcnow()
    async with get_session() as session:
        rows = list((await session.scalars(
            select(DiscoveredEvent).where(
                DiscoveredEvent.query_city == "Nederland",
                DiscoveredEvent.radius_km == 999,
                DiscoveredEvent.section_key.in_(keys),
                DiscoveredEvent.city.in_(nearby),
                DiscoveredEvent.ends_at > now,
                DiscoveredEvent.expires_at > now,
            ).order_by(DiscoveredEvent.starts_at, DiscoveredEvent.id)
        )).all())

    unique: list[DiscoveredEvent] = []
    seen: set[str] = set()
    for row in rows:
        key = (row.source_url or row.link or f"{row.title}|{row.event_date}").casefold()
        if key not in seen:
            seen.add(key)
            unique.append(row)

    if not unique:
        await message.answer(
            f"В афише текущего месяца пока нет мероприятий для <b>{html_lib.escape(city)}</b> "
            f"в выбранном радиусе.",
            reply_markup=events.main_menu(),
        )
        return

    month = _current_month()
    await message.answer(
        f"🎭 <b>Афиша · {html_lib.escape(city)}</b>\n"
        f"{base.MONTH_NAMES[month.month]} · найдено: <b>{len(unique)}</b>. Показываю ближайшие события 👇",
        reply_markup=events.main_menu(),
    )
    for row in unique[:6]:
        text_value = base._evenementen_event_text(row)
        kb = events._auto_event_kb(row.batch_key, 0, 1, row)
        if row.photo_url:
            try:
                await message.answer_photo(row.photo_url, caption=text_value, reply_markup=kb)
                continue
            except Exception:  # noqa: BLE001
                pass
        await message.answer(text_value, reply_markup=kb, disable_web_page_preview=True)


def _install_patch() -> None:
    # Keep the UI on the current month. The actual monthly build is handled by
    # evenementen_direct_source and never calls Anthropic.
    base._target_month = _current_month
    base._catalog_sections = _current_sections
    base._purge_non_target_catalog = _purge_keep_current_and_next
    base.show_monthly_catalog_section = show_current_catalog_section
    base.show_monthly_cached_afisha = show_current_cached_afisha


def install_evenementen_source() -> None:
    _install_patch()
    base.install_evenementen_source()


async def evenementen_catalog_loop(bot) -> None:
    """Build the current month directly once, then sleep until month rollover."""
    del bot
    _install_patch()
    await asyncio.sleep(8)
    while True:
        try:
            await build_current_month_once()
        except Exception as exc:  # noqa: BLE001
            log.exception("Direct monthly agenda build failed: %s", exc)
        sleep_for = base._seconds_until_next_month()
        log.info("Current-month agenda checked; next run in %.1f h", sleep_for / 3600)
        await asyncio.sleep(sleep_for)
