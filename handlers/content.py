"""Контент-центр: календарь и автоматические полезные посты в Telegram-канал."""
import asyncio
import html
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import func, select

import config
from database.db import get_session
from database.models import (
    BotUser,
    ContentClick,
    ContentPost,
    DiscoveredEvent,
    EventListing,
    Listing,
    Meta,
    Specialist,
)
from utils.analytics import log_product_event

log = logging.getLogger(__name__)
router = Router()
router.message.filter(F.chat.type == ChatType.PRIVATE)

AMSTERDAM = ZoneInfo("Europe/Amsterdam")
PAUSE_KEY = "content_paused"
MISSED_GRACE = timedelta(hours=3)


@dataclass(frozen=True)
class Template:
    kind: str
    destination: str
    button: str
    text: str


TEMPLATES: dict[str, Template] = {
    "events_intro": Template(
        "events", "events", "🎭 Найти события рядом",
        "«Что происходит рядом на этой неделе?» — вопрос простой, а потом "
        "приходится открывать несколько сайтов и проверять, не закончилось ли "
        "событие ещё вчера.\n\n"
        "В боте можно собрать свежую афишу по своему городу. Он покажет отдельные "
        "карточки с датой, местом и ссылкой на подробности.\n\n"
        "Укажите город — и посмотрите, куда можно сходить рядом 👇",
    ),
    "digest": Template(
        "digest", "digest", "🔔 Настроить подборку",
        "Не хочется каждый четверг заново искать планы на выходные?\n\n"
        "Бот может собирать персональную подборку сам. Вы выбираете город, радиус "
        "и темы: события, прогулки, специалисты, объявления или полезное.\n\n"
        "После настройки приходит не общая рассылка для всей страны, а подборка "
        "под ваши интересы и местоположение 👇",
    ),
    "board_intro": Template(
        "board", "board", "📋 Смотреть объявления",
        "Жильё, велосипед, работа, вещи для дома или попутчики — нужное объявление "
        "часто теряется в чатах уже через несколько часов.\n\n"
        "В боте есть доска объявлений по Нидерландам. Можно смотреть актуальные "
        "предложения, сохранять подходящие и бесплатно разместить своё после "
        "проверки.\n\n"
        "Посмотрите, что опубликовано сейчас 👇",
    ),
    "letter": Template(
        "utility", "letter", "📩 Разобрать письмо",
        "Пришло письмо от gemeente, Belastingdienst, IND или страховой, а "
        "переводчик перевёл слова, но не объяснил, что от вас хотят?\n\n"
        "Отправьте боту фотографию письма. Он простыми словами разберёт, от кого "
        "оно, что нужно сделать и есть ли в нём важный срок.\n\n"
        "Фото используется только для ответа и не сохраняется 👇",
    ),
    "events_dynamic": Template(
        "events", "events", "🎭 Открыть афишу",
        "Планы на ближайшие дни уже можно искать в боте.\n\n"
        "Он собирает актуальные события по городам Нидерландов и показывает дату, "
        "место и прямую ссылку на подробности.\n\n"
        "Откройте афишу и укажите свой город 👇",
    ),
    "home": Template(
        "profile", "home", "🏠 Настроить профиль",
        "У бота появилась персональная главная — «Мой Podslushano».\n\n"
        "Укажите город, радиус и интересы, чтобы в одном месте видеть события "
        "рядом, новые объявления, сохранённые карточки и статусы своих заявок.\n\n"
        "Это ваш короткий маршрут ко всему актуальному, без поиска по меню 👇",
    ),
    "salary": Template(
        "utility", "salary", "🧮 Рассчитать зарплату",
        "Bruto в вакансии выглядит понятно — пока не пытаешься представить, "
        "сколько придёт на счёт после налогов.\n\n"
        "В боте есть калькулятор зарплаты для Нидерландов. Укажите bruto в месяц "
        "и отметьте, применяется ли 30%-ruling — бот даст ориентировочный расчёт "
        "netto по актуальным ставкам.\n\n"
        "Проверьте свою сумму 👇",
    ),
    "listings_dynamic": Template(
        "board", "board", "📋 Посмотреть новые",
        "На доске бота появляются новые объявления о жилье, работе, вещах и "
        "попутчиках.\n\n"
        "Все карточки проходят проверку, а неактуальные объявления скрываются. "
        "Можно открыть нужную категорию или разместить своё предложение.\n\n"
        "Посмотрите новые объявления 👇",
    ),
    "notifications": Template(
        "notifications", "notifications", "🔔 Настроить уведомления",
        "Сохранили событие и вспомнили о нём на следующий день после окончания?\n\n"
        "В боте можно включить напоминания о сохранённых событиях, новых "
        "объявлениях рядом и изменениях статусов своих заявок. Каждый тип "
        "уведомлений настраивается отдельно.\n\n"
        "Выберите только то, что действительно нужно 👇",
    ),
    "ask": Template(
        "assistant", "askbot", "💬 Задать вопрос",
        "Боту не обязательно подбирать точную команду в меню.\n\n"
        "Можно просто написать обычной фразой: «Как получить DigiD?», «Куда "
        "обращаться, если не выплатили зарплату?» или «Нужен бухгалтер в "
        "Utrecht».\n\n"
        "Бот поймёт задачу, при необходимости проверит свежие источники или "
        "откроет подходящий раздел. Попробуйте задать свой вопрос 👇",
    ),
    "specialists_dynamic": Template(
        "specialists", "specialists", "🔍 Посмотреть специалистов",
        "Нужен русскоязычный специалист в Нидерландах?\n\n"
        "В боте можно искать по профессии, городу и формату работы. В карточке "
        "видны описание услуг, контакты и отзывы, а если рядом никого нет — бот "
        "предложит специалистов из соседних городов или онлайн.\n\n"
        "Напишите, кого ищете 👇",
    ),
    "selfadd": Template(
        "commercial", "selfadd", "➕ Добавить себя в гайд",
        "Если вы оказываете услуги в Нидерландах, добавьте свою карточку в гайд "
        "Podslushano NL.\n\n"
        "Пользователи находят специалистов по категории, городу и онлайн-формату, "
        "открывают описание и переходят к контактам напрямую.\n\n"
        "Анкета, оплата и отправка на проверку проходят внутри бота 👇",
    ),
}

# Первый пост про поиск специалистов уже был опубликован вручную и сюда не входит.
INITIAL_SCHEDULE = (
    ("c260728_events", "events_intro", datetime(2026, 7, 28, 12, 30)),
    ("c260730_digest", "digest", datetime(2026, 7, 30, 18, 30)),
    ("c260802_board", "board_intro", datetime(2026, 8, 2, 19, 0)),
    ("c260804_letter", "letter", datetime(2026, 8, 4, 12, 30)),
    ("c260806_events", "events_dynamic", datetime(2026, 8, 6, 18, 30)),
    ("c260809_home", "home", datetime(2026, 8, 9, 19, 0)),
    ("c260811_salary", "salary", datetime(2026, 8, 11, 12, 30)),
    ("c260813_board", "listings_dynamic", datetime(2026, 8, 13, 18, 30)),
    ("c260816_notify", "notifications", datetime(2026, 8, 16, 19, 0)),
    ("c260818_ask", "ask", datetime(2026, 8, 18, 12, 30)),
    ("c260820_specs", "specialists_dynamic", datetime(2026, 8, 20, 18, 30)),
    ("c260823_selfadd", "selfadd", datetime(2026, 8, 23, 19, 0)),
)

TUESDAY_ROTATION = (
    "letter", "home", "salary", "ask", "notifications",
    "events_intro", "board_intro", "digest",
)
THURSDAY_ROTATION = ("events_dynamic", "listings_dynamic", "specialists_dynamic")
ROLLING_DAYS = 70


def _local_now() -> datetime:
    """Наивное локальное время для совместимости с SQLite DateTime."""
    return datetime.now(AMSTERDAM).replace(tzinfo=None)


def _utc_now() -> datetime:
    return datetime.utcnow()


def _post_url(post: ContentPost) -> str:
    return f"{config.BOT_URL.rstrip('/')}?start={post.start_payload}"


def _post_kb(post: ContentPost) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=post.button_label, url=_post_url(post))
    ]])


async def seed_content_calendar() -> None:
    """Создаёт стартовый месяц и постоянно достраивает календарь вперёд."""
    async with get_session() as session:
        existing = set((await session.scalars(
            select(ContentPost.campaign_key)
        )).all())
        for campaign, template_key, scheduled_at in INITIAL_SCHEDULE:
            if campaign in existing:
                continue
            template = TEMPLATES[template_key]
            session.add(ContentPost(
                campaign_key=campaign,
                template_key=template_key,
                content_kind=template.kind,
                scheduled_at=scheduled_at,
                status="scheduled",
                button_label=template.button,
                start_payload=f"content_{campaign}",
            ))
        await session.commit()

    # После активного первого месяца: вторник — полезная функция, четверг —
    # живая подборка, последнее воскресенье месяца — коммерческий сценарий.
    # Горизонт каждый день сдвигается, поэтому календарь не заканчивается.
    async with get_session() as session:
        rows = (await session.scalars(
            select(ContentPost).order_by(ContentPost.scheduled_at)
        )).all()
        occupied = {row.scheduled_at.date() for row in rows}
        last_kind = TEMPLATES[rows[-1].template_key].kind if rows else ""
        start_day = max(
            _local_now().date(),
            rows[-1].scheduled_at.date() + timedelta(days=1) if rows
            else _local_now().date(),
        )
        end_day = _local_now().date() + timedelta(days=ROLLING_DAYS)
        day = start_day
        while day <= end_day:
            template_key = ""
            hour, minute = 12, 30
            if day.weekday() == 1:  # вторник
                index = (day.toordinal() // 7) % len(TUESDAY_ROTATION)
                candidates = TUESDAY_ROTATION[index:] + TUESDAY_ROTATION[:index]
                template_key = next(
                    key for key in candidates if TEMPLATES[key].kind != last_kind
                )
            elif day.weekday() == 3:  # четверг
                hour, minute = 18, 30
                index = (day.toordinal() // 7) % len(THURSDAY_ROTATION)
                candidates = THURSDAY_ROTATION[index:] + THURSDAY_ROTATION[:index]
                template_key = next(
                    key for key in candidates if TEMPLATES[key].kind != last_kind
                )
            elif day.weekday() == 6 and (day + timedelta(days=7)).month != day.month:
                hour, minute = 19, 0
                template_key = "selfadd"
            if template_key and day not in occupied:
                template = TEMPLATES[template_key]
                campaign = f"auto{day:%y%m%d}_{template_key}"[:64]
                session.add(ContentPost(
                    campaign_key=campaign,
                    template_key=template_key,
                    content_kind=template.kind,
                    scheduled_at=datetime(day.year, day.month, day.day, hour, minute),
                    status="scheduled",
                    button_label=template.button,
                    start_payload=f"content_{campaign}"[:64],
                ))
                occupied.add(day)
                last_kind = template.kind
            day += timedelta(days=1)
        await session.commit()


async def _is_paused() -> bool:
    async with get_session() as session:
        value = await session.get(Meta, PAUSE_KEY)
        return bool(value and value.value == "1")


async def _set_paused(paused: bool) -> None:
    async with get_session() as session:
        row = await session.get(Meta, PAUSE_KEY)
        if row is None:
            session.add(Meta(key=PAUSE_KEY, value="1" if paused else "0"))
        else:
            row.value = "1" if paused else "0"
        await session.commit()


async def _dynamic_events() -> tuple[str | None, list[str]]:
    now = _utc_now()
    async with get_session() as session:
        discovered = (await session.scalars(
            select(DiscoveredEvent).where(
                DiscoveredEvent.expires_at > now,
                DiscoveredEvent.starts_at.is_not(None),
                DiscoveredEvent.starts_at >= now,
            ).order_by(DiscoveredEvent.starts_at).limit(3)
        )).all()
        if len(discovered) < 3:
            month_keys = [f"{now:%Y-%m}", f"{now + timedelta(days=32):%Y-%m}"]
            manual = (await session.scalars(
                select(EventListing).where(
                    EventListing.status == "approved",
                    EventListing.month_key.in_(month_keys),
                ).order_by(EventListing.month_key, EventListing.id).limit(3)
            )).all()
        else:
            manual = []
    items: list[tuple[str, str, str]] = []
    for item in discovered:
        items.append((
            item.title,
            item.city or "Нидерланды",
            item.starts_at.strftime("%d.%m"),
        ))
    for item in manual:
        items.append((
            item.title,
            item.city or "Нидерланды",
            item.event_date or item.month_key,
        ))
    if len(items) < 3:
        return None, []
    lines = [
        "Три идеи из актуальной афиши бота 👇",
        "",
        *[
            f"• <b>{html.escape(title)}</b>\n  {html.escape(day)} · {html.escape(city)}"
            for title, city, day in items[:3]
        ],
        "",
        "Это только часть подборки. Укажите свой город — бот найдёт события рядом.",
    ]
    refs = [f"event:{title}" for title, _, _ in items[:3]]
    return "\n".join(lines), refs


async def _dynamic_listings() -> tuple[str | None, list[str]]:
    cutoff = _utc_now() - timedelta(days=7)
    async with get_session() as session:
        rows = (await session.scalars(
            select(Listing).where(
                Listing.status == "approved",
                Listing.created_at >= cutoff,
            ).order_by(Listing.created_at.desc()).limit(3)
        )).all()
    if len(rows) < 3:
        return None, []
    text = "\n".join([
        "Новое на доске объявлений за последние дни 👇",
        "",
        *[
            f"• <b>{html.escape(item.title)}</b>\n  📍 "
            f"{html.escape(item.city or 'по всей стране')}"
            for item in rows
        ],
        "",
        "Откройте доску, чтобы посмотреть карточки и контакты авторов.",
    ])
    return text, [f"listing:{item.id}" for item in rows]


async def _dynamic_specialists() -> tuple[str | None, list[str]]:
    cutoff = _local_now() - timedelta(days=60)
    async with get_session() as session:
        old_refs = (await session.scalars(
            select(ContentPost.dynamic_refs).where(
                ContentPost.status == "sent",
                ContentPost.sent_at >= cutoff,
                ContentPost.content_kind == "specialists",
            )
        )).all()
        excluded: set[int] = set()
        for raw in old_refs:
            try:
                excluded.update(
                    int(ref.split(":", 1)[1])
                    for ref in json.loads(raw or "[]")
                    if ref.startswith("specialist:")
                )
            except (ValueError, TypeError, json.JSONDecodeError):
                continue
        query = select(Specialist).where(Specialist.status == "active")
        if excluded:
            query = query.where(Specialist.id.not_in(excluded))
        rows = (await session.scalars(
            query.order_by(Specialist.is_premium.desc(), Specialist.id).limit(3)
        )).all()
    if len(rows) < 3:
        return None, []
    text = "\n".join([
        "Несколько направлений, которые уже можно найти в гайде 👇",
        "",
        *[
            f"• <b>{html.escape(item.category.capitalize())}</b> — "
            f"{html.escape(item.city or 'онлайн')}"
            for item in rows
        ],
        "",
        "Напишите профессию и город — бот покажет подходящие карточки с контактами.",
    ])
    return text, [f"specialist:{item.id}" for item in rows]


async def render_post(post: ContentPost) -> tuple[str, list[str]]:
    template = TEMPLATES[post.template_key]
    dynamic_text: str | None = None
    refs: list[str] = []
    if post.template_key == "events_dynamic":
        dynamic_text, refs = await _dynamic_events()
    elif post.template_key == "listings_dynamic":
        dynamic_text, refs = await _dynamic_listings()
    elif post.template_key == "specialists_dynamic":
        dynamic_text, refs = await _dynamic_specialists()
    return dynamic_text or template.text, refs


async def _notify_admins(bot, text: str) -> None:
    for admin_id in config.ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text)
        except Exception:  # noqa: BLE001
            pass


async def publish_content_post(bot, post_id: int, *, early: bool = False) -> bool:
    """Публикует один пост с блокировкой состояния и журналом результата."""
    async with get_session() as session:
        post = await session.get(ContentPost, post_id)
        if post is None or post.status not in {"scheduled", "failed"}:
            return False
        post.status = "sending"
        post.error_text = None
        await session.commit()

    try:
        text, refs = await render_post(post)
        sent = await bot.send_message(
            config.ANNOUNCE_CHANNEL,
            text,
            reply_markup=_post_kb(post),
            disable_web_page_preview=True,
        )
    except Exception as exc:  # noqa: BLE001
        async with get_session() as session:
            row = await session.get(ContentPost, post_id)
            row.status = "failed"
            row.error_text = str(exc)[:1000]
            await session.commit()
        await _notify_admins(
            bot,
            f"⚠️ Контент-центр не смог опубликовать {post.campaign_key}:\n"
            f"<code>{html.escape(str(exc)[:500])}</code>",
        )
        return False

    async with get_session() as session:
        row = await session.get(ContentPost, post_id)
        row.status = "sent"
        row.text = text
        row.dynamic_refs = json.dumps(refs, ensure_ascii=False)
        row.telegram_message_id = sent.message_id
        row.sent_at = _local_now()
        await session.commit()
    await _notify_admins(
        bot,
        f"✅ Контент-центр опубликовал пост «{post.template_key}»"
        + (" досрочно." if early else "."),
    )
    return True


async def content_tick(bot, now: datetime | None = None) -> None:
    """Один безопасный проход планировщика; вынесен отдельно для тестов."""
    await seed_content_calendar()
    if not config.ANNOUNCE_CHANNEL or await _is_paused():
        return
    current = now or _local_now()
    async with get_session() as session:
        # После аварийного рестарта возвращаем зависшую блокировку.
        stuck = (await session.scalars(
            select(ContentPost).where(
                ContentPost.status == "sending",
                ContentPost.scheduled_at < current - timedelta(minutes=10),
            )
        )).all()
        for row in stuck:
            row.status = "scheduled"
        due = (await session.scalars(
            select(ContentPost).where(
                ContentPost.status == "scheduled",
                ContentPost.scheduled_at <= current,
            ).order_by(ContentPost.scheduled_at)
        )).all()
        missed = [row for row in due if current - row.scheduled_at > MISSED_GRACE]
        ready = [row for row in due if current - row.scheduled_at <= MISSED_GRACE]
        for row in missed:
            row.status = "skipped"
            row.error_text = "missed while service was unavailable"
        await session.commit()
    for row in missed:
        await _notify_admins(
            bot,
            f"⏭ Контент-центр пропустил просроченный слот {row.scheduled_at:%d.%m %H:%M} "
            f"({row.template_key}), чтобы не публиковать старые посты пачкой.",
        )
    if ready:
        await publish_content_post(bot, ready[0].id)


async def content_publisher_loop(bot) -> None:
    await asyncio.sleep(15)
    while True:
        try:
            await content_tick(bot)
        except Exception as exc:  # noqa: BLE001
            log.exception("Ошибка Контент-центра: %s", exc)
        await asyncio.sleep(60)


async def _next_post() -> ContentPost | None:
    await seed_content_calendar()
    async with get_session() as session:
        return (await session.scalars(
            select(ContentPost).where(
                ContentPost.status.in_(("scheduled", "failed"))
            ).order_by(ContentPost.scheduled_at)
        )).first()


def _status_label(status: str) -> str:
    return {
        "scheduled": "🕒",
        "sending": "⏳",
        "sent": "✅",
        "skipped": "⏭",
        "failed": "❌",
    }.get(status, "•")


async def _send_plan(message: Message) -> None:
    await seed_content_calendar()
    async with get_session() as session:
        rows = (await session.scalars(
            select(ContentPost).order_by(ContentPost.scheduled_at)
        )).all()
    paused = await _is_paused()
    lines = [
        "🗓 <b>Контент-центр</b>",
        "",
        f"Автопубликация: <b>{'на паузе' if paused else 'включена'}</b>",
        "Часовой пояс: Europe/Amsterdam",
        "",
    ]
    for row in rows:
        lines.append(
            f"{_status_label(row.status)} {row.scheduled_at:%d.%m · %H:%M} — "
            f"{TEMPLATES[row.template_key].button}"
        )
    await message.answer(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👀 Следующий пост", callback_data="content:preview")],
            [InlineKeyboardButton(
                text="▶️ Продолжить" if paused else "⏸ Пауза",
                callback_data="content:pause",
            )],
        ]),
    )


@router.message(Command("contentplan"))
async def content_plan(message: Message) -> None:
    if message.from_user.id in config.ADMIN_IDS:
        await _send_plan(message)


@router.callback_query(F.data == "content:plan", F.from_user.id.in_(config.ADMIN_IDS))
async def content_plan_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    await _send_plan(callback.message)


async def _send_preview(message: Message) -> None:
    post = await _next_post()
    if post is None:
        await message.answer("В календаре больше нет ожидающих публикаций.")
        return
    text, refs = await render_post(post)
    await message.answer(
        f"👀 <b>Предпросмотр</b>\n"
        f"Слот: {post.scheduled_at:%d.%m.%Y · %H:%M}\n"
        f"Источник: {'реальные карточки' if refs else 'готовый полезный пост'}\n\n"
        f"{text}",
        reply_markup=_post_kb(post),
        disable_web_page_preview=True,
    )


@router.message(Command("contentpreview"))
async def content_preview(message: Message) -> None:
    if message.from_user.id in config.ADMIN_IDS:
        await _send_preview(message)


@router.callback_query(F.data == "content:preview", F.from_user.id.in_(config.ADMIN_IDS))
async def content_preview_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    await _send_preview(callback.message)


@router.message(Command("contentpause"))
async def content_pause(message: Message) -> None:
    if message.from_user.id not in config.ADMIN_IDS:
        return
    paused = not await _is_paused()
    await _set_paused(paused)
    await message.answer(
        "⏸ Автопубликации поставлены на паузу."
        if paused else "▶️ Автопубликации продолжены."
    )


@router.callback_query(F.data == "content:pause", F.from_user.id.in_(config.ADMIN_IDS))
async def content_pause_callback(callback: CallbackQuery) -> None:
    paused = not await _is_paused()
    await _set_paused(paused)
    await callback.answer("Пауза включена" if paused else "Автопубликации продолжены")
    await _send_plan(callback.message)


@router.message(Command("contentskip"))
async def content_skip(message: Message) -> None:
    if message.from_user.id not in config.ADMIN_IDS:
        return
    post = await _next_post()
    if post is None:
        await message.answer("Нет публикации, которую можно пропустить.")
        return
    async with get_session() as session:
        row = await session.get(ContentPost, post.id)
        row.status = "skipped"
        row.error_text = "skipped by admin"
        await session.commit()
    await message.answer(f"⏭ Пропущен пост {post.scheduled_at:%d.%m %H:%M}: {post.template_key}.")


@router.message(Command("contentsendnext"))
async def content_send_next(message: Message) -> None:
    if message.from_user.id not in config.ADMIN_IDS:
        return
    if not config.ANNOUNCE_CHANNEL:
        await message.answer("⚠️ Не задан ANNOUNCE_CHANNEL.")
        return
    post = await _next_post()
    if post is None:
        await message.answer("Нет публикации для отправки.")
        return
    await message.answer(f"⏳ Публикую {post.template_key} досрочно…")
    await publish_content_post(message.bot, post.id, early=True)


@router.message(Command("contentstats"))
async def content_stats(message: Message) -> None:
    if message.from_user.id not in config.ADMIN_IDS:
        return
    await seed_content_calendar()
    async with get_session() as session:
        rows = (await session.execute(
            select(
                ContentPost.campaign_key,
                ContentPost.template_key,
                ContentPost.status,
                func.count(ContentClick.id),
                func.coalesce(func.sum(ContentClick.is_new_user), 0),
                func.coalesce(func.sum(ContentClick.destination_opened), 0),
            ).outerjoin(
                ContentClick, ContentClick.campaign_key == ContentPost.campaign_key
            ).group_by(ContentPost.id).order_by(ContentPost.scheduled_at)
        )).all()
    sent = sum(1 for row in rows if row.status == "sent")
    clicks = sum(int(row[3] or 0) for row in rows)
    newcomers = sum(int(row[4] or 0) for row in rows)
    opened = sum(int(row[5] or 0) for row in rows)
    lines = [
        "📊 <b>Контент-центр</b>",
        "",
        f"Опубликовано: <b>{sent}</b>",
        f"Уникальных переходов: <b>{clicks}</b>",
        f"Новых пользователей: <b>{newcomers}</b>",
        f"Открытий нужного раздела: <b>{opened}</b>",
        "",
    ]
    for campaign, template, status, count, new, converted in rows:
        if status == "sent":
            lines.append(
                f"• {template}: {count} переходов · {new} новых · {converted} открытий"
            )
    await message.answer("\n".join(lines))


async def open_content_destination(
    message: Message, state: FSMContext, payload: str
) -> bool:
    """Атрибутирует deep-link и открывает обещанный в публикации раздел."""
    async with get_session() as session:
        post = (await session.scalars(select(ContentPost).where(
            ContentPost.start_payload == payload
        ))).first()
        if post is None:
            return False
        user = await session.get(BotUser, message.from_user.id)
        is_new = bool(
            user and user.created_at
            and _utc_now() - user.created_at <= timedelta(minutes=10)
        )
        click = (await session.scalars(select(ContentClick).where(
            ContentClick.campaign_key == post.campaign_key,
            ContentClick.user_id == message.from_user.id,
        ))).first()
        if click is None:
            click = ContentClick(
                campaign_key=post.campaign_key,
                user_id=message.from_user.id,
                is_new_user=is_new,
            )
            session.add(click)
        click.destination_opened = True
        await session.commit()

    await log_product_event(
        message.from_user.id,
        "content_destination_open",
        entity_type=post.template_key,
        source=post.campaign_key[:30],
    )
    destination = TEMPLATES[post.template_key].destination
    if destination == "events":
        from handlers.events import events_start
        await events_start(message, state)
    elif destination == "digest":
        from handlers.digest import _open_digest_settings
        await _open_digest_settings(message, state, message.from_user.id)
    elif destination == "board":
        from handlers.board import board_open
        await board_open(message, state)
    elif destination == "letter":
        from handlers.letters import letter_start
        await letter_start(message, state)
    elif destination == "home":
        from handlers.home import home_open
        await home_open(message, state)
    elif destination == "salary":
        from handlers.salary import salary_start
        await salary_start(message, state)
    elif destination == "notifications":
        from handlers.notifications import _open_settings
        await state.clear()
        await _open_settings(message, message.from_user.id, source=post.campaign_key[:30])
    elif destination == "specialists":
        from handlers.contacts import ask_query
        await state.clear()
        await ask_query(message, state)
    elif destination == "selfadd":
        from handlers.selfadd import self_start
        await self_start(message, state)
    else:
        await state.clear()
        await message.answer(
            "Напишите свой вопрос о жизни в Нидерландах обычной фразой — "
            "я постараюсь помочь 👇"
        )
    return True
