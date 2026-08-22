"""Ежемесячная афиша из evenementen.nl.

Главный принцип по расходам: Claude НЕ используется в фоне каждый день и НЕ
запускается при каждом открытии афиши пользователем. Один раз в календарный
месяц бот собирает шесть разделов на ПРЕДСТОЯЩИЙ месяц и дальше весь месяц
показывает сохранённый кэш. Платные EventListing организаторов не затрагиваются.
"""
from __future__ import annotations

import asyncio
import html as html_lib
import json
import logging
import re
from calendar import monthrange
from datetime import date, datetime, time, timedelta
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select, update

import config
from database.db import get_session
from database.models import DiscoveredEvent, Meta
from handlers import events
from utils.ai import (
    _create_with_server_tool_continuation,
    _extract_text_and_sources,
    _get_client,
    _web_search_errors,
    _web_search_tool,
    parse_event_cards,
)
from utils.geo import CITY_TO_PROVINCE, cities_within_radius
from utils.webpage import fetch_page_text

log = logging.getLogger(__name__)

SOURCE_DOMAIN = "evenementen.nl"
SOURCE_NAME = "Evenementen.nl"
TZ = ZoneInfo("Europe/Amsterdam")

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


def _target_month() -> date:
    """Первый день следующего календарного месяца."""
    today = datetime.now(TZ).date()
    return _add_months(date(today.year, today.month, 1), 1)


def _target_month_end(month: date | None = None) -> date:
    month = month or _target_month()
    return date(month.year, month.month, monthrange(month.year, month.month)[1])


def _catalog_sections() -> dict[str, tuple[str, str]]:
    """Только предстоящий месяц, разбитый на шесть направлений."""
    month = _target_month()
    last = _target_month_end(month)
    sections: dict[str, tuple[str, str]] = {}
    for short, slug, label in SITE_CATEGORIES:
        key = f"m{month:%y%m}_{short}"
        title = f"📅 {MONTH_NAMES[month.month]} · {label.split(' ', 1)[1]}"
        marker = f"evenementen|{slug}|{month.isoformat()}|{last.isoformat()}|{label}"
        sections[key] = (title, marker)
    return sections


def _evenementen_event_text(ev: DiscoveredEvent) -> str:
    place = " · ".join(x for x in (ev.venue, ev.city) if x)
    lines = [
        f"🎭 <b>{html_lib.escape(ev.title[:220])}</b>",
        "",
        f"📅 <b>{html_lib.escape(ev.event_date[:160])}</b>",
    ]
    if place:
        lines.append(f"📍 {html_lib.escape(place[:220])}")
    if ev.description:
        lines.extend(["", html_lib.escape(ev.description[:700])])
    lines.extend(["", f"<i>Источник: {SOURCE_NAME}</i>"])
    return "\n".join(lines)


def install_evenementen_source() -> None:
    """Включает месячный каталог и запрещает AI-поиск при открытии афиши."""
    events.AFISHA_SECTIONS = _catalog_sections()
    events.ai_event_cards = evenementen_event_cards
    events._auto_event_text = _evenementen_event_text
    # Важно: обе функции ниже работают ТОЛЬКО с уже сохранённым месячным кэшем.
    # Поэтому пользовательские клики по афише больше не создают расходы Anthropic.
    events.show_catalog_section = show_monthly_catalog_section
    events.show_auto_afisha = show_monthly_cached_afisha


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
    value = (raw or "").strip()
    if len(value) < 10:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _card_in_period(card: dict, date_from: str, date_till: str) -> bool:
    try:
        lower = date.fromisoformat(date_from)
        upper = date.fromisoformat(date_till)
    except ValueError:
        return False
    starts = _calendar_day(str(card.get("start") or ""))
    ends = _calendar_day(str(card.get("end") or "")) or starts
    return bool(starts and starts <= upper and ends and ends >= lower)


def _has_russian(text: str) -> bool:
    return bool(re.search(r"[А-Яа-яЁё]", text or ""))


async def _translate_descriptions_batch(cards: list[dict]) -> None:
    """Максимум ОДИН дополнительный AI-вызов на раздел, а не один на событие."""
    missing = [(idx, (card.get("description") or "").strip()) for idx, card in enumerate(cards)]
    missing = [(idx, text) for idx, text in missing if text and not _has_russian(text)]
    if not missing:
        return
    payload = [{"id": idx, "text": text[:1600]} for idx, text in missing]
    try:
        response = await _get_client().messages.create(
            model=config.AI_CHAT_MODEL,
            max_tokens=1800,
            system=(
                "Переведи описания мероприятий на естественный русский язык без добавления новых фактов. "
                "Сохрани цены, даты и ограничения. Верни ТОЛЬКО JSON-массив объектов "
                "вида {\"id\": число, \"text\": \"перевод\"}."
            ),
            messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
        )
        raw, _ = _extract_text_and_sources(response)
        match = re.search(r"\[.*\]", raw, re.S)
        rows = json.loads(match.group(0) if match else raw)
        translations = {int(row["id"]): str(row["text"]).strip() for row in rows if "id" in row and "text" in row}
        for idx, _ in missing:
            if translations.get(idx):
                cards[idx]["description"] = translations[idx]
    except Exception as exc:  # noqa: BLE001
        log.info("Пакетный перевод описаний не сработал: %s", exc)


async def _verified_evenementen_page(url: str) -> bool:
    if not _is_evenementen_url(url):
        return False
    try:
        return await fetch_page_text(url, max_chars=1200) is not None
    except Exception as exc:  # noqa: BLE001
        log.info("Не удалось проверить страницу evenementen.nl %s: %s", url, exc)
        return False


async def evenementen_event_cards(
    city: str,
    radius_km: int = 25,
    search_cities: list[str] | None = None,
    *,
    section_label: str = "",
    horizon_days: int = 90,
) -> list[dict[str, str]]:
    """Единственный AI-сборщик: вызывается только месячным фоновым заданием."""
    del horizon_days
    slug, date_from, date_till, category_label = _section_filter(section_label)
    if not date_from:
        month = _target_month()
        date_from = month.isoformat()
        date_till = _target_month_end(month).isoformat()

    places = search_cities or [city]
    place_text = "Nederland" if radius_km == 999 else ", ".join(places[:8])
    category_url = f"https://evenementen.nl/zoeken/{slug}" if slug else "https://evenementen.nl/"
    category_rule = (
        f"Gebruik alleen de categorie {category_label} ({category_url}). "
        if slug else "Gebruik alle relevante evenementcategorieën op evenementen.nl. "
    )

    system = (
        "Je maakt een maandelijkse evenementenkalender voor Russischtalige inwoners van Nederland. "
        "Gebruik VERPLICHT web search, uitsluitend evenementen.nl. "
        f"{category_rule}"
        f"Selecteer evenementen tussen {date_from} en {date_till}. Gebied: {place_text}. "
        "Neem alleen echte evenementen met concrete datum op. Open detailpagina's voor datum, locatie, "
        "inhoud en eventuele prijs. Geef 8 tot 12 bruikbare resultaten als die beschikbaar zijn. "
        "title blijft EXACT in de oorspronkelijke taal. description is VOLLEDIG IN HET RUSSISCH: "
        "3-5 concrete zinnen met programma/formaat, praktische details en doelgroep. "
        "Als een prijs staat: voeg «🎟 Билеты: €…» toe. Bij expliciet gratis: «🎟 Вход бесплатный». "
        "Verzin nooit een prijs of link. source_url moet een concrete evenementen.nl/events/... pagina zijn. "
        "Geef uitsluitend blokken zonder markdown:\n"
        "<event><title>Originele naam</title><start>YYYY-MM-DD of ISO 8601</start>"
        "<end>YYYY-MM-DD of ISO 8601 indien bekend</end><date>Leesbare datum/tijd</date>"
        "<venue>Locatie</venue><city>Plaats</city>"
        "<description>Описание только на русском языке.</description>"
        "<source_url>https://evenementen.nl/events/...</source_url>"
        "<ticket_url></ticket_url><source>Evenementen.nl</source><territory>Nederland</territory></event>"
    )
    kwargs = dict(
        model=config.AI_CHAT_MODEL,
        max_tokens=4200,
        system=system,
        messages=[{
            "role": "user",
            "content": (
                f"Zoek evenementen voor {place_text}, {date_from} t/m {date_till}. "
                f"Categorie: {category_label or 'alle categorieën'}. Begin bij {category_url}."
            ),
        }],
    )
    # Раньше было до 7 поисков × 30 сегментов × 4 раза в сутки.
    # Теперь максимум 4 поиска × 6 сегментов ОДИН РАЗ В МЕСЯЦ.
    tools = _web_search_tool([SOURCE_DOMAIN], max_uses=4)
    if tools:
        kwargs["tools"] = tools

    try:
        response = await _create_with_server_tool_continuation(
            _get_client(), max_continuations=1, **kwargs
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
        card["url"] = url
        card["source_url"] = url
        card["source"] = SOURCE_NAME
        card["ticket_url"] = ""
        card["territory"] = "Nederland"
        clean.append(card)

    await _translate_descriptions_batch(clean)
    log.info(
        "Evenementen.nl monthly %s: parsed=%d candidates=%d verified=%d sources=%d",
        section_label or city, len(cards), len(candidates), len(clean), len(evidence),
    )
    return clean[:12]


def _segment_meta_key(section_key: str) -> str:
    return f"evmonth:{section_key}"


async def _meta_value(key: str) -> str | None:
    async with get_session() as session:
        row = await session.get(Meta, key)
        return row.value if row else None


async def _set_meta(key: str, value: str) -> None:
    async with get_session() as session:
        row = await session.get(Meta, key)
        if row:
            row.value = value
        else:
            session.add(Meta(key=key, value=value))
        await session.commit()


async def _segment_has_rows(section_key: str) -> bool:
    now = datetime.utcnow()
    async with get_session() as session:
        row = await session.scalar(
            select(DiscoveredEvent.id).where(
                DiscoveredEvent.query_city == "Nederland",
                DiscoveredEvent.radius_km == 999,
                DiscoveredEvent.section_key == section_key,
                DiscoveredEvent.ends_at > now,
            ).limit(1)
        )
        return row is not None


async def _extend_segment_expiry(section_key: str, month: date) -> None:
    # Кэш не должен протухать через прежние 72 часа. Храним до конца целевого месяца.
    last = _target_month_end(month)
    expiry = datetime.combine(last + timedelta(days=1), time(3, 0))
    async with get_session() as session:
        await session.execute(
            update(DiscoveredEvent).where(
                DiscoveredEvent.query_city == "Nederland",
                DiscoveredEvent.radius_km == 999,
                DiscoveredEvent.section_key == section_key,
            ).values(expires_at=expiry)
        )
        await session.commit()


async def _purge_non_target_catalog() -> None:
    """Оставляет только автоматическую афишу предстоящего месяца."""
    keys = list(_catalog_sections())
    now = datetime.utcnow()
    async with get_session() as session:
        await session.execute(
            delete(DiscoveredEvent).where(
                (DiscoveredEvent.source_url == "")
                | (~DiscoveredEvent.source_url.contains(SOURCE_DOMAIN))
                | (~DiscoveredEvent.section_key.in_(keys))
                | (DiscoveredEvent.ends_at < now)
            )
        )
        await session.commit()


async def _build_target_month_once() -> None:
    month = _target_month()
    month_id = month.strftime("%Y-%m")
    events.AFISHA_SECTIONS = _catalog_sections()
    await _purge_non_target_catalog()

    for section_key, (_, search_label) in events.AFISHA_SECTIONS.items():
        marker = _segment_meta_key(section_key)
        # Если этот сегмент уже был собран в нужном месяце, НИКАКИХ AI-вызовов.
        if await _meta_value(marker) == month_id and await _segment_has_rows(section_key):
            await _extend_segment_expiry(section_key, month)
            continue
        # После миграции PR старый подход уже мог собрать этот будущий месяц.
        # Используем готовые данные и тоже не тратим API повторно.
        if await _segment_has_rows(section_key):
            await _extend_segment_expiry(section_key, month)
            await _set_meta(marker, month_id)
            continue

        try:
            result = await events.ensure_auto_afisha(
                "Nederland",
                999,
                config.ADMIN_IDS[0] if config.ADMIN_IDS else 0,
                section_key=section_key,
                section_label=search_label,
                horizon_days=40,
                force=True,
            )
            if result:
                await _extend_segment_expiry(section_key, month)
                await _set_meta(marker, month_id)
            else:
                log.warning("Месячный раздел %s не удалось наполнить", section_key)
        except Exception as exc:  # noqa: BLE001
            log.warning("Не удалось собрать месячный раздел %s: %s", section_key, exc)
        # Только шесть запросов в один месячный запуск; не создаём параллельный всплеск.
        await asyncio.sleep(8)


async def show_monthly_catalog_section(message, section_key: str, uid: int) -> None:
    """Открывает готовый раздел. Никогда не запускает Claude по клику."""
    del uid
    if section_key not in events.AFISHA_SECTIONS:
        await message.answer("Этот раздел уже относится к старой афише. Открой /afisha заново.")
        return
    cached = await events._auto_batch("Nederland", 999, section_key)
    if not cached:
        await message.answer(
            "Этот раздел афиши предстоящего месяца пока не заполнен. "
            "Бот не запускает дорогой повторный поиск по каждому клику — раздел появится после месячной сборки.",
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


async def show_monthly_cached_afisha(
    message,
    city: str,
    radius_km: int,
    uid: int,
    *,
    section_key: str = "nearby",
    section_label: str = "",
) -> None:
    """Персональная афиша берётся из общего месячного кэша без AI-запроса."""
    del uid, section_label
    if section_key != "nearby":
        await show_monthly_catalog_section(message, section_key, 0)
        return

    canonical = CITY_TO_PROVINCE.get((city or "").casefold(), (city, ""))[0]
    nearby = cities_within_radius(canonical, radius_km, limit=16)
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

    # Одно событие может попасть в две рубрики. Пользователю показываем его один раз.
    unique: list[DiscoveredEvent] = []
    seen: set[str] = set()
    for row in rows:
        key = (row.source_url or row.link or f"{row.title}|{row.event_date}").casefold()
        if key not in seen:
            seen.add(key)
            unique.append(row)

    if not unique:
        await message.answer(
            f"В месячной афише пока нет мероприятий для <b>{html_lib.escape(city)}</b> "
            f"в выбранном радиусе. Дополнительный AI-поиск по клику отключён, чтобы не тратить бюджет.",
            reply_markup=events.main_menu(),
        )
        return

    await message.answer(
        f"🎭 <b>Афиша · {html_lib.escape(city)}</b>\n"
        f"Предстоящий месяц · найдено: <b>{len(unique)}</b>. Показываю ближайшие события 👇",
        reply_markup=events.main_menu(),
    )
    # Персональная выборка формируется из разных месячных batch, поэтому отправляем
    # несколько самостоятельных карточек. У каждой сохраняются своё фото и ссылка.
    for row in unique[:6]:
        text_value = _evenementen_event_text(row)
        kb = events._auto_event_kb(row.batch_key, 0, 1, row)
        if row.photo_url:
            try:
                await message.answer_photo(row.photo_url, caption=text_value, reply_markup=kb)
                continue
            except Exception:  # noqa: BLE001
                pass
        await message.answer(text_value, reply_markup=kb, disable_web_page_preview=True)


def _seconds_until_next_month() -> float:
    now = datetime.now(TZ)
    next_month = _add_months(date(now.year, now.month, 1), 1)
    wake = datetime.combine(next_month, time(0, 15), tzinfo=TZ)
    return max(3600.0, (wake - now).total_seconds())


async def evenementen_catalog_loop(bot) -> None:
    """Один сбор при запуске/смене месяца, затем сон до следующего месяца."""
    del bot
    await asyncio.sleep(8)
    while True:
        await _build_target_month_once()
        sleep_for = _seconds_until_next_month()
        log.info("Месячная афиша готова; следующий плановый запуск через %.1f ч", sleep_for / 3600)
        await asyncio.sleep(sleep_for)
