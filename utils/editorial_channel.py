"""Редакционная линия Telegram-канала с обязательным предпросмотром."""
from __future__ import annotations

import asyncio
import html
import logging
import re
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select

import config
from database.db import get_session
from database.models import ContentPost, Meta
from utils.ai import (
    _create_with_server_tool_continuation,
    _extract_text_and_sources,
    _get_client,
    _web_search_errors,
    _web_search_tool,
    ai_enabled,
)

log = logging.getLogger(__name__)
router = Router()
AMSTERDAM = ZoneInfo("Europe/Amsterdam")
RECENT_SLOTS = 12
DRAFT_CHUNK = 95
PLAN_DAYS = 14

MORNING_SOURCES = [
    "knmi.nl", "ns.nl", "prorail.nl", "rijkswaterstaat.nl",
    "vananaarbeter.nl", "9292.nl",
]
EVENT_SOURCES = [
    "evenementen.nl", "iamsterdam.com", "uitagendautrecht.nl",
    "rotterdamfestivals.nl", "denhaag.com", "thisiseindhoven.com",
    "visitbrabant.com", "holland.com",
]
FACT_SOURCES = [
    "canonvannederland.nl", "rijksmuseum.nl", "openluchtmuseum.nl",
    "cultureelerfgoed.nl", "stadsarchief.amsterdam.nl", "archieven.nl",
    "holland.com",
]
EVENING_SOURCES = [
    "rijksoverheid.nl", "government.nl", "cbs.nl", "nos.nl", "nu.nl",
    "nltimes.nl", "dutchnews.nl", "holland.com", "iamsterdam.com",
    "canonvannederland.nl", "rijksmuseum.nl", "openluchtmuseum.nl",
]


def _now() -> datetime:
    return datetime.now(AMSTERDAM).replace(tzinfo=None)


async def _meta_get(key: str) -> str:
    async with get_session() as session:
        row = await session.get(Meta, key)
        return row.value if row else ""


async def _meta_set(key: str, value) -> None:
    async with get_session() as session:
        row = await session.get(Meta, key)
        value = str(value)[:100]
        if row is None:
            session.add(Meta(key=key, value=value))
        else:
            row.value = value
        await session.commit()


async def _attempt_allowed(key: str, now: datetime, cooldown: int = 20) -> bool:
    raw = await _meta_get(key)
    if raw:
        try:
            if now - datetime.fromisoformat(raw) < timedelta(minutes=cooldown):
                return False
        except ValueError:
            pass
    await _meta_set(key, now.isoformat(timespec="minutes"))
    return True


async def _recent_topics() -> list[str]:
    result = []
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
    return re.sub(r"<[^>]+>", "", text).strip()


async def _generate(system: str, user: str, domains: list[str], max_tokens: int = 900):
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
    return (text, sources) if text and sources else None


async def _morning_brief() -> str | None:
    system = (
        "Ты выпускающий редактор утреннего Telegram-брифа для русскоязычных жителей "
        "Нидерландов. Обязательно проверь свежие данные поиском. Используй KNMI для "
        "погоды, NS/ProRail/9292 для транспорта, Rijkswaterstaat/VanAnaarBeter для дорог. "
        "Ничего не выдумывай. Это ОДИН пост, не три отдельных. За 20 секунд читатель "
        "должен понять погоду на день, существенные сбои транспорта и крупные пробки, "
        "аварии или перекрытия. Мелкие локальные задержки не перечисляй. Если серьёзных "
        "проблем нет, скажи коротко. 450-750 знаков. Первая строка живой заголовок, "
        "затем три компактных блока ☁️, 🚆, 🚗. Без markdown и HTML."
    )
    result = await _generate(
        system,
        f"Сегодня {_now():%d.%m.%Y}, Europe/Amsterdam. Бриф только на сегодня.",
        MORNING_SOURCES,
        700,
    )
    return result[0] if result else None


async def _event_spotlight() -> str | None:
    recent = await _recent_topics()
    system = (
        "Ты редактор русскоязычного Telegram-медиа о Нидерландах. Найди ОДНО сильное "
        "реальное мероприятие на ближайшие 14 дней. В приоритете evenementen.nl, затем "
        "официальный сайт события или городская афиша. Проверь дату, место, цену и "
        "актуальный статус. Никаких списков. Выбирай событие с историей или визуальным/"
        "культурным поводом, а не первое в поиске. Начни с конкретного хука, затем 2-3 "
        "детали, почему туда стоит пойти, затем дата, город/адрес, цена и официальный "
        "источник. Без рекламных клише. 650-1000 знаков."
    )
    result = await _generate(
        system,
        f"Сегодня {_now():%d.%m.%Y}. Не повторяй: {', '.join(recent) or 'нет'}.",
        EVENT_SOURCES,
        900,
    )
    if not result:
        return None
    text, sources = result
    if "http://" not in text and "https://" not in text:
        text += f"\n\nИсточник: {sources[0]}"
    return text


async def _curiosity_post() -> str | None:
    recent = await _recent_topics()
    system = (
        "Ты редактор Telegram-медиа для людей, которые уже живут в Нидерландах. Найди "
        "один небанальный проверяемый сюжет: странную деталь истории, происхождение "
        "повседневной вещи или правила, инженерное решение, малоизвестную традицию, "
        "архитектурный след прошлого, музейный объект или языковую деталь с историей. "
        "Проверяй факты по надёжным нидерландским источникам. Без нового сильного угла "
        "запрещены темы: ниже уровня моря, велосипеды, тюльпаны, кофешопы, красные фонари, "
        "деревянные башмаки, мельницы, прямолинейность голландцев. Не начинай с «А вы "
        "знали?». Сначала информационный разрыв, потом объяснение и связь с сегодняшними "
        "Нидерландами. 650-1000 знаков."
    )
    result = await _generate(
        system,
        f"Сегодня {_now():%d.%m.%Y}. Не повторяй: {', '.join(recent) or 'нет'}.",
        FACT_SOURCES,
        900,
    )
    return result[0] if result else None


async def _evening_post() -> str | None:
    recent = await _recent_topics()
    system = (
        "Ты вечерний редактор Telegram-канала о жизни в Нидерландах. В 21:00 нужен один "
        "лёгкий, но содержательный пост, который хочется дочитать перед сном. Это НЕ сводка "
        "новостей: утренние новости уже выходят в 10:00, вечерние в 18:00. Выбери один "
        "конкретный сюжет из сегодняшней жизни страны, культуры, городских привычек, языка, "
        "истории, необычного места, повседневного правила или небольшого актуального "
        "наблюдения. Если берёшь актуальный повод, проверь его веб-поиском и объясни контекст, "
        "а не пересказывай новость. Никаких подборок и банальностей про тюльпаны, велосипеды, "
        "мельницы и уровень моря. Не начинай с «А вы знали?». Живой человеческий текст, "
        "500-850 знаков, один сюжет, без маркетинговых CTA, markdown и HTML."
    )
    result = await _generate(
        system,
        f"Сегодня {_now():%d.%m.%Y}. Не повторяй последние темы: {', '.join(recent) or 'нет'}.",
        EVENING_SOURCES,
        800,
    )
    return result[0] if result else None


async def _store_draft(draft_id: str, kind: str, text: str, button: bool) -> None:
    await _meta_set(f"ed_{draft_id}_kind", kind)
    await _meta_set(f"ed_{draft_id}_button", "1" if button else "0")
    await _meta_set(f"ed_{draft_id}_status", "pending")
    chunks = [text[i:i + DRAFT_CHUNK] for i in range(0, len(text), DRAFT_CHUNK)]
    await _meta_set(f"ed_{draft_id}_n", len(chunks))
    for index, chunk in enumerate(chunks):
        await _meta_set(f"ed_{draft_id}_{index}", chunk)


async def _load_draft(draft_id: str):
    if await _meta_get(f"ed_{draft_id}_status") != "pending":
        return None
    try:
        count = int(await _meta_get(f"ed_{draft_id}_n"))
    except ValueError:
        return None
    text = "".join([await _meta_get(f"ed_{draft_id}_{i}") for i in range(count)])
    return (
        await _meta_get(f"ed_{draft_id}_kind"),
        text,
        await _meta_get(f"ed_{draft_id}_button") == "1",
    )


def _approval_kb(draft_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Опубликовать", callback_data=f"edpub:{draft_id}"),
        InlineKeyboardButton(text="❌ Пропустить", callback_data=f"edskip:{draft_id}"),
    ]])


async def _send_for_approval(bot, kind: str, text: str, button: bool = False) -> bool:
    draft_id = f"{int(_now().timestamp()) % 100000000:08d}"
    await _store_draft(draft_id, kind, text, button)
    labels = {
        "morning": "Утренний бриф",
        "event": "Мероприятие",
        "curiosity": "Познавательный пост",
        "evening": "Вечерний пост",
    }
    sent = False
    for admin_id in config.ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"👀 <b>{labels.get(kind, kind)}. Предпросмотр</b>\n\n"
                f"{html.escape(text)}\n\n"
                "В канал ничего не уйдёт, пока вы не подтвердите публикацию.",
                reply_markup=_approval_kb(draft_id),
                disable_web_page_preview=True,
            )
            sent = True
        except Exception as exc:  # noqa: BLE001
            log.warning("Cannot send preview: %s", exc)
    return sent


def _channel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
        text="🎭 Открыть афишу в боте", url=config.BOT_URL
    )]])


async def _publish_editorial(bot, kind: str, text: str, button: bool) -> bool:
    try:
        await bot.send_message(
            config.ANNOUNCE_CHANNEL,
            text,
            parse_mode=None,
            reply_markup=_channel_kb() if button else None,
            disable_web_page_preview=True,
        )
        if kind in {"event", "curiosity", "evening"}:
            await _remember_topic(text)
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("Editorial publish failed: %s", exc)
        return False


@router.callback_query(F.data.startswith("edpub:"), F.from_user.id.in_(config.ADMIN_IDS))
async def editorial_publish_callback(callback: CallbackQuery):
    draft_id = callback.data.split(":", 1)[1]
    draft = await _load_draft(draft_id)
    if not draft:
        await callback.answer("Этот черновик уже обработан", show_alert=True)
        return
    kind, text, button = draft
    if await _publish_editorial(callback.bot, kind, text, button):
        await _meta_set(f"ed_{draft_id}_status", "published")
        await callback.answer("Опубликовано")
        await callback.message.edit_reply_markup(reply_markup=None)
    else:
        await callback.answer("Не удалось опубликовать", show_alert=True)


@router.callback_query(F.data.startswith("edskip:"), F.from_user.id.in_(config.ADMIN_IDS))
async def editorial_skip_callback(callback: CallbackQuery):
    draft_id = callback.data.split(":", 1)[1]
    if not await _load_draft(draft_id):
        await callback.answer("Этот черновик уже обработан", show_alert=True)
        return
    await _meta_set(f"ed_{draft_id}_status", "skipped")
    await callback.answer("Пропущено")
    await callback.message.edit_reply_markup(reply_markup=None)


async def _run_generated(bot, now, kind, date_key, generator, button=False):
    if await _meta_get(date_key) == now.date().isoformat():
        return
    if not await _attempt_allowed(f"{date_key}_try", now, 30):
        return
    text = await generator()
    if text and await _send_for_approval(bot, kind, text, button):
        await _meta_set(date_key, now.date().isoformat())


async def _run_morning(bot, now):
    if time(6, 45) <= now.time() < time(8, 0):
        await _run_generated(bot, now, "morning", "editorial_morning_date", _morning_brief)


async def _run_event(bot, now):
    if now.weekday() == 4 and time(13, 0) <= now.time() < time(15, 0):
        await _run_generated(bot, now, "event", "editorial_event_date", _event_spotlight, True)


async def _run_curiosity(bot, now):
    if now.weekday() == 5 and time(14, 0) <= now.time() < time(16, 0):
        await _run_generated(bot, now, "curiosity", "editorial_fact_date", _curiosity_post)


async def _run_evening(bot, now):
    if time(21, 0) <= now.time() < time(22, 0):
        await _run_generated(bot, now, "evening", "editorial_evening_date", _evening_post)


async def _queue_due_content_post(bot, now):
    from handlers.content import MISSED_GRACE, _post_kb, render_post, seed_content_calendar

    await seed_content_calendar()
    async with get_session() as session:
        due = (await session.scalars(
            select(ContentPost).where(
                ContentPost.status == "scheduled",
                ContentPost.scheduled_at <= now,
            ).order_by(ContentPost.scheduled_at)
        )).all()
        for row in due:
            if now - row.scheduled_at > MISSED_GRACE:
                row.status = "skipped"
                row.error_text = "missed before admin preview"
        await session.commit()
        ready = [row for row in due if now - row.scheduled_at <= MISSED_GRACE]
    if not ready:
        return
    post = ready[0]
    key = f"content_preview_{post.id}"
    if await _meta_get(key) == "1":
        return
    text, _ = await render_post(post)
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Опубликовать", callback_data=f"cpub:{post.id}"),
        InlineKeyboardButton(text="❌ Пропустить", callback_data=f"cskip:{post.id}"),
    ]])
    for admin_id in config.ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"👀 <b>Пост бота. Предпросмотр</b>\n"
                f"Слот: {post.scheduled_at:%d.%m · %H:%M}\n\n{text}",
                reply_markup=kb,
                disable_web_page_preview=True,
            )
            await bot.send_message(
                admin_id,
                "Кнопка под постом будет такой:",
                reply_markup=_post_kb(post),
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("Cannot send content preview: %s", exc)
    await _meta_set(key, "1")


@router.callback_query(F.data.startswith("cpub:"), F.from_user.id.in_(config.ADMIN_IDS))
async def content_publish_callback(callback: CallbackQuery):
    from handlers.content import publish_content_post

    post_id = int(callback.data.split(":", 1)[1])
    async with get_session() as session:
        post = await session.get(ContentPost, post_id)
    if not post or post.status not in {"scheduled", "failed"}:
        await callback.answer("Этот пост уже обработан", show_alert=True)
        return
    ok = await publish_content_post(callback.bot, post_id, early=True)
    await callback.answer("Опубликовано" if ok else "Ошибка публикации", show_alert=not ok)
    if ok:
        await callback.message.edit_reply_markup(reply_markup=None)


@router.callback_query(F.data.startswith("cskip:"), F.from_user.id.in_(config.ADMIN_IDS))
async def content_skip_callback(callback: CallbackQuery):
    post_id = int(callback.data.split(":", 1)[1])
    async with get_session() as session:
        post = await session.get(ContentPost, post_id)
        if not post or post.status not in {"scheduled", "failed"}:
            await callback.answer("Этот пост уже обработан", show_alert=True)
            return
        post.status = "skipped"
        post.error_text = "skipped by admin from preview"
        await session.commit()
    await callback.answer("Пропущено")
    await callback.message.edit_reply_markup(reply_markup=None)


def _day_label(day) -> str:
    names = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
    return names[day.weekday()]


async def _send_unified_plan(message: Message) -> None:
    """Показывает реальную сетку канала на 14 дней, а не только старые ContentPost."""
    from handlers.content import TEMPLATES, seed_content_calendar

    await seed_content_calendar()
    now = _now()
    end = now + timedelta(days=PLAN_DAYS)
    async with get_session() as session:
        content_posts = (await session.scalars(
            select(ContentPost).where(
                ContentPost.scheduled_at >= now.replace(hour=0, minute=0, second=0, microsecond=0),
                ContentPost.scheduled_at < end,
            ).order_by(ContentPost.scheduled_at)
        )).all()

    by_date: dict = {}
    for post in content_posts:
        by_date.setdefault(post.scheduled_at.date(), []).append((
            post.scheduled_at.strftime("%H:%M"),
            f"🤖 {TEMPLATES[post.template_key].button}",
            post.status,
        ))

    lines = [
        "🗓 <b>Контент-план канала · ближайшие 14 дней</b>",
        "",
        "Все публикации бота и редакционные посты идут через ваше подтверждение.",
        "10:00 и 18:00 показаны как фиксированные новостные слоты для контроля нагрузки.",
        "",
    ]

    day = now.date()
    for offset in range(PLAN_DAYS):
        current = day + timedelta(days=offset)
        items = [
            ("06:45", "🌦 Утренний бриф: погода + транспорт + дороги", "editorial"),
            ("10:00", "📰 Утренние новости", "fixed"),
            ("18:00", "📰 Вечерние новости", "fixed"),
            ("21:00", "🌙 Вечерний редакционный пост", "editorial"),
        ]
        if current.weekday() == 4:
            items.append(("13:00", "🎭 Одно интересное мероприятие", "editorial"))
        if current.weekday() == 5:
            items.append(("14:00", "💡 Небанальный факт / история", "editorial"))
        items.extend(by_date.get(current, []))
        items.sort(key=lambda item: item[0])

        lines.append(f"<b>{current:%d.%m} · {_day_label(current)}</b>")
        for slot, title, state in items:
            marker = ""
            if state not in {"editorial", "fixed"}:
                marker = {
                    "scheduled": " · 🕒",
                    "sent": " · ✅",
                    "skipped": " · ⏭",
                    "failed": " · ❌",
                    "sending": " · ⏳",
                }.get(state, "")
            lines.append(f"{slot}  {title}{marker}")
        lines.append("")

    await message.answer(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🔄 Обновить план", callback_data="editorial:plan")
        ]]),
    )


@router.message(Command("contentplan"))
async def unified_content_plan(message: Message) -> None:
    if message.from_user.id in config.ADMIN_IDS:
        await _send_unified_plan(message)


@router.callback_query(F.data == "editorial:plan", F.from_user.id.in_(config.ADMIN_IDS))
async def unified_content_plan_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    await _send_unified_plan(callback.message)


async def editorial_channel_loop(bot) -> None:
    await asyncio.sleep(35)
    while True:
        try:
            now = _now()
            await _run_morning(bot, now)
            await _run_event(bot, now)
            await _run_curiosity(bot, now)
            await _run_evening(bot, now)
            await _queue_due_content_post(bot, now)
        except Exception as exc:  # noqa: BLE001
            log.exception("Editorial channel loop failed: %s", exc)
        await asyncio.sleep(60)
