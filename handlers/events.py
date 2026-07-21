"""Раздел «Чем заняться» — афиша и сезонные идеи по городу.

Опирается на живой веб-поиск ИИ: реальные события на ближайшие дни + сезонные
идеи. Сезон определяется по дате автоматически («этим летом / этой осенью…»).
"""
import html
import logging
import secrets
from datetime import date, datetime, timedelta

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    Message,
)
from sqlalchemy import select

import config
from database.db import get_session
from database.models import DiscoveredEvent, EventListing
from handlers.afisha import _card_text, _month_label
from keyboards.menus import cancel_menu, main_menu
from states.forms import EventsSearch
from utils.ai import ai_enabled, ai_event_cards
from utils.analytics import log_event
from utils.limits import allow_ai
from utils.season import EVENTS_LABEL_CORE, current_season

log = logging.getLogger(__name__)

router = Router()
router.message.filter(F.chat.type == ChatType.PRIVATE)

POPULAR_CITIES = ["Amsterdam", "Rotterdam", "Den Haag", "Utrecht", "Eindhoven", "Groningen"]


def _cities_kb() -> InlineKeyboardMarkup:
    btns = [InlineKeyboardButton(text=c, callback_data=f"ev|{c}") for c in POPULAR_CITIES]
    rows = [btns[i:i + 2] for i in range(0, len(btns), 2)]
    rows.append([InlineKeyboardButton(text="🌍 По всей стране", callback_data="ev|__all__")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _is_events_button(message: Message) -> bool:
    """Кнопка меню «☀️/🍂/❄️/🌷 Чем заняться» — эмодзи меняется по сезону."""
    return bool(message.text) and message.text.endswith(EVENTS_LABEL_CORE)


@router.message(Command("afisha", "events"))
@router.message(_is_events_button)
async def events_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    s = current_season()
    month_label = _month_label(f"{date.today():%Y-%m}")
    rows = [
        [InlineKeyboardButton(text="🎭 Собрать свежую афишу рядом",
                              callback_data="ev_search")],
        [InlineKeyboardButton(text=f"📅 Афиша · {month_label.capitalize()}",
                              callback_data="ev_afisha")],
    ]
    walks = config.available_allo_walks()
    if walks:
        rows.insert(0, [InlineKeyboardButton(
            text=f"🚶 Allo Walks · {walks[0]['date'].split(' · ')[0]}",
            callback_data="ev_allo")])
    kb = InlineKeyboardMarkup(inline_keyboard=rows)
    allo_line = ("🚶 <b>Allo Walks</b> — прогулки для знакомств и общения.\n"
                 if walks else "")
    text = (
        f"{s['emoji']} <b>Чем заняться {s['phrase']}</b> 🎉\n\n"
        f"{allo_line}"
        "🎭 <b>Свежая афиша рядом</b> — отдельные карточки с датой, местом и ссылкой.\n"
        "📅 <b>Афиша месяца</b> — мероприятия, добавленные организаторами.\n\n"
        "<i>Организуете мероприятие? Разместите его в нашей афише: /afisha_add</i>"
    )
    await message.answer(
        text,
        reply_markup=kb,
    )


@router.callback_query(F.data == "ev_allo")
async def events_allo(callback: CallbackQuery, state: FSMContext) -> None:
    from handlers.allo import show_allo

    await callback.answer()
    await show_allo(callback.message, state, with_photos=True)


def _ticket_url(ev: EventListing) -> str | None:
    """Валидный http-URL мероприятия для кнопки «Билеты» (или None)."""
    link = (ev.link or "").strip()
    if not link or " " in link or "." not in link or link.startswith("@"):
        return None
    return link if link.startswith(("http://", "https://")) else f"https://{link}"


def _afisha_kb(month_key: str, idx: int, total: int, ev: EventListing) -> InlineKeyboardMarkup:
    """Клавиатура карточки афиши: «Билеты» + навигация ◀️ N/M ▶️."""
    rows: list[list[InlineKeyboardButton]] = []
    url = _ticket_url(ev)
    if url:
        rows.append([InlineKeyboardButton(text="🎟 Билеты / подробнее", url=url)])
    if total > 1:
        prev, nxt = (idx - 1) % total, (idx + 1) % total
        rows.append([
            InlineKeyboardButton(text="◀️", callback_data=f"afv:{month_key}:{prev}"),
            InlineKeyboardButton(text=f"{idx + 1}/{total}", callback_data="afv_noop"),
            InlineKeyboardButton(text="▶️", callback_data=f"afv:{month_key}:{nxt}"),
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _afisha_events(month_key: str) -> list[EventListing]:
    async with get_session() as session:
        return (
            await session.scalars(
                select(EventListing)
                .where(EventListing.month_key == month_key, EventListing.status == "approved")
                .order_by(EventListing.is_nationwide, EventListing.city, EventListing.id)
            )
        ).all()


async def _afisha_show(msg: Message, month_key: str, idx: int, edit: bool) -> None:
    """Показывает одну карточку афиши. edit=True — листание на месте (edit_media)."""
    rows = await _afisha_events(month_key)
    if not rows:
        await msg.answer(
            f"📅 Афиша на {_month_label(month_key)} пока готовится — загляни позже 🙌",
            reply_markup=main_menu(),
        )
        return
    idx %= len(rows)
    ev = rows[idx]
    caption = _card_text(ev)
    kb = _afisha_kb(month_key, idx, len(rows), ev)
    if edit and ev.photo_file_id:
        try:
            await msg.edit_media(
                InputMediaPhoto(media=ev.photo_file_id, caption=caption, parse_mode="HTML"),
                reply_markup=kb,
            )
            return
        except Exception:  # noqa: BLE001 — не вышло отредактировать, пришлём заново
            pass
    if ev.photo_file_id:
        try:
            await msg.answer_photo(ev.photo_file_id, caption=caption, reply_markup=kb)
            return
        except Exception:  # noqa: BLE001 — постер недоступен → текстом
            pass
    await msg.answer(caption, reply_markup=kb, disable_web_page_preview=True)


@router.callback_query(F.data == "ev_afisha")
async def events_afisha(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    month_key = f"{date.today():%Y-%m}"
    rows = await _afisha_events(month_key)
    if not rows:
        # Ручная платная афиша может быть пустой, но пользователь не должен
        # попадать в тупик: сразу открываем автоматическую афишу по городу.
        if not ai_enabled():
            await callback.message.answer(
                "Автоматический поиск событий сейчас недоступен. Попробуй позже 🙏",
                reply_markup=main_menu(),
            )
            return
        await state.set_state(EventsSearch.waiting_city)
        await callback.message.answer(
            "📍 В каком городе собрать афишу? Напиши или выбери 👇",
            reply_markup=cancel_menu(),
        )
        await callback.message.answer("Города:", reply_markup=_cities_kb())
        return
    await log_event("afisha_view", month_key)
    await callback.message.answer(
        f"📅 <b>Афиша · {_month_label(month_key)}</b> — {len(rows)} меропр. "
        "Листай кнопками ◀️ ▶️ под карточкой 👇",
        reply_markup=main_menu(),
    )
    await _afisha_show(callback.message, month_key, 0, edit=False)


@router.callback_query(F.data.startswith("afv:"))
async def afisha_nav(callback: CallbackQuery) -> None:
    try:
        _, month_key, idx = callback.data.split(":")
    except ValueError:
        await callback.answer()
        return
    await callback.answer()
    await _afisha_show(callback.message, month_key, int(idx), edit=True)


@router.callback_query(F.data == "afv_noop")
async def afisha_noop(callback: CallbackQuery) -> None:
    await callback.answer()


@router.callback_query(F.data == "ev_search")
async def events_search(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if not ai_enabled():
        await callback.message.answer(
            "Поиск событий сейчас недоступен 🙏 Загляни в «📅 Афиша месяца» — "
            "там наши мероприятия.",
            reply_markup=main_menu(),
        )
        return
    s = current_season()
    await state.set_state(EventsSearch.waiting_city)
    await callback.message.answer(
        f"{s['emoji']} В каком городе показать события? Напиши или выбери 👇",
        reply_markup=cancel_menu(),
    )
    await callback.message.answer("📍 Города:", reply_markup=_cities_kb())


@router.callback_query(F.data.startswith("ev|"))
async def events_city_cb(callback: CallbackQuery, state: FSMContext) -> None:
    city = callback.data.split("|", 1)[1]
    await callback.answer()
    await _show_events(callback.message, state, city, uid=callback.from_user.id)


@router.message(EventsSearch.waiting_city)
async def events_city_msg(message: Message, state: FSMContext) -> None:
    city = (message.text or "").strip()
    if not city:
        await message.answer("Напиши город текстом 🙂")
        return
    await _show_events(message, state, city, uid=message.from_user.id)


async def _show_events(message: Message, state: FSMContext, city: str, uid: int) -> None:
    await state.clear()
    query_city = "Нидерланды" if city == "__all__" else city
    await show_auto_afisha(message, query_city, 999 if city == "__all__" else 25, uid)


async def _auto_batch(city: str, radius_km: int) -> tuple[str, list[DiscoveredEvent]] | None:
    """Возвращает свежий кэш одного поиска, если он уже существует."""
    now = datetime.utcnow()
    async with get_session() as session:
        batch = await session.scalar(
            select(DiscoveredEvent.batch_key)
            .where(
                DiscoveredEvent.query_city == city,
                DiscoveredEvent.radius_km == radius_km,
                DiscoveredEvent.expires_at > now,
            )
            .order_by(DiscoveredEvent.fetched_at.desc())
            .limit(1)
        )
        if not batch:
            return None
        rows = (await session.scalars(
            select(DiscoveredEvent)
            .where(DiscoveredEvent.batch_key == batch)
            .order_by(DiscoveredEvent.id)
        )).all()
    return (batch, list(rows)) if rows else None


async def ensure_auto_afisha(city: str, radius_km: int, uid: int) -> tuple[str, list[DiscoveredEvent]] | None:
    """Берёт общий кэш сегмента либо один раз наполняет его живым веб-поиском."""
    cached = await _auto_batch(city, radius_km)
    if cached:
        return cached
    if not ai_enabled() or not allow_ai(uid):
        return None
    cards = await ai_event_cards(city, radius_km)
    if not cards:
        return None
    batch = secrets.token_hex(6)
    expires = datetime.utcnow() + timedelta(hours=24)
    async with get_session() as session:
        for card in cards:
            session.add(DiscoveredEvent(
                batch_key=batch,
                query_city=city,
                radius_km=radius_km,
                title=card["title"],
                description=card["description"],
                event_date=card["date"],
                venue=card["venue"],
                city=card["city"] or city,
                link=card["url"],
                source_name=card["source"],
                expires_at=expires,
            ))
        await session.commit()
    return await _auto_batch(city, radius_km)


def _auto_event_text(ev: DiscoveredEvent) -> str:
    place = " · ".join(x for x in (ev.venue, ev.city) if x)
    lines = [
        f"🎭 <b>{html.escape(ev.title)}</b>",
        "",
        f"📅 <b>{html.escape(ev.event_date)}</b>",
    ]
    if place:
        lines.append(f"📍 {html.escape(place)}")
    if ev.description:
        lines.extend(["", html.escape(ev.description)])
    if ev.source_name:
        lines.extend(["", f"<i>Источник: {html.escape(ev.source_name)}</i>"])
    return "\n".join(lines)


def _auto_event_kb(batch: str, idx: int, total: int, ev: DiscoveredEvent) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="🔗 Страница мероприятия", url=ev.link)]]
    if total > 1:
        rows.append([
            InlineKeyboardButton(text="◀️", callback_data=f"aev:{batch}:{(idx - 1) % total}"),
            InlineKeyboardButton(text=f"{idx + 1}/{total}", callback_data="aev_noop"),
            InlineKeyboardButton(text="▶️", callback_data=f"aev:{batch}:{(idx + 1) % total}"),
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _show_auto_card(msg: Message, batch: str, idx: int, edit: bool = False) -> None:
    async with get_session() as session:
        rows = (await session.scalars(
            select(DiscoveredEvent)
            .where(DiscoveredEvent.batch_key == batch)
            .order_by(DiscoveredEvent.id)
        )).all()
    if not rows:
        await msg.answer("Эта афиша уже обновилась — открой раздел ещё раз 🙂")
        return
    idx %= len(rows)
    text = _auto_event_text(rows[idx])
    kb = _auto_event_kb(batch, idx, len(rows), rows[idx])
    if edit:
        try:
            await msg.edit_text(text, reply_markup=kb, disable_web_page_preview=True)
            return
        except Exception:  # noqa: BLE001 — тип старого сообщения мог отличаться
            pass
    await msg.answer(text, reply_markup=kb, disable_web_page_preview=True)


async def show_auto_afisha(message: Message, city: str, radius_km: int, uid: int) -> None:
    """Показывает наполненную афишу: каждое мероприятие — отдельная карточка."""
    cached = await _auto_batch(city, radius_km)
    if not cached:
        radius = "по всей стране" if radius_km == 999 else f"в радиусе {radius_km} км"
        await message.answer(
            f"🔎 Собираю свежую афишу для <b>{html.escape(city)}</b> {radius}. "
            "Проверяю даты и ссылки — это может занять до минуты ⏳"
        )
        await message.bot.send_chat_action(message.chat.id, action="typing")
    result = cached or await ensure_auto_afisha(city, radius_km, uid)
    if not result:
        await message.answer(
            "Не получилось найти достаточно проверяемых событий с рабочими ссылками. "
            "Попробуй чуть позже или увеличь радиус.",
            reply_markup=main_menu(),
        )
        return
    batch, rows = result
    await log_event("events", city)
    await message.answer(
        f"🎭 <b>Афиша · {html.escape(city)}</b>\n"
        f"Нашёл карточек: <b>{len(rows)}</b>. Листай кнопками под событием 👇",
        reply_markup=main_menu(),
    )
    await _show_auto_card(message, batch, 0)


@router.callback_query(F.data.startswith("aev:"))
async def auto_event_nav(callback: CallbackQuery) -> None:
    try:
        _, batch, raw_idx = callback.data.split(":")
        idx = int(raw_idx)
    except (ValueError, IndexError):
        await callback.answer()
        return
    await callback.answer()
    await _show_auto_card(callback.message, batch, idx, edit=True)


@router.callback_query(F.data == "aev_noop")
async def auto_event_noop(callback: CallbackQuery) -> None:
    await callback.answer()
