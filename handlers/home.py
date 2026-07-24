"""Персональный центр пользователя «Мой Podslushano»."""
import html
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import func, or_, select

from database.db import get_session
from database.models import (
    AlloBooking,
    DigestPreference,
    DiscoveredEvent,
    EventListing,
    Listing,
    SavedItem,
    Specialist,
    Submission,
)
from keyboards.menus import BTN_HOME
from utils.analytics import log_product_event

router = Router()
router.message.filter(F.chat.type == ChatType.PRIVATE)

TYPE_LABELS = {
    "specialist": "Специалисты",
    "listing": "Объявления",
    "event": "События",
    "discovered_event": "События",
}
RADIUS_LABELS = {0: "мой город", 25: "до 25 км", 50: "до 50 км", 999: "вся страна"}
TOPIC_LABELS = {
    "events": "события",
    "walks": "Allo Walks",
    "specialists": "специалисты",
    "board": "объявления",
    "guides": "полезное",
}
STATUS_LABELS = {
    "pending": "на проверке",
    "approved": "опубликовано",
    "active": "активна",
    "awaiting_payment": "ждёт оплаты",
    "paid": "оплачено",
    "refund_requested": "возврат запрошен",
    "refunded": "возвращено",
    "rejected": "отклонено",
    "expired": "срок истёк",
    "closed": "закрыто",
}


@dataclass(frozen=True)
class HomeEvent:
    item_type: str
    item_id: int
    title: str
    date_label: str
    city: str
    url: str
    starts_on: date
    saved: bool = False


@dataclass(frozen=True)
class HomeSnapshot:
    saved_count: int
    action_count: int
    events: tuple[HomeEvent, ...]
    new_listings: tuple[Listing, ...]


def _home_kb(has_profile: bool, snapshot: HomeSnapshot) -> InlineKeyboardMarkup:
    profile = "⚙️ Настроить профиль" if has_profile else "📍 Указать город и интересы"
    rows = [
        [
            InlineKeyboardButton(
                text=f"📅 События рядом · {len(snapshot.events)}",
                callback_data="home:events",
            ),
            InlineKeyboardButton(
                text=f"🆕 Новые объявления · {len(snapshot.new_listings)}",
                callback_data="home:new",
            ),
        ],
        [
            InlineKeyboardButton(text="❤️ Сохранённое", callback_data="home:saved"),
            InlineKeyboardButton(text="🗂 Мои действия", callback_data="home:actions"),
        ],
        [InlineKeyboardButton(
            text="🔔 Центр уведомлений", callback_data="home:notifications"
        )],
        [InlineKeyboardButton(text=profile, callback_data="home:profile")],
        [InlineKeyboardButton(text="🔔 Настройки подборки", callback_data="home:digest")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _profile_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📍 Изменить город", callback_data="dg:city"),
            InlineKeyboardButton(text="🗺 Изменить радиус", callback_data="dg:radius"),
        ],
        [InlineKeyboardButton(text="🎛 Изменить интересы", callback_data="dg:topics")],
        [InlineKeyboardButton(text="⬅️ Мой Podslushano", callback_data="home:open")],
    ])


def _profile_text(pref: DigestPreference) -> str:
    topics = [
        TOPIC_LABELS[key]
        for key in (pref.topics_csv or "").split(",")
        if key in TOPIC_LABELS
    ]
    return (
        "⚙️ <b>Настройка профиля</b>\n\n"
        f"📍 Город: <b>{html.escape(pref.city)}</b>\n"
        f"🗺 Радиус: <b>{RADIUS_LABELS.get(pref.radius_km, f'{pref.radius_km} км')}</b>\n"
        f"🎛 Интересы: {html.escape(', '.join(topics) or 'не выбраны')}\n\n"
        "Эти данные используются для персональных рекомендаций в «Мой Podslushano»."
    )

async def _action_count(session, user_id: int, now: datetime) -> int:
    listings = await session.scalar(
        select(func.count()).select_from(Listing).where(
            Listing.submitter_user_id == user_id,
            Listing.status.in_(("pending", "approved", "awaiting_payment")),
            or_(Listing.expires_at.is_(None), Listing.expires_at > now),
        )
    ) or 0
    submissions = await session.scalar(
        select(func.count()).select_from(Submission).where(
            Submission.user_id == user_id, Submission.status == "pending"
        )
    ) or 0
    walks = await session.scalar(
        select(func.count()).select_from(AlloBooking).where(
            AlloBooking.user_id == user_id,
            AlloBooking.status.in_(("pending", "paid", "refund_requested")),
        )
    ) or 0
    events = await session.scalar(
        select(func.count()).select_from(EventListing).where(
            EventListing.submitter_user_id == user_id,
            EventListing.status.in_(("awaiting_payment", "pending", "approved")),
        )
    ) or 0
    cards = await session.scalar(
        select(func.count()).select_from(Specialist).where(
            Specialist.submitter_user_id == user_id,
            Specialist.status.in_(("awaiting_payment", "pending", "active")),
        )
    ) or 0
    return listings + submissions + walks + events + cards


async def _home_snapshot(
    user_id: int,
    pref: DigestPreference | None,
    *,
    now: datetime | None = None,
) -> HomeSnapshot:
    """Собирает только актуальные персональные данные для главного экрана."""
    from handlers.digest import _listing_event_day, location_matches

    current = now or datetime.utcnow()
    today = current.date()
    event_limit = today + timedelta(days=30)
    listing_since = current - timedelta(days=7)

    async with get_session() as session:
        saved_count = await session.scalar(
            select(func.count()).select_from(SavedItem).where(
                SavedItem.user_id == user_id
            )
        ) or 0
        saved_events = {
            (item.item_type, item.item_id)
            for item in (await session.scalars(select(SavedItem).where(
                SavedItem.user_id == user_id,
                SavedItem.item_type.in_(("event", "discovered_event")),
            ))).all()
        }
        action_count = await _action_count(session, user_id, current)

        manual_events = (await session.scalars(
            select(EventListing).where(EventListing.status == "approved")
            .order_by(EventListing.created_at.desc()).limit(100)
        )).all()
        discovered_events = (await session.scalars(
            select(DiscoveredEvent).where(
                DiscoveredEvent.expires_at > current,
                or_(
                    DiscoveredEvent.ends_at >= current,
                    DiscoveredEvent.ends_at.is_(None),
                ),
            ).order_by(DiscoveredEvent.starts_at.asc()).limit(100)
        )).all()
        listings = (await session.scalars(
            select(Listing).where(
                Listing.status == "approved",
                Listing.created_at >= listing_since,
                or_(Listing.expires_at.is_(None), Listing.expires_at > current),
            ).order_by(
                Listing.bumped_at.desc(), Listing.created_at.desc()
            ).limit(100)
        )).all()

    if pref is None:
        return HomeSnapshot(
            saved_count=saved_count,
            action_count=action_count,
            events=(),
            new_listings=(),
        )

    events: list[HomeEvent] = []
    seen: set[tuple[str, str, date]] = set()
    for item in manual_events:
        event_day = _listing_event_day(item.event_date, today=today)
        if (
            event_day is None
            or not today <= event_day <= event_limit
            or not item.link
            or not location_matches(
                pref, item.city, nationwide=item.is_nationwide
            )
        ):
            continue
        key = (item.title.casefold(), item.city.casefold(), event_day)
        if key in seen:
            continue
        seen.add(key)
        events.append(HomeEvent(
            item_type="event",
            item_id=item.id,
            title=item.title,
            date_label=item.event_date or f"{event_day:%d.%m}",
            city=item.city or "Нидерланды",
            url=item.link,
            starts_on=event_day,
            saved=("event", item.id) in saved_events,
        ))
    for item in discovered_events:
        event_day = item.starts_at.date() if item.starts_at else None
        if (
            event_day is None
            or not today <= event_day <= event_limit
            or not item.link
            or not location_matches(pref, item.city)
        ):
            continue
        key = (item.title.casefold(), item.city.casefold(), event_day)
        if key in seen:
            continue
        seen.add(key)
        events.append(HomeEvent(
            item_type="discovered_event",
            item_id=item.id,
            title=item.title,
            date_label=item.event_date or f"{event_day:%d.%m}",
            city=item.city or pref.city,
            url=item.link,
            starts_on=event_day,
            saved=("discovered_event", item.id) in saved_events,
        ))
    events.sort(key=lambda item: (item.starts_on, item.title.casefold()))

    nearby_listings = tuple(
        item for item in listings
        if location_matches(
            pref, item.city, nationwide=item.is_nationwide
        )
    )
    return HomeSnapshot(
        saved_count=saved_count,
        action_count=action_count,
        events=tuple(events[:20]),
        new_listings=nearby_listings[:20],
    )


def _snapshot_text(snapshot: HomeSnapshot) -> str:
    lines = [
        "<b>📌 Сейчас для тебя</b>",
        f"❤️ Сохранено: <b>{snapshot.saved_count}</b>",
        f"📅 Событий рядом на 30 дней: <b>{len(snapshot.events)}</b>",
        f"🆕 Новых объявлений за 7 дней: <b>{len(snapshot.new_listings)}</b>",
        f"🗂 Незавершённых действий: <b>{snapshot.action_count}</b>",
    ]
    if snapshot.events:
        event = snapshot.events[0]
        lines.append(
            f"\nБлижайшее: <b>{html.escape(event.title)}</b> · "
            f"{html.escape(event.date_label)}"
        )
    if snapshot.new_listings:
        lines.append(
            f"Новое: <b>{html.escape(snapshot.new_listings[0].title)}</b>"
        )
    return "\n".join(lines)


def _profile_summary(pref: DigestPreference | None) -> str:
    if not pref:
        return (
            "📍 <b>Профиль пока не настроен.</b>\n"
            "Укажи город и интересы — бот сможет показывать полезное рядом."
        )
    topics = [
        TOPIC_LABELS[key]
        for key in (pref.topics_csv or "").split(",")
        if key in TOPIC_LABELS
    ]
    digest = "включена" if pref.enabled else "выключена"
    return (
        f"📍 <b>{html.escape(pref.city)}</b> · "
        f"{RADIUS_LABELS.get(pref.radius_km, f'{pref.radius_km} км')}\n"
        f"🎛 {html.escape(', '.join(topics) or 'темы не выбраны')}\n"
        f"🔔 Еженедельная подборка: <b>{digest}</b>"
    )


async def _open_home(message: Message, user_id: int, first_name: str | None) -> None:
    async with get_session() as session:
        pref = await session.get(DigestPreference, user_id)
    snapshot = await _home_snapshot(user_id, pref)
    await message.answer(
        "🏠 <b>Мой Podslushano</b>\n\n"
        f"{html.escape(first_name or 'друг')}, здесь собрана твоя актуальная "
        "сводка.\n\n"
        f"{_profile_summary(pref)}\n\n"
        f"{_snapshot_text(snapshot)}",
        reply_markup=_home_kb(pref is not None, snapshot),
    )
    await log_product_event(user_id, "home_open")


@router.message(Command("my", "home"))
@router.message(F.text == BTN_HOME)
async def home_open(message: Message, state: FSMContext) -> None:
    await state.clear()
    await _open_home(message, message.from_user.id, message.from_user.first_name)


@router.callback_query(F.data == "home:open")
async def home_open_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    await _open_home(callback.message, callback.from_user.id, callback.from_user.first_name)


@router.callback_query(F.data == "home:profile")
async def home_profile(callback: CallbackQuery, state: FSMContext) -> None:
    from handlers.digest import _open_digest_settings

    await state.clear()
    async with get_session() as session:
        pref = await session.get(DigestPreference, callback.from_user.id)
    await callback.answer()
    await log_product_event(
        callback.from_user.id,
        "profile_open",
        source="existing" if pref else "new",
    )
    if pref is None:
        await _open_digest_settings(callback.message, state, callback.from_user.id)
        return
    await callback.message.answer(_profile_text(pref), reply_markup=_profile_kb())


@router.callback_query(F.data == "home:digest")
async def home_digest(callback: CallbackQuery, state: FSMContext) -> None:
    from handlers.digest import _open_digest_settings

    await callback.answer()
    await log_product_event(callback.from_user.id, "digest_open", source="home")
    await _open_digest_settings(callback.message, state, callback.from_user.id)


@router.callback_query(F.data == "home:events")
async def home_events_open(callback: CallbackQuery) -> None:
    async with get_session() as session:
        pref = await session.get(DigestPreference, callback.from_user.id)
    snapshot = await _home_snapshot(callback.from_user.id, pref)
    await log_product_event(callback.from_user.id, "home_events_open")
    back = [InlineKeyboardButton(
        text="⬅️ Мой Podslushano", callback_data="home:open"
    )]
    if pref is None:
        await callback.message.answer(
            "📅 <b>События рядом</b>\n\n"
            "Сначала укажи город и радиус — тогда здесь появятся подходящие события.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="📍 Настроить профиль", callback_data="home:profile"
                )],
                back,
            ]),
        )
        await callback.answer()
        return
    if not snapshot.events:
        await callback.message.answer(
            "📅 <b>События рядом</b>\n\n"
            "На ближайшие 30 дней подходящих событий пока нет.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[back]),
        )
        await callback.answer()
        return
    lines = ["📅 <b>События рядом на ближайшие 30 дней</b>"]
    buttons = []
    for item in snapshot.events[:10]:
        lines.append(
            f"\n• <b>{html.escape(item.title)}</b>\n"
            f"  {html.escape(item.date_label)} · {html.escape(item.city)}"
        )
        buttons.append([
            InlineKeyboardButton(text=f"Открыть · {item.title}"[:45], url=item.url),
            InlineKeyboardButton(
                text="❤️" if item.saved else "♡",
                callback_data=f"save:{item.item_type}:{item.item_id}",
            ),
        ])
    buttons.append(back)
    await callback.message.answer(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        disable_web_page_preview=True,
    )
    await callback.answer()


@router.callback_query(F.data == "home:new")
async def home_new_listings_open(callback: CallbackQuery) -> None:
    async with get_session() as session:
        pref = await session.get(DigestPreference, callback.from_user.id)
    snapshot = await _home_snapshot(callback.from_user.id, pref)
    await log_product_event(callback.from_user.id, "home_new_listings_open")
    back = [InlineKeyboardButton(
        text="⬅️ Мой Podslushano", callback_data="home:open"
    )]
    if pref is None:
        await callback.message.answer(
            "🆕 <b>Новые объявления</b>\n\n"
            "Сначала укажи город и радиус — тогда здесь появятся объявления рядом.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="📍 Настроить профиль", callback_data="home:profile"
                )],
                back,
            ]),
        )
        await callback.answer()
        return
    if not snapshot.new_listings:
        await callback.message.answer(
            "🆕 <b>Новые объявления</b>\n\n"
            "За последние 7 дней подходящих объявлений пока нет.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[back]),
        )
        await callback.answer()
        return
    buttons = [
        [InlineKeyboardButton(
            text=f"📋 {item.title}"[:60], callback_data=f"home:li:{item.id}"
        )]
        for item in snapshot.new_listings[:10]
    ]
    buttons.append(back)
    await callback.message.answer(
        "🆕 <b>Новые объявления за 7 дней</b>\n\n"
        "Выбери объявление, чтобы открыть:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("save:"))
async def toggle_saved(callback: CallbackQuery) -> None:
    try:
        _, item_type, raw_id = callback.data.split(":", 2)
        item_id = int(raw_id)
    except (ValueError, AttributeError):
        await callback.answer("Не удалось сохранить", show_alert=True)
        return
    if item_type not in TYPE_LABELS:
        await callback.answer("Этот тип пока нельзя сохранить", show_alert=True)
        return

    models = {
        "specialist": Specialist,
        "listing": Listing,
        "event": EventListing,
        "discovered_event": DiscoveredEvent,
    }
    model = models[item_type]
    async with get_session() as session:
        item = await session.get(model, item_id)
        event_unavailable = (
            item_type == "event" and item is not None and item.status != "approved"
        )
        discovered_unavailable = (
            item_type == "discovered_event"
            and item is not None
            and item.expires_at <= datetime.utcnow()
        )
        if item is None or event_unavailable or discovered_unavailable:
            await callback.answer("Карточка больше недоступна", show_alert=True)
            return
        saved = (await session.scalars(select(SavedItem).where(
            SavedItem.user_id == callback.from_user.id,
            SavedItem.item_type == item_type,
            SavedItem.item_id == item_id,
        ))).first()
        if saved:
            await session.delete(saved)
            added = False
        else:
            session.add(SavedItem(
                user_id=callback.from_user.id, item_type=item_type, item_id=item_id
            ))
            added = True
        await session.commit()
    await log_product_event(
        callback.from_user.id,
        "saved_add" if added else "saved_remove",
        entity_type=item_type,
        entity_id=item_id,
    )
    await callback.answer(
        (
            "Событие сохранено. Напоминания включаются в центре уведомлений 🔔"
            if added and item_type in {"event", "discovered_event"}
            else "Сохранено в «Мой Podslushano» ❤️"
            if added
            else "Удалено из сохранённого"
        ),
        show_alert=True,
    )
    # Сразу отражаем состояние на карточке, чтобы повторное нажатие было понятным.
    try:
        keyboard = callback.message.reply_markup.inline_keyboard
        updated = []
        for row in keyboard:
            updated.append([
                button.model_copy(update={
                    "text": (
                        ("❤️" if added else "♡")
                        if item_type in {"event", "discovered_event"}
                        else ("❤️ Сохранено" if added else "♡ Сохранить")
                    )
                }) if button.callback_data == callback.data else button
                for button in row
            ])
        await callback.message.edit_reply_markup(
            reply_markup=InlineKeyboardMarkup(inline_keyboard=updated)
        )
    except Exception:
        pass


@router.callback_query(F.data == "home:saved")
async def saved_open(callback: CallbackQuery) -> None:
    await log_product_event(callback.from_user.id, "saved_open")
    async with get_session() as session:
        rows = (await session.scalars(
            select(SavedItem).where(SavedItem.user_id == callback.from_user.id)
            .order_by(SavedItem.created_at.desc())
        )).all()
        spec_ids = [x.item_id for x in rows if x.item_type == "specialist"]
        listing_ids = [x.item_id for x in rows if x.item_type == "listing"]
        event_ids = [x.item_id for x in rows if x.item_type == "event"]
        discovered_ids = [
            x.item_id for x in rows if x.item_type == "discovered_event"
        ]
        specialists = {
            x.id: x for x in (await session.scalars(
                select(Specialist).where(Specialist.id.in_(spec_ids or [-1]))
            )).all()
        }
        listings = {
            x.id: x for x in (await session.scalars(
                select(Listing).where(Listing.id.in_(listing_ids or [-1]))
            )).all()
        }
        events = {
            x.id: x for x in (await session.scalars(
                select(EventListing).where(
                    EventListing.id.in_(event_ids or [-1]),
                    EventListing.status == "approved",
                    EventListing.link.is_not(None),
                )
            )).all()
        }
        discovered = {
            x.id: x for x in (await session.scalars(
                select(DiscoveredEvent).where(
                    DiscoveredEvent.id.in_(discovered_ids or [-1]),
                    DiscoveredEvent.expires_at > datetime.utcnow(),
                )
            )).all()
        }
    valid = [
        row for row in rows
        if (row.item_type == "specialist" and row.item_id in specialists)
        or (row.item_type == "listing" and row.item_id in listings)
        or (row.item_type == "event" and row.item_id in events)
        or (
            row.item_type == "discovered_event"
            and row.item_id in discovered
        )
    ]
    back = [InlineKeyboardButton(text="⬅️ Мой Podslushano", callback_data="home:open")]
    if not valid:
        await callback.message.answer(
            "❤️ <b>Сохранённое</b>\n\nПока пусто. Нажимай «♡ Сохранить» "
            "на карточках специалистов, объявлений и событий.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[back]),
        )
        await callback.answer()
        return

    buttons = []
    for row in valid[:20]:
        if row.item_type == "specialist":
            title = f"🔍 {specialists[row.item_id].name}"
            data = f"home:sp:{row.item_id}"
            buttons.append([InlineKeyboardButton(text=title[:60], callback_data=data)])
        elif row.item_type == "listing":
            title = f"📋 {listings[row.item_id].title}"
            data = f"home:li:{row.item_id}"
            buttons.append([InlineKeyboardButton(text=title[:60], callback_data=data)])
        else:
            event = (
                events[row.item_id]
                if row.item_type == "event"
                else discovered[row.item_id]
            )
            buttons.append([InlineKeyboardButton(
                text=f"📅 {event.title}"[:60],
                url=event.link,
            )])
    buttons.append(back)
    await callback.message.answer(
        f"❤️ <b>Сохранённое</b>\n\nКарточек: <b>{len(valid)}</b>. Выбери, чтобы открыть:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("home:sp:"))
async def saved_specialist_open(callback: CallbackQuery, state: FSMContext) -> None:
    from handlers.contacts import show_specialist_card

    await callback.answer()
    await show_specialist_card(
        callback.message,
        state,
        int(callback.data.rsplit(":", 1)[1]),
        source="saved",
    )


@router.callback_query(F.data.startswith("home:li:"))
async def saved_listing_open(callback: CallbackQuery) -> None:
    from handlers.board import _card_text, _contact_url

    listing_id = int(callback.data.rsplit(":", 1)[1])
    async with get_session() as session:
        listing = await session.get(Listing, listing_id)
    if listing is None or listing.status != "approved":
        await callback.answer("Объявление больше не активно", show_alert=True)
        return
    await log_product_event(
        callback.from_user.id,
        "listing_open",
        entity_type="listing",
        entity_id=listing.id,
        source="saved",
    )
    rows = [[InlineKeyboardButton(
        text="💔 Удалить из сохранённого", callback_data=f"save:listing:{listing.id}"
    )]]
    url = _contact_url(listing.contact)
    if url:
        rows.insert(0, [InlineKeyboardButton(text="✍️ Написать", url=url)])
    markup = InlineKeyboardMarkup(inline_keyboard=rows)
    if listing.photo_file_id:
        try:
            await callback.message.answer_photo(
                listing.photo_file_id, caption=_card_text(listing), reply_markup=markup
            )
            await callback.answer()
            return
        except Exception:
            pass
    await callback.message.answer(
        _card_text(listing), reply_markup=markup, disable_web_page_preview=True
    )
    await callback.answer()


@router.callback_query(F.data == "home:actions")
async def actions_open(callback: CallbackQuery) -> None:
    uid = callback.from_user.id
    await log_product_event(uid, "actions_open")
    async with get_session() as session:
        submissions = (await session.scalars(
            select(Submission).where(Submission.user_id == uid)
            .order_by(Submission.created_at.desc()).limit(5)
        )).all()
        listings = (await session.scalars(
            select(Listing).where(Listing.submitter_user_id == uid)
            .order_by(Listing.created_at.desc()).limit(5)
        )).all()
        walks = (await session.scalars(
            select(AlloBooking).where(AlloBooking.user_id == uid)
            .order_by(AlloBooking.created_at.desc()).limit(5)
        )).all()
        events = (await session.scalars(
            select(EventListing).where(EventListing.submitter_user_id == uid)
            .order_by(EventListing.created_at.desc()).limit(5)
        )).all()
        cards = (await session.scalars(
            select(Specialist).where(Specialist.submitter_user_id == uid)
            .order_by(Specialist.id.desc()).limit(5)
        )).all()

    lines = ["🗂 <b>Мои действия</b>"]
    sections = [
        ("📋 Объявления", listings, lambda x: x.title),
        ("🚶 Allo Walks", walks, lambda x: x.walk_key),
        ("🔍 Карточки в гайде", cards, lambda x: x.name),
        ("📅 Мероприятия", events, lambda x: x.title),
        ("✍️ Предложка", submissions, lambda x: x.type),
    ]
    for label, items, title in sections:
        if items:
            lines += ["", f"<b>{label}</b>"] + [
                f"• {html.escape(title(x))} — "
                f"{html.escape(STATUS_LABELS.get(x.status, x.status))}" for x in items
            ]
    if len(lines) == 1:
        lines += ["", "Здесь появятся объявления, заявки, записи и другие действия."]

    buttons = []
    if listings:
        buttons.append([InlineKeyboardButton(
            text="📋 Управлять объявлениями", callback_data="board:my"
        )])
    if cards:
        buttons.append([InlineKeyboardButton(
            text="👤 Кабинет специалиста", callback_data="home:cabinet"
        )])
    buttons.append([InlineKeyboardButton(text="⬅️ Мой Podslushano", callback_data="home:open")])
    await callback.message.answer(
        "\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()


@router.callback_query(F.data == "home:cabinet")
async def specialist_cabinet_open(callback: CallbackQuery, state: FSMContext) -> None:
    from handlers.cabinet import open_cabinet_for

    await callback.answer()
    await open_cabinet_for(callback.message, state, callback.from_user.id)
