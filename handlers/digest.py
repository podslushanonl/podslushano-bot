"""Персональная еженедельная подборка «Планы на выходные».

Пользователь сам выбирает город, радиус и темы. События наполняются живым
веб-поиском и сохраняются в общую кэшированную карусель города.
Автоматический цикл по четвергам готовит напоминание админу, но ничего не
рассылает без явного подтверждения.
"""
import asyncio
import html
import logging
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramForbiddenError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import func, or_, select

import config
from database.db import get_session
from database.models import (
    AnnouncementDelivery,
    BotUser,
    DigestDeliveryLog,
    DigestPreference,
    EventListing,
    Listing,
    Meta,
    Specialist,
)
from keyboards.menus import BTN_SUBSCRIPTIONS, cancel_menu, main_menu
from states.forms import DigestSetup
from utils.geo import detect_city, distance_km, province_of_city

log = logging.getLogger(__name__)
router = Router()
router.message.filter(F.chat.type == ChatType.PRIVATE)

TOPICS = {
    "events": "🎭 События",
    "walks": "🚶 Allo Walks",
    "specialists": "🔍 Новые специалисты",
    "board": "📋 Объявления",
    "guides": "📚 Полезное о жизни в NL",
}
DEFAULT_TOPICS = {"events", "walks"}
RADIUS_LABELS = {0: "только мой город", 25: "до 25 км", 50: "до 50 км", 999: "вся страна"}
ANNOUNCEMENT_KEY = "digest-subscriptions-ready-2026-07-21"

# Координаты нужны только для локальной фильтрации уже сохранённых карточек.
# Если города нет в справочнике, безопасный fallback — точное совпадение города.
def _topics(csv: str | None) -> set[str]:
    return {x for x in (csv or "").split(",") if x in TOPICS}


def _topics_csv(items: set[str]) -> str:
    return ",".join(key for key in TOPICS if key in items)


def _week_key(now: datetime | None = None) -> str:
    current = now or datetime.now(ZoneInfo("Europe/Amsterdam"))
    year, week, _ = current.isocalendar()
    return f"{year}-W{week:02d}"


def _weekend_label(today: date | None = None) -> str:
    current = today or datetime.now(ZoneInfo("Europe/Amsterdam")).date()
    days = (5 - current.weekday()) % 7
    saturday = current + timedelta(days=days)
    sunday = saturday + timedelta(days=1)
    return f"{saturday:%d.%m}–{sunday:%d.%m}"


def _canonical_city(raw: str) -> tuple[str, str]:
    known = detect_city(raw)
    if known:
        return known
    city = " ".join(raw.strip().split())[:100]
    return city, province_of_city(city) or ""


def _distance_km(a: str, b: str) -> float | None:
    return distance_km(a, b)


def location_matches(pref: DigestPreference, target_city: str,
                     *, nationwide: bool = False, target_province: str = "") -> bool:
    """Проверяем, попадает ли карточка в выбранный пользователем радиус."""
    if nationwide or pref.radius_km == 999:
        return True
    city, province = _canonical_city(target_city) if target_city else ("", target_province)
    if city.casefold() == pref.city.casefold():
        return True
    if pref.radius_km == 0 or not city:
        return False
    distance = _distance_km(pref.city, city)
    if distance is not None:
        return distance <= pref.radius_km
    # Для неизвестных координат ничего не угадываем; при 50 км допускаем ту же
    # провинцию как прозрачный и достаточно консервативный fallback.
    return bool(pref.radius_km >= 50 and pref.province and province == pref.province)


def _radius_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏙 Только мой город", callback_data="dg:r:0")],
        [InlineKeyboardButton(text="🚲 До 25 км", callback_data="dg:r:25"),
         InlineKeyboardButton(text="🚆 До 50 км", callback_data="dg:r:50")],
        [InlineKeyboardButton(text="🇳🇱 Вся страна", callback_data="dg:r:999")],
    ])


def _topics_kb(selected: set[str]) -> InlineKeyboardMarkup:
    rows = []
    for key, label in TOPICS.items():
        mark = "✅" if key in selected else "▫️"
        rows.append([InlineKeyboardButton(text=f"{mark} {label}", callback_data=f"dg:t:{key}")])
    rows.append([InlineKeyboardButton(text="Готово →", callback_data="dg:t:done")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _settings_kb(pref: DigestPreference) -> InlineKeyboardMarkup:
    toggle = "🔕 Отключить подборку" if pref.enabled else "🔔 Включить подборку"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👀 Посмотреть пример", callback_data="dg:preview")],
        [InlineKeyboardButton(text="📍 Изменить город", callback_data="dg:city"),
         InlineKeyboardButton(text="🗺 Изменить радиус", callback_data="dg:radius")],
        [InlineKeyboardButton(text="🎛 Выбрать темы", callback_data="dg:topics")],
        [InlineKeyboardButton(text=toggle, callback_data="dg:toggle")],
    ])


def _settings_text(pref: DigestPreference) -> str:
    selected = _topics(pref.topics_csv)
    topics = ", ".join(TOPICS[x] for x in TOPICS if x in selected) or "не выбраны"
    status = "включена" if pref.enabled else "выключена"
    return (
        "🔔 <b>Моя подборка на выходные</b>\n\n"
        f"📍 Город: <b>{html.escape(pref.city)}</b>\n"
        f"🗺 Радиус: <b>{RADIUS_LABELS.get(pref.radius_km, f'{pref.radius_km} км')}</b>\n"
        f"🎛 Темы: {topics}\n"
        f"📨 Рассылка: <b>{status}</b>\n\n"
        "Подборка приходит по четвергам. Город, темы и радиус можно изменить в любой момент."
    )


async def _get_pref(user_id: int) -> DigestPreference | None:
    async with get_session() as session:
        return await session.get(DigestPreference, user_id)


async def _open_digest_settings(message: Message, state: FSMContext, user_id: int) -> None:
    """Открывает настройки как из команды, так и из кнопки в рассылке."""
    await state.clear()
    pref = await _get_pref(user_id)
    if pref:
        await message.answer(_settings_text(pref), reply_markup=_settings_kb(pref))
        return
    await state.set_state(DigestSetup.waiting_city)
    await message.answer(
        "🔔 <b>Планы на выходные — лично для тебя</b>\n\n"
        "Каждый четверг буду присылать интересное рядом: события, прогулки и другие "
        "выбранные темы. Никакой геолокации или адреса — нужен только город.\n\n"
        "📍 В каком городе ты живёшь?",
        reply_markup=cancel_menu(),
    )


@router.message(Command("digest", "subscriptions"))
@router.message(F.text == BTN_SUBSCRIPTIONS)
async def digest_start(message: Message, state: FSMContext) -> None:
    await _open_digest_settings(message, state, message.from_user.id)


@router.callback_query(F.data == "dg:announce:setup")
async def digest_announcement_setup(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await _open_digest_settings(callback.message, state, callback.from_user.id)


@router.message(DigestSetup.waiting_city)
async def digest_city_input(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    if len(raw) < 2:
        await message.answer("Напиши название города текстом 🙂")
        return
    city, province = _canonical_city(raw)
    await state.update_data(dg_city=city, dg_province=province)
    await state.set_state(DigestSetup.choosing_radius)
    await message.answer(
        f"Запомнил: <b>{html.escape(city)}</b> 📍\n\nКак далеко готов ехать ради интересного события?",
        reply_markup=_radius_kb(),
    )


@router.callback_query(F.data.startswith("dg:r:"))
async def digest_radius_pick(callback: CallbackQuery, state: FSMContext) -> None:
    radius = int(callback.data.rsplit(":", 1)[1])
    current = await state.get_state()
    pref = await _get_pref(callback.from_user.id)
    if current == DigestSetup.choosing_radius.state:
        data = await state.get_data()
        selected = set(data.get("dg_topics") or (pref and _topics(pref.topics_csv)) or DEFAULT_TOPICS)
        await state.update_data(dg_radius=radius, dg_topics=list(selected))
        await state.set_state(DigestSetup.choosing_topics)
        await callback.message.answer(
            "Что включать в твою подборку? Можно выбрать несколько тем 👇",
            reply_markup=_topics_kb(selected),
        )
    elif pref:
        async with get_session() as session:
            row = await session.get(DigestPreference, callback.from_user.id)
            row.radius_km = radius
            await session.commit()
        updated = await _get_pref(callback.from_user.id)
        await callback.message.answer("Радиус обновлён ✅", reply_markup=_settings_kb(updated))
    await callback.answer()


@router.callback_query(F.data.startswith("dg:t:"))
async def digest_topic_pick(callback: CallbackQuery, state: FSMContext) -> None:
    key = callback.data.rsplit(":", 1)[1]
    data = await state.get_data()
    choosing = await state.get_state() == DigestSetup.choosing_topics.state
    pref = await _get_pref(callback.from_user.id)
    selected = set(data.get("dg_topics", [])) if choosing else _topics(pref.topics_csv if pref else "")
    if key != "done":
        selected.symmetric_difference_update({key})
        await state.update_data(dg_topics=list(selected))
        await callback.message.edit_reply_markup(reply_markup=_topics_kb(selected))
        await callback.answer("Выбрано" if key in selected else "Убрано")
        return
    if not selected:
        await callback.answer("Выбери хотя бы одну тему", show_alert=True)
        return
    if pref:
        async with get_session() as session:
            row = await session.get(DigestPreference, callback.from_user.id)
            row.topics_csv = _topics_csv(selected)
            if data.get("dg_city"):
                row.city = data["dg_city"]
                row.province = data.get("dg_province", "")
                row.radius_km = int(data.get("dg_radius", row.radius_km))
            await session.commit()
        await state.clear()
        await callback.message.answer("Настройки обновлены ✅", reply_markup=_settings_kb(await _get_pref(callback.from_user.id)))
    else:
        city, province = data["dg_city"], data.get("dg_province", "")
        async with get_session() as session:
            session.add(DigestPreference(
                user_id=callback.from_user.id, city=city, province=province,
                radius_km=int(data.get("dg_radius", 25)),
                topics_csv=_topics_csv(selected), enabled=True,
            ))
            await session.commit()
        await state.clear()
        saved = await _get_pref(callback.from_user.id)
        await callback.message.answer(
            "Готово — подборка включена 🙌\n\n" + _settings_text(saved),
            reply_markup=_settings_kb(saved),
        )
    await callback.answer()


@router.callback_query(F.data == "dg:city")
async def digest_change_city(callback: CallbackQuery, state: FSMContext) -> None:
    pref = await _get_pref(callback.from_user.id)
    await state.set_state(DigestSetup.waiting_city)
    if pref:
        await state.update_data(
            dg_topics=list(_topics(pref.topics_csv)), dg_radius=pref.radius_km,
            dg_edit_city=True,
        )
    await callback.message.answer("📍 Напиши новый город:", reply_markup=cancel_menu())
    await callback.answer()


@router.callback_query(F.data == "dg:radius")
async def digest_change_radius(callback: CallbackQuery) -> None:
    await callback.message.answer("Какой радиус использовать?", reply_markup=_radius_kb())
    await callback.answer()


@router.callback_query(F.data == "dg:topics")
async def digest_change_topics(callback: CallbackQuery, state: FSMContext) -> None:
    pref = await _get_pref(callback.from_user.id)
    if not pref:
        await callback.answer("Сначала настрой подборку", show_alert=True)
        return
    await state.set_state(DigestSetup.choosing_topics)
    await state.update_data(dg_topics=list(_topics(pref.topics_csv)), dg_edit=True)
    await callback.message.answer("Выбери темы:", reply_markup=_topics_kb(_topics(pref.topics_csv)))
    await callback.answer()


@router.callback_query(F.data == "dg:toggle")
async def digest_toggle(callback: CallbackQuery) -> None:
    async with get_session() as session:
        pref = await session.get(DigestPreference, callback.from_user.id)
        if not pref:
            await callback.answer("Сначала настрой подборку", show_alert=True)
            return
        pref.enabled = not pref.enabled
        enabled = pref.enabled
        await session.commit()
    updated = await _get_pref(callback.from_user.id)
    await callback.message.answer(
        "Подборка включена 🔔" if enabled else "Подборка отключена. Вернуться можно в любой момент 🔕",
        reply_markup=_settings_kb(updated),
    )
    await callback.answer()


def _next_month_key(day: date) -> str:
    first = (day.replace(day=28) + timedelta(days=4)).replace(day=1)
    return f"{first:%Y-%m}"


_MONTHS = {
    "januari": 1, "январ": 1, "februari": 2, "феврал": 2,
    "maart": 3, "март": 3, "april": 4, "апрел": 4,
    "mei": 5, "май": 5, "июн": 6, "juni": 6, "июл": 7, "juli": 7,
    "augustus": 8, "август": 8, "september": 9, "сентябр": 9,
    "oktober": 10, "октябр": 10, "november": 11, "ноябр": 11,
    "december": 12, "декабр": 12,
}


def _listing_event_day(raw: str | None, *, today: date | None = None) -> date | None:
    """Консервативно извлекает дату ручной афиши; непонятную дату не угадывает."""
    text = (raw or "").strip().casefold()
    current = today or datetime.now(ZoneInfo("Europe/Amsterdam")).date()
    match = re.search(r"\b(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})\b", text)
    if match:
        try:
            return date(*map(int, match.groups()))
        except ValueError:
            return None
    match = re.search(r"\b(\d{1,2})[-/.](\d{1,2})(?:[-/.](20\d{2}))?\b", text)
    if match:
        day, month, year = match.groups()
        try:
            return date(int(year or current.year), int(month), int(day))
        except ValueError:
            return None
    for word, month in _MONTHS.items():
        match = re.search(rf"\b(\d{{1,2}})\s+{word}\w*(?:\s+(20\d{{2}}))?", text)
        if match:
            try:
                return date(int(match.group(2) or current.year), month, int(match.group(1)))
            except ValueError:
                return None
    return None


async def build_digest(pref: DigestPreference) -> str:
    """Собирает персональный выпуск с рабочими переходами и реальной пользой."""
    selected = _topics(pref.topics_csv)
    today = datetime.now(ZoneInfo("Europe/Amsterdam")).date()
    month_keys = [f"{today:%Y-%m}", _next_month_key(today)]
    discovered = []
    if "events" in selected:
        # Поиск общий для сегмента и кэшируется на сутки, поэтому не создаёт
        # отдельный AI-запрос на каждого получателя рассылки.
        from handlers.events import ensure_auto_afisha
        result = await ensure_auto_afisha(pref.city, pref.radius_km, pref.user_id)
        if result:
            _, discovered = result
    async with get_session() as session:
        events = (await session.scalars(
            select(EventListing).where(
                EventListing.status == "approved", EventListing.month_key.in_(month_keys)
            ).order_by(EventListing.month_key, EventListing.id)
        )).all()
        specialists = (await session.scalars(
            select(Specialist).where(Specialist.status == "active", Specialist.source == "self")
            .order_by(Specialist.id.desc()).limit(30)
        )).all()
        listings = (await session.scalars(
            select(Listing).where(
                Listing.status == "approved",
                or_(Listing.expires_at.is_(None), Listing.expires_at > datetime.utcnow()),
            ).order_by(Listing.bumped_at.desc(), Listing.id.desc()).limit(40)
        )).all()

    # Ручная афиша — только с распознаваемой будущей датой и отдельной ссылкой.
    # Так старые карточки текущего месяца не возвращаются в подборку.
    local_events = [
        x for x in events
        if location_matches(pref, x.city, nationwide=x.is_nationwide)
        and _listing_event_day(x.event_date, today=today) is not None
        and _listing_event_day(x.event_date, today=today) >= today
        and bool(x.link)
    ][:4]
    local_specs = [x for x in specialists if location_matches(
        pref, x.city, nationwide=x.is_online, target_province=x.province
    )][:3]
    local_listings = [x for x in listings if location_matches(pref, x.city, nationwide=x.is_nationwide)][:3]
    walks = []
    for walk in config.available_allo_walks():
        walk_city, _ = _canonical_city(f"{walk.get('title', '')} {walk.get('meet', '')}")
        if location_matches(pref, walk_city):
            walks.append(walk)

    radius = RADIUS_LABELS.get(pref.radius_km, f"до {pref.radius_km} км")
    lines = [
        f"☀️ <b>Планы на выходные · {_weekend_label(today)}</b>",
        f"📍 {html.escape(pref.city)} · {radius}",
    ]
    useful = 0
    if "events" in selected:
        lines.extend(["", "<b>🎭 События рядом</b>"])
        if discovered:
            for ev in discovered[:4]:
                title = f'<a href="{html.escape(ev.link, quote=True)}">{html.escape(ev.title)}</a>'
                place = " · ".join(x for x in (ev.venue, ev.city) if x)
                lines.append(
                    f"• <b>{title}</b> · {html.escape(ev.event_date)}\n"
                    f"  {html.escape(place)}"
                )
                useful += 1
        elif local_events:
            for ev in local_events:
                when = f" · {html.escape(ev.event_date)}" if ev.event_date else ""
                where = "онлайн / вся страна" if ev.is_nationwide else ev.city
                title = html.escape(ev.title)
                if ev.link:
                    url = ev.link if ev.link.startswith(("http://", "https://")) else f"https://{ev.link}"
                    title = f'<a href="{html.escape(url, quote=True)}">{title}</a>'
                lines.append(f"• <b>{title}</b>{when}\n  {html.escape(where)}")
                useful += 1
        else:
            lines.append("Не удалось найти проверяемые события с рабочими ссылками — попробуй обновить афишу кнопкой ниже.")
    if "walks" in selected and walks:
        lines.extend(["", "<b>🚶 Allo Walks</b>"])
        for walk in walks[:2]:
            lines.append(f"• <b>{html.escape(walk['date'])}</b> · {html.escape(walk['title'])}")
            useful += 1
    if "specialists" in selected:
        lines.extend(["", "<b>🔍 Новые специалисты</b>"])
        if local_specs:
            for sp in local_specs:
                where = "онлайн" if sp.is_online else (sp.city or sp.province)
                name = (
                    f'<a href="{html.escape(config.specialist_url(sp.id), quote=True)}">'
                    f'{html.escape(sp.name)}</a>'
                )
                lines.append(f"• <b>{name}</b> · {html.escape(sp.category)} · {html.escape(where)}")
                useful += 1
        else:
            lines.append("Новых карточек рядом на этой неделе нет.")
    if "board" in selected:
        lines.extend(["", "<b>📋 Свежие объявления</b>"])
        if local_listings:
            for item in local_listings:
                lines.append(f"• {html.escape(item.title)} · {html.escape(item.city or 'вся страна')}")
                useful += 1
        else:
            lines.append("Свежих объявлений рядом пока нет.")
    if "guides" in selected:
        from handlers.guides import weekly_tip
        tip = weekly_tip(today.isocalendar().week)
        lines.extend([
            "",
            f"<b>📚 Полезное на этой неделе: {html.escape(tip['title'])}</b>",
            html.escape(tip["text"]),
        ])
        useful += 1
    lines.extend([
        "",
        ("Выбирай, что открыть подробнее 👇" if useful else
         "Пока рядом немного карточек, но живой поиск уже доступен по кнопке ниже 👇"),
        "<i>Настройки города и тем — /digest</i>",
    ])
    return "\n".join(lines)


def _digest_kb(pref: DigestPreference) -> InlineKeyboardMarkup:
    rows = []
    if "events" in _topics(pref.topics_csv):
        rows.append([InlineKeyboardButton(text="🎭 Листать афишу рядом", callback_data="dg:afisha")])
    if "walks" in _topics(pref.topics_csv) and config.available_allo_walks():
        rows.append([InlineKeyboardButton(text="🚶 Allo Walks", callback_data="ev_allo")])
    if "guides" in _topics(pref.topics_csv):
        from handlers.guides import weekly_tip
        tip = weekly_tip(datetime.now(ZoneInfo("Europe/Amsterdam")).isocalendar().week)
        rows.append([InlineKeyboardButton(
            text=tip.get("button", "📚 Официальный источник"),
            url=tip["url"],
        )])
    rows.append([InlineKeyboardButton(text="⚙️ Настроить подборку", callback_data="dg:settings")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data == "dg:preview")
async def digest_preview_user(callback: CallbackQuery) -> None:
    pref = await _get_pref(callback.from_user.id)
    if pref:
        await callback.message.answer(await build_digest(pref), reply_markup=_digest_kb(pref))
    await callback.answer()


@router.callback_query(F.data == "dg:settings")
async def digest_settings_callback(callback: CallbackQuery) -> None:
    pref = await _get_pref(callback.from_user.id)
    if pref:
        await callback.message.answer(_settings_text(pref), reply_markup=_settings_kb(pref))
    await callback.answer()


@router.callback_query(F.data == "dg:live")
async def digest_live_events(callback: CallbackQuery, state: FSMContext) -> None:
    pref = await _get_pref(callback.from_user.id)
    if not pref:
        await callback.answer("Сначала настрой город", show_alert=True)
        return
    await callback.answer()
    from handlers.events import _show_events
    await _show_events(callback.message, state, pref.city, callback.from_user.id)


@router.callback_query(F.data == "dg:afisha")
async def digest_auto_afisha(callback: CallbackQuery, state: FSMContext) -> None:
    pref = await _get_pref(callback.from_user.id)
    if not pref:
        await callback.answer("Сначала настрой город", show_alert=True)
        return
    await callback.answer()
    await state.clear()
    from handlers.events import show_auto_afisha
    await show_auto_afisha(
        callback.message, pref.city, pref.radius_km, callback.from_user.id
    )


async def _digest_admin_summary() -> str:
    async with get_session() as session:
        total = await session.scalar(select(func.count()).select_from(DigestPreference)) or 0
        enabled = await session.scalar(select(func.count()).select_from(DigestPreference).where(DigestPreference.enabled.is_(True))) or 0
        cities = (await session.execute(
            select(DigestPreference.city, func.count()).where(DigestPreference.enabled.is_(True))
            .group_by(DigestPreference.city).order_by(func.count().desc()).limit(10)
        )).all()
        sent = await session.scalar(select(func.count()).select_from(DigestDeliveryLog).where(
            DigestDeliveryLog.week_key == _week_key(), DigestDeliveryLog.status == "sent"
        )) or 0
        failed = await session.scalar(select(func.count()).select_from(DigestDeliveryLog).where(
            DigestDeliveryLog.week_key == _week_key(), DigestDeliveryLog.status == "failed"
        )) or 0
    city_lines = "\n".join(f"• {html.escape(city)} — {count}" for city, count in cities) or "Пока нет городов."
    return (
        "☀️ <b>Персональная подборка на выходные</b>\n\n"
        f"Подписки: {enabled} включено · {total} настроено\n"
        f"Текущая неделя: ✅ {sent} · ❌ {failed}\n\n"
        f"<b>Города</b>\n{city_lines}\n\n"
        "Предпросмотр: <code>/digestpreview Amsterdam</code>\n"
        "Отправка: <code>/digestsend</code>"
    )


@router.message(Command("digeststats"), F.from_user.id.in_(config.ADMIN_IDS))
async def digest_stats(message: Message) -> None:
    await message.answer(await _digest_admin_summary())


@router.callback_query(F.data == "admin:digest", F.from_user.id.in_(config.ADMIN_IDS))
async def digest_admin_button(callback: CallbackQuery) -> None:
    await callback.message.answer(await _digest_admin_summary())
    await callback.answer()


@router.message(Command("digestpreview"), F.from_user.id.in_(config.ADMIN_IDS))
async def digest_preview_admin(message: Message) -> None:
    raw = (message.text or "").partition(" ")[2].strip()
    pref = await _get_pref(message.from_user.id) if not raw else None
    if pref is None:
        city, province = _canonical_city(raw or "Amsterdam")
        pref = DigestPreference(
            user_id=message.from_user.id, city=city, province=province, radius_km=25,
            topics_csv=_topics_csv(set(TOPICS)), enabled=True,
        )
    await message.answer(
        f"👁 <b>Предпросмотр: {html.escape(pref.city)} · "
        f"{html.escape(RADIUS_LABELS.get(pref.radius_km, f'{pref.radius_km} км'))}</b>\n\n"
        + await build_digest(pref),
        reply_markup=_digest_kb(pref),
    )


@router.message(Command("digesttest"), F.from_user.id.in_(config.ADMIN_IDS))
async def digest_test_admin(message: Message) -> None:
    """Отправляет админу точную копию его будущей рассылки без журнала доставки."""
    pref = await _get_pref(message.from_user.id)
    if pref is None:
        await message.answer(
            "Сначала настрой свою подборку через /digest, а затем повтори /digesttest."
        )
        return
    await message.answer(
        "🧪 <b>Тестовая отправка только тебе</b>\n"
        "Следующее сообщение — точно такой вид будет иметь еженедельная подборка. "
        "Тест не засчитывается как рассылка."
    )
    await message.bot.send_message(
        message.from_user.id,
        await build_digest(pref),
        reply_markup=_digest_kb(pref),
        disable_web_page_preview=True,
    )


def _send_confirm_kb(count: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"✅ Отправить персонально ({count})", callback_data="dg:send:yes")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="dg:send:no")],
    ])


@router.message(Command("digestsend"), F.from_user.id.in_(config.ADMIN_IDS))
async def digest_send_confirm(message: Message) -> None:
    async with get_session() as session:
        count = await session.scalar(
            select(func.count()).select_from(DigestPreference)
            .join(BotUser, BotUser.user_id == DigestPreference.user_id)
            .where(DigestPreference.enabled.is_(True), BotUser.is_blocked.is_(False),
                   or_(DigestPreference.last_sent_week.is_(None), DigestPreference.last_sent_week != _week_key()))
        ) or 0
    await message.answer(
        f"Подготовлена персональная рассылка на неделю {_week_key()}.\n"
        f"Получателей без отправки на этой неделе: <b>{count}</b>.\n\nОтправить?",
        reply_markup=_send_confirm_kb(count),
    )


@router.callback_query(F.data == "dg:send:no", F.from_user.id.in_(config.ADMIN_IDS))
async def digest_send_cancel(callback: CallbackQuery) -> None:
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("Рассылка отменена 👌")
    await callback.answer()


@router.callback_query(F.data == "dg:send:yes", F.from_user.id.in_(config.ADMIN_IDS))
async def digest_send_start(callback: CallbackQuery) -> None:
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("🚀 Персональная рассылка запущена. Итог пришлю сюда.")
    asyncio.create_task(_send_all_digests(callback.bot, callback.from_user.id))
    await callback.answer()


async def _send_all_digests(bot, admin_id: int) -> None:
    week = _week_key()
    async with get_session() as session:
        rows = (await session.scalars(
            select(DigestPreference).join(BotUser, BotUser.user_id == DigestPreference.user_id)
            .where(DigestPreference.enabled.is_(True), BotUser.is_blocked.is_(False),
                   or_(DigestPreference.last_sent_week.is_(None), DigestPreference.last_sent_week != week))
        )).all()
    sent = failed = 0
    rendered: dict[tuple[str, str, int, str], str] = {}
    for pref in rows:
        segment = (pref.city, pref.province, pref.radius_km, pref.topics_csv)
        text = rendered.get(segment)
        if text is None:
            text = await build_digest(pref)
            rendered[segment] = text
        message_id = None
        error = None
        try:
            msg = await bot.send_message(pref.user_id, text, reply_markup=_digest_kb(pref), disable_web_page_preview=True)
            message_id = getattr(msg, "message_id", None)
            sent += 1
        except TelegramForbiddenError as exc:
            error = f"{type(exc).__name__}: {exc}"
            failed += 1
            async with get_session() as session:
                user = await session.get(BotUser, pref.user_id)
                if user:
                    user.is_blocked = True
                    await session.commit()
        except Exception as exc:  # noqa: BLE001
            error = f"{type(exc).__name__}: {exc}"
            failed += 1
        async with get_session() as session:
            session.add(DigestDeliveryLog(
                user_id=pref.user_id, week_key=week, city=pref.city,
                status="sent" if error is None else "failed", message_text=text,
                telegram_message_id=message_id, error_text=error,
            ))
            current = await session.get(DigestPreference, pref.user_id)
            if current and error is None:
                current.last_sent_week = week
            await session.commit()
        await asyncio.sleep(0.05)
    try:
        await bot.send_message(admin_id, f"✅ Подборка {_week_key()} завершена.\nДоставлено: {sent}\nНе доставлено: {failed}")
    except Exception:  # noqa: BLE001
        pass


async def digest_draft_loop(bot) -> None:
    """По четвергам один раз напоминает админам проверить и запустить выпуск."""
    while True:
        try:
            now = datetime.now(ZoneInfo("Europe/Amsterdam"))
            if now.weekday() == 3:
                key = f"digest_draft:{_week_key(now)}"
                async with get_session() as session:
                    done = await session.get(Meta, key)
                    if done is None:
                        await session.merge(Meta(key=key, value=now.isoformat()[:19]))
                        await session.commit()
                        for admin_id in config.ADMIN_IDS:
                            try:
                                await bot.send_message(
                                    admin_id,
                                    "☀️ <b>Пора подготовить подборку на выходные</b>\n\n"
                                    "Посмотри сегменты: /digeststats\n"
                                    "Проверь пример: /digestpreview Amsterdam\n"
                                    "Запусти после проверки: /digestsend",
                                )
                            except Exception as exc:  # noqa: BLE001
                                log.warning("Не удалось напомнить админу %s о подборке: %s", admin_id, exc)
        except Exception as exc:  # noqa: BLE001
            log.warning("Ошибка цикла еженедельной подборки: %s", exc)
        await asyncio.sleep(6 * 3600)


def digest_announcement_text() -> str:
    """Утверждённый анонс добровольных персональных подписок."""
    return (
        "☀️ <b>Теперь я могу собирать планы на выходные именно для тебя</b>\n\n"
        "Не общую афишу на всю страну, а подборку рядом с домом. Ты указываешь "
        "свой город, выбираешь, как далеко готов(а) ехать — только по городу, "
        "до 25 или 50 км — и отмечаешь, что тебе интересно.\n\n"
        "По четвергам я буду присылать:\n\n"
        "🎭 события рядом — с датой, местом и прямой ссылкой;\n"
        "🚶 новые Allo Walks;\n"
        "🔍 новых специалистов — имя открывает карточку и контакты;\n"
        "📋 свежие объявления;\n"
        "📚 один практический совет о жизни в Нидерландах прямо в сообщении.\n\n"
        "События можно листать по одной карточке, как афишу.\n\n"
        "Можно выбрать только нужные темы, изменить город или отключить подборку "
        "в любой момент.\n\n"
        "Адрес и геолокация мне не нужны — сохраняется только выбранный город.\n\n"
        "Настроим твою подборку? 👇"
    )


def digest_announcement_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="🔔 Настроить мою подборку", callback_data="dg:announce:setup")],
        [InlineKeyboardButton(
            text="☀️ Найти события сейчас", callback_data="ev_search")],
    ])


@router.message(Command("digestannouncepreview"), F.from_user.id.in_(config.ADMIN_IDS))
async def digest_announcement_preview(message: Message) -> None:
    await message.answer(
        digest_announcement_text(), reply_markup=digest_announcement_kb(),
        disable_web_page_preview=True,
    )


async def _send_digest_announcement(bot) -> tuple[int, int]:
    """Рассылает анонс всем активным пользователям, продолжая после рестарта."""
    async with get_session() as session:
        already_sent = select(AnnouncementDelivery.user_id).where(
            AnnouncementDelivery.campaign_key == ANNOUNCEMENT_KEY,
            AnnouncementDelivery.status == "sent",
        )
        user_ids = (await session.scalars(
            select(BotUser.user_id).where(
                BotUser.is_blocked.is_(False),
                BotUser.user_id.not_in(already_sent),
            )
        )).all()
    sent = failed = 0
    for user_id in user_ids:
        message_id = None
        error = None
        status = "failed"
        try:
            message = await bot.send_message(
                user_id, digest_announcement_text(),
                reply_markup=digest_announcement_kb(), disable_web_page_preview=True,
            )
            message_id = getattr(message, "message_id", None)
            status = "sent"
            sent += 1
        except TelegramForbiddenError as exc:
            error = f"{type(exc).__name__}: {exc}"
            status = "blocked"
            failed += 1
            async with get_session() as session:
                user = await session.get(BotUser, user_id)
                if user:
                    user.is_blocked = True
                    await session.commit()
        except Exception as exc:  # noqa: BLE001
            error = f"{type(exc).__name__}: {exc}"
            failed += 1
            log.warning("Не удалось отправить анонс подписок пользователю %s: %s", user_id, exc)
        async with get_session() as session:
            previous = await session.scalar(select(AnnouncementDelivery).where(
                AnnouncementDelivery.campaign_key == ANNOUNCEMENT_KEY,
                AnnouncementDelivery.user_id == user_id,
            ))
            if previous:
                previous.status = status
                previous.telegram_message_id = message_id
                previous.error_text = error
            else:
                session.add(AnnouncementDelivery(
                    campaign_key=ANNOUNCEMENT_KEY,
                    user_id=user_id,
                    status=status,
                    telegram_message_id=message_id,
                    error_text=error,
                ))
            await session.commit()
        await asyncio.sleep(0.05)
    return sent, failed


async def digest_announcement_loop(bot) -> None:
    """Сразу после деплоя запускает одну возобновляемую массовую отправку."""
    async with get_session() as session:
        marker = await session.get(Meta, ANNOUNCEMENT_KEY)
        if marker is not None and marker.value.startswith("done:"):
            return
        await session.merge(Meta(
            key=ANNOUNCEMENT_KEY,
            value=f"started:{datetime.now(ZoneInfo('Europe/Amsterdam')):%Y-%m-%dT%H:%M}",
        ))
        await session.commit()

    sent, failed = await _send_digest_announcement(bot)
    async with get_session() as session:
        marker = await session.get(Meta, ANNOUNCEMENT_KEY)
        if marker:
            marker.value = f"done:sent={sent}:failed={failed}"
            await session.commit()
    for admin_id in config.ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                "✅ <b>Анонс персональных подписок отправлен</b>\n"
                f"Доставлено: {sent}\nНе доставлено: {failed}",
            )
        except Exception:  # noqa: BLE001
            pass
