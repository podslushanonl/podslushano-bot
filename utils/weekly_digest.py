"""Еженедельный дайджест в Telegram-канал: понедельник 09:00 (Europe/Amsterdam).

Берёт новости, опубликованные на сайте за последние 7 дней (таблица site_news_items,
status='published'), подтягивает русские заголовки и лиды из WordPress REST, просит
Claude выбрать 8–10 самых полезных и написать по одной фразе на каждую. Пост уходит
в ANNOUNCE_CHANNEL (@podslushanovnl) через utils.morning_bridge.deliver.

Отметка «неделя уже отправлена» лежит в таблице meta (ключ weekly_digest:last_week),
поэтому после перезапуска дайджест не уходит повторно. Если бот был выключен в 09:00
понедельника, пост выйдет позже в тот же понедельник, но не в другие дни.
Команда /digest_now (только админы) собирает и публикует дайджест сразу, для проверки.
"""
from __future__ import annotations

import asyncio
import html
import json
import logging
import re
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import select

import config
from database.db import get_session
from database.models import Meta, SiteNewsItem
from utils import wordpress as wp
from utils.ai import ai_enabled
from utils.morning_bridge import channel_status, deliver
from utils.site_news import _ask_claude

log = logging.getLogger(__name__)
router = Router()

AMSTERDAM = ZoneInfo("Europe/Amsterdam")
DIGEST_WEEKDAY = 0  # понедельник
DIGEST_TIME = time(9, 0)
CHECK_SECONDS = 300  # проверка раз в 5 минут
WINDOW = timedelta(days=7)
MAX_CANDIDATES = 60
MIN_ITEMS = 4
MAX_ITEMS = 10
LAST_WEEK_KEY = "weekly_digest:last_week"

_HEADER = "<b>Дайджест новостей</b>\nГлавные события недели в Нидерландах"
_FOOTER = "Вот такие новости. Не забывайте ставить огонечки 🔥"

_DIGEST_SYSTEM = """Ты — редактор Podslushano.nl, русскоязычного медиа для жителей Нидерландов.
Тебе дают заголовки и лиды новостей, уже опубликованных на сайте за последнюю неделю.
Поле link — адрес записи на сайте.

Выбери от 8 до 10 самых важных новостей для русскоязычных жителей Нидерландов.
Приоритет у практической пользы: цены, жильё, налоги, пособия, правила, транспорт, здоровье.
Одну и ту же историю бери только один раз, близкие дубли отбрасывай.
Лучше меньше, чем проходные новости.

Для каждой выбранной новости напиши одну короткую фразу по-русски (до 200 символов).
Правила:
• Только факты из заголовков и лидов. Не придумывай цифр, дат, имён и цитат.
• Голландские имена собственные, города, учреждения и компании пиши латиницей, как в Нидерландах.
  Никогда не транслитерируй их по-русски.
• Бренд пишется так: Podslushano.nl.
• Не используй выражение «по-русски».
• Без канцелярита, живым простым языком.
• Без эмодзи внутри текста, без markdown и HTML.
• link_word — слово или несколько слов из text, которые станут ссылкой. Они обязательно
  буквально встречаются в text.
• emoji — один эмодзи по теме новости.
• wp_link — точно значение link из списка.

Ответь СТРОГО JSON-массивом без пояснений:
[{"emoji": "🚆", "text": "...", "link_word": "...", "wp_link": "..."}]"""


# --- Настройки и состояние -------------------------------------------------------

def enabled() -> bool:
    return bool(config.WEEKLY_DIGEST_ENABLED and wp.wp_enabled() and ai_enabled())


def _iso_week(now: datetime) -> str:
    year, week, _ = now.isocalendar()
    return f"{year}-W{week:02d}"


async def _meta_get(key: str) -> str | None:
    async with get_session() as session:
        row = await session.get(Meta, key)
        return row.value if row and row.value else None


async def _meta_set(key: str, value: str) -> None:
    async with get_session() as session:
        await session.merge(Meta(key=key, value=value))
        await session.commit()


async def _paused() -> bool:
    from handlers.content import _is_paused  # импорт здесь, как в news_bridge

    return await _is_paused()


# --- Данные ----------------------------------------------------------------------

async def _candidates(now: datetime) -> list[tuple[int, str]]:
    """(wp_post_id, wp_link) опубликованных за 7 суток новостей, свежие первыми."""
    cutoff = (now.astimezone(timezone.utc) - WINDOW).replace(tzinfo=None)
    async with get_session() as session:
        rows = (await session.scalars(
            select(SiteNewsItem).where(
                SiteNewsItem.status == "published",
                SiteNewsItem.wp_post_id.is_not(None),
                SiteNewsItem.wp_link.is_not(None),
                SiteNewsItem.created_at >= cutoff,
            ).order_by(SiteNewsItem.created_at.desc()).limit(MAX_CANDIDATES)
        )).all()
        return [(row.wp_post_id, row.wp_link) for row in rows]


def _plain(raw: str) -> str:
    text = re.sub(r"<[^>]+>", " ", raw or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


async def _load_posts(rows: list[tuple[int, str]]) -> list[dict]:
    """Русский заголовок и лид из WordPress. Ссылка — wp_link из базы."""
    sem = asyncio.Semaphore(5)

    async def one(post_id: int, link: str) -> dict | None:
        async with sem:
            data = await wp.get_post(post_id)
        if not data:
            return None
        title = _plain((data.get("title") or {}).get("rendered", ""))
        lead = _plain((data.get("excerpt") or {}).get("rendered", ""))
        if not title:
            return None
        return {"link": link, "title": title, "lead": lead[:400]}

    results = await asyncio.gather(*(one(pid, link) for pid, link in rows))
    return [r for r in results if r]


# --- Claude и проверка ответа ---------------------------------------------------------

def _parse_items(raw: str) -> list[dict]:
    start, end = raw.find("["), raw.rfind("]")
    if start == -1 or end < start:
        return []
    try:
        data = json.loads(raw[start : end + 1])
    except Exception:  # noqa: BLE001
        return []
    return data if isinstance(data, list) else []


def _valid_items(raw_items: list, allowed_links: set[str]) -> list[dict]:
    """Оставляет только корректные пункты: ссылка из списка, link_word внутри text."""
    out: list[dict] = []
    seen: set[str] = set()
    for it in raw_items:
        if not isinstance(it, dict):
            continue
        emoji = str(it.get("emoji", "")).strip()
        text = re.sub(r"\s+", " ", str(it.get("text", ""))).strip()
        word = str(it.get("link_word", "")).strip()
        link = str(it.get("wp_link", "")).strip()
        if not (emoji and len(emoji) <= 8 and 20 <= len(text) <= 300):
            continue
        if not word or word not in text or link not in allowed_links or link in seen:
            continue
        seen.add(link)
        out.append({"emoji": emoji, "text": text, "link_word": word, "wp_link": link})
    return out[:MAX_ITEMS]


async def _pick(posts: list[dict]) -> list[dict] | None:
    """Один вызов Claude: отбор и текст. None — если модель не ответила."""
    content = "Новости за неделю:\n" + "\n".join(
        f"- link: {p['link']}\n  заголовок: {p['title']}\n  лид: {p['lead']}" for p in posts
    )
    try:
        raw = await _ask_claude(config.SITE_NEWS_WRITE_MODEL, _DIGEST_SYSTEM, content, max_tokens=3000)
    except Exception as e:  # noqa: BLE001
        log.warning("Дайджест: ошибка Claude: %s", e)
        return None
    return _valid_items(_parse_items(raw), {p["link"] for p in posts})


# --- Сборка сообщения ---------------------------------------------------------------

def render(items: list[dict]) -> str:
    blocks = []
    for it in items:
        text = html.escape(it["text"])
        word = html.escape(it["link_word"])
        anchor = f'<a href="{html.escape(it["wp_link"], quote=True)}">{word}</a>'
        text = text.replace(word, anchor, 1)
        blocks.append(f"{it['emoji']} {text}")
    return f"{_HEADER}\n\n" + "\n\n".join(blocks) + f"\n\n{_FOOTER}"


async def run_digest(bot, now: datetime) -> dict:
    """Собирает и публикует дайджест. Возвращает {status, detail, url}.

    status: posted | skipped (мало новостей) | error (Claude/WordPress/Telegram).
    """
    rows = await _candidates(now)
    posts = await _load_posts(rows)
    if len(posts) < MIN_ITEMS:
        return {"status": "skipped", "detail": f"за неделю с текстом только {len(posts)} новостей", "url": None}

    picked = await _pick(posts)
    if picked is None:
        return {"status": "error", "detail": "Claude не ответил", "url": None}
    if len(picked) < MIN_ITEMS:
        return {"status": "skipped", "detail": f"Claude отобрал только {len(picked)} новостей", "url": None}

    try:
        info = await channel_status(bot)
        message = await deliver(bot, render(picked))
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "detail": f"Telegram: {type(e).__name__}: {e}", "url": None}
    url = f"https://t.me/{info['username']}/{message.message_id}"
    log.info("Дайджест опубликован: %s (%s новостей)", url, len(picked))
    return {"status": "posted", "detail": "", "url": url}


# --- Уведомления админам ------------------------------------------------------------

async def _notify_admins(bot, text: str) -> None:
    # Та же схема, что _notify_admins в site_news: инбокс перенаправит в тему «Контент и новости».
    for admin_id in config.ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, parse_mode="HTML", disable_web_page_preview=True)
        except Exception as e:  # noqa: BLE001
            log.warning("Дайджест: не удалось уведомить админа %s: %s", admin_id, e)


async def _finish(bot, result: dict, week: str, *, mark_week: bool) -> None:
    if result["status"] == "posted":
        await _notify_admins(bot, f"🗞 Дайджест опубликован\n{html.escape(result['url'])}")
    elif result["status"] == "skipped":
        await _notify_admins(bot, f"ℹ️ Дайджест не опубликован: {html.escape(result['detail'])}")
    else:
        await _notify_admins(bot, f"⚠️ Дайджест не опубликован: {html.escape(result['detail'])}")
    # Ошибки и пропуски для расписания тоже закрывают неделю: без автоповтора и спама.
    should_mark = result["status"] == "posted" or mark_week
    if should_mark:
        await _meta_set(LAST_WEEK_KEY, week)


# --- Расписание ---------------------------------------------------------------------

async def scheduled_pass(bot, now: datetime | None = None) -> None:
    now = now or datetime.now(AMSTERDAM)
    if now.weekday() != DIGEST_WEEKDAY or now.time() < DIGEST_TIME:
        return
    week = _iso_week(now)
    if await _meta_get(LAST_WEEK_KEY) == week:
        return
    if await _paused():
        log.info("Дайджест отложен: публикация на паузе")
        return
    result = await run_digest(bot, now)
    await _finish(bot, result, week, mark_week=True)


async def weekly_digest_loop(bot) -> None:
    """Фоновая задача: проверяет расписание каждые CHECK_SECONDS секунд."""
    if not enabled():
        log.info("Недельный дайджест выключен (WEEKLY_DIGEST_ENABLED=0 или нет ANTHROPIC/WP_*)")
        return
    await asyncio.sleep(120)
    while True:
        try:
            await scheduled_pass(bot)
        except Exception as e:  # noqa: BLE001
            log.exception("Недельный дайджест: ошибка: %s", e)
        await asyncio.sleep(CHECK_SECONDS)


# --- Команда /digest_now ------------------------------------------------------------

@router.message(Command("digest_now"), F.from_user.id.in_(config.ADMIN_IDS))
async def digest_now(message: Message) -> None:
    if not enabled():
        await message.answer("Дайджест выключен: нужны WEEKLY_DIGEST_ENABLED, ANTHROPIC_API_KEY и WP_*.")
        return
    if await _paused():
        await message.answer("Публикация на паузе — дайджест не отправлен.")
        return
    await message.answer("Собираю дайджест…")
    now = datetime.now(AMSTERDAM)
    result = await run_digest(message.bot, now)
    # Ручной запуск помечает неделю только при успехе: иначе понедельничный пост не выйдет.
    await _finish(message.bot, result, _iso_week(now), mark_week=False)

