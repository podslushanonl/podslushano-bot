"""Interactive editorial radar for the private Podslushano.nl newsroom.

Each search result is a separate, scannable Telegram card. Editorial choices
are persisted and become feedback for later searches. Nothing is published to
the public channels from this module.
"""
from __future__ import annotations

import asyncio
import html
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, time
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select

import config
from database.db import get_session
from database.models import EditorialIdea
from utils import editorial_channel as editorial

log = logging.getLogger(__name__)
router = Router()
AMSTERDAM = ZoneInfo("Europe/Amsterdam")
MAX_ATTEMPTS = 2
RETRY_MINUTES = 20
RECENT_IDEA_SLOTS = 30
MIN_SCORE = 8
_generation_lock = asyncio.Lock()


@dataclass(frozen=True)
class ResearchStream:
    key: str
    label: str
    emoji: str
    starts_at: time
    ends_at: time
    instructions: str
    domains: tuple[str, ...] = ()


_QUALITY_RULES = """
Это не агрегатор и не список ссылок. Найди не больше трёх тем, ради которых редактор реально
отложит другие задачи. Лучше вернуть ноль тем, чем одну проходную.

Тема проходит только если одновременно есть:
1. конкретное новое событие, дата, решение, конфликт, редкость или неожиданный поворот;
2. понятная ставка для русскоязычного жителя Нидерландов: деньги, польза, эмоция, спор,
   узнавание себя или сильное «я этого не знал»;
3. доказательная и визуальная база: официальный документ, точное место, карта, реальные фото,
   видео, статистика, архив или официальный аккаунт.

Сразу отбрасывай:
• обычные анонсы gemeente, рядовые открытия и стандартные фестивальные списки;
• международные «дни чего-либо», дни рождения и годовщины без сильного нидерландского угла;
• бытовую криминальную хронику без последствий для широкой аудитории;
• банальности про велосипеды, тюльпаны, каналы и мельницы;
• знаменитость без нового поступка, конфликта, признания или общественной реакции;
• единичный вирусный пост без подтверждаемого масштаба;
• тему, которую нельзя показать убедительнее, чем стоковой фотографией.

Проверь каждую тему вопросом: «Станут ли её сохранять, пересылать или обсуждать хотя бы по двум
разным причинам?» Если нет — не включай. Оцени по 12 баллам: актуальность 0–3, эмоция 0–3,
польза 0–2, визуал/доказательства 0–2, срочность 0–2. Не возвращай темы ниже 8 баллов.
Не повторяй одну новость разными формулировками.

Верни только валидный JSON без markdown:
{
  "editor_note": "одна честная строка о результате поиска",
  "ideas": [
    {
      "headline": "короткий конкретный заголовок",
      "verdict": "now|develop",
      "score": 10,
      "hook": "сильный угол будущей публикации, не кликбейт",
      "what_happened": "2–3 предложения с конкретикой",
      "why_now": "почему публиковать именно сейчас",
      "audience_value": "почему это заденет или поможет нашей аудитории",
      "format": "карусель|пост|Stories|Reels|Telegram",
      "visual": "конкретные реальные материалы, которые нужно показать",
      "source_urls": ["прямая подтверждающая ссылка"]
    }
  ]
}
У каждой идеи должна быть хотя бы одна прямая подтверждающая ссылка. Не пиши готовый пост.
""".strip()

_NEWS_RULES = (
    "Ищи только важные новости, решения властей, правила, предупреждения и практические изменения: "
    "деньги, налоги, жильё, работа, транспорт, медицина, образование и документы. Соцсети — для "
    "обнаружения; факт подтверждай официальным источником либо двумя независимыми надёжными. "
    "Максимум одна криминальная тема и только с широкой значимостью. Не забирай несрочные темы "
    "специализированных потоков."
)

STREAMS: tuple[ResearchStream, ...] = (
    ResearchStream("morning", "Инфоповоды — утро", "🌅", time(7, 30), time(11, 55),
                   _NEWS_RULES + " Учти ночь, предупреждения и изменения на сегодня или ближайшие дни.",
                   ("rijksoverheid.nl", "nos.nl", "nu.nl", "cbs.nl", "knmi.nl", "ns.nl", "prorail.nl", "anwb.nl", "politie.nl")),
    ResearchStream("people", "Люди Нидерландов", "🎙", time(7, 40), time(11, 55),
                   "Ищи за 24–72 часа публичную жизнь Нидерландов: музыкантов, актёров, телеведущих, спортсменов вне результатов, крупных блогеров и королевскую семью. Нужен новый поступок, признание, конфликт, сильное интервью, общественная реакция или визуальный момент. Сплетни запрещены."),
    ResearchStream("events", "Афиша Нидерландов", "🎪", time(7, 50), time(11, 55),
                   "Ищи на ближайшие 2–8 недель только события с самостоятельным сюжетом: редкий доступ, огромный масштаб, необычная традиция, сильная локация или ограниченное окно посещения. Проверь даты, город, цену, билеты, ограничения, официальный сайт и Instagram. Прошедшее запрещено.",
                   ("evenementen.nl", "holland.com", "iamsterdam.com", "uitagendautrecht.nl", "rotterdamfestivals.nl", "denhaag.com", "thisiseindhoven.com", "visitbrabant.com")),
    ResearchStream("provinces", "Радар 12 провинций", "🗺", time(8, 0), time(11, 55),
                   "Просмотри источники всех 12 провинций. Нужны локальные истории, которые поймёт вся страна: редкая инициатива, изменение города, традиция, спор или человеческий сюжет. Обязательно назови провинцию и город. Не своди поиск к Randstad и не включай рутинные объявления gemeente."),
    ResearchStream("calendar", "Календарь Нидерландов", "📅", time(8, 10), time(11, 55),
                   "Проверь сегодня, завтра и 30 дней вперёд: официальные и локальные даты, церемонии, традиционные сезоны, городские праздники и юбилеи. Нужна история, объясняющая Нидерланды, а не календарная справка. Укажи точную дату и оптимальный день публикации.",
                   ("rijksoverheid.nl", "koninklijkhuis.nl", "nationaalarchief.nl", "canonvannederland.nl", "openluchtmuseum.nl", "cultureelerfgoed.nl", "holland.com")),
    ResearchStream("buzz", "Что обсуждают", "💬", time(8, 20), time(11, 55),
                   "Ищи за 24–72 часа заметную нидерландскую интернет-дискуссию: видео, телевидение, потребительский тренд, кампанию бренда, городскую привычку, мем или спор. Масштаб подтверди минимум двумя признаками. Единичный пост и слух запрещены."),
    ResearchStream("evergreen", "Неочевидные Нидерланды", "🔎", time(8, 30), time(11, 55),
                   "Ищи сильный журналистский evergreen: инфраструктура, архитектура, вода, транспорт, жильё, язык, дизайн, наука, история, правила или известная компания. Нужны неожиданный вопрос, доказательства и визуальный маршрут истории. Не повторяй huisarts и аренду.",
                   ("canonvannederland.nl", "rijksmuseum.nl", "openluchtmuseum.nl", "cultureelerfgoed.nl", "nationaalarchief.nl", "archieven.nl", "cbs.nl", "tudelft.nl")),
    ResearchStream("day", "Инфоповоды — день", "☀️", time(12, 0), time(16, 55),
                   _NEWS_RULES + " Ищи только появившееся после утра или существенное подтверждённое развитие.",
                   ("rijksoverheid.nl", "nos.nl", "nu.nl", "cbs.nl", "ns.nl", "prorail.nl", "anwb.nl", "politie.nl")),
    ResearchStream("evening", "Инфоповоды — вечер", "🌆", time(17, 0), time(22, 0),
                   _NEWS_RULES + " Ищи только новое после дневной проверки и сильнейший сюжет дня.",
                   ("rijksoverheid.nl", "nos.nl", "nu.nl", "cbs.nl", "ns.nl", "prorail.nl", "anwb.nl", "politie.nl")),
)
STREAM_BY_KEY = {stream.key: stream for stream in STREAMS}
_VERDICT = {"now": "🔥 БРАТЬ СЕЙЧАС", "develop": "🟠 МОЖНО РАЗВИТЬ"}
_FORMAT_LABELS = {"instagram": "Instagram", "telegram": "Telegram", "stories": "Stories", "reels": "Reels"}
_REJECTION_LABELS = {
    "boring": "банально",
    "audience": "не для нашей аудитории",
    "visual": "нет сильного визуала",
    "late": "неактуально",
}


def _now() -> datetime:
    return datetime.now(AMSTERDAM).replace(tzinfo=None)


def _is_due(stream: ResearchStream, now: datetime) -> bool:
    return stream.starts_at <= now.time() < stream.ends_at


async def _recent_ideas() -> list[str]:
    values = []
    for index in range(RECENT_IDEA_SLOTS):
        value = await editorial._meta_get(f"research_recent_{index}")
        if value:
            values.append(value)
    return values


async def _feedback_prompt(limit: int = 30) -> str:
    async with get_session() as session:
        rows = (await session.scalars(
            select(EditorialIdea).where(EditorialIdea.status.in_(("selected", "rejected")))
            .order_by(EditorialIdea.id.desc()).limit(limit)
        )).all()
    selected = [row.headline for row in rows if row.status == "selected"][:12]
    rejected = [
        f"[{_REJECTION_LABELS.get(row.feedback_reason, 'не подошло')}] {row.headline}"
        for row in rows if row.status == "rejected"
    ][:12]
    parts = []
    if selected:
        parts.append("Редактор выбирал похожие темы — положительный сигнал: " + " | ".join(selected))
    if rejected:
        parts.append("Редактор отклонил эти темы — не повторяй их механику без нового сильного угла: " + " | ".join(rejected))
    return "\n".join(parts) or "Истории редакторских выборов пока нет."


def _parse_payload(raw: str, tool_sources: list[str] | None = None) -> dict | None:
    clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", (raw or "").strip())
    start, end = clean.find("{"), clean.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        source = json.loads(clean[start:end + 1])
    except (TypeError, ValueError):
        return None
    raw_ideas = source.get("ideas")
    if not isinstance(raw_ideas, list):
        return None
    fallback_sources = [url for url in (tool_sources or []) if str(url).startswith("http")][:3]
    ideas = []
    for item in raw_ideas[:3]:
        if not isinstance(item, dict):
            continue
        try:
            score = max(0, min(12, int(item.get("score", 0))))
        except (TypeError, ValueError):
            continue
        urls = [str(url).strip() for url in item.get("source_urls", []) if str(url).startswith("http")][:3]
        if not urls:
            urls = fallback_sources
        required = ("headline", "hook", "what_happened", "why_now", "audience_value", "visual")
        if score < MIN_SCORE or not urls or any(not str(item.get(key) or "").strip() for key in required):
            continue
        ideas.append({
            "headline": str(item["headline"]).strip()[:240],
            "verdict": str(item.get("verdict")) if item.get("verdict") in _VERDICT else "develop",
            "score": score,
            "hook": str(item["hook"]).strip()[:500],
            "what_happened": str(item["what_happened"]).strip()[:900],
            "why_now": str(item["why_now"]).strip()[:500],
            "audience_value": str(item["audience_value"]).strip()[:600],
            "format": str(item.get("format") or "карусель").strip()[:80],
            "visual": str(item["visual"]).strip()[:700],
            "source_urls": urls,
        })
    return {"editor_note": str(source.get("editor_note") or "").strip()[:500], "ideas": ideas}


async def _generate_digest(stream: ResearchStream) -> dict | None:
    recent = await _recent_ideas()
    published = await editorial._recent_topics()
    exclusions = " | ".join((recent + published)[:24]) or "нет"
    feedback = await _feedback_prompt()
    system = (
        "Ты — требовательный выпускающий редактор Podslushano.nl, локального русскоязычного медиа "
        "о Нидерландах. Проведи свежий веб-поиск. " + stream.instructions + "\n\n" + _QUALITY_RULES
    )
    user = (
        f"Сегодня {_now():%d.%m.%Y}, Europe/Amsterdam. Поток: {stream.label}.\n"
        f"Нельзя повторять без существенного развития: {exclusions}.\n{feedback}"
    )
    async with _generation_lock:
        result = await editorial._generate(system, user, list(stream.domains), 2200)
    if not result:
        return None
    return _parse_payload(result[0], result[1])


async def _remember_ideas(payload: dict) -> None:
    fresh = [item["headline"] for item in payload.get("ideas", [])]
    if not fresh:
        return
    recent = await _recent_ideas()
    fresh_keys = {value.casefold() for value in fresh}
    merged = fresh + [old for old in recent if old.casefold() not in fresh_keys]
    for index, value in enumerate(merged[:RECENT_IDEA_SLOTS]):
        await editorial._meta_set(f"research_recent_{index}", value)


async def _topic_destination(stream: ResearchStream) -> tuple[int | None, int | None]:
    raw_chat = await editorial._meta_get("research_desk_chat_id")
    raw_topic = await editorial._meta_get(f"research_topic_{stream.key}")
    try:
        return (int(raw_chat), int(raw_topic)) if raw_chat and raw_topic else (None, None)
    except ValueError:
        return None, None


def _card_text(item: dict) -> str:
    esc = lambda value: html.escape(str(value or ""))
    return (
        f"{_VERDICT[item['verdict']]} · <b>{item['score']}/12</b>\n\n"
        f"<b>{esc(item['headline'])}</b>\n\n"
        f"<blockquote>{esc(item['hook'])}</blockquote>\n\n"
        f"<b>Что произошло</b>\n{esc(item['what_happened'])}\n\n"
        f"<b>Почему сейчас</b>\n{esc(item['why_now'])}\n\n"
        f"<b>Почему зайдёт</b>\n{esc(item['audience_value'])}\n\n"
        f"<b>Как показать</b>\n{esc(item['visual'])}\n\n"
        f"<b>Лучший формат:</b> {esc(item['format'])}"
    )


def _idea_kb(idea_id: int, item: dict) -> InlineKeyboardMarkup:
    rows = []
    urls = item.get("source_urls", [])[:2]
    if urls:
        rows.append([InlineKeyboardButton(text=f"🔗 Источник {i + 1}", url=url) for i, url in enumerate(urls)])
    rows.extend([
        [InlineKeyboardButton(text="✅ В работу", callback_data=f"ideawork:{idea_id}"),
         InlineKeyboardButton(text="🔎 Углубить", callback_data=f"ideadeep:{idea_id}")],
        [InlineKeyboardButton(text="📌 В запас", callback_data=f"ideareserve:{idea_id}"),
         InlineKeyboardButton(text="🚫 Не подходит", callback_data=f"ideareject:{idea_id}")],
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _save_idea(stream: ResearchStream, item: dict) -> int:
    async with get_session() as session:
        row = EditorialIdea(stream_key=stream.key, headline=item["headline"],
                            payload_json=json.dumps(item, ensure_ascii=False), status="pending")
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row.id


async def _load_idea(idea_id: int) -> tuple[EditorialIdea, dict] | None:
    async with get_session() as session:
        row = await session.get(EditorialIdea, idea_id)
        if not row:
            return None
        try:
            return row, json.loads(row.payload_json)
        except (TypeError, ValueError):
            return None


async def _deliver_digest(bot, stream: ResearchStream, payload: dict) -> bool:
    ideas = payload.get("ideas", [])
    note = html.escape(payload.get("editor_note") or "")
    summary = (
        f"{stream.emoji} <b>{html.escape(stream.label)}</b>\n"
        f"{_now():%d.%m.%Y} · сильных тем: <b>{len(ideas)}</b>\n\n"
        f"{note or ('Проходных тем нет — выпуск намеренно пустой.' if not ideas else 'Ниже только темы, прошедшие жёсткий отбор.')}"
    )
    chat_id, topic_id = await _topic_destination(stream)
    targets = [(chat_id, topic_id)] if chat_id else [(admin_id, None) for admin_id in config.ADMIN_IDS]
    stored_ideas = [(await _save_idea(stream, item), item) for item in ideas]
    delivered = False
    for target_chat, target_topic in targets:
        if target_chat is None:
            continue
        try:
            await bot.send_message(target_chat, summary, message_thread_id=target_topic,
                                   parse_mode="HTML", disable_web_page_preview=True)
            for idea_id, item in stored_ideas:
                await bot.send_message(target_chat, _card_text(item), message_thread_id=target_topic,
                                       parse_mode="HTML", disable_web_page_preview=True,
                                       reply_markup=_idea_kb(idea_id, item))
            delivered = True
        except Exception as exc:  # noqa: BLE001
            log.warning("Cannot deliver research stream %s to %s: %s", stream.key, target_chat, exc)
    return delivered


async def _alert_failure(bot, stream: ResearchStream, detail: str) -> None:
    for admin_id in config.ADMIN_IDS:
        try:
            await bot.send_message(admin_id, f"⚠️ {stream.label}: поиск не завершён. {detail}\nПовтор будет автоматически; вручную: /ideas.", parse_mode=None)
        except Exception:
            pass


async def _run_stream(bot, stream: ResearchStream, now: datetime, *, force: bool = False) -> bool:
    today = now.date().isoformat()
    date_key = f"research_digest_{stream.key}_date"
    if not force and (await editorial._meta_get(date_key) == today or not _is_due(stream, now)):
        return False
    attempt_key = f"research_digest_{stream.key}_attempts_{today}"
    cooldown_key = f"research_digest_{stream.key}_try"
    try:
        attempts = int(await editorial._meta_get(attempt_key) or "0")
    except ValueError:
        attempts = 0
    if not force:
        if attempts >= MAX_ATTEMPTS or not await editorial._attempt_allowed(cooldown_key, now, RETRY_MINUTES):
            return False
        await editorial._meta_set(attempt_key, attempts + 1)
    try:
        payload = await _generate_digest(stream)
    except Exception as exc:  # noqa: BLE001
        log.exception("Research stream %s failed", stream.key)
        if not force:
            await _alert_failure(bot, stream, f"Ошибка {type(exc).__name__}.")
        return False
    if payload is None:
        if not force:
            await _alert_failure(bot, stream, "Web Search не вернул проверенный результат.")
        return False
    if not await _deliver_digest(bot, stream, payload):
        return False
    await _remember_ideas(payload)
    if not force:
        await editorial._meta_set(date_key, today)
    return True


def _ideas_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{stream.emoji} {stream.label}", callback_data=f"ideas:{stream.key}")]
        for stream in STREAMS
    ])


@router.message(Command("ideas", "editorialdesk"))
async def ideas_command(message: Message) -> None:
    if message.from_user.id not in config.ADMIN_IDS:
        return
    chat_id, _ = await _topic_destination(STREAMS[0])
    destination = "отдельные темы редакционной группы" if chat_id else "личный чат с ботом"
    await message.answer(
        "🧭 <b>Редакционный радар</b>\n\n"
        "Каждая находка приходит отдельной карточкой с оценкой, источниками и действиями. "
        "Слабые подборки бот не добивает для количества.\n\n"
        f"Доставка: {destination}.", parse_mode="HTML", reply_markup=_ideas_menu())


@router.callback_query(F.data.startswith("ideas:"), F.from_user.id.in_(config.ADMIN_IDS))
async def ideas_callback(callback: CallbackQuery) -> None:
    stream = STREAM_BY_KEY.get(callback.data.split(":", 1)[1])
    if not stream:
        await callback.answer("Неизвестная категория", show_alert=True)
        return
    await callback.answer("Ищу только сильные темы…")
    ok = await _run_stream(callback.bot, stream, _now(), force=True)
    await callback.message.answer(f"{'✅ Поиск завершён' if ok else '❌ Поиск не завершён'}: {stream.label}", parse_mode=None)


def _format_kb(idea_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Instagram", callback_data=f"ideaformat:{idea_id}:instagram"),
         InlineKeyboardButton(text="Telegram", callback_data=f"ideaformat:{idea_id}:telegram")],
        [InlineKeyboardButton(text="Stories", callback_data=f"ideaformat:{idea_id}:stories"),
         InlineKeyboardButton(text="Reels", callback_data=f"ideaformat:{idea_id}:reels")],
    ])


@router.callback_query(F.data.startswith("ideawork:"), F.from_user.id.in_(config.ADMIN_IDS))
async def idea_work(callback: CallbackQuery) -> None:
    idea_id = int(callback.data.split(":", 1)[1])
    loaded = await _load_idea(idea_id)
    if not loaded or loaded[0].status not in {"pending", "reserved"}:
        await callback.answer("Тема уже обработана", show_alert=True)
        return
    await callback.answer()
    await callback.message.answer("Для какой площадки готовим редакционное ТЗ?", reply_markup=_format_kb(idea_id))


async def _set_status(idea_id: int, status: str, chosen_format: str | None = None,
                      feedback_reason: str | None = None) -> bool:
    async with get_session() as session:
        row = await session.get(EditorialIdea, idea_id)
        if not row or row.status not in {"pending", "reserved"}:
            return False
        row.status = status
        if chosen_format:
            row.chosen_format = chosen_format
        if feedback_reason:
            row.feedback_reason = feedback_reason
        await session.commit()
        return True


@router.callback_query(F.data.startswith("ideareserve:"), F.from_user.id.in_(config.ADMIN_IDS))
async def idea_reserve(callback: CallbackQuery) -> None:
    idea_id = int(callback.data.split(":", 1)[1])
    ok = await _set_status(idea_id, "reserved")
    await callback.answer("Добавлено в запас" if ok else "Тема не найдена", show_alert=not ok)
    if ok:
        await callback.message.edit_reply_markup(reply_markup=None)


@router.callback_query(F.data.startswith("ideareject:"), F.from_user.id.in_(config.ADMIN_IDS))
async def idea_reject(callback: CallbackQuery) -> None:
    idea_id = int(callback.data.split(":", 1)[1])
    loaded = await _load_idea(idea_id)
    if not loaded or loaded[0].status not in {"pending", "reserved"}:
        await callback.answer("Тема уже обработана", show_alert=True)
        return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Слишком банально", callback_data=f"ideareason:{idea_id}:boring")],
        [InlineKeyboardButton(text="Не для нашей аудитории", callback_data=f"ideareason:{idea_id}:audience")],
        [InlineKeyboardButton(text="Нет сильного визуала", callback_data=f"ideareason:{idea_id}:visual")],
        [InlineKeyboardButton(text="Уже неактуально", callback_data=f"ideareason:{idea_id}:late")],
    ])
    await callback.answer()
    await callback.message.answer("Почему тема не подходит?", reply_markup=keyboard)


@router.callback_query(F.data.startswith("ideareason:"), F.from_user.id.in_(config.ADMIN_IDS))
async def idea_rejection_reason(callback: CallbackQuery) -> None:
    _, raw_id, reason = callback.data.split(":")
    if reason not in _REJECTION_LABELS:
        await callback.answer("Неизвестная причина", show_alert=True)
        return
    ok = await _set_status(int(raw_id), "rejected", feedback_reason=reason)
    await callback.answer("Причина сохранена — следующий поиск её учтёт" if ok else "Тема уже обработана", show_alert=not ok)
    if ok:
        await callback.message.edit_text(f"🚫 Отклонено: {_REJECTION_LABELS[reason]}", reply_markup=None)


async def _develop(idea: dict, mode: str) -> str | None:
    if mode == "deep":
        task = ("Проведи дополнительный поиск. Подготовь факт-лист: что точно известно, ключевые цифры и даты, "
                "чего нельзя утверждать, какие первоисточники и реальные визуальные материалы использовать. Не пиши пост.")
    else:
        task = (f"Подготовь практичное редакционное ТЗ для {_FORMAT_LABELS[mode]}: главный хук, логичная структура, "
                "факты и доказательства для каждого блока, конкретные визуальные материалы, финальный вопрос или CTA. Не пиши готовую публикацию.")
    result = await editorial._generate(
        "Ты — выпускающий редактор Podslushano.nl. Пиши по-русски, конкретно, без канцелярита и ИИ-штампов.",
        task + "\n\nКарточка темы:\n" + json.dumps(idea, ensure_ascii=False), [], 1700)
    return result[0] if result else None


@router.callback_query(F.data.startswith("ideadeep:"), F.from_user.id.in_(config.ADMIN_IDS))
async def idea_deep(callback: CallbackQuery) -> None:
    idea_id = int(callback.data.split(":", 1)[1])
    loaded = await _load_idea(idea_id)
    if not loaded or loaded[0].status not in {"pending", "reserved"}:
        await callback.answer("Тема уже обработана", show_alert=True)
        return
    await callback.answer("Углубляю тему…")
    result = await _develop(loaded[1], "deep")
    await callback.message.answer(result or "Не удалось получить надёжный факт-лист.", parse_mode=None, disable_web_page_preview=True)


@router.callback_query(F.data.startswith("ideaformat:"), F.from_user.id.in_(config.ADMIN_IDS))
async def idea_format(callback: CallbackQuery) -> None:
    _, raw_id, mode = callback.data.split(":")
    if mode not in _FORMAT_LABELS:
        await callback.answer("Неизвестный формат", show_alert=True)
        return
    idea_id = int(raw_id)
    loaded = await _load_idea(idea_id)
    if not loaded or loaded[0].status not in {"pending", "reserved"}:
        await callback.answer("Тема уже обработана", show_alert=True)
        return
    await callback.answer(f"Готовлю ТЗ для {_FORMAT_LABELS[mode]}…")
    result = await _develop(loaded[1], mode)
    if not result:
        await callback.message.answer("Не удалось подготовить ТЗ. Попробуйте ещё раз.", parse_mode=None)
        return
    if not await _set_status(idea_id, "selected", mode):
        await callback.message.answer("Эту тему уже обработали в другом действии.", parse_mode=None)
        return
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(f"✅ В работе · {_FORMAT_LABELS[mode]}\n\n{result}", parse_mode=None, disable_web_page_preview=True)


@router.message(Command("ideassetup"))
async def ideas_setup_command(message: Message) -> None:
    if message.from_user.id not in config.ADMIN_IDS:
        return
    if message.chat.type != "supergroup" or not getattr(message.chat, "is_forum", False):
        await message.answer("Запустите /ideassetup в закрытой супергруппе с темами. Боту нужны права управления темами.", parse_mode=None)
        return
    existing_chat = await editorial._meta_get("research_desk_chat_id")
    existing_topics = [await editorial._meta_get(f"research_topic_{stream.key}") for stream in STREAMS]
    if existing_chat == str(message.chat.id) and all(existing_topics):
        await message.answer("✅ Эта редакционная группа уже подключена: все 9 тем настроены.", parse_mode=None)
        return
    created, pending_topics = [], {}
    try:
        for stream in STREAMS:
            topic = await message.bot.create_forum_topic(message.chat.id, name=f"{stream.emoji} {stream.label}")
            pending_topics[stream.key] = topic.message_thread_id
            created.append(stream.label)
        for key, topic_id in pending_topics.items():
            await editorial._meta_set(f"research_topic_{key}", topic_id)
        await editorial._meta_set("research_desk_chat_id", message.chat.id)
    except Exception as exc:  # noqa: BLE001
        log.exception("Editorial research forum setup failed")
        await message.answer(f"❌ Не удалось создать все темы: {type(exc).__name__}. Проверьте права бота.", parse_mode=None)
        return
    await message.answer("✅ Созданы отдельные темы:\n\n" + "\n".join(f"• {name}" for name in created), parse_mode=None)


async def editorial_research_loop(bot) -> None:
    await asyncio.sleep(50)
    while True:
        try:
            now = _now()
            for stream in STREAMS:
                await _run_stream(bot, stream, now)
        except Exception as exc:  # noqa: BLE001
            log.exception("Editorial research loop failed: %s", exc)
        await asyncio.sleep(60)
