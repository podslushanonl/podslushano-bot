"""Поиск официального сайта и изображения мероприятия без Anthropic/AI.

Evenementen.nl используется как каталог. Сначала пытаемся извлечь официальный
сайт из detail-page события. Если явной ссылки там нет, делаем обычный HTML-
поиск DuckDuckGo по названию, городу и году, проверяем кандидатов и только затем
берём Event.image / og:image / релевантное hero-фото с официального сайта.
"""
from __future__ import annotations

import html as html_lib
import json
import logging
import re
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse

import aiohttp

log = logging.getLogger(__name__)

_JSONLD_RE = re.compile(
    r"<script\b[^>]*type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
    re.I | re.S,
)
_A_RE = re.compile(r"<a\b([^>]*)>(.*?)</a>", re.I | re.S)
_IMG_RE = re.compile(r"<img\b[^>]*>", re.I)
_META_RE = re.compile(r"<meta\b[^>]*>", re.I)
_ATTR_RE = re.compile(
    r'''([:\w-]+)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+))''',
    re.I,
)
_TAG_RE = re.compile(r"<[^>]+>")
_DDG_RESULT_RE = re.compile(
    r'<a[^>]+class=["\'][^"\']*result__a[^"\']*["\'][^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
    re.I | re.S,
)

_BLOCKED_HOSTS = {
    "evenementen.nl", "facebook.com", "instagram.com", "youtube.com", "youtu.be",
    "tiktok.com", "x.com", "twitter.com", "linkedin.com", "ticketmaster.nl",
    "eventbrite.nl", "eventbrite.com", "google.com", "maps.google.com", "goo.gl",
    "bit.ly", "t.co", "pinterest.com", "wikipedia.org", "tripadvisor.nl",
    "tripadvisor.com", "allevents.in", "uitagenda.nl", "eventim.nl", "ticketswap.nl",
}
_AD_TOKENS = (
    "advert", "advertentie", "reclame", "banner", "doubleclick", "googleads",
    "adsystem", "adservice", "affiliate", "sponsor", "product", "shop/", "/shop",
    "bestel", "aanbieding", "korting", "sale", "earplug", "oordop", "cookie",
)
_IMAGE_BAD_TOKENS = _AD_TOKENS + (
    "favicon", "logo", "icon", "sprite", "avatar", "placeholder", "default-image",
    "tracking", "pixel", "badge",
)
_STOPWORDS = {
    "2026", "2025", "festival", "event", "events", "the", "and", "van", "het",
    "een", "in", "op", "de", "die", "met", "voor", "live", "open", "dag",
    "dagen", "edition", "editie", "netherlands", "nederland",
}


def _attrs(tag: str) -> dict[str, str]:
    return {
        name.casefold(): html_lib.unescape(double or single or bare)
        for name, double, single, bare in _ATTR_RE.findall(tag)
    }


def _host(url: str) -> str:
    return urlparse(url).netloc.casefold().removeprefix("www.")


def _is_blocked_host(host: str) -> bool:
    host = (host or "").casefold().removeprefix("www.")
    return any(host == item or host.endswith("." + item) for item in _BLOCKED_HOSTS)


def _external_url(raw: str, page_url: str) -> str | None:
    value = urljoin(page_url, html_lib.unescape((raw or "").strip()))
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    host = parsed.netloc.casefold().removeprefix("www.")
    if _is_blocked_host(host):
        return None
    low = value.casefold()
    if any(token in low for token in _AD_TOKENS):
        return None
    return value[:1200]


def _title_tokens(title: str) -> set[str]:
    words = re.findall(r"[a-z0-9]{3,}", (title or "").casefold())
    return {word for word in words if word not in _STOPWORDS}


def _event_jsonld(html: str) -> list[dict]:
    found: list[dict] = []

    def walk(value):
        if isinstance(value, dict):
            raw_type = value.get("@type")
            types = raw_type if isinstance(raw_type, list) else [raw_type]
            if any(str(t).casefold() == "event" for t in types if t):
                found.append(value)
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    for raw in _JSONLD_RE.findall(html[:1_000_000]):
        try:
            walk(json.loads(html_lib.unescape(raw).strip()))
        except Exception:  # noqa: BLE001
            continue
    return found


def _jsonld_official_candidates(html: str, page_url: str) -> list[str]:
    candidates: list[str] = []
    for event in _event_jsonld(html):
        values = [event.get("url"), event.get("sameAs")]
        organizer = event.get("organizer")
        if isinstance(organizer, dict):
            values.extend([organizer.get("url"), organizer.get("sameAs")])
        elif isinstance(organizer, list):
            for item in organizer:
                if isinstance(item, dict):
                    values.extend([item.get("url"), item.get("sameAs")])
        for value in values:
            for raw in value if isinstance(value, list) else [value]:
                if isinstance(raw, str):
                    url = _external_url(raw, page_url)
                    if url and url not in candidates:
                        candidates.append(url)
    return candidates


def _anchor_official_candidates(html: str, page_url: str, title: str) -> list[str]:
    tokens = _title_tokens(title)
    scored: list[tuple[int, str]] = []
    for attrs_raw, body in _A_RE.findall(html[:1_200_000]):
        attrs = _attrs("<a " + attrs_raw + ">")
        url = _external_url(attrs.get("href", ""), page_url)
        if not url:
            continue
        text = _TAG_RE.sub(" ", html_lib.unescape(body))
        haystack = f"{text} {urlparse(url).netloc} {urlparse(url).path}".casefold()
        score = 0
        if any(x in haystack for x in ("website", "offici", "homepage", "meer info", "informatie")):
            score += 5
        matched = sum(1 for token in tokens if token in haystack)
        score += matched * 3
        if matched >= max(1, min(2, len(tokens))):
            score += 3
        if any(x in haystack for x in ("tickets", "ticket", "facebook", "instagram", "route", "maps")):
            score -= 5
        if score >= 3:
            scored.append((score, url))
    scored.sort(key=lambda row: row[0], reverse=True)
    out: list[str] = []
    for _, url in scored:
        if url not in out:
            out.append(url)
    return out


async def _fetch_html(url: str, max_bytes: int = 1_200_000) -> tuple[str, str] | None:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.6",
        "Accept-Language": "nl,en;q=0.8",
    }
    try:
        timeout = aiohttp.ClientTimeout(total=18)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=headers, allow_redirects=True) as response:
                ctype = (response.headers.get("Content-Type") or "").casefold()
                if response.status >= 400 or (ctype and "html" not in ctype):
                    return None
                raw = await response.content.read(max_bytes)
                return str(response.url), raw.decode("utf-8", errors="ignore")
    except Exception as exc:  # noqa: BLE001
        log.info("event photo fetch failed %s: %s", url, exc)
        return None


def _ddg_target(raw: str) -> str:
    value = html_lib.unescape(raw or "")
    if value.startswith("//"):
        value = "https:" + value
    parsed = urlparse(value)
    if "duckduckgo.com" in parsed.netloc:
        uddg = parse_qs(parsed.query).get("uddg", [])
        if uddg:
            return unquote(uddg[0])
    return value


async def _search_web_candidates(title: str, city: str = "", event_date: str = "") -> list[str]:
    """Бесплатный HTML-поиск официального сайта. Anthropic/API не используется."""
    title = (title or "").strip()
    if not title:
        return []
    year_match = re.search(r"\b20\d{2}\b", event_date or "")
    year = year_match.group(0) if year_match else "2026"
    query = " ".join(x for x in (f'"{title}"', city, year, "official website") if x)
    search_url = "https://html.duckduckgo.com/html/?q=" + quote_plus(query)
    page = await _fetch_html(search_url, max_bytes=700_000)
    if not page:
        return []
    _, html = page
    tokens = _title_tokens(title)
    scored: list[tuple[int, str]] = []
    for raw_url, raw_label in _DDG_RESULT_RE.findall(html):
        url = _ddg_target(raw_url)
        parsed = urlparse(url)
        host = parsed.netloc.casefold().removeprefix("www.")
        if parsed.scheme not in {"http", "https"} or not host or _is_blocked_host(host):
            continue
        low_url = url.casefold()
        if any(token in low_url for token in _AD_TOKENS):
            continue
        label = _TAG_RE.sub(" ", html_lib.unescape(raw_label)).casefold()
        haystack = f"{label} {host} {parsed.path}".casefold()
        matched = sum(1 for token in tokens if token in haystack)
        score = matched * 4
        if city and city.casefold() in haystack:
            score += 2
        if year in haystack:
            score += 1
        if any(word in haystack for word in ("official", "officiële", "officieel", "festival", "programma")):
            score += 2
        if any(word in haystack for word in ("tickets", "agenda", "nieuws", "facebook", "instagram")):
            score -= 2
        # Для уникального названия одного совпавшего токена часто достаточно.
        if score >= 4:
            scored.append((score, url[:1200]))
    scored.sort(key=lambda item: item[0], reverse=True)
    out: list[str] = []
    for _, url in scored:
        if _host(url) not in {_host(existing) for existing in out}:
            out.append(url)
        if len(out) >= 6:
            break
    return out


def _page_relevance(html: str, page_url: str, title: str, city: str = "", event_date: str = "") -> int:
    """Не даёт принять случайный сайт из поисковой выдачи за официальный."""
    text = _TAG_RE.sub(" ", html_lib.unescape(html[:500_000])).casefold()
    host_path = f"{_host(page_url)} {urlparse(page_url).path}".casefold()
    tokens = _title_tokens(title)
    matched = sum(1 for token in tokens if token in text or token in host_path)
    score = matched * 4
    if tokens and matched >= max(1, min(2, len(tokens))):
        score += 3
    if city and city.casefold() in text:
        score += 2
    year_match = re.search(r"\b20\d{2}\b", event_date or "")
    if year_match and year_match.group(0) in text:
        score += 2
    if _event_jsonld(html):
        score += 3
    return score


def _absolute_image(raw: str, page_url: str) -> str | None:
    value = urljoin(page_url, html_lib.unescape((raw or "").strip()))
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    low = value.casefold()
    if any(token in low for token in _IMAGE_BAD_TOKENS):
        return None
    return value[:1200]


def _official_image(html: str, page_url: str, title: str) -> str | None:
    for event in _event_jsonld(html):
        image = event.get("image")
        values = image if isinstance(image, list) else [image]
        for item in values:
            if isinstance(item, dict):
                item = item.get("url") or item.get("contentUrl")
            if isinstance(item, str):
                value = _absolute_image(item, page_url)
                if value:
                    return value

    for tag in _META_RE.findall(html[:700_000]):
        attrs = _attrs(tag)
        key = (attrs.get("property") or attrs.get("name") or "").casefold()
        if key in {"og:image", "og:image:url", "twitter:image", "twitter:image:src"}:
            value = _absolute_image(attrs.get("content", ""), page_url)
            if value:
                return value

    tokens = _title_tokens(title)
    scored: list[tuple[int, str]] = []
    for tag in _IMG_RE.findall(html[:1_000_000]):
        attrs = _attrs(tag)
        raw = attrs.get("data-src") or attrs.get("data-lazy-src") or attrs.get("src") or ""
        if not raw and attrs.get("srcset"):
            raw = attrs["srcset"].split(",")[-1].strip().split(" ")[0]
        value = _absolute_image(raw, page_url)
        if not value:
            continue
        text = " ".join((attrs.get("alt", ""), attrs.get("title", ""), value)).casefold()
        if any(token in text for token in _IMAGE_BAD_TOKENS):
            continue
        score = sum(3 for token in tokens if token in text)
        dims = []
        for name in ("width", "height"):
            digits = re.sub(r"\D", "", attrs.get(name, ""))
            dims.append(int(digits) if digits else 0)
        if dims[0] >= 600 or dims[1] >= 400:
            score += 3
        if attrs.get("alt"):
            score += 1
        scored.append((score, value))
    scored.sort(key=lambda row: row[0], reverse=True)
    return scored[0][1] if scored and scored[0][0] >= 3 else None


async def resolve_official_event_media(
    event_page_url: str,
    title: str,
    city: str = "",
    event_date: str = "",
) -> tuple[str, str]:
    """Возвращает (official_site, photo_url). Никаких Anthropic/AI-вызовов."""
    source = await _fetch_html(event_page_url)
    if not source:
        return "", ""
    page_url, html = source
    candidates = _jsonld_official_candidates(html, page_url)
    candidates.extend(
        url for url in _anchor_official_candidates(html, page_url, title)
        if url not in candidates
    )

    # Если агрегатор не содержит официальный сайт — бесплатный web fallback.
    if len(candidates) < 2:
        searched = await _search_web_candidates(title, city, event_date)
        candidates.extend(url for url in searched if url not in candidates)

    best_site = ""
    best_score = -1
    for candidate in candidates[:10]:
        official = await _fetch_html(candidate)
        if not official:
            continue
        official_url, official_html = official
        if _is_blocked_host(_host(official_url)):
            continue
        relevance = _page_relevance(official_html, official_url, title, city, event_date)
        if relevance < 4:
            continue
        if relevance > best_score:
            best_score = relevance
            best_site = official_url[:1200]
        image = _official_image(official_html, official_url, title)
        if image and relevance >= 7:
            return official_url[:1200], image

    return best_site, ""
