"""Утренние «Хорошие новости»: черновик для админов, в канал НЕ публикуется.

Каждый день в 07:30 (Europe/Amsterdam); если бот был выключен — догоняем до 12:00.
Одна попытка в день (meta good_news:last_day).

Источники — RSS региональных вещателей и NOS (config.GOOD_NEWS_FEEDS), записи за 24 ч.
Экономия токенов: статьи не загружаются; регекс-фильтр работает до Claude; в Claude уходят короткие
строки «id | заголовок | начало описания» (не больше MAX_CANDIDATES) и ОДИН вызов, который
и отбирает, и пишет русский текст. Ссылка — URL исходной статьи.
"""
import asyncio
import logging
import re
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.types import Message

import config
from utils import digest_core as core
from utils.ai import _extract_text_and_sources, _get_client
from utils.site_news import fetch_feed, parse_feed

log = logging.getLogger(__name__)

AMSTERDAM = ZoneInfo("Europe/Amsterdam")
POST_TIME = time(7, 30)
CATCHUP_UNTIL = time(12, 0)  # догоняем только утром
CHECK_SECONDS = 300
WINDOW = timedelta(hours=24)
MAX_ITEMS = 3
MAX_CANDIDATES = 80  # сколько записей уходит в Claude
DESC_CHARS = 200  # сколько символов описания уходит в Claude
MAX_TOKENS = 600
HEADLINE_MAX_WORDS = 10  # в промпте просим не больше 8; 10 — допуск
TEXT_MAX_CHARS = 300
LAST_DAY_KEY = "good_news:last_day"

HEADER = "☀️ Хорошие новости для «Голландского перекрёстка»\n\nДоброе утро ☕️ Немного хорошего на сегодня:"
FOOTER = "Хорошего дня 🧡"
EMPTY = "Сегодня хороших новостей не нашлось 🙈"

# Регекс — только запасной фильтр до Claude; основной отбор делает модель.
# Стеблы, а не полные слова: «спасли», «gered», «brandweer» (пожарная служба) не попадают.
EXCLUDE = re.compile(
    r"\b("
    r"погиб|смерт|умер|умира|ДТП|авари[яиюе]|пожар(?:а|е|у|ом|ов|ы)?\b|ранен|ранил|арест|полици|"
    r"убий|убит|нападен|изнасил|войн|армия|армии|армию|ракет|атак|терак|стачк|забастов|увольн|"
    r"сокращени|банкрот|наводнени|шторм|ураган|эвакуац|взрыв|мошенни|преступ|политик|цены|цена\b|"
    r"подорожа|повышени|болезн|больн|рак\b|инсульт|инфаркт|онколог|"
    r"doden|dode\b|dood\b|gewond|ongeluk|ongeval|brand\b|politie|oorlog|staking|prijs|ziek\b|"
    r"aanslag|diefstal|inbraak|overled|overlijd|verongel"
    r")",
    re.IGNORECASE,
)


def enabled() -> bool:
    return core.enabled(config.GOOD_NEWS_ENABLED)


def is_due(now: datetime) -> bool:
    """Утренний промежуток: с 07:30 до 12:00 по Амстердаму."""
    local = now.astimezone(AMSTERDAM).time()
    return POST_TIME <= local < CATCHUP_UNTIL


def excluded(title: str, lead: str) -> bool:
    return bool(EXCLUDE.search(f"{title} {lead}"))


def _title_key(title: str) -> str:
    return re.sub(r"[\W_]+", " ", title.casefold()).strip()


def _one_line(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


async def collect(now: datetime) -> list[dict]:
    """Записи за 24 ч из всех лент: без повторов по заголовку, без регекс-совпадений, новые первыми.
    Лента, которая не загрузилась или не разобралась, пропускается молча."""
    since = now - WINDOW
    seen: set[str] = set()
    out: list[dict] = []
    for feed in config.GOOD_NEWS_FEEDS:
        try:
            raw = await fetch_feed(feed)
            if not raw:
                continue
            items = parse_feed(raw, feed)
        except Exception:  # noqa: BLE001
            continue
        for it in items:
            if it.published is None or it.published < since:
                continue
            key = _title_key(it.title)
            if not key or key in seen:
                continue
            desc = _one_line(it.description)[:DESC_CHARS]
            if excluded(it.title, desc):
                continue
            seen.add(key)
            out.append({"title": it.title, "desc": desc, "link": it.url, "published": it.published})
    out.sort(key=lambda x: x["published"], reverse=True)
    return out


def _system_prompt() -> str:
    return (
        "Ты — редактор «Голландского перекрёстка», русскоязычного медиа для людей в Нидерландах.\n"
        "Тебе дают местные новости за последние сутки в формате: id | заголовок | начало описания.\n"
        "Используй ТОЛЬКО эти данные. Не добавляй фактов, которых в них нет.\n\n"
        f"Выбери до {MAX_ITEMS} действительно хороших, добрых, тёплых местных новостей Нидерландов: люди, "
        "животные, помощь соседям, сообщество, рекорды, природа, приятные сюрпризы, открытия, достижения.\n"
        "СТРОГО НЕ берём: преступления, ДТП и аварии, смерти, болезни, катастрофы и стихийные бедствия, "
        "политику, войну, международные отношения, забастовки, повышение цен, увольнения и сокращения.\n"
        "Если хороших новостей нет — верни []. Не натягивай: лучше ничего.\n\n"
        "Для каждой выбранной записи:\n"
        "• emoji — один эмодзи по теме;\n"
        "• headline — тёплый заголовок по-русски, не больше 8 слов;\n"
        "• text — 1–2 живых предложения по-русски по заголовку и описанию;\n"
        "• голландские места и имена пиши латиницей, как в оригинале.\n"
        "Ссылки и URL не пиши.\n\n"
        "Ответь СТРОГО JSON-массивом без пояснений:\n"
        '[{"id": 12, "emoji": "🐕", "headline": "...", "text": "..."}]'
    )


async def _call_claude(system: str, user: str) -> tuple[str, object]:
    """Один вызов модели GOOD_NEWS_MODEL. Возвращает текст ответа и usage (счётчики токенов)."""
    resp = await _get_client().messages.create(
        model=config.GOOD_NEWS_MODEL, max_tokens=MAX_TOKENS, system=system,
        messages=[{"role": "user", "content": user}],
        extra_body={"output_config": {"effort": "low"}},
    )
    text = _extract_text_and_sources(resp)[0].strip()
    return text, getattr(resp, "usage", None)


def validate(raw_items: list, by_id: dict[int, dict]) -> list[dict]:
    """Только id из кандидатов, не больше MAX_ITEMS; ссылка — URL источника, не из ответа модели."""
    out: list[dict] = []
    seen: set[int] = set()
    for entry in raw_items:
        if not isinstance(entry, dict) or len(out) == MAX_ITEMS:
            continue
        try:
            item_id = int(entry.get("id"))
        except (TypeError, ValueError):
            continue
        if item_id not in by_id or item_id in seen:
            continue
        headline, text = _one_line(entry.get("headline")), _one_line(entry.get("text"))
        if not headline or not text:
            continue
        if len(headline.split()) > HEADLINE_MAX_WORDS:
            continue
        sentences = [s for s in re.split(r"(?<=[.!?])\s+", text) if s]
        if len(sentences) > 2 or len(text) > TEXT_MAX_CHARS:
            continue
        if re.search(r"https?://|www\.", f"{headline} {text}", re.IGNORECASE):
            continue
        emoji = _one_line(entry.get("emoji"))
        if not emoji or len(emoji) > 8 or re.search(r"[A-Za-z0-9]", emoji):
            emoji = "🌟"
        seen.add(item_id)
        out.append({"id": item_id, "link": by_id[item_id]["link"], "emoji": emoji,
                    "headline": headline, "text": text})
    return out


async def build(now: datetime) -> list[dict]:
    cands = (await collect(now))[:MAX_CANDIDATES]
    if not cands:
        return []
    by_id = {i: c for i, c in enumerate(cands, 1)}
    lines = "\n".join(f"{i} | {c['title']} | {c['desc']}" for i, c in by_id.items())
    text, usage = await _call_claude(_system_prompt(), "Записи:\n" + lines)
    log.info("Хорошие новости: модель=%s записей=%d вход=%s выход=%s токенов",
             config.GOOD_NEWS_MODEL, len(cands),
             getattr(usage, "input_tokens", None), getattr(usage, "output_tokens", None))
    return validate(core.parse_array(text), by_id)


def render(items: list[dict]) -> str:
    """Обычный текст без HTML и разметки: копируется в Instagram как есть."""
    if not items:
        return EMPTY
    blocks = [f"{it['emoji']} {it['headline']}\n{it['text']}\n{it['link']}" for it in items]
    return f"{HEADER}\n\n" + "\n\n".join(blocks) + f"\n\n{FOOTER}"


async def send_to_admins(bot, text: str) -> None:
    # Та же схема, что _notify_admins: инбокс направит в тему «Контент и новости» (utils.good_news).
    for admin_id in config.ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, disable_web_page_preview=True)
        except Exception as e:  # noqa: BLE001
            log.warning("Хорошие новости: не удалось отправить админу %s: %s", admin_id, e)


async def run(bot, now: datetime | None = None) -> str:
    """Собирает и отправляет черновик админам. Возвращает статус: sent | none | error."""
    now = now or datetime.now(AMSTERDAM)
    try:
        items = await build(now)
    except Exception as e:  # noqa: BLE001
        log.exception("Хорошие новости: ошибка: %s", e)
        await send_to_admins(bot, f"⚠️ Хорошие новости не собраны: {type(e).__name__}: {e}")
        return "error"
    await send_to_admins(bot, render(items))
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
        log.info("Хорошие новости выключены (GOOD_NEWS_ENABLED=0 или нет ANTHROPIC)")
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
    "error": "Ошибка, подробности отправлены админам.",
}


@router.message(Command("goodnews_now"), F.chat.type == ChatType.PRIVATE, ADMIN)
async def goodnews_now(message: Message) -> None:
    """Ручной запуск черновика. Дневной guard не расходует."""
    if not enabled():
        await message.answer("Хорошие новости выключены (GOOD_NEWS_ENABLED=0 или нет ANTHROPIC).")
        return
    status = await run(message.bot, datetime.now(AMSTERDAM))
    await message.answer(_STATUS_TEXT.get(status, status))

