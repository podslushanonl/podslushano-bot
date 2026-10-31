"""Общее ядро дайджестов: недельного и ежедневного.

Источник — site_news_items (status='published') и русские заголовки записей WordPress.
Claude выбирает записи, упорядочивает их, подбирает эмодзи и отмечает 1–2 слова заголовка
для ссылки. Сам текст заголовка не меняется: в ссылку оборачивается только выбранный фрагмент.

Тестовый режим: DIGEST_TEST_RUNS одобренных запусков на рубрику (по умолчанию 0 — выключен,
всё публикуется сразу). Пока одобрений меньше — черновик админам с кнопками.
"""
from __future__ import annotations

import asyncio
import html
import json
import logging
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select

import config
from database.db import get_session
from database.models import Meta, SiteNewsItem
from utils import wordpress as wp
from utils.ai import ai_enabled
from utils.morning_bridge import channel_status, deliver
from utils.site_news import _ask_claude

log = logging.getLogger(__name__)

MAX_TEXT = 3800  # запас до лимита Telegram 4096
MAX_CANDIDATES = 80
PARALLEL_WP = 5
_RUN_LOCK = asyncio.Lock()


@dataclass(frozen=True)
class Rubric:
    key: str
    label: str
    header: str
    footer: str
    max_items: int
    min_items: int


WEEKLY = Rubric(
    key="weekly",
    label="недельный дайджест",
    header="<b>Дайджест новостей</b>\n\nГлавные события недели в Нидерландах",
    footer="Вот такие новости. Не забывайте ставить огонечки 🔥\n\n#pnl_дайджест",
    max_items=20,
    min_items=4,
)
DAILY = Rubric(
    key="daily",
    label="новости дня",
    header="<b>Новости дня</b>",
    footer="#pnl_новости",
    max_items=config.DAILY_DIGEST_MAX_ITEMS,
    min_items=3,
)
RUBRICS = {WEEKLY.key: WEEKLY, DAILY.key: DAILY}


# --- Состояние (таблица meta) --------------------------------------------------------

async def meta_get(key: str) -> str | None:
    async with get_session() as session:
        row = await session.get(Meta, key)
        return row.value if row and row.value else None


async def meta_set(key: str, value: str) -> None:
    async with get_session() as session:
        await session.merge(Meta(key=key, value=value))
        await session.commit()


def test_runs() -> int:
    """Сколько одобренных тестовых запусков нужно рубрике. 0 — тестового режима нет."""
    return max(0, int(config.DIGEST_TEST_RUNS))


def _count_key(rubric_key: str) -> str:
    return f"digest:approved:{rubric_key}"


async def approved_count(rubric_key: str) -> int:
    return int(await meta_get(_count_key(rubric_key)) or 0)


async def in_test_mode(rubric_key: str) -> bool:
    runs = test_runs()
    return runs > 0 and await approved_count(rubric_key) < runs


async def reset_tests() -> None:
    for key in RUBRICS:
        await meta_set(_count_key(key), "0")


def enabled(flag: bool) -> bool:
    return bool(flag and wp.wp_enabled() and ai_enabled())


async def is_paused() -> bool:
    from handlers.content import _is_paused  # импорт здесь, как в news_bridge

    return await _is_paused()


# --- Данные ----------------------------------------------------------------------------

async def candidates(since: datetime) -> list[tuple[int, str]]:
    """(wp_post_id, wp_link) опубликованных записей с момента since, свежие первыми."""
    cutoff = since.astimezone(timezone.utc).replace(tzinfo=None)
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


def plain_title(raw: str) -> str:
    """Заголовок WordPress: без тегов, сущности раскрыты, пробелы сжаты."""
    text = re.sub(r"<[^>]+>", " ", raw or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


async def load_headlines(rows: list[tuple[int, str]]) -> list[dict]:
    """Русские заголовки из WordPress. Неопубликованные и пустые записи отбрасываются."""
    sem = asyncio.Semaphore(PARALLEL_WP)

    async def one(post_id: int, link: str) -> dict | None:
        async with sem:
            data = await wp.get_post(post_id)
        if not data or data.get("status", "publish") != "publish":
            return None
        title = plain_title((data.get("title") or {}).get("rendered", ""))
        if not title or len(title) > 400:
            return None
        return {"id": post_id, "link": link, "title": title}

    results = await asyncio.gather(*(one(pid, link) for pid, link in rows))
    return [r for r in results if r]


# --- Отбор (Claude) и проверка ответа ----------------------------------------------------

def _count_rule(rubric: Rubric) -> str:
    """Сколько брать: для «Новости дня» — 5–max, меньше только если день тихий."""
    if rubric.key == "daily":
        return (f"выбрать от {min(5, rubric.max_items)} до {rubric.max_items} самых важных; "
                f"если день был тихим — меньше, но не меньше {rubric.min_items}, самые важные сверху")
    return f"не больше {rubric.max_items}, самые важные сверху"


def _select_system(rubric: Rubric) -> str:
    return f"""Ты — редактор podslushano.nl, русскоязычного медиа для жителей Нидерландов.
Тебе дают записи сайта: wp_post_id и русский заголовок. Заголовки готовы: их НЕ меняй и НЕ пересказывай.

Задача — выбрать и упорядочить записи для дайджеста «{rubric.label}»: {_count_rule(rubric)}.

БЕРЁМ только местные новости Нидерландов, важные для жизни здесь: цены, жильё, налоги, пособия,
правила, транспорт, здоровье, погода и её влияние, города, общество, культура.

НЕ БЕРЁМ:
• международные отношения и зарубежную политику;
• войны и всё, что связано с войнами и военными действиями;
• геополитику;
• спортивные результаты и светские новости;
• почти одинаковые истории: из нескольких записей об одном событии оставь одну, самую полную.

Для каждой выбранной записи:
• emoji — один короткий эмодзи по теме (один символ, без букв и цифр);
• link_text — 1–2 слова ИЗ ЗАГОЛОВКА, побуквенно как в заголовке (та же форма, регистр и знаки),
  лучше всего ключевое существительное или предмет новости. Не перефразируй и не добавляй слов.

Ответь СТРОГО JSON-массивом без пояснений:
[{{"wp_post_id": 123, "emoji": "🚆", "link_text": "NS"}}]
Используй только wp_post_id из списка."""


def parse_array(raw: str) -> list:
    """JSON-массив из ответа модели, даже если он обёрнут в текст."""
    start, end = raw.find("["), raw.rfind("]")
    if start == -1 or end < start:
        return []
    try:
        data = json.loads(raw[start : end + 1])
    except ValueError:
        return []
    return data if isinstance(data, list) else []


def pick_link_text(title: str, candidate: object) -> str:
    """Фрагмент для ссылки: точная подстрока заголовка из 1–2 слов (с учётом регистра).
    Иначе — первое слово заголовка, оно всегда есть в заголовке."""
    if isinstance(candidate, str):
        text = candidate.strip()
        if (text and text in title and "\n" not in text and len(text.split()) in (1, 2)):
            return text
    return title.split()[0]


def validate_selection(raw_items: list, by_id: dict[int, dict], max_items: int) -> list[dict]:
    """Только id из кандидатов, без повторов; эмодзи короткий и без букв/цифр; link_text проверен."""
    out: list[dict] = []
    seen: set[int] = set()
    for entry in raw_items:
        if not isinstance(entry, dict):
            continue
        try:
            post_id = int(entry.get("wp_post_id"))
        except (TypeError, ValueError):
            continue
        if post_id not in by_id or post_id in seen:
            continue
        emoji = str(entry.get("emoji", "")).strip()
        if not emoji or len(emoji) > 8 or re.search(r"[A-Za-z0-9]", emoji):
            emoji = "📰"
        item = by_id[post_id]
        seen.add(post_id)
        out.append({**item, "emoji": emoji, "link_text": pick_link_text(item["title"], entry.get("link_text"))})
        if len(out) == max_items:
            break
    return out


async def select_items(rubric: Rubric, items: list[dict]) -> list[dict]:
    by_id = {it["id"]: it for it in items}
    listing = "\n".join(f"- wp_post_id: {it['id']} | заголовок: {it['title']}" for it in items)
    raw = await _ask_claude(config.SITE_NEWS_TRIAGE_MODEL, _select_system(rubric),
                            "Записи:\n" + listing, max_tokens=2000)
    return validate_selection(parse_array(raw), by_id, rubric.max_items)


# --- Сообщение ---------------------------------------------------------------------------

def _item_line(it: dict) -> str:
    """«{эмодзи} {текст}<a href=wp_link>{фрагмент}</a>{текст}» — оборачиваем только фрагмент."""
    title, frag = it["title"], it["link_text"]
    start = title.index(frag)
    before, after = title[:start], title[start + len(frag):]
    return (f'{html.escape(it["emoji"])} {html.escape(before)}'
            f'<a href="{html.escape(it["link"], quote=True)}">{html.escape(frag)}</a>'
            f'{html.escape(after)}')


def render(rubric: Rubric, items: list[dict]) -> str:
    """Заголовок, пункты через пустую строку, подпись — с пустыми строками между блоками."""
    body = "\n\n".join(_item_line(it) for it in items)
    return f"{rubric.header}\n\n{body}\n\n{rubric.footer}"


# --- Черновики, админы, публикация -------------------------------------------------------

async def notify_admins(bot, text: str, markup: InlineKeyboardMarkup | None = None) -> None:
    # Та же схема, что _notify_admins в site_news: инбокс перенаправит в тему «Контент и новости».
    for admin_id in config.ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, parse_mode="HTML",
                                   disable_web_page_preview=True, reply_markup=markup)
        except Exception as e:  # noqa: BLE001
            log.warning("Дайджест: не удалось уведомить админа %s: %s", admin_id, e)


def draft_markup(draft_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Опубликовать", callback_data=f"dg:pub:{draft_id}"),
        InlineKeyboardButton(text="❌ Пропустить", callback_data=f"dg:skip:{draft_id}"),
    ]])


async def _save_draft(draft_id: str, draft: dict) -> None:
    await meta_set(f"digest:draft:{draft_id}", json.dumps(draft, ensure_ascii=False))


async def _load_draft(draft_id: str) -> dict | None:
    raw = await meta_get(f"digest:draft:{draft_id}")
    return json.loads(raw) if raw else None


async def publish_text(bot, text: str) -> str:
    """Публикация в ANNOUNCE_CHANNEL (проверка канала — в morning_bridge). Возвращает ссылку."""
    info = await channel_status(bot)
    message = await deliver(bot, text)
    return f"https://t.me/{info['username']}/{message.message_id}"


async def produce(bot, rubric: Rubric, since: datetime) -> dict:
    """Собирает дайджест. В тестовом режиме — черновик админам, иначе публикация.

    Возвращает {status: posted|drafted|skipped, detail, url}. Частичный вывод не отправляется.
    """
    items = await load_headlines(await candidates(since))
    if len(items) < rubric.min_items:
        return {"status": "skipped", "detail": f"подходящих записей {len(items)} из {rubric.min_items}", "url": None}
    chosen = await select_items(rubric, items)
    if len(chosen) < rubric.min_items:
        return {"status": "skipped", "detail": f"Claude отобрал {len(chosen)} из {rubric.min_items}", "url": None}
    text = render(rubric, chosen)
    if len(text) > MAX_TEXT:
        raise ValueError("дайджест длиннее лимита Telegram")

    if await in_test_mode(rubric.key):
        draft_id = secrets.token_hex(4)
        await _save_draft(draft_id, {"rubric": rubric.key, "text": text, "test": True, "state": "pending"})
        done = await approved_count(rubric.key)
        head = f"🧪 Тестовый запуск: {rubric.label} ({done}/{test_runs()}). Публикация по кнопке."
        await notify_admins(bot, f"{head}\n\n{text}", draft_markup(draft_id))
        return {"status": "drafted", "detail": "", "url": None}

    url = await publish_text(bot, text)
    return {"status": "posted", "detail": "", "url": url}


async def run(bot, rubric: Rubric, since: datetime) -> dict:
    """Один запуск под общей блокировкой. Ошибки и пропуски сообщаются админам, без публикации."""
    async with _RUN_LOCK:
        if await is_paused():
            return {"status": "paused", "detail": "", "url": None}
        try:
            result = await produce(bot, rubric, since)
        except Exception as e:  # noqa: BLE001
            log.exception("Дайджест %s: ошибка: %s", rubric.key, e)
            result = {"status": "error", "detail": f"{type(e).__name__}: {e}", "url": None}
    await _announce(bot, rubric, result)
    return result


async def _announce(bot, rubric: Rubric, result: dict) -> None:
    status = result["status"]
    if status == "posted":
        text = f"🗞 Опубликовано ({rubric.label})\n{html.escape(result['url'])}"
    elif status == "skipped":
        text = f"ℹ️ {rubric.label.capitalize()} не опубликован: {html.escape(result['detail'])}"
    elif status == "error":
        text = f"⚠️ {rubric.label.capitalize()} не опубликован: {html.escape(result['detail'])}"
    else:
        return  # черновик уже отправлен; пауза — тихо
    await notify_admins(bot, text)


async def approve(bot, draft_id: str) -> str:
    draft = await _load_draft(draft_id)
    if not draft:
        return "Черновик не найден."
    if draft["state"] != "pending":
        return f"Уже обработано: {draft['state']}."
    rubric = RUBRICS[draft["rubric"]]
    draft["state"] = "publishing"  # защита от двойного нажатия
    await _save_draft(draft_id, draft)
    try:
        url = await publish_text(bot, draft["text"])
    except Exception as e:  # noqa: BLE001
        # «failed», а не «pending»: неизвестно, ушло ли сообщение — повторно не шлём
        draft["state"] = "failed"
        await _save_draft(draft_id, draft)
        await notify_admins(bot, f"⚠️ Публикация не выполнена ({rubric.label}): "
                                 f"{html.escape(type(e).__name__ + ': ' + str(e))}")
        return "Не опубликовано, см. уведомление."
    draft["state"] = "published"
    await _save_draft(draft_id, draft)
    if draft.get("test"):
        await meta_set(_count_key(rubric.key), str(await approved_count(rubric.key) + 1))
    await notify_admins(bot, f"🗞 Опубликовано ({rubric.label})\n{html.escape(url)}")
    return "Опубликовано."


async def skip(draft_id: str) -> str:
    draft = await _load_draft(draft_id)
    if not draft:
        return "Черновик не найден."
    if draft["state"] != "pending":
        return f"Уже обработано: {draft['state']}."
    draft["state"] = "skipped"
    await _save_draft(draft_id, draft)
    return "Пропущено."

