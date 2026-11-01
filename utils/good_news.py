"""Утренние «Хорошие новости»: черновик для админов, в канал НЕ публикуется.

Каждый день в 07:30 (Europe/Amsterdam); если бот был выключен — догоняем до 12:00.
Одна попытка в день (meta good_news:last_day).

Источники: RSS NOS и региональных вещателей (config.GOOD_NEWS_FEEDS) и новости нашего сайта.
Конвейер, без токенов где можно:
  1. сбор записей за 24 ч, дедупликация по URL и заголовку, отсев уже отправленных URL (Meta),
     регекс-фильтр негатива — всё до Claude;
  2. вызов 1 (Haiku): ТОЛЬКО короткий JSON-список до 3 id;
  3. вызов 2 (Haiku): тексты только для выбранных id, max_tokens 700;
  4. проверка по коду: каждое число и латинское имя с заглавной должно быть в источнике записи;
  5. футер «Источник: … · дд.мм.гггг» и исходный URL собираются кодом.
Причина пустого результата логируется; ошибка разбора отличается от «ничего не нашлось».
"""
import asyncio
import dataclasses
import json
import logging
import re
from datetime import datetime, time, timedelta, timezone
from urllib.parse import urlparse, urlunparse
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import select

import config
from database.db import get_session
from database.models import SiteNewsItem
from utils import digest_core as core
from utils import wordpress as wp
from utils.ai import _extract_text_and_sources, _get_client
from utils.site_news import FeedItem, fetch_feed, normalize_url, parse_feed

log = logging.getLogger(__name__)

AMSTERDAM = ZoneInfo("Europe/Amsterdam")
POST_TIME = time(7, 30)
CATCHUP_UNTIL = time(12, 0)  # догоняем только утром
CHECK_SECONDS = 300
WINDOW = timedelta(hours=24)
MAX_CANDIDATES = 60  # сколько записей уходит в Claude
MAX_ITEMS = 3
DESC_SELECT = 200  # описание в вызове 1 (только для отбора)
DESC_WRITE = 600  # описание в вызове 2 (для текста)
DESC_VERIFY = 1500  # описание, по которому проверяются числа и имена
SELECT_MAX_TOKENS = 100  # вызов 1: только короткий список id
WRITE_MAX_TOKENS = 700  # вызов 2: тексты для выбранных записей
HEADLINE_MAX_WORDS = 10  # в промпте просим не больше 8; 10 — допуск
TEXT_MAX_CHARS = 300
LAST_DAY_KEY = "good_news:last_day"
SENT_KEY = "good_news:sent_urls"  # JSON {url_key: дата отправки}
SENT_KEEP_DAYS = 14
SENT_MAX = 500
SITE_SOURCE = "Голландский перекрёсток"

HEADER = "☀️ Хорошие новости для «Голландского перекрёстка»\n\nДоброе утро ☕️ Немного хорошего на сегодня:"
FOOTER = "Хорошего дня 🧡"
EMPTY = "Сегодня хороших новостей не нашлось 🙈"
ERROR_PREFIX = "⚠️ Ошибка, а не отсутствие новостей: "

# Домен → название вещателя для футера.
BROADCASTERS = {
    "nos.nl": "NOS",
    "omroepbrabant.nl": "Omroep Brabant",
    "rtvoost.nl": "RTV Oost",
    "rtvutrecht.nl": "RTV Utrecht",
    "omroepgelderland.nl": "Omroep Gelderland",
    "rtvnoord.nl": "RTV Noord",
    "rijnmond.nl": "Rijnmond",
    "omroepwest.nl": "Omroep West",
    "omroepzeeland.nl": "Omroep Zeeland",
    "rtvdrenthe.nl": "RTV Drenthe",
    "omropfryslan.nl": "Omrop Fryslân",
    "l1.nl": "L1",
    "nhnieuws.nl": "NH Nieuws",
    "omroepflevoland.nl": "Omroep Flevoland",
}

# Жёсткий фильтр по заголовку и описанию — до Claude.
EXCLUDE = re.compile(
    r"\b("
    r"погиб|смерт|умер|умира|ДТП|авари[яиюе]|пожар(?:а|е|у|ом|ов|ы)?\b|ранен|ранил|арест|полици|"
    r"убий|убит|нападен|изнасил|войн|армия|армии|армию|ракет|атак|терак|стачк|забастов|увольн|"
    r"сокращени|банкрот|наводнени|шторм|ураган|эвакуац|взрыв|мошенни|преступ|политик|цены|цена\b|"
    r"подорожа|повышени|болезн|больн|рак\b|инсульт|инфаркт|онколог|"
    r"doden|dode\b|dood\b|gewond|ongeluk|ongeval|brand\b|politie|oorlog|staking|prijs|ziek\b|"
    r"aanslag|diefstal|inbraak|overled|overlijd|gewond|verongel"
    r")",
    re.IGNORECASE,
)

NUMBER_RE = re.compile(r"\d+")
LATIN_NAME_RE = re.compile(r"(?<![A-Za-zÀ-ÿ])[A-Z][A-Za-zÀ-ÿ'’-]+")  # латинские слова с заглавной
_BAD_XML_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")
_BARE_AMP = re.compile(r"&(?!#?\w+;)")
_XML_DECL_ENCODING = re.compile(r"^(\s*<\?xml[^>]*encoding=[\"'])[^\"']+", re.IGNORECASE)


def enabled() -> bool:
    return core.enabled(config.GOOD_NEWS_ENABLED)


def is_due(now: datetime) -> bool:
    """Утренний промежуток: с 07:30 до 12:00 по Амстердаму."""
    local = now.astimezone(AMSTERDAM).time()
    return POST_TIME <= local < CATCHUP_UNTIL


def excluded(title: str, text: str) -> bool:
    return bool(EXCLUDE.search(f"{title} {text}"))


def broadcaster(url: str) -> str:
    host = (urlparse(url).hostname or "").casefold().removeprefix("www.")
    for domain, name in BROADCASTERS.items():
        if host == domain or host.endswith("." + domain):
            return name
    return host or "Источник"


def url_key(url: str) -> str:
    """Ключ для сравнения URL: без utm-меток, якоря, лишнего слэша; хост в нижнем регистре."""
    p = urlparse(normalize_url(url))
    return urlunparse(p._replace(netloc=p.netloc.lower())).rstrip("/")


def _title_key(title: str) -> str:
    return re.sub(r"[\W_]+", " ", title.casefold()).strip()


def sanitize_feed(raw: bytes) -> bytes:
    """Мягкая очистка перед разбором: недопустимые символы XML, голый «&», кодировка в объявлении."""
    text = raw.decode("utf-8", errors="replace")
    text = _BAD_XML_CHARS.sub("", text)
    text = _BARE_AMP.sub("&amp;", text)
    text = _XML_DECL_ENCODING.sub(r"\g<1>utf-8", text, count=1)
    return text.encode("utf-8")


# --- Сбор записей (без LLM) ----------------------------------------------------------

async def _load_feed(url: str) -> list[FeedItem]:
    raw = await fetch_feed(url)
    if not raw:
        log.warning("Хорошие новости: лента пропущена (не загрузилась): %s", url)
        return []
    items = parse_feed(sanitize_feed(raw), url)
    if not items:
        log.warning("Хорошие новости: лента пропущена (нет записей или не XML): %s", url)
    name = broadcaster(url)
    return [dataclasses.replace(it, source=name) for it in items]


async def _load_all_feeds() -> list[FeedItem]:
    results = await asyncio.gather(*(_load_feed(u) for u in config.GOOD_NEWS_FEEDS), return_exceptions=True)
    items: list[FeedItem] = []
    for url, res in zip(config.GOOD_NEWS_FEEDS, results):
        if isinstance(res, BaseException):
            log.warning("Хорошие новости: ошибка ленты %s: %s", url, res)
            continue
        items += res
    return items


async def _site_items(since: datetime) -> list[FeedItem]:
    """Наши новости за окно: ссылка — wp_link, выдержка — из WordPress."""
    cutoff = since.astimezone(timezone.utc).replace(tzinfo=None)
    async with get_session() as session:
        rows = (await session.execute(
            select(SiteNewsItem.wp_post_id, SiteNewsItem.wp_link,
                   SiteNewsItem.title_nl, SiteNewsItem.created_at).where(
                SiteNewsItem.status == "published",
                SiteNewsItem.wp_post_id.is_not(None),
                SiteNewsItem.wp_link.is_not(None),
                SiteNewsItem.created_at >= cutoff,
            ))).all()
    sem = asyncio.Semaphore(5)

    async def one(row) -> FeedItem | None:
        async with sem:
            try:
                data = await wp.get_post(row.wp_post_id)
            except Exception:  # noqa: BLE001
                data = None
        if data is not None and data.get("status", "publish") != "publish":
            return None
        title = core.plain_title(((data or {}).get("title") or {}).get("rendered", "")) or row.title_nl
        lead = core.plain_title(((data or {}).get("excerpt") or {}).get("rendered", ""))[:DESC_VERIFY]
        if not title:
            return None
        return FeedItem(url=normalize_url(row.wp_link), title=title, description=lead,
                        published=row.created_at.replace(tzinfo=timezone.utc), source=SITE_SOURCE)

    return [i for i in await asyncio.gather(*(one(r) for r in rows)) if i]


def collect(now: datetime, sent: set[str], items: list[FeedItem]) -> list[FeedItem]:
    """Предфильтр без токенов: 24 ч, без дубля URL и заголовка, без уже отправленных, без негатива."""
    cutoff = now.astimezone(timezone.utc) - WINDOW
    seen: dict[str, FeedItem] = {}
    titles: set[str] = set()
    for it in items:  # сначала наши новости (им передали выдержку), затем ленты
        if it.published is None or it.published < cutoff:
            continue
        key = url_key(it.url)
        if key in sent or key in seen:
            continue
        if excluded(it.title, it.description):
            continue
        tkey = _title_key(it.title)
        if tkey in titles:
            continue
        titles.add(tkey)
        seen[key] = it
    ranked = sorted(seen.values(), key=lambda i: i.published, reverse=True)
    return ranked[:MAX_CANDIDATES]


# --- Учёт отправленных URL (Meta) ----------------------------------------------------

async def _load_sent(now: datetime) -> dict[str, str]:
    raw = await core.meta_get(SENT_KEY)
    try:
        data = json.loads(raw) if raw else {}
    except ValueError:
        data = {}
    if not isinstance(data, dict):
        return {}
    floor = (now.astimezone(AMSTERDAM).date() - timedelta(days=SENT_KEEP_DAYS)).isoformat()
    kept = {u: d for u, d in data.items() if isinstance(d, str) and d >= floor}
    if len(kept) > SENT_MAX:
        kept = dict(sorted(kept.items(), key=lambda kv: kv[1], reverse=True)[:SENT_MAX])
    return kept


async def _save_sent(now: datetime, urls: list[str]) -> None:
    data = await _load_sent(now)
    today = now.astimezone(AMSTERDAM).date().isoformat()
    for u in urls:
        data[url_key(u)] = today
    data = dict(sorted(data.items(), key=lambda kv: kv[1], reverse=True)[:SENT_MAX])
    await core.meta_set(SENT_KEY, json.dumps(data, ensure_ascii=False))


# --- LLM -------------------------------------------------------------------------------

async def _call(system: str, user: str, max_tokens: int, label: str) -> tuple[str, str | None]:
    """Один вызов Claude. Возвращает (текст, stop_reason). Ошибки API не глушим — их покажет run()."""
    resp = await _get_client().messages.create(
        model=config.GOOD_NEWS_MODEL, max_tokens=max_tokens, system=system,
        messages=[{"role": "user", "content": user}],
        extra_body={"output_config": {"effort": "low"}},
    )
    usage = getattr(resp, "usage", None)
    stop = getattr(resp, "stop_reason", None)
    log.info("Хорошие новости [%s] модель=%s вход=%s выход=%s стоп=%s", label, config.GOOD_NEWS_MODEL,
             getattr(usage, "input_tokens", None), getattr(usage, "output_tokens", None), stop)
    return _extract_text_and_sources(resp)[0].strip(), stop


def _select_system() -> str:
    return (
        "Ты отбираешь местные новости Нидерландов для тёплой утренней подборки.\n"
        "Оценивай только по заголовку и описанию. Выбери до 3 записей, которые действительно хорошие и добрые: "
        "люди, животные, помощь соседям, сообщество, рекорды, природа, приятные сюрпризы.\n"
        "НЕ выбирай: преступления, ДТП и аварии, смерти, болезни, катастрофы, политику, войну, "
        "забастовки, повышение цен, увольнения.\n"
        "Если хороших нет — пустой список. Ответь ТОЛЬКО JSON-массивом id, например [2, 7] или []. "
        "Ничего больше."
    )


def _write_system() -> str:
    return (
        "Ты — редактор «Голландского перекрёстка», русскоязычного медиа для людей в Нидерландах.\n"
        "Для каждой записи напиши: emoji — один эмодзи по теме; headline — короткий тёплый заголовок "
        "по-русски, не больше 8 слов; text — 1–2 естественных предложения по-русски.\n"
        "Используй ТОЛЬКО заголовок и описание записи. Не добавляй фактов, чисел, имён и деталей, "
        "которых там нет. Голландские имена и места пиши латиницей, как в оригинале. Ссылки не пиши.\n"
        "Ответь ТОЛЬКО JSON-массивом без пояснений: "
        '[{"id": 3, "emoji": "🐕", "headline": "...", "text": "..."}]'
    )


def parse_ids(text: str) -> list[int] | None:
    """Список id из ответа вызова 1. None — ответ не разобран."""
    m = re.search(r"\[[\s\d,]*\]", text or "")
    if not m:
        return None
    try:
        data = json.loads(m.group())
    except ValueError:
        return None
    if not isinstance(data, list):
        return None
    ids: list[int] = []
    for v in data:
        if isinstance(v, int) and not isinstance(v, bool) and v not in ids:
            ids.append(v)
    return ids[:MAX_ITEMS]


def parse_json_array(text: str) -> list | None:
    """JSON-массив из ответа вызова 2. Обрезанный ответ или не массив — None."""
    start, end = (text or "").find("["), (text or "").rfind("]")
    if start == -1 or end < start:
        return None
    try:
        data = json.loads(text[start : end + 1])
    except ValueError:
        return None
    return data if isinstance(data, list) else None


def _clean(value: object) -> str:
    return re.sub(r"\s+", " ", value).strip() if isinstance(value, str) else ""


def validate(raw_items: list, picked: dict[int, FeedItem]) -> list[dict]:
    """Только выбранные id, не больше MAX_ITEMS. Ссылку и источник берём из записи, не из ответа."""
    out: list[dict] = []
    seen: set[int] = set()
    for entry in raw_items:
        if not isinstance(entry, dict) or len(out) == MAX_ITEMS:
            continue
        try:
            pid = int(entry.get("id"))
        except (TypeError, ValueError):
            continue
        if pid not in picked or pid in seen:
            continue
        headline, text = _clean(entry.get("headline")), _clean(entry.get("text"))
        if not headline or not text or len(headline.split()) > HEADLINE_MAX_WORDS:
            continue
        sentences = [s for s in re.split(r"(?<=[.!?])\s+", text) if s]
        if len(sentences) > 2 or len(text) > TEXT_MAX_CHARS:
            continue
        if re.search(r"https?://|www\.", f"{headline} {text}", re.IGNORECASE):
            continue
        emoji = _clean(entry.get("emoji"))
        if not emoji or len(emoji) > 8 or re.search(r"[A-Za-z0-9]", emoji):
            emoji = "🌟"
        seen.add(pid)
        out.append({"id": pid, "emoji": emoji, "headline": headline, "text": text})
    return out


def verify_item(generated: str, source: str) -> list[str]:
    """Числа и латинские слова с заглавной из текста должны быть в источнике. Возвращает то, чего нет."""
    missing = [n for n in NUMBER_RE.findall(generated) if n not in set(NUMBER_RE.findall(source))]
    src_low = source.casefold()
    missing += [w for w in LATIN_NAME_RE.findall(generated) if w.casefold() not in src_low]
    return missing


def verify_all(items: list[dict], picked: dict[int, FeedItem]) -> tuple[list[dict], list[str]]:
    kept: list[dict] = []
    dropped: list[str] = []
    for it in items:
        src = picked[it["id"]]
        missing = verify_item(f"{it['headline']} {it['text']}", f"{src.title} {src.description}")
        if missing:
            dropped.append(f"{src.title[:60]} → нет в источнике: {', '.join(missing)}")
            continue
        kept.append({
            **it,
            "source": src.source,
            "date": src.published.astimezone(AMSTERDAM).strftime("%d.%m.%Y"),
            "url": src.url,
        })
    return kept, dropped


def _listing(items: dict[int, FeedItem], desc_chars: int) -> str:
    return "\n".join(
        f"- id: {i} | заголовок: {it.title} | описание: {it.description[:desc_chars]} | источник: {it.source}"
        for i, it in items.items()
    )


async def build(now: datetime) -> tuple[list[dict], str]:
    """Возвращает (записи, причина). Причина: ok | no_sources | no_candidates | model_none |
    parse_error_select | parse_error_write | validation_empty | dropped_by_verification."""
    sent = set((await _load_sent(now)).keys())
    feeds = await _load_all_feeds()
    site = await _site_items(now - WINDOW)
    if not feeds and not site:
        log.warning("Хорошие новости: нет ни одной записи (ленты и сайт пусты)")
        return [], "no_sources"
    cands = collect(now, sent, [*site, *feeds])
    log.info("Хорошие новости: записей сайт=%d лента=%d → после фильтров %d", len(site), len(feeds), len(cands))
    if not cands:
        log.info("Хорошие новости: причина — нет кандидатов после фильтров")
        return [], "no_candidates"

    by_id = dict(enumerate(cands, 1))
    text, stop = await _call(system=_select_system(), user="Записи:\n" + _listing(
        by_id, DESC_SELECT), max_tokens=SELECT_MAX_TOKENS, label="отбор")
    ids = parse_ids(text)
    if ids is None:
        log.warning("Хорошие новости: ошибка разбора ответа отбора (стоп=%s): %r", stop, (text or "")[:200])
        return [], "parse_error_select"
    picked = {i: by_id[i] for i in ids if i in by_id}
    if not ids:
        log.info("Хорошие новости: причина — модель не выбрала ни одной записи")
        return [], "model_none"
    if not picked:
        log.warning("Хорошие новости: модель вернула неизвестные id %s", ids)
        return [], "parse_error_select"

    text, stop = await _call(system=_write_system(), user="Записи:\n" + _listing(
        picked, DESC_WRITE), max_tokens=WRITE_MAX_TOKENS, label="текст")
    if stop == "max_tokens":
        log.warning("Хорошие новости: текст обрезан по max_tokens (%d)", WRITE_MAX_TOKENS)
        return [], "parse_error_write"
    raw = parse_json_array(text)
    if raw is None:
        log.warning("Хорошие новости: ошибка разбора текстов (стоп=%s): %r", stop, (text or "")[:200])
        return [], "parse_error_write"
    validated = validate(raw, picked)
    if not validated:
        log.info("Хорошие новости: причина — ни один текст не прошёл проверку формата")
        return [], "validation_empty"
    kept, dropped = verify_all(validated, picked)
    for reason in dropped:
        log.warning("Хорошие новости: запись отброшена проверкой: %s", reason)
    if not kept:
        return [], "dropped_by_verification"
    return kept, "ok"


def render(items: list[dict]) -> str:
    """Обычный текст без HTML: копируется в Instagram как есть."""
    if not items:
        return EMPTY
    blocks = [
        f"{it['emoji']} {it['headline']}\n{it['text']}\nИсточник: {it['source']} · {it['date']}\n{it['url']}"
        for it in items
    ]
    return f"{HEADER}\n\n" + "\n\n".join(blocks) + f"\n\n{FOOTER}"


async def send_to_admins(bot, text: str) -> None:
    # Та же схема, что _notify_admins: инбокс направит в тему «Контент и новости» (utils.good_news).
    for admin_id in config.ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, disable_web_page_preview=True)
        except Exception as e:  # noqa: BLE001
            log.warning("Хорошие новости: не удалось отправить админу %s: %s", admin_id, e)


async def run(bot, now: datetime | None = None) -> str:
    """Собирает и отправляет черновик админам. Статус: sent | none | error."""
    now = now or datetime.now(AMSTERDAM)
    try:
        items, reason = await build(now)
    except Exception as e:  # noqa: BLE001
        log.exception("Хорошие новости: ошибка API или сборки: %s", e)
        await send_to_admins(bot, f"{ERROR_PREFIX}{type(e).__name__}: {e}")
        return "error"
    if reason.startswith("parse_error"):
        step = "отбор" if reason.endswith("select") else "текст"
        await send_to_admins(bot, f"{ERROR_PREFIX}не разобрали ответ модели ({step}), см. лог")
        return "error"
    if reason == "no_sources":
        await send_to_admins(bot, f"{ERROR_PREFIX}ни одна лента и не загрузилась, новостей сайта нет")
        return "error"
    log.info("Хорошие новости: итог — %s (%s), записей %d", reason, "отправлено" if items else "пусто", len(items))
    await send_to_admins(bot, render(items))
    if items:
        try:
            await _save_sent(now, [it["url"] for it in items])
        except Exception as e:  # noqa: BLE001
            log.exception("Хорошие новости: не записал отправленные URL: %s", e)
    return "sent" if items else "none"


async def scheduled_pass(bot, now: datetime | None = None) -> None:
    now = now or datetime.now(AMSTERDAM)
    if not enabled() or not is_due(now):
        return
    today = now.astimezone(AMSTERDAM).date().isoformat()
    if await core.meta_get(LAST_DAY_KEY) == today:
        return
    try:
        await run(bot, now)
    finally:
        # Одна попытка в день: при ошибке админы уже получили сообщение, повторы не нужны.
        await core.meta_set(LAST_DAY_KEY, today)


async def good_news_loop(bot) -> None:
    """Фоновая задача: проверяет расписание каждые CHECK_SECONDS секунд."""
    if not enabled():
        log.info("Хорошие новости выключены (GOOD_NEWS_ENABLED=0 или нет ANTHROPIC/WP_*)")
        return
    await asyncio.sleep(180)
    while True:
        try:
            await scheduled_pass(bot)
        except Exception as e:  # noqa: BLE001
            log.exception("Хорошие новости: ошибка расписания: %s", e)
        await asyncio.sleep(CHECK_SECONDS)


router = Router()
ADMIN = F.from_user.id.in_(config.ADMIN_IDS)
_STATUS_TEXT = {
    "sent": "Черновик отправлен админам.",
    "none": EMPTY,
    "error": "Ошибка, см. уведомление.",
}


@router.message(Command("goodnews_now"), F.chat.type == ChatType.PRIVATE, ADMIN)
async def goodnews_now(message: Message) -> None:
    if not enabled():
        await message.answer("Хорошие новости выключены или не настроены (GOOD_NEWS_ENABLED, ANTHROPIC_API_KEY, WP_*).")
        return
    now = datetime.now(AMSTERDAM)
    await message.answer("Собираю хорошие новости…")
    # Ручной запуск считается сегодняшним: утренний автозапуск не продублирует черновик.
    try:
        status = await run(message.bot, now)
    finally:
        await core.meta_set(LAST_DAY_KEY, now.date().isoformat())
    await message.answer(_STATUS_TEXT[status])

