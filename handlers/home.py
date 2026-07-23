"""Персональный центр пользователя «Мой Podslushano»."""
import html
from datetime import datetime

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
    EventListing,
    Listing,
    SavedItem,
    Specialist,
    Submission,
)
from keyboards.menus import BTN_HOME

router = Router()
router.message.filter(F.chat.type == ChatType.PRIVATE)

TYPE_LABELS = {"specialist": "Специалисты", "listing": "Объявления"}
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


def _home_kb(has_profile: bool) -> InlineKeyboardMarkup:
    profile = "⚙️ Настроить профиль" if has_profile else "📍 Указать город и интересы"
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="❤️ Сохранённое", callback_data="home:saved"),
            InlineKeyboardButton(text="🗂 Мои действия", callback_data="home:actions"),
        ],
        [InlineKeyboardButton(text=profile, callback_data="home:profile")],
        [InlineKeyboardButton(text="🔔 Настройки подборки", callback_data="home:digest")],
    ])


async def _counts(user_id: int) -> tuple[int, int]:
    now = datetime.utcnow()
    async with get_session() as session:
        saved = await session.scalar(
            select(func.count()).select_from(SavedItem).where(SavedItem.user_id == user_id)
        ) or 0
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
    return saved, listings + submissions + walks + events + cards


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


def _profile_settings_kb(pref: DigestPreference) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="📍 Изменить город", callback_data="home:profile:city"
            ),
            InlineKeyboardButton(
                text="🗺 Изменить радиус", callback_data="home:profile:radius"
            ),
        ],
        [
            InlineKeyboardButton(
                text="🎛 Изменить интересы", callback_data="home:profile:topics"
            )
        ],
        [InlineKeyboardButton(text="⬅️ Мой Podslushano", callback_data="home:open")],
    ])


def _profile_settings_text(pref: DigestPreference) -> str:
    topics = [
        TOPIC_LABELS[key]
        for key in (pref.topics_csv or "").split(",")
        if key in TOPIC_LABELS
    ]
    return (
        "⚙️ <b>Настройки профиля</b>\n\n"
        f"📍 Город: <b>{html.escape(pref.city)}</b>\n"
        f"🗺 Радиус: <b>"
        f"{RADIUS_LABELS.get(pref.radius_km, f'{pref.radius_km} км')}</b>\n"
        f"🎛 Интересы: {html.escape(', '.join(topics) or 'не выбраны')}\n\n"
        "Эти настройки помогают показывать подходящие материалы и услуги рядом."
    )


async def _open_home(message: Message, user_id: int, first_name: str | None) -> None:
    async with get_session() as session:
        pref = await session.get(DigestPreference, user_id)
    saved, actions = await _counts(user_id)
    await message.answer(
        "🏠 <b>Мой Podslushano</b>\n\n"
        f"{html.escape(first_name or 'друг')}, здесь всё твоё: профиль, "
        "сохранённые карточки, подписка и действия.\n\n"
        f"{_profile_summary(pref)}\n\n"
        f"❤️ Сохранено: <b>{saved}</b>\n"
        f"🗂 Активных действий: <b>{actions}</b>",
        reply_markup=_home_kb(pref is not None),
    )


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
    from keyboards.menus import cancel_menu
    from states.forms import DigestSetup

    await state.clear()
    await callback.answer()
    async with get_session() as session:
        pref = await session.get(DigestPreference, callback.from_user.id)
    if pref:
        await callback.message.answer(
            _profile_settings_text(pref), reply_markup=_profile_settings_kb(pref)
        )
        return
    await state.update_data(dg_origin="profile")
    await state.set_state(DigestSetup.waiting_city)
    await callback.message.answer(
        "⚙️ <b>Настройка профиля</b>\n\n"
        "Укажи город, радиус и интересы — бот сможет показывать подходящие "
        "материалы и услуги рядом.\n\n"
        "📍 В каком городе ты живёшь?",
        reply_markup=cancel_menu(),
    )


@router.callback_query(F.data == "home:digest")
async def home_digest(callback: CallbackQuery, state: FSMContext) -> None:
    from handlers.digest import _open_digest_settings

    await callback.answer()
    await _open_digest_settings(callback.message, state, callback.from_user.id)


@router.callback_query(F.data.startswith("home:profile:"))
async def home_profile_edit(callback: CallbackQuery, state: FSMContext) -> None:
    from handlers.digest import _get_pref, _radius_kb, _topics, _topics_kb
    from keyboards.menus import cancel_menu
    from states.forms import DigestSetup

    action = callback.data.rsplit(":", 1)[1]
    pref = await _get_pref(callback.from_user.id)
    if not pref:
        await callback.answer("Сначала настрой профиль", show_alert=True)
        return
    await state.clear()
    await state.update_data(dg_origin="profile")
    if action == "city":
        await state.set_state(DigestSetup.waiting_city)
        await state.update_data(
            dg_topics=list(_topics(pref.topics_csv)),
            dg_radius=pref.radius_km,
            dg_edit_city=True,
        )
        await callback.message.answer(
            "📍 Напиши новый город:", reply_markup=cancel_menu()
        )
    elif action == "radius":
        await callback.message.answer(
            "Какой радиус использовать?", reply_markup=_radius_kb()
        )
    elif action == "topics":
        selected = _topics(pref.topics_csv)
        await state.set_state(DigestSetup.choosing_topics)
        await state.update_data(dg_topics=list(selected), dg_edit=True)
        await callback.message.answer(
            "Выбери интересы:", reply_markup=_topics_kb(selected)
        )
    else:
        await callback.answer("Неизвестная настройка", show_alert=True)
        return
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

    model = Specialist if item_type == "specialist" else Listing
    async with get_session() as session:
        item = await session.get(model, item_id)
        if item is None:
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
    await callback.answer(
        "Сохранено в «Мой Podslushano» ❤️" if added else "Удалено из сохранённого",
        show_alert=True,
    )
    # Сразу отражаем состояние на карточке, чтобы повторное нажатие было понятным.
    try:
        keyboard = callback.message.reply_markup.inline_keyboard
        updated = []
        for row in keyboard:
            updated.append([
                button.model_copy(update={
                    "text": ("❤️ Сохранено" if added else "♡ Сохранить")
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
    async with get_session() as session:
        rows = (await session.scalars(
            select(SavedItem).where(SavedItem.user_id == callback.from_user.id)
            .order_by(SavedItem.created_at.desc())
        )).all()
        spec_ids = [x.item_id for x in rows if x.item_type == "specialist"]
        listing_ids = [x.item_id for x in rows if x.item_type == "listing"]
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
    valid = [
        row for row in rows
        if (row.item_type == "specialist" and row.item_id in specialists)
        or (row.item_type == "listing" and row.item_id in listings)
    ]
    back = [InlineKeyboardButton(text="⬅️ Мой Podslushano", callback_data="home:open")]
    if not valid:
        await callback.message.answer(
            "❤️ <b>Сохранённое</b>\n\nПока пусто. Нажимай «♡ Сохранить» "
            "на карточках специалистов и объявлений.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[back]),
        )
        await callback.answer()
        return

    buttons = []
    for row in valid[:20]:
        if row.item_type == "specialist":
            title = f"🔍 {specialists[row.item_id].name}"
            data = f"home:sp:{row.item_id}"
        else:
            title = f"📋 {listings[row.item_id].title}"
            data = f"home:li:{row.item_id}"
        buttons.append([InlineKeyboardButton(text=title[:60], callback_data=data)])
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
        callback.message, state, int(callback.data.rsplit(":", 1)[1])
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
