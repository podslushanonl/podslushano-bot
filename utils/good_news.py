"""Утренние «Хорошие новости»: черновик для Алекса, в канал НЕ публикуется.

Каждый день в 07:30 (Europe/Amsterdam). Если бот был выключен — догоняем в тот же утренний
промежуток (до 12:00). Одна попытка в день: отметка в meta (good_news:last_day).
Кандидаты — записи сайта за последние 24 ч (заголовок и выдержка из WordPress REST).
Отбор и текст — один вызов Claude; до 3 историй или «ничего», если хорошего нет.
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
from utils import wordpress as wp
from utils.site_news import _ask_claude

log = logging.getLogger(__name__)

AMSTERDAM = ZoneInfo("Europe/Amsterdam")
POST_TIME = time(7, 30)
CATCHUP_UNTIL = time(12, 0)  # догоняем только утром
CHECK_SECONDS = 300
WINDOW = timedelta(hours=24)
MAX_ITEMS = 3
HEADLINE_MAX_WORDS = 10  # в промпте просим не больше 8; 10 — допуск
TEXT_MAX_CHARS = 300
LEAD_MAX_CHARS = 600
LAST_DAY_KEY = "good_news:last_day"
PARALLEL_WP = 5

HEADER = "☀️ Хорошие новости для «Голландского перекрёстка»\n\nДоброе утро ☕️ Немного хорошего на сегодня:"
FOOTER = "Хорошего дня 🧡"
EMPTY = "Сегодня хороших новостей не нашлось 🙈"

# Жёсткий фильтр по заголовку и выдержке — до Claude; «почти хорошие» новости не проходят.
EXCLUDE = re.compile(
    r"\b("
    # русские корни: глаголы/существительные с окончаниями
    r"погиб|смерт|умер|умира|ДТП|авари[яиюе]|пожар(?:а|е|у|ом|ов|ы)?\b|ранен|ранил|арест|полици|"
    r"убий|убит|нападен|изнасил|войн|армия|армии|армию|ракет|атак|терак|стачк|забастов|увольн|"
    r"сокращени|банкрот|наводнени|шторм|ураган|эвакуац|взрыв|мошенни|преступ|политик|цены|цена\b|"
    r"подорожа|повышени|болезн|больн|рак\b|инсульт|инфаркт|онколог|"
    # нидерландские слова (заголовки и выдержки на сайте могут быть и на нидерландском)
    r"doden|dode\b|dood\b|gewond|ongeluk|ongeval|brand\b|politie|oorlog|staking|prijs|ziek\b|"
    r"aanslag|diefstal|inbraak|overled|overlijd|gewond|verongel"
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


async def load_leads(rows: list[tuple[int, str]]) -> list[dict]:
    """Заголовок и выдержка (lead) через WordPress REST. Неопубликованные записи отбрасываются."""
    sem = asyncio.Semaphore(PARALLEL_WP)

    async def one(post_id: int, link: str) -> dict | None:
        async with sem:
            data = await wp.get_post(post_id)
        if not data or data.get("status", "publish") != "publish":
            return None
        title = core.plain_title((data.get("title") or {}).get("rendered", ""))
        lead = core.plain_title((data.get("excerpt") or {}).get("rendered", ""))[:LEAD_MAX_CHARS]
        if not title:
            return None
        return {"id": post_id, "link": link, "title": title, "lead": lead}

    results = await asyncio.gather(*(one(pid, link) for pid, link in rows))
    return [r for r in results if r and not excluded(r["title"], r["lead"])]


def _system_prompt() -> str:
    return (
        "Ты — редактор «Голландского перекрёстка», русскоязычного медиа для людей в Нидерландах.\n"
        "Тебе дают записи сайта за последние сутки: wp_post_id, русский заголовок и выдержку (lead).\n"
        "Используй ТОЛЬКО эти данные. Не добавляй фактов, которых в них нет.\n\n"
        "Выбери до 3 действительно хороших, добрых, тёплых местных новостей Нидерландов: люди, животные, "
        "помощь соседям, сообщество, рекорды, природа, приятные сюрпризы.\n"
        "СТРОГО НЕ берём: преступления, ДТП и аварии, смерти, болезни, катастрофы и стихийные бедствия, "
        "политику, войну, международные отношения, забастовки, повышение цен, увольнения и сокращения.\n"
        "Если хороших новостей нет — верни пустой массив []. Не натягивай: лучше ничего.\n\n"
        "Для каждой выбранной записи:\n"
        "• emoji — один эмодзи по теме;\n"
        "• headline — короткий тёплый заголовок по-русски, не больше 8 слов;\n"
        "• text — 1–2 живых предложения по-русски по заголовку и выдержке;\n"
        "• голландские места и имена пиши латиницей, как в оригинале, без перевода.\n"
        "Ссылки и URL не пиши.\n\n"
        "Ответь СТРОГО JSON-массивом без пояснений:\n"
        '[{"wp_post_id": 123, "emoji": "🐕", "headline": "...", "text": "..."}]'
    )


def _clean(value: object) -> str:
    return re.sub(r"\s+", " ", value).strip() if isinstance(value, str) else ""


def validate(raw_items: list, by_id: dict[int, dict]) -> list[dict]:
    """Только id из кандидатов, не больше MAX_ITEMS; ссылка — из WordPress, не из ответа модели."""
    out: list[dict] = []
    seen: set[int] = set()
    for entry in raw_items:
        if not isinstance(entry, dict) or len(out) == MAX_ITEMS:
            continue
        try:
            post_id = int(entry.get("wp_post_id"))
        except (TypeError, ValueError):
            continue
        if post_id not in by_id or post_id in seen:
            continue
        headline, text = _clean(entry.get("headline")), _clean(entry.get("text"))
        if not headline or not text:
            continue
        if len(headline.split()) > HEADLINE_MAX_WORDS:
            continue
        sentences = [s for s in re.split(r"(?<=[.!?])\s+", text) if s]
        if len(sentences) > 2 or len(text) > TEXT_MAX_CHARS:
            continue
        if re.search(r"https?://|www\.", f"{headline} {text}", re.IGNORECASE):
            continue
        emoji = _clean(entry.get("emoji"))
        if not emoji or len(emoji) > 8 or re.search(r"[A-Za-z0-9]", emoji):
            emoji = "🌟"
        seen.add(post_id)
        out.append({"id": post_id, "link": by_id[post_id]["link"], "emoji": emoji,
                    "headline": headline, "text": text})
    return out


async def build(now: datetime) -> list[dict]:
    rows = await core.candidates(now - WINDOW)
    leads = await load_leads(rows)
    if not leads:
        return []
    listing = "\n".join(
        f"- wp_post_id: {it['id']} | заголовок: {it['title']} | выдержка: {it['lead']}" for it in leads
    )
    raw = await _ask_claude(config.SITE_NEWS_WRITE_MODEL, _system_prompt(), "Записи:\n" + listing, max_tokens=1500)
    return validate(core.parse_array(raw), {it["id"]: it for it in leads})


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
    await message.answer({"sent": "Черновик отправлен админам.", "none": EMPTY, "error": "Ошибка, см. уведомление."}[status])

