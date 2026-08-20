"""Источник автоматической афиши: evenementen.nl.

Модуль не заменяет платные EventListing от организаторов. Он заменяет только
автоматически найденный каталог DiscoveredEvent: старый кэш из разных источников
удаляется, а общая и персональная афиша собираются через evenementen.nl.
"""
from __future__ import annotations

import asyncio
import logging
import re
from calendar import monthrange
from datetime import date, datetime, timedelta
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
from utils.webpage import fetch_page_text

log = logging.getLogger(__name__)

SOURCE_DOMAIN = "evenementen.nl"
SOURCE_NAME = "Evenementen.nl"

MONTH_NAMES = {
    1: "Январь", 2: "Февраль", 3: "Март", 4: "Апрель",
    5: "Май", 6: "Июнь", 7: "Июль", 8: "Август",
    9: "Сентябрь", 10: "Октябрь", 11: "Ноябрь", 12: "Декабрь",
}

SITE_CATEGORIES = (
    ("fest", "festivals", "🎪 Фестивали"),
    ("concert", "concerten_theater", "🎵 Концерты и театр"),
    ("events", "events", "🎭 События"),
    ("sport", "sportevenementen", "🏃 Спорт"),
    ("kermis", "kermis", "🎡 Kermis"),
    ("market", "markten", "🛍 Маркеты"),
)


def _add_months(day: date, count: int) -> date:
    value = day.year * 12 + (day.month - 1) + count
    return date(value // 12, value % 12 + 1, 1)


def _catalog_sections(month_count: int = 5) -> dict[str, tuple[str, str]]:
    """Текущий месяц + четыре следующих, каждый разбит по направлениям."""
    first = date(date.today().year, date.today().month, 1)
    sections: dict[str, tuple[str, str]] = {}
    for offset in range(month_count):
        month = _add_months(first, offset)
        last = date(month.year, month.month, monthrange(month.year, month.month)[1])
        for short, slug, label in SITE_CATEGORIES:
            key = f"m{month:%y%m}_{short}"
            title = f"📅 {MONTH_NAMES[month.month]} · {label.split(' ', 1)[1]}"
            marker = f"evenementen|{slug}|{month.isoformat()}|{last.isoformat()}|{label}"
            sections[key] = (title, marker)
    return sections


def install_evenementen_source() -> None:
    """Подменяет источник и разделы существующего обработчика афиши."""
    events.AFISHA_SECTIONS = _catalog_sections()
    events.ai_event_cards = evenementen_event_cards


def _is_evenementen_url(value: str) -> bool:
    parsed = urlparse(value or "")
    host = parsed.netloc.lower().removeprefix("www.")
    return (host == SOURCE_DOMAIN or host.endswith("." + SOURCE_DOMAIN)) and "/events/" in parsed.path


def _normalise_url(value: str) -> str:
    parsed = urlparse(value or "")
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower().removeprefix('www.')}{parsed.path.rstrip('/')}"


def _section_filter(section_label: str) -> tuple[str, str, str, str]:
    if not section_label.startswith("evenementen|"):
        return "", "", "", ""
    parts = section_label.split("|", 4)
    if len(parts) != 5:
        return "", "", "", ""
    return parts[1], parts[2], parts[3], parts[4]


def _calendar_day(raw: str) -> date | None:
    """Берёт календарную дату из исходного ISO до преобразования в UTC."""
    value = (raw or "").strip()
    if len(value) < 10:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _card_in_period(card: dict, date_from: str, date_till: str) -> bool:
    """Не даёт положить событие в неправильный месячный раздел."""
    try:
        lower = date.fromisoformat(date_from)
        upper = date.fromisoformat(date_till)
    except ValueError:
        return False
    starts = _calendar_day(str(card.get("start") or ""))
    ends = _calendar_day(str(card.get("end") or "")) or starts
    if starts is None:
        return False
    return starts <= upper and ends >= lower


def _has_russian(text: str) -> bool:
    return bool(re.search(r"[А-Яа-яЁё]", text or ""))


async def _translate_description(card: dict) -> str:
    """Страховка: если поиск вернул описание не по-русски, переводим его отдельно."""
    original = (card.get("description") or "").strip()
    if not original or _has_russian(original):
        return original
    try:
        response = await _get_client().messages.create(
            model=config.AI_CHAT_MODEL,
            max_tokens=500,
            system=(
                "Переведи описание мероприятия на естественный русский язык. "
                "Название мероприятия не переводи и не добавляй. Сохрани все факты, даты, "
                "цены и возрастные ограничения. Ничего не придумывай. Ответь только переводом."
            ),
            messages=[{"role": "user", "content": original[:1800]}],
        )
        translated, _ = _extract_text_and_sources(response)
        return translated.strip() or original
    except Exception as exc:  # noqa: BLE001
        log.info("Не удалось перевести описание события: %s", exc)
        return original


async def _verified_evenementen_page(url: str) -> bool:
    """Проверяет, что сгенерированная карточкой ссылка реально открывается на evenementen.nl."""
    if not _is_evenementen_url(url):
        return False
    try:
        page = await fetch_page_text(url, max_chars=1200)
    except Exception as exc:  # noqa: BLE001
        log.info("Не удалось проверить страницу evenementen.nl %s: %s", url, exc)
        return False
    return page is not None


async def evenementen_event_cards(
    city: str,
    radius_km: int = 25,
    search_cities: list[str] | None = None,
    *,
    section_label: str = "",
    horizon_days: int = 90,
) -> list[dict[str, str]]:
    """Ищет реальные события только на evenementen.nl."""
    slug, date_from, date_till, category_label = _section_filter(section_label)
    today = date.today()
    if not date_from:
        date_from = today.isoformat()
        date_till = (today + timedelta(days=max(7, min(horizon_days, 120)))).isoformat()

    places = search_cities or [city]
    place_text = "Nederland" if radius_km == 999 else ", ".join(places[:8])
    category_url = f"https://evenementen.nl/zoeken/{slug}" if slug else "https://evenementen.nl/"
    category_rule = (
        f"Gebruik alleen de categorie {category_label} ({category_url}). "
        if slug else "Gebruik alle relevante evenementcategorieën op evenementen.nl. "
    )

    system = (
        "Je maakt een actuele evenementenkalender voor Russischtalige inwoners van Nederland. "
        "Gebruik VERPLICHT web search, maar uitsluitend evenementen.nl. Gebruik geen andere bronnen. "
        f"{category_rule}"
        f"Selecteer evenementen tussen {date_from} en {date_till}. Gebied: {place_text}. "
        "Neem alleen echte evenementen met een concrete datum op. Laat permanente attracties, "
        "doorlopende activiteiten en items zonder bruikbare datum weg. Open elke detailpagina om "
        "datum, locatie, inhoud en eventuele ticketprijs te controleren. Geef 8 tot 12 resultaten indien beschikbaar. "
        "BELANGRIJK VOOR DE TEKST: title moet exact de oorspronkelijke naam van het evenement behouden, "
        "in de oorspronkelijke taal. date, venue en city mogen de officiële lokale schrijfwijze behouden. "
        "description moet VOLLEDIG IN HET RUSSISCH zijn: 3 tot 5 concrete zinnen over wat er gebeurt, "
        "programma/formaat, voor wie het interessant is en relevante praktische details. Vertaal geen eventnaam. "
        "Als op evenementen.nl een ticketprijs staat, voeg aan het einde van description een aparte zin toe: "
        "«🎟 Билеты: €…». Als expliciet staat dat toegang gratis is, schrijf «🎟 Вход бесплатный». "
        "Als prijs niet staat, verzin hem niet en voeg geen prijsregel toe. "
        "Elke source_url moet een concrete evenementen.nl/events/... pagina zijn die je in web search hebt gevonden. "
        "Verzin geen links. Geef uitsluitend blokken in dit formaat, zonder markdown en zonder Nederlandse beschrijving:\n"
        "<event><title>Originele naam</title><start>YYYY-MM-DD of ISO 8601</start>"
        "<end>YYYY-MM-DD of ISO 8601 indien bekend</end><date>Leesbare datum/tijd</date>"
        "<venue>Locatie</venue><city>Plaats</city>"
        "<description>Подробное описание только на русском языке. Цена, если она есть.</description>"
        "<source_url>https://evenementen.nl/events/...</source_url>"
        "<ticket_url></ticket_url><source>Evenementen.nl</source>"
        "<territory>Nederland</territory></event>"
    )
    kwargs = dict(
        model=config.AI_CHAT_MODEL,
        max_tokens=5200,
        system=system,
        messages=[{
            "role": "user",
            "content": (
                f"Zoek op evenementen.nl naar evenementen voor {place_text}, van {date_from} tot {date_till}. "
                f"Categorie: {category_label or 'alle categorieën'}. Begin bij {category_url}. "
                "Controleer per evenement ook of er op de pagina een toegangsprijs of gratis toegang wordt genoemd."
            ),
        }],
    )
    tools = _web_search_tool([SOURCE_DOMAIN], max_uses=7)
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
    text, sources = _extract_text_and_sources(response)
    evidence = {_normalise_url(url) for url in sources if _is_evenementen_url(url)}
    cards = parse_event_cards(text)

    candidates: list[tuple[dict, str, str]] = []
    seen: set[str] = set()
    for card in cards:
        url = card.get("source_url") or card.get("url") or ""
        normalised = _normalise_url(url)
        if not _is_evenementen_url(url) or not _card_in_period(card, date_from, date_till):
            continue
        if not normalised or normalised in seen:
            continue
        seen.add(normalised)
        candidates.append((card, url, normalised))

    semaphore = asyncio.Semaphore(4)

    async def verified(item: tuple[dict, str, str]) -> tuple[dict, str] | None:
        card, url, normalised = item
        if normalised in evidence:
            return card, url
        async with semaphore:
            return (card, url) if await _verified_evenementen_page(url) else None

    verified_rows = await asyncio.gather(*(verified(item) for item in candidates))

    clean: list[dict[str, str]] = []
    for item in verified_rows:
        if item is None:
            continue
        card, url = item
        card["description"] = await _translate_description(card)
        card["url"] = url
        card["source_url"] = url
        card["source"] = SOURCE_NAME
        card["ticket_url"] = ""
        card["territory"] = "Nederland"
        clean.append(card)
    log.info(
        "Evenementen.nl %s: parsed=%d candidates=%d verified=%d sources=%d",
        section_label or city,
        len(cards),
        len(candidates),
        len(clean),
        len(evidence),
    )
    return clean[:12]


async def _purge_old_automatic_afisha() -> None:
    """Удаляет старую автоафишу из других источников и прошедшие карточки."""
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


async def _clear_segment(section_key: str) -> None:
    """Удаляет текущий кэш сегмента перед обязательной 6-часовой пересборкой."""
    async with get_session() as session:
        await session.execute(
            delete(DiscoveredEvent).where(
                DiscoveredEvent.query_city == "Nederland",
                DiscoveredEvent.radius_km == 999,
                DiscoveredEvent.section_key == section_key,
            )
        )
        await session.commit()


async def evenementen_catalog_loop(bot) -> None:
    """Пересобирает месяцы/направления и далее поддерживает их в актуальном виде."""
    del bot
    await asyncio.sleep(8)
    await _purge_old_automatic_afisha()

    while True:
        events.AFISHA_SECTIONS = _catalog_sections()
        for section_key, (_, search_label) in events.AFISHA_SECTIONS.items():
            try:
                await _clear_segment(section_key)
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
            await asyncio.sleep(12)
        await _purge_old_automatic_afisha()
        await asyncio.sleep(6 * 3600)
