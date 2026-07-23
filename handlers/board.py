"""Доска объявлений: бесплатная подача с модерацией, просмотр каруселью,
платное «поднятие наверх» (Mollie).

Поток подачи: 📋 Объявления → ➕ Подать → категория → заголовок → описание →
цена → город → фото → контакт → предпросмотр → модерация админом → публикация.
Просмотр: категория → город → карусель карточек. «Поднять» — платно через
общий webhook (on_payment_paid, kind="bump").
"""
import html
import logging
from datetime import datetime, timedelta

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy import func, or_, select

import config
from database.db import get_session
from database.models import Listing, Meta
from keyboards.menus import BTN_BOARD, BTN_CONTACTS, BTN_SELF_ADD, cancel_menu, main_menu
from states.forms import ListingBrowse, ListingForm
from utils.analytics import log_event
from utils.payments import create_payment

log = logging.getLogger(__name__)

router = Router()
router.message.filter(F.chat.type == ChatType.PRIVATE)

DESC = "Omhoog plaatsen advertentie Podslushano-bord"
DESC_LISTING = "Plaatsing woning-advertentie Podslushano-bord"

ONLINE_WORDS = {"онлайн", "online", "по всей стране", "вся страна", "удалённо"}

# Услуги намеренно НЕ на доске: они размещаются в платном контакт-гайде, чтобы
# доска не каннибализировала гайд. Кнопка «Услуги» ведёт в гайд (см. svc_guide).
CATEGORIES = [
    ("housing", "🏠 Жильё"),
    ("goods", "🛋 Вещи"),
    ("free", "🎁 Отдам даром"),
    ("jobs", "💼 Работа"),
    ("rides", "🚗 Попутчики"),
    ("other", "📦 Разное"),
]
CATEGORY_LABELS = dict(CATEGORIES)


def _housing_paid() -> bool:
    """Платное ли размещение жилья (есть цена и подключена оплата)."""
    price = (config.BOARD_HOUSING_PRICE or "").strip()
    return config.payments_enabled() and price not in ("", "0", "0.00")

POPULAR_CITIES = ["Amsterdam", "Rotterdam", "Den Haag", "Utrecht", "Eindhoven", "Groningen"]


# --- Вспомогательные ---------------------------------------------------------

def _board_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔎 Смотреть объявления", callback_data="board:browse")],
        [InlineKeyboardButton(text="➕ Подать объявление", callback_data="board:new")],
        [InlineKeyboardButton(text="🗂 Мои объявления", callback_data="board:my")],
    ])


def _category_kb(prefix: str) -> InlineKeyboardMarkup:
    btns = [InlineKeyboardButton(text=label, callback_data=f"{prefix}:{key}")
            for key, label in CATEGORIES]
    rows = [btns[i:i + 2] for i in range(0, len(btns), 2)]
    # Услуги — отдельной кнопкой, ведёт в гайд специалистов (не на доску)
    rows.append([InlineKeyboardButton(text="🧰 Услуги (в гайде)", callback_data=f"svcguide:{prefix}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data.startswith("svcguide:"))
async def services_to_guide(callback: CallbackQuery, state: FSMContext) -> None:
    """«Услуги» на доске нет — направляем в платный контакт-гайд."""
    await state.clear()
    prefix = callback.data.split(":", 1)[1]
    if prefix == "ncat":  # хотел разместить услугу
        await callback.message.answer(
            "🧰 Услуги размещаются не на доске, а в нашем <b>проверенном гайде "
            "специалистов</b> — там вас находят по городу и категории, с отзывами и "
            f"рейтингом.\n\nДобавить себя: кнопка «{BTN_SELF_ADD}» в меню или /selfadd.",
            reply_markup=main_menu(),
        )
    else:  # искал услугу
        await callback.message.answer(
            "🧰 Специалистов и услуги ищите в нашем гайде — там проверенные контакты "
            f"с отзывами.\n\nНажмите «{BTN_CONTACTS}» в меню, чтобы найти 👍",
            reply_markup=main_menu(),
        )
    await callback.answer()


def _browse_city_kb(cat: str) -> InlineKeyboardMarkup:
    btns = [InlineKeyboardButton(text=c, callback_data=f"bcity:{cat}:{c}") for c in POPULAR_CITIES]
    rows = [btns[i:i + 2] for i in range(0, len(btns), 2)]
    rows.append([InlineKeyboardButton(text="🌍 Все города", callback_data=f"bcity:{cat}:__all__")])
    rows.append([InlineKeyboardButton(text="✏️ Другой город", callback_data=f"bcityx:{cat}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _contact_url(contact: str | None) -> str | None:
    c = (contact or "").strip()
    if not c:
        return None
    if c.startswith("@") and " " not in c and len(c) > 1:
        return f"https://t.me/{c[1:]}"
    if c.startswith(("http://", "https://")):
        return c
    return None


def _card_text(l: Listing, with_status: bool = False) -> str:
    parts = [CATEGORY_LABELS.get(l.category, "📦 Разное"), "", f"<b>{html.escape(l.title)}</b>"]
    if l.price:
        parts.append(f"💶 {html.escape(l.price)}")
    where = "по всей стране / онлайн" if l.is_nationwide else l.city
    if where:
        parts.append(f"📍 {html.escape(where)}")
    if l.description:
        parts += ["", html.escape(l.description)]
    if l.contact:
        parts += ["", f"✍️ Контакт: {html.escape(l.contact)}"]
    if l.category == "housing":
        parts += ["", "⚠️ Никогда не переводите предоплату до личного просмотра жилья."]
    if with_status:
        st = {"pending": "🕒 на проверке", "approved": "✅ опубликовано"}.get(l.status, l.status)
        parts += ["", f"<i>Статус: {st}</i>"]
    return "\n".join(parts)


async def _safe_send(bot, chat_id, text, reply_markup=None) -> None:
    try:
        await bot.send_message(chat_id, text, reply_markup=reply_markup,
                               disable_web_page_preview=True)
    except Exception as e:  # noqa: BLE001
        log.warning("Доска: не удалось отправить %s: %s", chat_id, e)


# --- Меню доски --------------------------------------------------------------

@router.message(Command("board"))
@router.message(F.text == BTN_BOARD)
async def board_open(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        "📋 <b>Доска объявлений</b>\n\n"
        "Жильё, вещи, услуги, работа, попутчики и не только — для нашего "
        "сообщества в Нидерландах. Подать объявление бесплатно (после проверки).",
        reply_markup=_board_menu_kb(),
    )


@router.callback_query(F.data == "board:menu")
async def board_menu_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.answer("📋 <b>Доска объявлений</b> — что делаем?",
                                  reply_markup=_board_menu_kb())
    await callback.answer()


# --- Подача объявления -------------------------------------------------------

@router.callback_query(F.data == "board:new")
async def new_start(callback: CallbackQuery, state: FSMContext) -> None:
    await start_new_listing(callback.message, state, callback.from_user.id)
    await callback.answer()


async def start_new_listing(message: Message, state: FSMContext, uid: int) -> None:
    """Начинает подачу объявления (из меню доски или по deep-link ?start=board)."""
    await state.clear()
    now = datetime.utcnow()
    async with get_session() as session:
        active = await session.scalar(
            select(func.count()).select_from(Listing).where(
                Listing.submitter_user_id == uid,
                Listing.status.in_(["pending", "approved"]),
                or_(Listing.expires_at.is_(None), Listing.expires_at > now),
            )
        ) or 0
    if active >= config.BOARD_MAX_ACTIVE:
        await message.answer(
            f"У вас уже {active} активных объявлений (максимум "
            f"{config.BOARD_MAX_ACTIVE}). Закройте лишнее в «🗂 Мои объявления» "
            "и попробуйте снова 🙂",
            reply_markup=main_menu(),
        )
        return
    await message.answer(
        "➕ <b>Новое объявление.</b> Выберите категорию:", reply_markup=_category_kb("ncat")
    )


@router.callback_query(F.data.startswith("ncat:"))
async def new_category(callback: CallbackQuery, state: FSMContext) -> None:
    cat = callback.data.split(":", 1)[1]
    if cat not in CATEGORY_LABELS:
        await callback.answer("Неизвестная категория", show_alert=True)
        return
    await state.update_data(l_cat=cat)
    await state.set_state(ListingForm.title)
    note = ""
    if cat == "housing" and _housing_paid():
        note = (f"\n\n💶 Размещение жилья — символические "
                f"<b>{config.BOARD_HOUSING_PRICE} {config.LISTING_CURRENCY}</b> "
                "(оплата в конце) — это отсеивает мошенников.")
    await callback.message.answer(
        f"Категория: <b>{CATEGORY_LABELS[cat]}</b> ✅{note}\n\n"
        "Шаг 1. Короткий заголовок объявления?",
        reply_markup=cancel_menu(),
    )
    await callback.answer()


@router.message(ListingForm.title)
async def new_title(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("Напишите заголовок текстом 🙂")
        return
    await state.update_data(l_title=message.text.strip()[:200])
    await state.set_state(ListingForm.description)
    await message.answer("Шаг 2. Описание (подробности)?", reply_markup=cancel_menu())


@router.message(ListingForm.description)
async def new_description(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("Напишите описание текстом 🙂")
        return
    await state.update_data(l_desc=message.text.strip())
    data = await state.get_data()
    if data.get("l_cat") == "free":
        await state.update_data(l_price="Даром")
        await state.set_state(ListingForm.city)
        await message.answer("Шаг 3. В каком городе? (или «по всей стране»)",
                             reply_markup=cancel_menu())
        return
    await state.set_state(ListingForm.price)
    await message.answer(
        "Шаг 3. Цена? Напр. <b>€50</b>, <b>договорная</b>.", reply_markup=cancel_menu()
    )


@router.message(ListingForm.price)
async def new_price(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("Напишите цену текстом 🙂")
        return
    await state.update_data(l_price=message.text.strip()[:100])
    await state.set_state(ListingForm.city)
    await message.answer("Шаг 4. В каком городе? (или «по всей стране»)",
                         reply_markup=cancel_menu())


@router.message(ListingForm.city)
async def new_city(message: Message, state: FSMContext) -> None:
    loc = (message.text or "").strip()
    if not loc:
        await message.answer("Напишите город или «по всей стране» 🙂")
        return
    if loc.lower() in ONLINE_WORDS:
        await state.update_data(l_city="", l_nationwide=True)
    else:
        await state.update_data(l_city=loc[:100], l_nationwide=False)
    await state.set_state(ListingForm.photo)
    await message.answer(
        "Шаг 5. Пришлите фото (одно) — повышает доверие. Или напишите «пропустить».",
        reply_markup=cancel_menu(),
    )


@router.message(ListingForm.photo)
async def new_photo(message: Message, state: FSMContext) -> None:
    if message.photo:
        await state.update_data(l_photo=message.photo[-1].file_id)
    elif message.text and message.text.strip().lower() in ("-", "пропустить", "skip", "нет"):
        await state.update_data(l_photo=None)
    else:
        await message.answer("Пришлите фото картинкой или напишите «пропустить» 🙂")
        return
    await state.set_state(ListingForm.contact)
    uname = message.from_user.username
    hint = f"\nМожно использовать ваш: <code>@{uname}</code>" if uname else ""
    await message.answer(
        "Шаг 6. Как с вами связаться? Укажите @username, телефон или ссылку." + hint,
        reply_markup=cancel_menu(),
    )


@router.message(ListingForm.contact)
async def new_contact(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("Напишите контакт текстом 🙂")
        return
    await state.update_data(l_contact=message.text.strip()[:300])
    data = await state.get_data()
    preview = Listing(
        category=data["l_cat"], title=data["l_title"], description=data.get("l_desc"),
        price=data.get("l_price"), city=data.get("l_city", ""),
        is_nationwide=data.get("l_nationwide", False), contact=data.get("l_contact"),
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Опубликовать (на проверку)", callback_data="lpub"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="lcancel"),
    ]])
    await message.answer("Вот как будет выглядеть объявление 👇")
    photo = data.get("l_photo")
    caption = _card_text(preview)
    if photo:
        try:
            await message.answer_photo(photo, caption=caption)
        except Exception:  # noqa: BLE001
            await message.answer(caption, disable_web_page_preview=True)
    else:
        await message.answer(caption, disable_web_page_preview=True)
    await message.answer("Публикуем? После проверки объявление появится на доске.",
                         reply_markup=kb)


@router.callback_query(F.data == "lcancel")
async def new_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.answer("Отменил — объявление не сохранено.", reply_markup=main_menu())
    await callback.answer()


@router.callback_query(F.data == "lpub")
async def new_publish(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await state.clear()
    if not data.get("l_title"):
        await callback.answer("Данные потерялись, начните заново", show_alert=True)
        return
    paid = data["l_cat"] == "housing" and _housing_paid()
    async with get_session() as session:
        listing = Listing(
            category=data["l_cat"], title=data["l_title"], description=data.get("l_desc"),
            price=data.get("l_price"), city=data.get("l_city", ""),
            is_nationwide=data.get("l_nationwide", False), photo_file_id=data.get("l_photo"),
            contact=data.get("l_contact"), submitter_user_id=callback.from_user.id,
            submitter_username=callback.from_user.username,
            status="awaiting_payment" if paid else "pending",
        )
        session.add(listing)
        await session.commit()
        await session.refresh(listing)
        lid, title = listing.id, listing.title
    await callback.answer()

    if paid:
        payment = await create_payment(
            f"{DESC_LISTING}: {title}", {"listing_id": lid, "kind": "listing"},
            config.BOARD_HOUSING_PRICE,
        )
        if not payment or not payment.get("checkout_url"):
            await callback.message.answer(
                "Не получилось создать ссылку на оплату 😔 Попробуйте позже.",
                reply_markup=main_menu(),
            )
            return
        async with get_session() as session:
            l = await session.get(Listing, lid)
            if l:
                l.payment_id = payment["id"]
                await session.commit()
        await callback.message.answer(
            f"Почти готово! Размещение жилья — "
            f"<b>{config.BOARD_HOUSING_PRICE} {config.LISTING_CURRENCY}</b>. "
            "После оплаты отправим на проверку и опубликуем ✅",
            reply_markup=main_menu(),
        )
        await callback.message.answer(
            "👇 Кнопка для оплаты:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
                text=f"💳 Оплатить {config.BOARD_HOUSING_PRICE} {config.LISTING_CURRENCY}",
                url=payment["checkout_url"])]]),
        )
        return

    await callback.message.answer(
        "Спасибо! 🙌 Объявление отправлено на проверку — опубликуем и я сообщу ✅",
        reply_markup=main_menu(),
    )
    async with get_session() as session:
        listing = await session.get(Listing, lid)
    for admin_id in config.ADMIN_IDS:
        await _safe_send(callback.bot, admin_id, "🆕 <b>Новое объявление на доску</b> — проверка:")
        await _send_admin_card(callback.bot, admin_id, listing)


async def on_listing_paid(bot, payment_id: str, payment: dict) -> None:
    """Оплачено платное размещение (жильё) → на проверку админам."""
    status = payment.get("status")
    meta = payment.get("metadata") or {}
    lid = meta.get("listing_id")
    if not lid or status != "paid":
        return
    async with get_session() as session:
        if await session.get(Meta, f"pay:{payment_id}"):
            return
        listing = await session.get(Listing, int(lid))
        if listing is None:
            return
        listing.status = "pending"
        session.add(Meta(key=f"pay:{payment_id}", value="done"))
        await session.commit()
        sub = listing.submitter_user_id
        lid_int = listing.id
    await log_event("payment", "listing")
    async with get_session() as session:
        listing = await session.get(Listing, lid_int)
    for admin_id in config.ADMIN_IDS:
        await _safe_send(bot, admin_id, "🆕 <b>Оплаченное объявление (жильё)</b> — проверка:")
        await _send_admin_card(bot, admin_id, listing)
    if sub:
        await _safe_send(bot, sub,
                         "Оплата получена, спасибо! 🙌 Объявление на проверке — сообщу, "
                         "как опубликуем ✅")


async def _send_admin_card(bot, chat_id, listing: Listing) -> None:
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Опубликовать", callback_data=f"lstok:{listing.id}"),
        InlineKeyboardButton(text="❌ Отклонить", callback_data=f"lstno:{listing.id}"),
    ]])
    caption = _card_text(listing)
    if listing.photo_file_id:
        try:
            await bot.send_photo(chat_id, listing.photo_file_id, caption=caption, reply_markup=kb)
            return
        except Exception:  # noqa: BLE001
            pass
    await _safe_send(bot, chat_id, caption, kb)


# --- Модерация (только админы) ----------------------------------------------

@router.callback_query(F.data.startswith("lstok:"), F.from_user.id.in_(config.ADMIN_IDS))
async def listing_approve(callback: CallbackQuery) -> None:
    lid = int(callback.data.split(":", 1)[1])
    async with get_session() as session:
        listing = await session.get(Listing, lid)
        if listing is None:
            await callback.answer("Не найдено", show_alert=True)
            return
        listing.status = "approved"
        listing.expires_at = datetime.utcnow() + timedelta(days=config.BOARD_LISTING_DAYS)
        await session.commit()
        sub, title = listing.submitter_user_id, listing.title
    await callback.answer("Опубликовано")
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:  # noqa: BLE001
        pass
    await callback.message.answer(f"✅ Опубликовано: «{html.escape(title)}»")
    if sub:
        await _safe_send(callback.bot, sub,
                         f"🎉 Ваше объявление «{title}» опубликовано на доске. Спасибо!")


@router.callback_query(F.data.startswith("lstno:"), F.from_user.id.in_(config.ADMIN_IDS))
async def listing_reject(callback: CallbackQuery) -> None:
    lid = int(callback.data.split(":", 1)[1])
    async with get_session() as session:
        listing = await session.get(Listing, lid)
        if listing is None:
            await callback.answer("Не найдено", show_alert=True)
            return
        listing.status = "rejected"
        await session.commit()
        sub, title = listing.submitter_user_id, listing.title
    await callback.answer("Отклонено")
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:  # noqa: BLE001
        pass
    await callback.message.answer(f"❌ Отклонено: «{html.escape(title)}»")
    if sub:
        await _safe_send(callback.bot, sub,
                         f"К сожалению, объявление «{title}» не прошло проверку. "
                         "Если думаете, что это ошибка — напишите нам через /contact.")


# --- Просмотр (карусель) -----------------------------------------------------

@router.callback_query(F.data == "board:browse")
async def browse_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.answer("🔎 Выберите категорию:", reply_markup=_category_kb("bcat"))
    await callback.answer()


@router.callback_query(F.data.startswith("bcat:"))
async def browse_category(callback: CallbackQuery, state: FSMContext) -> None:
    cat = callback.data.split(":", 1)[1]
    if cat not in CATEGORY_LABELS:
        await callback.answer()
        return
    # Город не спрашиваем — он указан в каждой карточке. Показываем всё по категории.
    await callback.answer()
    await _browse_collect(callback.message, state, cat, "")


@router.callback_query(F.data.startswith("bcityx:"))
async def browse_city_other(callback: CallbackQuery, state: FSMContext) -> None:
    cat = callback.data.split(":", 1)[1]
    await state.set_state(ListingBrowse.waiting_city)
    await state.update_data(b_cat=cat)
    await callback.message.answer("Напишите город:", reply_markup=cancel_menu())
    await callback.answer()


@router.message(ListingBrowse.waiting_city)
async def browse_city_typed(message: Message, state: FSMContext) -> None:
    city = (message.text or "").strip()
    data = await state.get_data()
    cat = data.get("b_cat", "other")
    await _browse_collect(message, state, cat, city)


@router.callback_query(F.data.startswith("bcity:"))
async def browse_city_btn(callback: CallbackQuery, state: FSMContext) -> None:
    _, cat, city = callback.data.split(":", 2)
    await callback.answer()
    await _browse_collect(callback.message, state, cat, "" if city == "__all__" else city)


async def _browse_collect(msg: Message, state: FSMContext, cat: str, city: str) -> None:
    now = datetime.utcnow()
    q = select(Listing).where(
        Listing.status == "approved", Listing.category == cat,
        or_(Listing.expires_at.is_(None), Listing.expires_at > now),
    )
    if city:
        q = q.where(or_(Listing.is_nationwide.is_(True), Listing.city.ilike(f"%{city}%")))
    q = q.order_by(Listing.bumped_at.is_(None), Listing.bumped_at.desc(), Listing.created_at.desc())
    async with get_session() as session:
        rows = (await session.scalars(q)).all()
    await state.clear()
    where = f" в «{city}»" if city else ""
    if not rows:
        await msg.answer(
            f"Пока нет объявлений в категории {CATEGORY_LABELS.get(cat, cat)}{where} 🙂\n"
            "Загляните позже или подайте своё.",
            reply_markup=main_menu(),
        )
        return
    await state.update_data(lst_ids=[l.id for l in rows])
    await log_event("board_view", cat)
    await msg.answer(
        f"🔎 {CATEGORY_LABELS.get(cat, cat)}{where}: <b>{len(rows)}</b> объявл. "
        "Листай ◀️ ▶️ 👇",
        reply_markup=main_menu(),
    )
    await _browse_show(msg, state, 0, replace=False)


def _browse_kb(l: Listing, idx: int, total: int) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    url = _contact_url(l.contact)
    if url:
        rows.append([InlineKeyboardButton(text="✍️ Написать", url=url)])
    rows.append([InlineKeyboardButton(
        text="♡ Сохранить", callback_data=f"save:listing:{l.id}"
    )])
    rows.append([InlineKeyboardButton(text="🚩 Пожаловаться", callback_data=f"lrep:{l.id}")])
    if total > 1:
        p, n = (idx - 1) % total, (idx + 1) % total
        rows.append([
            InlineKeyboardButton(text="◀️", callback_data=f"lbv:{p}"),
            InlineKeyboardButton(text=f"{idx + 1}/{total}", callback_data="lb_noop"),
            InlineKeyboardButton(text="▶️", callback_data=f"lbv:{n}"),
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _browse_show(msg: Message, state: FSMContext, idx: int, replace: bool) -> None:
    data = await state.get_data()
    ids = data.get("lst_ids") or []
    if not ids:
        await msg.answer("Список устарел — откройте доску заново 🙂", reply_markup=main_menu())
        return
    idx %= len(ids)
    async with get_session() as session:
        l = await session.get(Listing, ids[idx])
    if l is None:
        await msg.answer("Объявление пропало — откройте заново 🙂", reply_markup=main_menu())
        return
    kb = _browse_kb(l, idx, len(ids))
    chat_id, bot = msg.chat.id, msg.bot
    if replace:
        try:
            await msg.delete()
        except Exception:  # noqa: BLE001
            pass
    if l.photo_file_id:
        try:
            await bot.send_photo(chat_id, l.photo_file_id, caption=_card_text(l), reply_markup=kb)
            return
        except Exception:  # noqa: BLE001
            pass
    await bot.send_message(chat_id, _card_text(l), reply_markup=kb, disable_web_page_preview=True)


@router.callback_query(F.data.startswith("lbv:"))
async def browse_nav(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        idx = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.answer()
        return
    await callback.answer()
    await _browse_show(callback.message, state, idx, replace=True)


@router.callback_query(F.data == "lb_noop")
async def browse_noop(callback: CallbackQuery) -> None:
    await callback.answer()


# --- Жалоба ------------------------------------------------------------------

@router.callback_query(F.data.startswith("lrep:"))
async def listing_report(callback: CallbackQuery) -> None:
    lid = int(callback.data.split(":", 1)[1])
    who = f"@{callback.from_user.username}" if callback.from_user.username else f"id {callback.from_user.id}"
    for admin_id in config.ADMIN_IDS:
        await _safe_send(callback.bot, admin_id,
                         f"🚩 Жалоба на объявление #{lid} от {who}. Проверьте: /listing {lid}")
    await callback.answer("Спасибо! Передал на проверку 🙏", show_alert=True)


# --- Мои объявления ----------------------------------------------------------

@router.callback_query(F.data == "board:my")
async def my_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    now = datetime.utcnow()
    async with get_session() as session:
        rows = (await session.scalars(
            select(Listing).where(
                Listing.submitter_user_id == callback.from_user.id,
                Listing.status.in_(["pending", "approved"]),
                or_(Listing.expires_at.is_(None), Listing.expires_at > now),
            ).order_by(Listing.created_at.desc())
        )).all()
    await callback.answer()
    if not rows:
        await callback.message.answer("У вас нет активных объявлений 🙂", reply_markup=main_menu())
        return
    await state.update_data(my_ids=[l.id for l in rows])
    await callback.message.answer(f"🗂 Ваши объявления: <b>{len(rows)}</b>. Листай ◀️ ▶️ 👇",
                                  reply_markup=main_menu())
    await _my_show(callback.message, state, 0, replace=False)


def _my_kb(l: Listing, idx: int, total: int) -> InlineKeyboardMarkup:
    rows = []
    if l.status == "approved":
        rows.append([InlineKeyboardButton(
            text=f"📌 Поднять наверх ({config.BOARD_BUMP_PRICE} {config.LISTING_CURRENCY})",
            callback_data=f"lbump:{l.id}")])
    rows.append([InlineKeyboardButton(text="🗑 Закрыть", callback_data=f"lclose:{l.id}")])
    if total > 1:
        p, n = (idx - 1) % total, (idx + 1) % total
        rows.append([
            InlineKeyboardButton(text="◀️", callback_data=f"lmv:{p}"),
            InlineKeyboardButton(text=f"{idx + 1}/{total}", callback_data="lb_noop"),
            InlineKeyboardButton(text="▶️", callback_data=f"lmv:{n}"),
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _my_show(msg: Message, state: FSMContext, idx: int, replace: bool) -> None:
    data = await state.get_data()
    ids = data.get("my_ids") or []
    if not ids:
        await msg.answer("Список устарел — откройте «Мои объявления» заново 🙂",
                         reply_markup=main_menu())
        return
    idx %= len(ids)
    async with get_session() as session:
        l = await session.get(Listing, ids[idx])
    if l is None:
        await msg.answer("Объявление пропало 🙂", reply_markup=main_menu())
        return
    kb = _my_kb(l, idx, len(ids))
    chat_id, bot = msg.chat.id, msg.bot
    if replace:
        try:
            await msg.delete()
        except Exception:  # noqa: BLE001
            pass
    if l.photo_file_id:
        try:
            await bot.send_photo(chat_id, l.photo_file_id, caption=_card_text(l, with_status=True),
                                 reply_markup=kb)
            return
        except Exception:  # noqa: BLE001
            pass
    await bot.send_message(chat_id, _card_text(l, with_status=True), reply_markup=kb,
                           disable_web_page_preview=True)


@router.callback_query(F.data.startswith("lmv:"))
async def my_nav(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        idx = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.answer()
        return
    await callback.answer()
    await _my_show(callback.message, state, idx, replace=True)


@router.callback_query(F.data.startswith("lclose:"))
async def my_close(callback: CallbackQuery) -> None:
    lid = int(callback.data.split(":", 1)[1])
    async with get_session() as session:
        l = await session.get(Listing, lid)
        if l is None or l.submitter_user_id != callback.from_user.id:
            await callback.answer("Не найдено", show_alert=True)
            return
        l.status = "closed"
        await session.commit()
        title = l.title
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:  # noqa: BLE001
        pass
    await callback.message.answer(f"🗑 Закрыто: «{html.escape(title)}»", reply_markup=main_menu())
    await callback.answer("Закрыто")


@router.callback_query(F.data.startswith("lbump:"))
async def my_bump(callback: CallbackQuery) -> None:
    lid = int(callback.data.split(":", 1)[1])
    if not config.payments_enabled():
        await callback.answer("Оплата сейчас недоступна 🙏", show_alert=True)
        return
    async with get_session() as session:
        l = await session.get(Listing, lid)
        if l is None or l.submitter_user_id != callback.from_user.id:
            await callback.answer("Не найдено", show_alert=True)
            return
        title = l.title
    payment = await create_payment(
        f"{DESC}: {title}", {"listing_id": lid, "kind": "bump"}, config.BOARD_BUMP_PRICE
    )
    if not payment or not payment.get("checkout_url"):
        await callback.answer("Не вышло создать оплату, попробуйте позже", show_alert=True)
        return
    async with get_session() as session:
        l = await session.get(Listing, lid)
        if l:
            l.payment_id = payment["id"]
            await session.commit()
    await callback.message.answer(
        f"📌 Поднять «{html.escape(title)}» наверх — "
        f"{config.BOARD_BUMP_PRICE} {config.LISTING_CURRENCY}.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
            text=f"💳 Оплатить {config.BOARD_BUMP_PRICE} {config.LISTING_CURRENCY}",
            url=payment["checkout_url"])]]),
    )
    await callback.answer()


async def on_bump_paid(bot, payment_id: str, payment: dict) -> None:
    """Поднятие объявления наверх после оплаты (вызывается из on_payment_paid)."""
    status = payment.get("status")
    meta = payment.get("metadata") or {}
    lid = meta.get("listing_id")
    if not lid or status != "paid":
        return
    async with get_session() as session:
        if await session.get(Meta, f"pay:{payment_id}"):
            return
        l = await session.get(Listing, int(lid))
        if l is None:
            return
        now = datetime.utcnow()
        l.bumped_at = now
        # Поднятие заодно продлевает показ
        l.expires_at = now + timedelta(days=config.BOARD_LISTING_DAYS)
        session.add(Meta(key=f"pay:{payment_id}", value="done"))
        await session.commit()
        sub, title = l.submitter_user_id, l.title
    await log_event("payment", "bump")
    if sub:
        await _safe_send(bot, sub, f"📌 Готово! Объявление «{title}» поднято наверх. Спасибо 🙌")


# --- Просмотр одной карточки админом (по жалобе) -----------------------------

@router.message(Command("listing"), F.from_user.id.in_(config.ADMIN_IDS))
async def admin_listing(message: Message, state: FSMContext) -> None:
    await state.clear()
    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer("Использование: <code>/listing ID</code>", reply_markup=main_menu())
        return
    async with get_session() as session:
        l = await session.get(Listing, int(parts[1]))
    if l is None:
        await message.answer("Объявление не найдено 🤔", reply_markup=main_menu())
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🗑 Снять (отклонить)", callback_data=f"lstno:{l.id}"),
    ]])
    caption = _card_text(l, with_status=True)
    if l.photo_file_id:
        try:
            await message.answer_photo(l.photo_file_id, caption=caption, reply_markup=kb)
            return
        except Exception:  # noqa: BLE001
            pass
    await message.answer(caption, reply_markup=kb, disable_web_page_preview=True)
