"""Загрузка и очистка веб-страницы до читаемого текста.

Используется для постов «по ссылке» (/post): админ кидает ссылку на статью/
новость/страницу, мы скачиваем её, вынимаем текст и заголовок, а ИИ уже пишет
пост на основе этого материала. Без тяжёлых зависимостей — простой разбор HTML
регулярками (достаточно, чтобы накормить модель)."""
import html as _html
import logging
import re

import aiohttp

log = logging.getLogger(__name__)

# Блоки, содержимое которых выбрасываем целиком (скрипты, стили, разметка головы)
_DROP_RE = re.compile(
    r"<(script|style|noscript|svg|head|template|iframe)\b[^>]*>.*?</\1>",
    re.I | re.S,
)
# Закрывающие/блочные теги превращаем в перенос строки, чтобы сохранить абзацы
_BLOCK_RE = re.compile(
    r"(?i)</(p|div|li|h[1-6]|tr|section|article|header|footer)>|<br\s*/?>|<li\b[^>]*>",
)
_TAG_RE = re.compile(r"<[^>]+>")
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)


async def fetch_page_text(url: str, max_chars: int = 12000) -> tuple[str, str] | None:
    """Скачивает страницу и возвращает (заголовок, текст) или None.

    None — если ссылка не открылась, это не HTML/текст, или текста почти нет."""
    url = (url or "").strip()
    if not url:
        return None
    if not url.lower().startswith(("http://", "https://")):
        url = "https://" + url
    # Браузерный User-Agent: многие сайты отдают 403 «ботам». Страницу открывает
    # админ осознанно по своей ссылке, так что ведём себя как обычный браузер.
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
