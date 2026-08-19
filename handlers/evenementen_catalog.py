"""Источник автоматической афиши: evenementen.nl.

Модуль не заменяет платные EventListing от организаторов. Он заменяет только
автоматически найденный каталог DiscoveredEvent: старый кэш из разных источников
удаляется, а общая и персональная афиша собираются через evenementen.nl.
"""
from __future__ import annotations

import asyncio
import logging
from calendar import monthrange
from datetime import date, datetime
from urllib.parse import urlparse

from sqlalchemy import delete, or_

import config
from database.db import get_session
from database.models import DiscoveredEvent
from handlers import events
from utils.ai import (
    _create_with_server_tool_continuation,
    _extract_text_and_sources,
    _get_client,
    _web_search_errors,
    _web_search_tool,
    parse_event_cards,
)

log = logging.getLogger(__name__)

SOURCE_DOMAIN = "evenementen.nl"
SOURCE_NAME = "Evenementen.nl"

MONTH_NAMES = {
    1: "Январь", 2: "Февраль", 3: "Март", 4: "Апрель",
    5: "Май", 6: "Июнь", 7: "Июль", 8: "Август",
    9: "Сентябрь", 10: "Октябрь", 11: "Ноябрь", 12: "Декабрь",
}

# Направления ровно по основным разделам evenementen.nl.
SITE_CATEGORIES = (
    ("fest", "festivals", "🎪 Фестивали"),
    ("concert", "concerten_theater", "🎵 Концерты и театр"),
    ("events", "events", "🎭 События"),
    ("sport", "sportevenementen", "🏃 Спорт"),
    ("kermis", "kermis", "🎡 Kermis"),
    ("market", "markten", "🛍 Маркеты"),
)


def _month_start(year: int, month: int) -> date:
    return date(year, month, 1)


def _add_months(day: date, count: int) -> date:
    value = day.year * 12 + (day.month - 1) + count
    return date(value // 12, value % 12 + 1, 1)


def _catalog_sections(month_count: int = 5) -> dict[str, tuple[str, str]]:
    """Текущий месяц + четыре следующих, каждый разбит по направлениям."""
    first = _month_start(date.today().year, date.today().month)
    sections: dict[str, tuple[str, str]] = {}
    for offset in range(month_count):
        month = _add_months(first, offset)
        last = date(month.year, month.month, monthrange(month.year, month.month)[1])
        for short, slug, label in SITE_CATEGORIES:
            # section_key <= 24 символов, потому используем компактный ключ.
            key = f"m{month:%y%m}_{short}"
            title = f"📅 {MONTH_NAMES[month.month]} · {label.split(' ', 1)[1]}"
            marker = (
                f"evenementen|{slug}|{month.isoformat()}|{last.isoformat()}|{label}"
            )
            sections[key] = (title, marker)
    return sections


def install_evenementen_source() -> None:
    """Подменяет источник и разделы существующего обработчика афиши."""
    events.AFISHA_SECTIONS = _catalog_sections()
    events.ai_event_cards = evenementen_event_cards


def _is_evenementen_url(value: str) -> bool:
    host = urlparse(value or "").netloc.lower().removeprefix("www.")
    return host == SOURCE_DOMAIN or host.endswith("." + SOURCE_DOMAIN)


def _section_filter(section_label: str) -> tuple[str, str, str, str]:
    if not section_label.startswith("evenementen|"):
        return "", "", "", ""
    parts = section_label.split("|", 4)
    if len(parts) != 5:
        return "", "", "", ""
    return parts[1], parts[2], parts[3], parts[4]


async def evenementen_event_cards(
    city: str,
    radius_km: int = 25,
    search_cities: list[str] | None = None,
    *,
    section_label: str = "",
    horizon_days: int = 90,
) -> list[dict[str, str]]:
    """Ищет события только на evenementen.nl и возвращает карточки старого формата."""
    slug, date_from, date_till, category_label = _section_filter(section_label)
    today = date.today()
    if not date_from:
        date_from = today.isoformat()
        # Для персональной афиши сохраняем текущий горизонт, но источник один.
        end = today.fromordinal(today.toordinal() + max(7, min(horizon_days, 120)))
        date_till = end.isoformat()

    places = search_cities or [city]
    if radius_km == 999:
        place_text = "Nederland"
    else:
        place_text = ", ".join(places[:8])

    category_url = (
        f"https://evenementen.nl/zoeken/{slug}"
        if slug else "https://evenementen.nl/"
    )
    category_rule = (
        f"Gebruik alleen de categorie {category_label} ({category_url}). "
        if slug else "Gebruik alle relevante evenementcategorieën op evenementen.nl. "
    )

    system = (
        "Je maakt een actuele Nederlandse evenementenkalender. Gebruik VERPLICHT web search, "
        "maar uitsluitend evenementen.nl. Gebruik geen Eventbrite, Ticketmaster, gemeentelijke "
        "sites, VVV-sites of andere bronnen. "
        f"{category_rule}"
        f"Selecteer evenementen die plaatsvinden tussen {date_from} en {date_till}. "
        f"Geografisch gebied: {place_text}. "
        "Neem alleen echte evenementen met een concrete datum op. Laat doorlopende attracties, "
        "algemene museumbezoeken, permanente wandelroutes en items zonder bruikbare datum weg. "
        "Open waar nodig de detailpagina op evenementen.nl om datum, locatie en omschrijving te controleren. "
        "Geef 8 tot 12 verschillende bruikbare resultaten als die beschikbaar zijn. "
        "Alle source_url- en url-waarden moeten naar een concrete evenementen.nl/events/... pagina wijzen. "
        "Gebruik geen verzonnen links. Geef uitsluitend blokken in dit formaat, zonder markdown of uitleg:\n"
        "<event><title>Naam</title><start>YYYY-MM-DD of ISO 8601</start>"
        "<end>YYYY-MM-DD of ISO 8601 indien bekend</end>"
        "<date>Leesbare datum/tijd</date><venue>Locatie</venue><city>Plaats</city>"
        "<description>Korte concrete omschrijving in het Russisch</description>"
        "<source_url>https://evenementen.nl/events/...</source_url>"
        "<ticket_url></ticket_url><source>Evenementen.nl</source>"
        "<territory>Nederland</territory></event>"
    )
    prompt = (
        f"Zoek op evenementen.nl naar evenementen voor {place_text}, van {date_from} tot {date_till}. "
        f"Categorie: {category_label or 'alle categorieën'}. Begin bij {category_url}."
    )
    kwargs = dict(
        model=config.AI_CHAT_MODEL,
        max_tokens=4200,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    tools = _web_search_tool([SOURCE_DOMAIN], max_uses=5)
    if tools:
        kwargs["tools"] = tools
    try:
        response = await _create_with_server_tool_continuation(
            _get_client(), max_continuations=2, **kwargs
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("Evenementen.nl zoekopdracht mislukt voor %s: %s", section_label or city, exc)
        return []

    errors = _web_search_errors(response)
    if errors:
        log.warning("Evenementen.nl web search fouten: %s", ", ".join(errors))
    text, _ = _extract_text_and_sources(response)
    cards = parse_event_cards(text)

    clean: list[dict[str, str]] = []
    seen: set[str] = set()
    for card in cards:
        url = card.get("source_url") or card.get("url") or ""
        if not _is_evenementen_url(url):
            continue
        if "/events/" not in url:
            continue
        key = url.casefold().rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        card["url"] = url
        card["source_url"] = url
        card["source"] = SOURCE_NAME
        card["ticket_url"] = ""
        card["territory"] = "Nederland"
        clean.append(card)
    return clean[:12]


async def _purge_old_automatic_afisha() -> None:
    """Удаляет старую автоафишу из других источников и просроченный кэш."""
    now = datetime.utcnow()
    async with get_session() as session:
        await session.execute(
            delete(DiscoveredEvent).where(
                or_(
                    DiscoveredEvent.source_url == "",
                    ~DiscoveredEvent.source_url.contains(SOURCE_DOMAIN),
                    DiscoveredEvent.ends_at < now,
                )
            )
        )
        await session.commit()


async def evenementen_catalog_loop(bot) -> None:
    """Пересобирает месяцы/направления и далее поддерживает их в актуальном виде."""
    del bot  # сигнатура совпадает с остальными фоновыми задачами
    install_evenementen_source()
    await asyncio.sleep(8)
    await _purge_old_automatic_afisha()

    while True:
        # Месяцы меняются со временем, поэтому пересчитываем разделы на каждом цикле.
        events.AFISHA_SECTIONS = _catalog_sections()
        for section_key, (_, search_label) in events.AFISHA_SECTIONS.items():
            try:
                if not await events._auto_batch("Nederland", 999, section_key):
                    await events.ensure_auto_afisha(
                        "Nederland",
                        999,
                        config.ADMIN_IDS[0] if config.ADMIN_IDS else 0,
                        section_key=section_key,
                        section_label=search_label,
                        horizon_days=120,
                        force=True,
                    )
            except Exception as exc:  # noqa: BLE001
                log.warning("Не удалось собрать %s с evenementen.nl: %s", section_key, exc)
            # Не создаём очередь из десятков одновременных web-search запросов.
            await asyncio.sleep(12)
        await _purge_old_automatic_afisha()
        await asyncio.sleep(6 * 3600)


# Патч нужен уже при импорте: пользователь может открыть /afisha раньше первого цикла.
install_evenementen_source()
