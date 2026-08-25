"""Поиск официального сайта и изображения мероприятия без AI/API расходов.

Evenementen.nl используется как каталог. Для фото мы сначала извлекаем ссылку на
официальный сайт конкретного события из detail-page, затем берём Event.image,
og:image или релевантное hero-фото уже с официального сайта. Рекламные баннеры,
товары и социальные сети отбрасываются.
"""
from __future__ import annotations

import html as html_lib
import json
import logging
import re
from urllib.parse import urljoin, urlparse

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

_BLOCKED_HOSTS = {
    "evenementen.nl", "www.evenementen.nl",
    "facebook.com", "www.facebook.com", "instagram.com", "www.instagram.com",
    "youtube.com", "www.youtube.com", "youtu.be", "tiktok.com", "www.tiktok.com",
    "x.com", "twitter.com", "linkedin.com", "www.linkedin.com",
    "ticketmaster.nl", "www.ticketmaster.nl", "eventbrite.nl", "www.eventbrite.nl",
    "eventbrite.com", "www.eventbrite.com", "google.com", "www.google.com",
    "maps.google.com", "goo.gl", "bit.ly", "t.co",
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
    "2026", "festival", "event", "events", "the", "and", "van", "het", "een",
    "in", "op", "de", "die", "met", "voor", "live", "open", "dag", "dagen",
}


def _attrs(tag: str) -> dict[str, str]:
    return {
        name.casefold(): html_lib.unescape(double or single or bare)
        for name, double, single, bare in _ATTR_RE.findall(tag)
    }


def _host(url: str) -> str:
    return urlparse(url).netloc.casefold().removeprefix("www.")


def _external_url(raw: str, page_url: str) -> str | None:
    value = urljoin(page_url, html_lib.unescape((raw or "").strip()))
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    host = parsed.netloc.casefold().removeprefix("www.")
    if host == "evenementen.nl" or host.endswith(".evenementen.nl"):
        return None
    if parsed.netloc.casefold() in _BLOCKED_HOSTS or host in {h.removeprefix("www.") for h in _BLOCKED_HOSTS}:
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
        if matched and matched >= max(1, min(2, len(tokens))):
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
    # 1. schema.org Event.image на официальном сайте.
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

    # 2. og:image официального сайта — обычно hero/афиша самого события.
    for tag in _META_RE.findall(html[:700_000]):
        attrs = _attrs(tag)
        key = (attrs.get("property") or attrs.get("name") or "").casefold()
        if key in {"og:image", "og:image:url", "twitter:image", "twitter:image:src"}:
            value = _absolute_image(attrs.get("content", ""), page_url)
            if value:
                return value

    # 3. Крупное изображение, связанное с названием мероприятия.
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


async def resolve_official_event_media(event_page_url: str, title: str) -> tuple[str, str]:
    """Возвращает (official_site, photo_url). Никаких AI-вызовов."""
    source = await _fetch_html(event_page_url)
    if not source:
        return "", ""
    page_url, html = source
    candidates = _jsonld_official_candidates(html, page_url)
    candidates.extend(
        url for url in _anchor_official_candidates(html, page_url, title)
        if url not in candidates
    )

    for candidate in candidates[:6]:
        official = await _fetch_html(candidate)
        if not official:
            continue
        official_url, official_html = official
        # После redirect ещё раз проверяем, что нас не увело на соцсеть/агрегатор.
        if _host(official_url) in {h.removeprefix("www.") for h in _BLOCKED_HOSTS}:
            continue
        image = _official_image(official_html, official_url, title)
        if image:
            return official_url[:1200], image

    # Если официальный сайт найден, но без фото, всё равно сохраняем его.
    if candidates:
        return candidates[0][:1200], ""
    return "", ""
