"""Автоматические новости на сайт: голландские RSS → русская новость в WordPress.

Раз в SITE_NEWS_INTERVAL секунд бот смотрит ленты (по умолчанию NOS), отбирает
новые статьи, полезные русскоязычным жителям Нидерландов (один запрос к Claude
на всю пачку), пишет по каждой отобранной короткую новость на русском и
публикует её на сайте с собственным фото статьи-источника (og:image).

Каждая рассмотренная статья записывается в таблицу site_news_items — так бот не
берёт её второй раз. При самом первом запуске (таблица пустая) всё, что сейчас
есть в лентах, помечается как skipped/initial, чтобы не завалить сайт старыми
новостями. Переменные окружения — в config.py (SITE_NEWS_*).
"""
from __future__ import annotations

import asyncio
import email.utils
import html
import json
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from zoneinfo import ZoneInfo

import aiohttp
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

import config
from database.db import get_session
from database.models import SiteNewsItem
from utils import wordpress as wp
from utils.ai import _extract_text_and_sources, _get_client, _parse_json, ai_enabled
from utils.webpage import _title_and_text, fetch_article, read_limited

log = logging.getLogger(__name__)

AMSTERDAM = ZoneInfo("Europe/Amsterdam")
# Берём только свежие статьи: старше — уже не новость.
MAX_AGE = timedelta(hours=6)
PARENT_CATEGORY = "Новости"
CATEGORIES = (
    "Транспорт", "Погода", "Жильё", "Деньги", "Здоровье", "Безопасность",
    "Общество", "Природа", "Работа", "Образование", "Культура",
)
# Известные источники: домен → как подписываем «По материалам …» и «Фото: …»
SOURCE_NAMES = {
    "nos.nl": "NOS",
    "nu.nl": "NU.nl",
    "rtlnieuws.nl": "RTL Nieuws",
    "at5.nl": "AT5",
    "parool.nl": "Het Parool",
    "nltimes.nl": "NL Times",
    "dutchnews.nl": "DutchNews.nl",
}
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
_MAX_IMAGE_BYTES = 12_000_000

# Кэш id рубрик WordPress на время жизни процесса: {название: id}
_category_ids: dict[str, int] = {}


@dataclass
class FeedItem:
    url: str
    title: str
    description: str  # обычный текст, без HTML
    published: datetime | None  # UTC, aware
    source: str  # «NOS»
    image: str | None = None  # enclosure из ленты — запасное фото


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def enabled() -> bool:
    return bool(config.SITE_NEWS_ENABLED and wp.wp_enabled() and ai_enabled())


# --- Ленты -------------------------------------------------------------------

def source_name(url: str) -> str:
    """Название источника по домену ленты: feeds.nos.nl → NOS."""
    host = (urlparse(url).hostname or "").casefold().removeprefix("www.")
    parts = host.split(".")
    domain = ".".join(parts[-2:]) if len(parts) >= 2 else host
    if domain in SOURCE_NAMES:
        return SOURCE_NAMES[domain]
    label = parts[-2] if len(parts) >= 2 else host
    return label.upper() if len(label) <= 4 else label.capitalize()


def normalize_url(url: str) -> str:
    """Убирает #якорь и utm-метки, чтобы одна статья не считалась двумя."""
    parsed = urlparse((url or "").strip())
    query = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
             if not k.lower().startswith("utm_")]
    return urlunparse(parsed._replace(query=urlencode(query), fragment=""))


def _plain(raw: str) -> str:
    return _title_and_text(raw or "")[1]


def _parse_date(raw: str | None) -> datetime | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        dt = email.utils.parsedate_to_datetime(raw)  # RSS: RFC 822
    except (TypeError, ValueError):
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))  # Atom
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_feed(xml_bytes: bytes, feed_url: str) -> list[FeedItem]:
    """Разбирает RSS 2.0 (и простой Atom) стандартной библиотекой."""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as e:
        log.warning("Лента %s не разобралась: %s", feed_url, e)
        return []
    source = source_name(feed_url)
    items: list[FeedItem] = []
    for it in root.iter("item"):
        link = (it.findtext("link") or it.findtext("guid") or "").strip()
        title = (it.findtext("title") or "").strip()
        if not link.startswith(("http://", "https://")) or not title:
            continue
        enclosure = it.find("enclosure")
        image = None
        if enclosure is not None and (enclosure.get("type") or "image").startswith("image"):
            image = enclosure.get("url") or None
        items.append(FeedItem(
            url=normalize_url(link), title=html.unescape(title),
            description=_plain(it.findtext("description") or ""),
            published=_parse_date(it.findtext("pubDate")), source=source, image=image,
        ))
    atom = "{http://www.w3.org/2005/Atom}"
    for entry in root.iter(f"{atom}entry"):
        link_el = entry.find(f"{atom}link[@rel='alternate']")
        if link_el is None:
            link_el = entry.find(f"{atom}link")
        link = (link_el.get("href") if link_el is not None else "") or ""
        title = (entry.findtext(f"{atom}title") or "").strip()
        if not link.startswith(("http://", "https://")) or not title:
            continue
        items.append(FeedItem(
            url=normalize_url(link), title=html.unescape(title),
            description=_plain(entry.findtext(f"{atom}summary")
                               or entry.findtext(f"{atom}content") or ""),
            published=_parse_date(entry.findtext(f"{atom}updated")
                                  or entry.findtext(f"{atom}published")),
            source=source,
        ))
    return items


async def fetch_feed(url: str) -> bytes | None:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, headers={"User-Agent": _UA, "Accept": "application/rss+xml,*/*"},
                timeout=aiohttp.ClientTimeout(total=20),
            ) as r:
                if r.status != 200:
                    log.warning("Лента %s: HTTP %s", url, r.status)
                    return None
                return await read_limited(r, 5_000_000)
    except Exception as e:  # noqa: BLE001
        log.warning("Лента %s не загрузилась: %s", url, e)
        return None


async def collect_items() -> list[FeedItem]:
    """Все статьи из всех лент, без повторов (одна статья бывает в нескольких лентах)."""
    seen: dict[str, FeedItem] = {}
    for feed in config.SITE_NEWS_FEEDS:
        raw = await fetch_feed(feed)
        if not raw:
            continue
        for item in parse_feed(raw, feed):
            seen.setdefault(item.url, item)
    return list(seen.values())


def is_fresh(item: FeedItem, now: datetime | None = None) -> bool:
    # Без даты считаем свежей: от повторов защищает таблица site_news_items.
    if item.published is None:
        return True
    return (now or _utcnow()) - item.published <= MAX_AGE


# --- База --------------------------------------------------------------------

async def _known_urls(urls: list[str]) -> set[str]:
    if not urls:
        return set()
    async with get_session() as session:
        rows = await session.scalars(
            select(SiteNewsItem.source_url).where(SiteNewsItem.source_url.in_(urls)))
        return set(rows.all())


async def _table_empty() -> bool:
    async with get_session() as session:
        return not (await session.scalar(select(func.count(SiteNewsItem.id))))


def _day_start_utc(now: datetime | None = None) -> datetime:
    """Начало текущих суток по Амстердаму — в UTC без пояса, как хранится created_at."""
    local = (now or _utcnow()).astimezone(AMSTERDAM)
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight.astimezone(timezone.utc).replace(tzinfo=None)


async def published_today(now: datetime | None = None) -> int:
    async with get_session() as session:
        return int(await session.scalar(
            select(func.count(SiteNewsItem.id)).where(
                SiteNewsItem.status == "published",
                SiteNewsItem.created_at >= _day_start_utc(now),
            )) or 0)


async def _record(item: FeedItem, status: str, reason: str | None = None,
                  post: dict | None = None) -> None:
    async with get_session() as session:
        session.add(SiteNewsItem(
            source_url=item.url[:500], title_nl=item.title[:500], status=status,
            reason=(reason or None) and reason[:300],
            wp_post_id=(post or {}).get("id"), wp_link=((post or {}).get("link") or None),
            created_at=_utcnow().replace(tzinfo=None),
        ))
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()  # уже записана — ничего страшного


async def _record_many(items: list[FeedItem], status: str, reason: str) -> None:
    for item in items:
        await _record(item, status, reason)


# --- Claude ------------------------------------------------------------------

_TRIAGE_SYSTEM = """Ты — выпускающий редактор podslushano.nl, русскоязычного медиа для жителей Нидерландов.
Тебе дают свежие статьи голландских новостных лент. Отбери те, что действительно полезны или
важны русскоязычным жителям Нидерландов.

БЕРЁМ: транспорт (NS, поезда, пробки, дороги, Schiphol, общественный транспорт), погоду и
предупреждения KNMI, жильё и аренду, деньги (цены, налоги, toeslagen, зарплаты, энергия),
здравоохранение, безопасность и заметные местные происшествия, правила и законы, которые
меняют повседневную жизнь, природу и животных, заметные новости городов, культуру и события.

НЕ БЕРЁМ: партийную политику, выборы и парламентские дебаты, зарубежные новости без влияния
на Нидерланды, спортивные результаты, светские сплетни, live-блоги, повторы одной и той же
истории (из нескольких статей об одном событии выбери максимум одну — самую полную).

Лучше не взять ничего, чем взять проходное. Расставь выбранные по важности.
Ответь СТРОГО JSON без пояснений:
{"chosen": ["url", ...], "skipped": {"url": "короткая причина на русском", ...}}"""

_WRITE_SYSTEM = f"""Ты — редактор новостей podslushano.nl для русскоязычных жителей Нидерландов.
По голландской статье напиши короткую новость на русском.

Правила:
• Пиши по-русски, нейтральным новостным стилем редакции.
• Только факты из источника. Ничего не придумывай: ни цифр, ни дат, ни имён, ни цитат.
• Без политики и оценок, без собственного мнения.
• Без эмодзи, без markdown, без HTML.
• Голландские города, провинции, учреждения и компании всегда пиши по-голландски латиницей,
  как в Нидерландах: Amsterdam, Den Haag, Zuid-Holland, Belastingdienst, gemeente, NS, KNMI.
  Никогда не транслитерируй их по-русски («Амстердам», «Гаага», «Беластингдинст» — нельзя).
• Никогда не пиши «NL» как сокращение страны — пиши «Нидерланды».
• Название нашего сайта пишется строчными: podslushano.nl.
• Цитаты (если есть в источнике) переводи на русский и оформляй блоком "quote".

Ответь СТРОГО JSON без пояснений:
{{"cat": одна из {json.dumps(list(CATEGORIES), ensure_ascii=False)},
 "h": "заголовок",
 "lead": "лид в 1–2 предложения",
 "blocks": [["p", "абзац"], ["h2", "подзаголовок"], ["quote", "цитата"], ...]}}
В blocks от 4 до 8 элементов, в основном абзацы "p"; лид в blocks не повторяй."""


async def _ask_claude(model: str, system: str, content: str, max_tokens: int) -> str:
    resp = await _get_client().messages.create(
        model=model, max_tokens=max_tokens, system=system,
        messages=[{"role": "user", "content": content}],
    )
    return _extract_text_and_sources(resp)[0].strip()


async def triage(items: list[FeedItem]) -> tuple[list[str], dict[str, str]] | None:
    """Один запрос на всю пачку. (выбранные url по важности, {url: причина}) или None."""
    lines = []
    for item in items:
        desc = re.sub(r"\s+", " ", item.description)[:300]
        lines.append(f"- url: {item.url}\n  заголовок: {item.title}\n  описание: {desc}")
    try:
        raw = await _ask_claude(
            config.AI_CHAT_MODEL, _TRIAGE_SYSTEM,
            "Статьи:\n" + "\n".join(lines), max_tokens=1500)
    except Exception as e:  # noqa: BLE001
        log.warning("Отбор новостей: ошибка Claude: %s", e)
        return None
    data = _parse_json(raw)
    if not isinstance(data.get("chosen"), list):
        log.warning("Отбор новостей: непонятный ответ: %s", raw[:300])
        return None
    known = {item.url for item in items}
    chosen: list[str] = []
    for url in data["chosen"]:
        url = normalize_url(str(url))
        if url in known and url not in chosen:
            chosen.append(url)
    reasons = data.get("skipped") if isinstance(data.get("skipped"), dict) else {}
    reasons = {normalize_url(str(k)): str(v) for k, v in reasons.items()}
    return chosen, reasons


_EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF☀-➿️]")


def _tidy(text: str) -> str:
    text = _EMOJI_RE.sub("", str(text or ""))
    text = text.replace("**", "").replace("__", "")
    text = re.sub(r"(?i)podslushano\.nl", "podslushano.nl", text)
    return re.sub(r"\s+", " ", text).strip()


def validate_article(data: object) -> dict | None:
    """Проверяет JSON новости от Claude. Возвращает очищенный dict или None."""
    if not isinstance(data, dict):
        return None
    cat, h, lead = data.get("cat"), _tidy(data.get("h")), _tidy(data.get("lead"))
    if cat not in CATEGORIES or not h or not lead or len(h) > 200:
        return None
    blocks = []
    for b in data.get("blocks") or []:
        if (isinstance(b, (list, tuple)) and len(b) == 2
                and b[0] in ("p", "h2", "quote") and _tidy(b[1])):
            blocks.append((b[0], _tidy(b[1])))
    if len(blocks) < 4:
        return None
    return {"cat": cat, "h": h, "lead": lead, "blocks": blocks[:8]}


async def write_article(item: FeedItem, page_text: str) -> dict | None:
    content = (
        f"Источник: {item.source}\nЗаголовок: {item.title}\n\n"
        f"Текст статьи:\n{page_text[:9000]}"
    )
    try:
        raw = await _ask_claude(config.AI_POST_MODEL, _WRITE_SYSTEM, content, max_tokens=2500)
    except Exception as e:  # noqa: BLE001
        log.warning("Новость для сайта: ошибка Claude: %s", e)
        return None
    return validate_article(_parse_json(raw))


# --- Сборка и публикация ---------------------------------------------------------

def build_html(article: dict, source_url: str, source: str) -> str:
    """Тело записи блоками Gutenberg — как импортёр темы (inc/importer.php)."""
    esc = html.escape
    parts = []
    for kind, text in article["blocks"]:
        if kind == "h2":
            parts.append(f"<!-- wp:heading -->\n<h2>{esc(text)}</h2>\n<!-- /wp:heading -->")
        elif kind == "quote":
            parts.append(
                '<!-- wp:quote -->\n<blockquote class="wp-block-quote"><p>'
                f"{esc(text)}</p></blockquote>\n<!-- /wp:quote -->")
        else:
            parts.append(f"<!-- wp:paragraph -->\n<p>{esc(text)}</p>\n<!-- /wp:paragraph -->")
    parts.append(
        f'<!-- wp:paragraph -->\n<p><em>По материалам <a href="{esc(source_url)}" '
        f'target="_blank" rel="noopener">{esc(source)}</a>. Текст подготовила редакция '
        "podslushano.nl.</em></p>\n<!-- /wp:paragraph -->")
    return "\n\n".join(parts)


_TRANSLIT = dict(zip(
    "абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
    ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "y", "k", "l", "m", "n", "o",
     "p", "r", "s", "t", "u", "f", "kh", "ts", "ch", "sh", "shch", "", "y", "", "e",
     "yu", "ya"],
))


def make_slug(title: str, max_len: int = 60) -> str:
    """Короткий латинский адрес записи из русского заголовка."""
    text = "".join(_TRANSLIT.get(ch, ch) for ch in (title or "").casefold())
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    if len(text) > max_len:
        text = text[:max_len].rsplit("-", 1)[0]
    return text


async def _category_id(name: str) -> int | None:
    if PARENT_CATEGORY not in _category_ids:
        parent = await wp.ensure_category(PARENT_CATEGORY)
        if not parent:
            return None
        _category_ids[PARENT_CATEGORY] = parent
    if name not in _category_ids:
        cid = await wp.ensure_category(name, parent_id=_category_ids[PARENT_CATEGORY])
        if not cid:
            return _category_ids[PARENT_CATEGORY]
        _category_ids[name] = cid
    return _category_ids[name]


async def download_image(url: str) -> tuple[bytes, str] | None:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, headers={"User-Agent": _UA}, timeout=aiohttp.ClientTimeout(total=30),
            ) as r:
                mime = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
                if r.status != 200 or not mime.startswith("image/"):
                    return None
                data = await read_limited(r, _MAX_IMAGE_BYTES + 1)
    except Exception as e:  # noqa: BLE001
        log.warning("Фото %s не скачалось: %s", url, e)
        return None
    if not data or len(data) > _MAX_IMAGE_BYTES:
        return None
    return data, mime


async def _upload_photo(image_url: str, article: dict, source: str, slug: str) -> int | None:
    got = await download_image(image_url)
    if not got:
        return None
    data, mime = got
    ext = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp",
           "image/gif": "gif"}.get(mime, "jpg")
    media, err = await wp.upload_media(
        f"{slug or 'news'}.{ext}", data, mime,
        caption=f"Фото: {source}", alt_text=f"{article['h']}. Фото: {source}",
    )
    if not media:
        log.warning("Фото новости не загрузилось: %s", err)
        return None
    return media.get("id")


async def _notify_admins(bot, article: dict, link: str, source_url: str) -> None:
    text = (
        "📰 Новость опубликована на сайте\n"
        f"<b>{html.escape(article['h'])}</b>\n"
        f"{html.escape(link)}\n"
        f"Источник: {html.escape(source_url)}"
    )
    for admin_id in config.ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, parse_mode="HTML",
                                   disable_web_page_preview=True)
        except Exception as e:  # noqa: BLE001
            log.warning("Не удалось уведомить админа %s: %s", admin_id, e)


async def publish_item(bot, item: FeedItem) -> bool:
    """Пишет и публикует одну новость. Всегда записывает итог в site_news_items."""
    page = await fetch_article(item.url)
    source_url = (page or {}).get("url") or item.url
    # У NOS полный текст статьи уже лежит в описании ленты; страница — запасной вариант.
    text = item.description
    if len(text) < 600 and page and len(page.get("text") or "") > len(text):
        text = page["text"]
    if len(text) < 150:
        await _record(item, "failed", "нет текста статьи")
        return False

    article = await write_article(item, text)
    if not article:
        await _record(item, "failed", "Claude вернул некорректный JSON")
        return False

    slug = make_slug(article["h"])
    featured = None
    image_url = (page or {}).get("image") or item.image
    if image_url:
        featured = await _upload_photo(image_url, article, item.source, slug)

    cat_id = await _category_id(article["cat"])
    post, err = await wp.create_post(
        article["h"], build_html(article, source_url, item.source), status="publish",
        category_ids=[cat_id] if cat_id else None, featured_media=featured,
        excerpt=article["lead"], slug=slug or None,
    )
    if not post:
        await _record(item, "failed", f"WordPress: {err}")
        return False
    await _record(item, "published", article["cat"], post=post)
    log.info("Новость на сайте: %s → %s", item.url, post.get("link"))
    if bot is not None:
        await _notify_admins(bot, article, post.get("link") or post.get("edit", ""), source_url)
    return True


async def run_once(bot, now: datetime | None = None) -> None:
    """Один проход: ленты → отбор → публикация."""
    now = now or _utcnow()
    items = await collect_items()
    if not items:
        return
    if await _table_empty():
        # Первый запуск: всё, что уже есть в лентах, — старое, не публикуем.
        await _record_many(items, "skipped", "initial")
        log.info("Новости сайта: первый запуск, пропущено %s статей", len(items))
        return

    fresh = [item for item in items if is_fresh(item, now)]
    known = await _known_urls([item.url for item in fresh])
    new = [item for item in fresh if item.url not in known]
    if not new:
        return

    live = [item for item in new if "liveblog" in item.url.casefold()
            or re.match(r"live\b", item.title.casefold())]
    await _record_many(live, "skipped", "live-блог")
    new = [item for item in new if item not in live]
    if not new:
        return

    room = min(config.SITE_NEWS_PER_RUN,
               config.SITE_NEWS_DAILY_MAX - await published_today(now))
    if room <= 0:
        await _record_many(new, "skipped", "дневной лимит")
        return

    picked = await triage(new)
    if picked is None:
        return  # Claude не ответил — попробуем в следующий раз
    chosen, reasons = picked
    chosen_set = set(chosen)
    for item in new:
        if item.url not in chosen_set:
            await _record(item, "skipped", reasons.get(item.url) or "не подошла по теме")
    # Подходящие сверх лимита запуска не записываем — их возьмём в следующий раз.
    by_url = {item.url: item for item in new}
    for url in chosen[:room]:
        try:
            await publish_item(bot, by_url[url])
        except Exception as e:  # noqa: BLE001
            log.exception("Новость %s не опубликована: %s", url, e)
            await _record(by_url[url], "failed", f"ошибка: {type(e).__name__}")


async def site_news_loop(bot) -> None:
    """Фоновая задача: проверяет ленты каждые SITE_NEWS_INTERVAL секунд."""
    if not enabled():
        log.info("Автоновости сайта выключены (нужны WP_*, ключ ИИ и SITE_NEWS_ENABLED≠0)")
        return
    await asyncio.sleep(45)
    while True:
        try:
            await run_once(bot)
        except Exception as e:  # noqa: BLE001
            log.exception("Автоновости сайта: ошибка запуска: %s", e)
        await asyncio.sleep(config.SITE_NEWS_INTERVAL)
