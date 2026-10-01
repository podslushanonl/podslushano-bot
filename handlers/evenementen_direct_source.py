"""Direct evenementen.nl monthly source with no Anthropic dependency."""
from __future__ import annotations

import asyncio
import html
import json
import logging
import re
import secrets
from calendar import monthrange
from datetime import date, datetime, time, timedelta, timezone
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import aiohttp
from sqlalchemy import delete, select

from database.db import get_session
from database.models import DiscoveredEvent
from handlers import evenementen_catalog as base
from handlers import events

log = logging.getLogger(__name__)
TZ = ZoneInfo("Europe/Amsterdam")
BASE_URL = "https://evenementen.nl"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
)

DUTCH_MONTHS = {
    "jan": 1, "feb": 2, "mrt": 3, "apr": 4, "mei": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "okt": 10, "nov": 11, "dec": 12,
}


def current_month() -> date:
    now = datetime.now(TZ).date()
    return date(now.year, now.month, 1)


def month_end(month: date) -> date:
    return date(month.year, month.month, monthrange(month.year, month.month)[1])


def sections_for(month: date) -> dict[str, tuple[str, str]]:
    last = month_end(month)
    result: dict[str, tuple[str, str]] = {}
    for short, slug, label in base.SITE_CATEGORIES:
        key = f"m{month:%y%m}_{short}"
        title = f"📅 {base.MONTH_NAMES[month.month]} · {label.split(' ', 1)[1]}"
        marker = f"direct|{slug}|{month.isoformat()}|{last.isoformat()}|{label}"
        result[key] = (title, marker)
    return result


def _strip_tags(raw: str) -> str:
    value = re.sub(r"(?is)<script.*?</script>|<style.*?</style>", " ", raw or "")
    value = re.sub(r"(?s)<[^>]+>", " ", value)
    value = html.unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def _meta(raw: str, key: str) -> str:
    patterns = [
        rf'(?is)<meta[^>]+(?:property|name)=["\']{re.escape(key)}["\'][^>]+content=["\']([^"\']+)["\']',
        rf'(?is)<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']{re.escape(key)}["\']',
    ]
    for pattern in patterns:
        match = re.search(pattern, raw)
        if match:
            return html.unescape(match.group(1)).strip()
    return ""


def _h1(raw: str) -> str:
    match = re.search(r"(?is)<h1[^>]*>(.*?)</h1>", raw or "")
    return _strip_tags(match.group(1)) if match else ""


def _jsonld_objects(raw: str) -> list[dict]:
    objects: list[dict] = []
    for block in re.findall(
        r'(?is)<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        raw or "",
    ):
        try:
            data = json.loads(html.unescape(block).strip())
        except Exception:
            continue
        queue = data if isinstance(data, list) else [data]
        while queue:
            item = queue.pop(0)
            if not isinstance(item, dict):
                continue
            graph = item.get("@graph")
            if isinstance(graph, list):
                queue.extend(graph)
            objects.append(item)
    return objects


def _event_jsonld(raw: str) -> dict:
    for item in _jsonld_objects(raw):
        raw_type = item.get("@type")
        types = raw_type if isinstance(raw_type, list) else [raw_type]
        if any(str(value).casefold() == "event" for value in types if value):
            return item
    return {}


def _parse_iso_day(value: str | None) -> date | None:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(raw[:10])
        except ValueError:
            return None


def _parse_dutch_date(text: str) -> tuple[date, date] | None:
    pattern = re.compile(
        r"(?i)\b(\d{1,2})\s+(jan|feb|mrt|apr|mei|jun|jul|aug|sep|okt|nov|dec)\s+(\d{4})"
        r"(?:\s+t/m\s+(\d{1,2})\s+(jan|feb|mrt|apr|mei|jun|jul|aug|sep|okt|nov|dec)\s+(\d{4}))?"
    )
    match = pattern.search(text or "")
    if not match:
        return None
    try:
        start = date(int(match.group(3)), DUTCH_MONTHS[match.group(2).lower()], int(match.group(1)))
        if match.group(4):
            end = date(int(match.group(6)), DUTCH_MONTHS[match.group(5).lower()], int(match.group(4)))
        else:
            end = start
    except ValueError:
        return None
    return start, end


def _location_from_jsonld(event: dict) -> tuple[str, str]:
    location = event.get("location")
    if isinstance(location, list):
        location = next((item for item in location if isinstance(item, dict)), {})
    if not isinstance(location, dict):
        return "", ""
    venue = str(location.get("name") or "").strip()
    address = location.get("address")
    city = ""
    if isinstance(address, dict):
        city = str(address.get("addressLocality") or "").strip()
    elif isinstance(address, str):
        city = address.strip()
    return venue, city


def _fallback_city_and_venue(text: str) -> tuple[str, str]:
    city = ""
    venue = ""
    city_match = re.search(r"(?i)\bStad\s+(.+?)\s+Provincie\b", text)
    if city_match:
        city = city_match.group(1).strip(" -")
    venue_match = re.search(
        r"(?i)\bLocatie\(s\)\s+(.+?)(?:\s+Website\b|\s+Naar website\b|\s+Aankomende\b|$)",
        text,
    )
    if venue_match:
        venue = venue_match.group(1).strip(" -")
    return venue[:200], city[:100]


def _to_naive_utc(day: date, end: bool = False) -> datetime:
    local = datetime.combine(day, time.max if end else time.min, tzinfo=TZ)
    return local.astimezone(timezone.utc).replace(tzinfo=None)


def _date_label(start: date, end: date) -> str:
    if start == end:
        return start.strftime("%d.%m.%Y")
    return f"{start:%d.%m.%Y}–{end:%d.%m.%Y}"


def _in_month(start: date, end: date, month: date) -> bool:
    return start <= month_end(month) and end >= month


def _clean_description(value: str) -> str:
    clean = _strip_tags(value)
    return re.sub(r"\s+", " ", clean).strip()[:700]


async def _get(session: aiohttp.ClientSession, url: str) -> str:
    try:
        async with session.get(url, allow_redirects=True) as response:
            if response.status != 200:
                log.info("Evenementen direct GET %s -> %s", url, response.status)
                return ""
            return await response.text(errors="ignore")
    except Exception as exc:  # noqa: BLE001
        log.info("Evenementen direct GET failed %s: %s", url, exc)
        return ""


def _event_links(raw: str) -> list[str]:
    """Extract relative or absolute evenementen.nl event links from search HTML."""
    links: list[str] = []
    seen: set[str] = set()
    pattern = re.compile(
        r'(?is)href=["\']((?:https?://(?:www\.)?evenementen\.nl)?/events/[^"\'#?]+(?:\?[^"\'#]*)?)["\']'
    )
    for href in pattern.findall(raw or ""):
        url = urljoin(BASE_URL, html.unescape(href)).split("#", 1)[0]
        if url.startswith(BASE_URL + "/events/") and url not in seen:
            seen.add(url)
            links.append(url)
    return links


async def _detail_card(session: aiohttp.ClientSession, url: str, month: date) -> dict | None:
    raw = await _get(session, url)
    if not raw:
        return None

    event = _event_jsonld(raw)
    text = _strip_tags(raw)
    start = _parse_iso_day(str(event.get("startDate") or "")) if event else None
    end = _parse_iso_day(str(event.get("endDate") or "")) if event else None

    if not start:
        parsed = _parse_dutch_date(text)
        if parsed:
            start, end = parsed
    if not start:
        slug_date = re.search(r"-(20\d{2})-(\d{2})-(\d{2})(?:$|[/?#])", url)
        if slug_date:
            try:
                start = date(int(slug_date.group(1)), int(slug_date.group(2)), int(slug_date.group(3)))
            except ValueError:
                start = None
    if not start:
        return None

    end = end or start
    if not _in_month(start, end, month):
        return None

    title = str(event.get("name") or "").strip() if event else ""
    title = title or _meta(raw, "og:title") or _h1(raw)
    if not title:
        return None
    title = re.sub(r"\s*\|\s*Evenementen\.nl\s*$", "", title, flags=re.I).strip()

    description = str(event.get("description") or "").strip() if event else ""
    description = _clean_description(description or _meta(raw, "og:description"))

    venue, city = _location_from_jsonld(event) if event else ("", "")
    if not venue or not city:
        fallback_venue, fallback_city = _fallback_city_and_venue(text)
        venue = venue or fallback_venue
        city = city or fallback_city

    image = ""
    raw_image = event.get("image") if event else None
    if isinstance(raw_image, list):
        image = str(raw_image[0] or "") if raw_image else ""
    elif isinstance(raw_image, dict):
        image = str(raw_image.get("url") or "")
    elif isinstance(raw_image, str):
        image = raw_image
    image = image or _meta(raw, "og:image")

    return {
        "title": title[:240],
        "description": description,
        "date": _date_label(start, end),
        "venue": venue[:200],
        "city": city[:100],
        "url": url,
        "source_url": url,
        "photo_url": image[:1000],
        "starts_at": _to_naive_utc(start),
        "ends_at": _to_naive_utc(end, end=True),
    }


async def _category_cards(slug: str, month: date, limit: int = 12) -> list[dict]:
    first = month.isoformat()
    last = month_end(month).isoformat()
    timeout = aiohttp.ClientTimeout(total=30)
    connector = aiohttp.TCPConnector(limit=8)
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.7",
    }

    async with aiohttp.ClientSession(timeout=timeout, connector=connector, headers=headers) as session:
        links: list[str] = []
        seen: set[str] = set()
        for page in range(1, 5):
            suffix = f"&page={page}" if page > 1 else ""
            url = f"{BASE_URL}/zoeken/{slug}?datefrom={first}&datetill={last}{suffix}"
            raw = await _get(session, url)
            found = _event_links(raw)
            log.info("Evenementen direct listing %s page %d -> %d event links", slug, page, len(found))
            for link in found:
                if link not in seen:
                    seen.add(link)
                    links.append(link)
            if len(links) >= 36:
                break

        if not links:
            return []

        semaphore = asyncio.Semaphore(6)

        async def load(link: str):
            async with semaphore:
                return await _detail_card(session, link, month)

        rows = await asyncio.gather(*(load(link) for link in links[:40]))
        clean: list[dict] = []
        seen_titles: set[str] = set()
        for row in rows:
            if not row:
                continue
            normalized = re.sub(r"\W+", "", row["title"].casefold())
            if not normalized or normalized in seen_titles:
                continue
            seen_titles.add(normalized)
            clean.append(row)
            if len(clean) >= limit:
                break
        return clean


async def _segment_has_rows(section_key: str) -> bool:
    now = datetime.utcnow()
    async with get_session() as session:
        row = await session.scalar(
            select(DiscoveredEvent.id).where(
                DiscoveredEvent.query_city == "Nederland",
                DiscoveredEvent.radius_km == 999,
                DiscoveredEvent.section_key == section_key,
                DiscoveredEvent.ends_at > now,
                DiscoveredEvent.expires_at > now,
            ).limit(1)
        )
        return row is not None


async def _extend_expiry(section_key: str, month: date) -> None:
    expiry = datetime.combine(month_end(month) + timedelta(days=1), time(3, 0))
    async with get_session() as session:
        rows = (
            await session.scalars(
                select(DiscoveredEvent).where(
                    DiscoveredEvent.query_city == "Nederland",
                    DiscoveredEvent.radius_km == 999,
                    DiscoveredEvent.section_key == section_key,
                )
            )
        ).all()
        for row in rows:
            row.expires_at = expiry
        await session.commit()


async def build_current_month_once() -> None:
    month = current_month()
    events.AFISHA_SECTIONS = sections_for(month)

    now = datetime.utcnow()
    async with get_session() as session:
        await session.execute(
            delete(DiscoveredEvent).where(
                DiscoveredEvent.ends_at.is_not(None),
                DiscoveredEvent.ends_at < now,
            )
        )
        await session.commit()

    for short, slug, _label in base.SITE_CATEGORIES:
        section_key = f"m{month:%y%m}_{short}"
        if await _segment_has_rows(section_key):
            await _extend_expiry(section_key, month)
            continue

        cards: list[dict] = []
        for attempt in range(2):
            cards = await _category_cards(slug, month)
            if cards:
                break
            if attempt == 0:
                await asyncio.sleep(2)

        if not cards:
            log.warning("Evenementen direct: no rows for %s after retry", section_key)
            continue

        batch = secrets.token_hex(6)
        expiry = datetime.combine(month_end(month) + timedelta(days=1), time(3, 0))
        async with get_session() as session:
            for card in cards:
                session.add(
                    DiscoveredEvent(
                        batch_key=batch,
                        query_city="Nederland",
                        radius_km=999,
                        title=card["title"],
                        description=card["description"],
                        event_date=card["date"],
                        venue=card["venue"],
                        city=card["city"],
                        link=card["url"],
                        source_name=base.SOURCE_NAME,
                        section_key=section_key,
                        source_url=card["source_url"],
                        ticket_url="",
                        photo_url=card["photo_url"],
                        territory="Nederland",
                        starts_at=card["starts_at"],
                        ends_at=card["ends_at"],
                        expires_at=expiry,
                    )
                )
            await session.commit()
        log.info("Evenementen direct: %s -> %d rows", section_key, len(cards))
        await asyncio.sleep(1)
