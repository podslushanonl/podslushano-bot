"""Живая редакционная линия Telegram-канала.

Дополняет служебный контент-центр тремя форматами:
- ежедневный утренний бриф: погода, транспорт, дороги;
- один выбранный анонс события вместо длинной подборки;
- небанальный факт/история о Нидерландах.

Все факты генерируются только после веб-поиска. Если поиск/ИИ недоступен,
бот ничего не публикует вместо того, чтобы выпускать потенциально устаревший текст.
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import config
from database.db import get_session
from database.models import Meta
from utils.ai import (
    _create_with_server_tool_continuation,
    _extract_text_and_sources,
    _get_client,
    _web_search_errors,
    _web_search_tool,
    ai_enabled,
)

log = logging.getLogger(__name__)
AMSTERDAM = ZoneInfo("Europe/Amsterdam")

MORNING_SOURCES = [
    "knmi.nl",
    "ns.nl",
    "prorail.nl",
    "rijkswaterstaat.nl",
    "vananaarbeter.nl",
    "9292.nl",
]

EVENT_SOURCES = [
    "evenementen.nl",
    "iamsterdam.com",
    "uitagendautrecht.nl",
    "rotterdamfestivals.nl",
    "denhaag.com",
    "thisiseindhoven.com",
    "visitbrabant.com",
    "holland.com",
]

FACT_SOURCES = [
    "canonvannederland.nl",
    "rijksmuseum.nl",
    "openluchtmuseum.nl",
    "cultureelerfgoed.nl",
    "historischcentrumoverijssel.nl",
    "stadsarchief.amsterdam.nl",
    "archieven.nl",
    "holland.com",
]

RECENT_SLOTS = 8


def _now() -> datetime:
    return datetime.now(AMSTERDAM).replace(tzinfo=None)


async def _meta_get(key: str) -> str:
    async with get_session() as session:
        row = await session.get(Meta, key)
        return row.value if row else ""


async def _meta_set(key: str, value: str) -> None:
    async with get_session() as session:
        row = await session.get(Meta, key)
        if row is None:
            session.add(Meta(key=key, value=value[:100]))
        else:
            row.value = value[:100]
        await session.commit()


async def _attempt_allowed(key: str, now: datetime, cooldown: int = 20) -> bool:
    raw = await _meta_get(key)
    if raw:
        try:
            previous = datetime.fromisoformat(raw)
            if now - previous < timedelta(minutes=cooldown):
                return False
        except ValueError:
            pass
    await _meta_set(key, now.isoformat(timespec="minutes"))
    return True


async def _recent_topics() -> list[str]:
    result: list[str] = []
    for index in range(RECENT_SLOTS):
        value = await _meta_get(f"editorial_recent_{index}")
        if value:
            result.append(value)
    return result


async def _remember_topic(text: str) -> None:
    first = next((line.strip() for line in text.splitlines() if line.strip()), "")
    first = re.sub(r"^[^\wА-Яа-яЁё]+", "", first)[:90]
    if not first:
        return
    recent = await _recent_topics()
    values = [first] + [item for item in recent if item.lower() != first.lower()]
    for index, value in enumerate(values[:RECENT_SLOTS]):
        await _meta_set(f"editorial_recent_{index}", value)


def _clean_text(text: str) -> str:
    text = re.sub(r"^```(?:text)?\s*|\s*```$", "", (text or "").strip())
    text = text.replace("**", "").replace("__", "")
    text = re.sub(r"<[^>]+>", "", text)
    return text.strip()


async def _generate(system: str, user: str, domains: list[str], max_tokens: int = 900) -> tuple[str, list[str]] | None:
    if not ai_enabled() or not config.AI_WEB_SEARCH:
        return None
    tools = _web_search_tool(domains, max_uses=6)
    if not tools:
        return None
    try:
        response = await _create_with_server_tool_continuation(
            _get_client(),
            model=config.AI_POST_MODEL,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            tools=tools,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("Editorial web generation failed: %s", exc)
        return None
    if _web_search_errors(response):
        return None
    text, sources = _extract_text_and_sources(response)
    text = _clean_text(text)
    if not text or not sources:
        return None
    return text, sources


async def _morning_brief() -> str | None:
    today = _now().strftime("%d.%m.%Y")
    system = (
        "Ты выпускающий редактор утреннего Telegram-брифа для русскоязычных жителей "
        "Нидерландов. Перед ответом обязательно проверь свежие данные веб-поиском. "
        "Используй только KNMI для погоды, NS/ProRail/9292 для общественного "
        "транспорта и Rijkswaterstaat/VanAnaarBeter для дорог. Ничего не выдумывай. "
        "Пиши по-русски, очень конкретно и естественно. Это не прогноз ради прогноза: "
        "читателю за 20 секунд должно стать понятно, понадобится ли зонт/тёплая одежда, "
        "есть ли заметные проблемы с поездами и есть ли крупные дорожные ограничения. "
        "Не перечисляй мелкие локальные задержки по всей стране. Выбирай только то, что "
        "реально может затронуть много людей. Если по транспорту или дорогам крупных "
        "проблем нет, скажи это одной короткой фразой. Не используй клише, риторические "
        "вопросы и фразы вроде «доброе утро, Нидерланды». Без markdown и HTML. "
        "Объём 450-750 знаков. Формат: первая строка короткий живой заголовок; затем "
        "три компактных блока с маркерами ☁️, 🚆, 🚗."
    )
    result = await _generate(
        system,
        f"Сегодня {today}, часовой пояс Europe/Amsterdam. Подготовь бриф именно на сегодня.",
        MORNING_SOURCES,
        max_tokens=700,
    )
    return result[0] if result else None


async def _event_spotlight() -> str | None:
    recent = await _recent_topics()
    today = _now().strftime("%d.%m.%Y")
    system = (
        "Ты редактор русскоязычного Telegram-медиа о Нидерландах. Найди ОДНО реально "
        "существующее мероприятие в Нидерландах на ближайшие 14 дней и расскажи о нём "
        "так, чтобы захотелось открыть календарь. В приоритете evenementen.nl, затем "
        "официальный сайт мероприятия или городская афиша. Проверяй дату, место, цену "
        "и статус события. Не делай подборку. Не выбирай проходное событие только потому, "
        "что оно первое в поиске. Ищи визуально, культурно или сюжетно сильный повод: "
        "фестиваль, необычная экскурсия, историческое событие, световое шоу, ярмарка, "
        "парад, музейная ночь, природный сезонный формат и т.п. Пиши как редактор, а не "
        "как рекламный буклет. Сначала конкретный хук, затем 2-3 детали, которые объясняют, "
        "почему событие стоит внимания, затем отдельной строкой дата, город/адрес, цена и "
        "официальная ссылка. Без риторических вопросов, клише, преувеличений, markdown и HTML. "
        "Объём 650-1000 знаков. Не используй банальные слова «уникальный», «атмосферный», "
        "«незабываемый», если они ничего не объясняют."
    )
    result = await _generate(
        system,
        f"Сегодня {today}. Не повторяй недавние темы: {', '.join(recent) if recent else 'нет'}.",
        EVENT_SOURCES,
        max_tokens=900,
    )
    if not result:
        return None
    text, sources = result
    # Если модель не вставила ссылку, добавляем один реальный источник поиска.
    if "http://" not in text and "https://" not in text:
        text = f"{text}\n\nИсточник: {sources[0]}"
    return text


async def _curiosity_post() -> str | None:
    recent = await _recent_topics()
    today = _now().strftime("%d.%m.%Y")
    system = (
        "Ты редактор Telegram-медиа для людей, которые уже живут в Нидерландах и знают "
        "базовые факты о стране. Найди один небанальный, проверяемый сюжет и преврати его "
        "в короткий пост. Это может быть странная деталь городской истории, происхождение "
        "обычного предмета или правила, инженерное решение, малоизвестная традиция, "
        "архитектурный след прошлого, музейный объект, языковая деталь с историей или "
        "неожиданный поворот в повседневной жизни. Факты обязательно проверяй поиском по "
        "надёжным нидерландским историческим/музейным источникам. Запрещённые банальные темы "
        "без нового угла: страна ниже уровня моря, велосипеды, тюльпаны, кофешопы, квартал "
        "красных фонарей, деревянные башмаки, ветряные мельницы, «голландцы прямолинейны». "
        "Не начинай с «А вы знали?» и не называй текст «интересным фактом». Сначала дай "
        "деталь, которая вызывает информационный разрыв, затем объясни, откуда она взялась "
        "и почему её можно заметить в Нидерландах сегодня. Пиши живо, но без выдуманных "
        "сцен, диалогов и дешёвого юмора. Без markdown и HTML. 650-1000 знаков."
    )
    result = await _generate(
        system,
        f"Сегодня {today}. Недавние темы, которые нельзя повторять: {', '.join(recent) if recent else 'нет'}.",
        FACT_SOURCES,
        max_tokens=900,
    )
    return result[0] if result else None


def _event_button() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
        text="🎭 Открыть афишу в боте",
        url=config.BOT_URL,
    )]])


async def _publish(bot, text: str, *, button: bool = False) -> bool:
    if not config.ANNOUNCE_CHANNEL:
        return False
    try:
        await bot.send_message(
            config.ANNOUNCE_CHANNEL,
            text,
            parse_mode=None,
            reply_markup=_event_button() if button else None,
            disable_web_page_preview=True,
        )
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("Editorial publish failed: %s", exc)
        return False


async def _run_morning(bot, now: datetime) -> None:
    if not (time(6, 45) <= now.time() < time(8, 15)):
        return
    date_key = now.date().isoformat()
    if await _meta_get("editorial_morning_date") == date_key:
        return
    if not await _attempt_allowed("editorial_morning_try", now):
        return
    text = await _morning_brief()
    if text and await _publish(bot, text):
        await _meta_set("editorial_morning_date", date_key)


async def _run_event(bot, now: datetime) -> None:
    # Пятница днём: один сильный повод перед выходными и следующей неделей.
    if now.weekday() != 4 or not (time(12, 30) <= now.time() < time(14, 30)):
        return
    date_key = now.date().isoformat()
    if await _meta_get("editorial_event_date") == date_key:
        return
    if not await _attempt_allowed("editorial_event_try", now, cooldown=30):
        return
    text = await _event_spotlight()
    if text and await _publish(bot, text, button=True):
        await _meta_set("editorial_event_date", date_key)
        await _remember_topic(text)


async def _run_curiosity(bot, now: datetime) -> None:
    # Суббота: материал, который читают не ради срочности, а ради открытия.
    if now.weekday() != 5 or not (time(11, 0) <= now.time() < time(13, 0)):
        return
    date_key = now.date().isoformat()
    if await _meta_get("editorial_fact_date") == date_key:
        return
    if not await _attempt_allowed("editorial_fact_try", now, cooldown=30):
        return
    text = await _curiosity_post()
    if text and await _publish(bot, text):
        await _meta_set("editorial_fact_date", date_key)
        await _remember_topic(text)


async def editorial_channel_loop(bot) -> None:
    """Фоновый планировщик живого редакционного контента."""
    await asyncio.sleep(35)
    while True:
        try:
            now = _now()
            await _run_morning(bot, now)
            await _run_event(bot, now)
            await _run_curiosity(bot, now)
        except Exception as exc:  # noqa: BLE001
            log.exception("Editorial channel loop failed: %s", exc)
        await asyncio.sleep(60)
