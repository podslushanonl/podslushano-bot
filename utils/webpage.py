"""Загрузка и очистка веб-страницы до читаемого текста.

Используется для постов «по ссылке» (/post) и для афиши. Для карточек событий
фото берётся с конкретной страницы события, без случайного поиска картинок.
"""
import html as _html
import json
import logging
import re
from urllib.parse import urljoin, urlparse

import aiohttp

log = logging.getLogger(__name__)

_DROP_RE = re.compile(
    r"<(script|style|noscript|svg|head|template|iframe)\b[^>]*>.*?</\1>",
    re.I | re.S,
)
_BLOCK_RE = re.compile(
    r"(?i)</(p|div|li|h[1-6]|tr|section|article|header|footer)>|<br\s*/?>|<li\b[^>]*>",
)
_TAG_RE = re.compile(r"<[^>]+>")
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_META_RE = re.compile(r"<meta\b[^>]*>", re.I)
_IMG_RE = re.compile(r"<img\b[^>]*>", re.I)
_JSONLD_RE = re.compile(
    r"<script\b[^>]*type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
    re.I | re.S,
)
_ATTR_RE = re.compile(
    r"""([:\w-]+)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+))""",
    re.I,
)


def _attrs(tag: str) -> dict[str, str]:
    return {
        name.casefold(): _html.unescape(double or single or bare)
        for name, double, single, bare in _ATTR_RE.findall(tag)
    }


def _absolute_image(raw: str, page_url: str) -> str | None:
    image_url = urljoin(page_url, (raw or "").strip())
    parsed = urlparse(image_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    low = image_url.casefold()
    # Не используем служебную графику сайта как «фото мероприятия».
    if any(token in low for token in (
        "favicon", "logo.", "/logo/", "icon-", "/icons/", "placeholder",
        "avatar", "sprite", "blank.", "default-image", "default_image",
    )):
        return None
    return image_url[:1000]


def _jsonld_event_image(html: str, page_url: str) -> str | None:
    """Приоритетно берёт image из schema.org Event на самой странице события."""
    def walk(value):
        if isinstance(value, dict):
            event_type = value.get("@type")
            types = event_type if isinstance(event_type, list) else [event_type]
            if any(str(item).casefold() == "event" for item in types if item):
                image = value.get("image")
                values = image if isinstance(image, list) else [image]
                for item in values:
                    if isinstance(item, dict):
                        item = item.get("url") or item.get("contentUrl")
                    if isinstance(item, str):
                        found = _absolute_image(item, page_url)
                        if found:
                            return found
            for child in value.values():
                found = walk(child)
                if found:
                    return found
        elif isinstance(value, list):
            for child in value:
                found = walk(child)
                if found:
                    return found
        return None

    for raw in _JSONLD_RE.findall(html[:800_000]):
        try:
            data = json.loads(_html.unescape(raw).strip())
        except Exception:  # noqa: BLE001 — некорректный JSON-LD просто пропускаем
            continue
        found = walk(data)
        if found:
            return found
    return None


def _content_image(html: str, page_url: str) -> str | None:
    """Ищет крупное содержательное изображение внутри страницы, а не логотип/иконку."""
    candidates: list[tuple[int, str]] = []
    for tag in _IMG_RE.findall(html[:900_000]):
        attrs = _attrs(tag)
        raw = attrs.get("data-src") or attrs.get("data-lazy-src") or attrs.get("src") or ""
        if not raw and attrs.get("srcset"):
            raw = attrs["srcset"].split(",")[-1].strip().split(" ")[0]
        image = _absolute_image(raw, page_url)
        if not image:
            continue
        text = " ".join((attrs.get("alt", ""), attrs.get("title", ""))).casefold()
        if any(token in text for token in ("logo", "icoon", "icon", "avatar")):
            continue
        score = 0
        try:
            width = int(re.sub(r"\D", "", attrs.get("width", "")) or 0)
            height = int(re.sub(r"\D", "", attrs.get("height", "")) or 0)
            if width >= 500 or height >= 350:
                score += 4
            elif width and width < 250:
                score -= 4
        except ValueError:
            pass
        if any(token in image.casefold() for token in ("event", "festival", "upload", "media", "image")):
            score += 2
        if text:
            score += 1
        candidates.append((score, image))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1] if candidates[0][0] >= 0 else None


def _meta_image(html: str, page_url: str) -> str | None:
    """Последний fallback: og:image/twitter:image, если он не выглядит служебным."""
    for tag in _META_RE.findall(html[:500_000]):
        attrs = _attrs(tag)
        key = (attrs.get("property") or attrs.get("name") or "").casefold()
        if key in {"og:image", "og:image:url", "twitter:image", "twitter:image:src"}:
            found = _absolute_image(attrs.get("content", ""), page_url)
            if found:
                return found
    return None


async def fetch_page_image(url: str) -> str | None:
    """Берёт собственное фото конкретного события с его detail-page.

    Приоритет: schema.org Event.image -> содержательное <img> -> og:image. Случайные
    картинки не подставляются. Если у события нет собственного изображения, лучше
    вернуть None, чем повторять общий баннер сайта на разных карточках.
    """
    url = (url or "").strip()
    if not url:
        return None
    if not url.lower().startswith(("http://", "https://")):
        url = "https://" + url
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
            "AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1"
        ),
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5",
        "Accept-Language": "nl,en;q=0.8",
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15),
                allow_redirects=True,
            ) as response:
                ctype = (response.headers.get("Content-Type") or "").casefold()
                if response.status >= 400 or ("html" not in ctype and ctype):
                    return None
                raw = await response.content.read(900_000)
                page_url = str(response.url)
    except Exception as exc:  # noqa: BLE001 — отсутствие фото не скрывает событие
        log.info("Не удалось получить фото страницы %s: %s", url, exc)
        return None
    html = raw.decode("utf-8", errors="ignore")
    return (
        _jsonld_event_image(html, page_url)
        or _content_image(html, page_url)
        or _meta_image(html, page_url)
    )


async def fetch_page_text(url: str, max_chars: int = 12000) -> tuple[str, str] | None:
    """Скачивает страницу и возвращает (заголовок, текст) или None.

    None — если ссылка не открылась, это не HTML/текст, или текста почти нет."""
    url = (url or "").strip()
    if not url:
        return None
    if not url.lower().startswith(("http://", "https://")):
        url = "https://" + url
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "nl,en;q=0.8,ru;q=0.6",
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=20),
                allow_redirects=True,
            ) as r:
                if r.status >= 400:
                    log.warning("fetch_page_text HTTP %s для %s", r.status, url)
                    return None
                ctype = (r.headers.get("Content-Type") or "").lower()
                if "html" not in ctype and "text" not in ctype and ctype:
                    log.warning("fetch_page_text не HTML (%s) для %s", ctype, url)
                    return None
                raw = await r.read()
    except Exception as e:  # noqa: BLE001 — сеть/таймаут не должны ронять бота
        log.warning("fetch_page_text ошибка %s: %s", url, e)
        return None

    html = raw.decode("utf-8", errors="ignore")

    m = _TITLE_RE.search(html)
    title = _TAG_RE.sub("", _html.unescape(m.group(1))).strip() if m else ""

    body = _DROP_RE.sub(" ", html)
    body = _BLOCK_RE.sub("\n", body)
    body = _TAG_RE.sub(" ", body)
    body = _html.unescape(body)
    body = re.sub(r"[ \t\r\f]+", " ", body)
    body = re.sub(r"\n[ \t]*", "\n", body)
    body = re.sub(r"\n{3,}", "\n\n", body).strip()

    if len(body) < 80:
        log.warning("fetch_page_text пусто/мало текста для %s", url)
        return None
    return title[:300], body[:max_chars]
