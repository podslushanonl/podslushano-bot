"""Доска объявлений: анкета по типу объявления, модерация и управление.

Обычные объявления бесплатны, размещение жилья оплачивается через Mollie.
Услуги намеренно вынесены в Контакт-гайд. Все пользовательские данные проходят
проверку, а перед отправкой на модерацию показывается редактируемый предпросмотр.
"""
import html
import logging
import re
from datetime import datetime, timedelta

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import func, or_, select

import config
from database.db import get_session
from database.models import DigestPreference, Listing, Meta, NotificationDelivery
from keyboards.menus import BTN_BOARD, BTN_CONTACTS, BTN_SELF_ADD, main_menu
from states.forms import ListingBrowse, ListingForm
from utils.analytics import log_event
from utils.contact_links import TELEGRAM_TYPES, parse_contact_links
from utils.payments import create_payment

log = logging.getLogger(__name__)
router = Router()
router.message.filter(F.chat.type == ChatType.PRIVATE)

DESC = "Omhoog plaatsen advertentie Podslushano-bord"
DESC_LISTING = "Plaatsing woning-advertentie Podslushano-bord"

CATEGORIES = [
    ("housing", "🏠 Жильё"),
    ("goods", "🛋 Вещи"),
    ("free", "🎁 Отдам даром"),
    ("jobs", "💼 Работа"),
    ("rides", "🚗 Попутчики"),
    ("other", "📦 Разное"),
]
CATEGORY_LABELS = dict(CATEGORIES)
INTENTS = {
    "housing": [("offer", "Предлагаю жильё"), ("seek", "Ищу жильё")],
    "jobs": [("offer", "Предлагаю вакансию"), ("seek", "Ищу работу")],
    "goods": [("offer", "Продаю"), ("seek", "Ищу / куплю")],
    "rides": [("driver", "Ищу пассажиров"), ("passenger", "Ищу водителя")],
}
INTENT_LABELS = {
    (category, key): label
    for category, options in INTENTS.items()
    for key, label in options
}
POPULAR_CITIES = ["Amsterdam", "Rotterdam", "Den Haag", "Utrecht", "Eindhoven", "Groningen"]
ONLINE_WORDS = {"онлайн", "online", "по всей стране", "вся страна", "нидерланды"}

_EMAIL_RE = re.compile(
    r"^[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9-]+(?:\.[A-Z0-9-]+)+$",
    re.IGNORECASE,
)
_CONTACT_FIELDS = {
    "instagram": ("l_contact_instagram", "Instagram", "📷"),
    "telegram": ("l_contact_telegram", "Telegram", "✈️"),
    "whatsapp": ("l_contact_whatsapp", "WhatsApp", "💬"),
    "email": ("l_contact_email", "Почта", "✉️"),
    "phone": ("l_contact_phone", "Телефон", "📞"),
}


def _housing_paid() -> bool:
    price = (config.BOARD_HOUSING_PRICE or "").strip()
    return config.payments_enabled() and price not in ("", "0", "0.00")


def _clean(value: str) -> str:
    return " ".join((value or "").split())


def _valid_title(value: str) -> bool:
    chars = re.findall(r"[A-Za-zА-Яа-яЁё0-9]", value)
    return 5 <= len(value) <= 100 and len(chars) >= 4


def _valid_description(value: str) -> bool:
    words = re.findall(r"[A-Za-zА-Яа-яЁё0-9]+", value)
    letters = re.findall(r"[A-Za-zА-Яа-яЁё]", value)
    return 20 <= len(value) <= 600 and len(words) >= 3 and len(letters) >= 12


def _valid_price(value: str) -> bool:
    return 1 <= len(value) <= 100 and bool(re.search(r"[A-Za-zА-Яа-яЁё0-9€]", value))


def _valid_city(value: str) -> bool:
    return 2 <= len(value) <= 60 and len(re.findall(r"[A-Za-zА-Яа-яЁё]", value)) >= 2


def _normalize_phone(value: str) -> str | None:
    digits = re.sub(r"\D", "", value)
    if digits.startswith("00"):
        digits = digits[2:]
    elif value.strip().startswith("0"):
        digits = "31" + digits[1:]
    return f"+{digits}" if 8 <= len(digits) <= 15 else None


def _normalize_contact(kind: str, value: str) -> str | None:
    value = _clean(value).strip(" ,;")
    if kind == "instagram":
        match = re.fullmatch(
            r"(?:https?://)?(?:www\.)?instagram\.com/([A-Za-z0-9._]{1,30})/?(?:\?.*)?",
            value, re.IGNORECASE,
        )
        handle = match.group(1) if match else value.lstrip("@")
        return f"@{handle}" if re.fullmatch(r"[A-Za-z0-9._]{1,30}", handle) else None
    if kind == "telegram":
        match = re.fullmatch(
            r"(?:https?://)?(?:www\.)?t\.me/([A-Za-z][A-Za-z0-9_]{4,31})/?(?:\?.*)?",
            value, re.IGNORECASE,
        )
        handle = match.group(1) if match else value.lstrip("@")
        return f"@{handle}" if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{4,31}", handle) else None
    if kind == "email":
        value = value.lower()
        return value if len(value) <= 200 and _EMAIL_RE.fullmatch(value) else None
    if kind in {"phone", "whatsapp"}:
        return _normalize_phone(value)
    return None


def _build_contacts(data: dict) -> str:
    labels = {
        "instagram": "Instagram", "telegram": "Telegram", "whatsapp": "WhatsApp",
        "email": "E-mail", "phone": "Телефон",
    }
    return " · ".join(
        f"{labels[kind]}: {data[field]}"
        for kind, (field, _title, _icon) in _CONTACT_FIELDS.items()
        if data.get(field)
    )


def _contact_data(contact: str | None) -> dict:
    result: dict[str, str] = {}
    for item in parse_contact_links(contact):
        kind, url = item["type"], item["url"]
        field = _CONTACT_FIELDS.get(kind, (None,))[0]
        if not field:
            continue
        if kind == "instagram":
            result[field] = "@" + url.split("instagram.com/", 1)[-1].strip("/")
        elif kind == "telegram":
            result[field] = "@" + url.split("t.me/", 1)[-1].strip("/")
        elif kind == "whatsapp":
            result[field] = "+" + url.split("wa.me/", 1)[-1].strip("/")
        elif kind == "email":
            result[field] = url.removeprefix("mailto:")
        elif kind == "phone":
            result[field] = url.removeprefix("tel:")
    raw = (contact or "").strip()
    if raw.startswith("@") and not result:
        result["l_contact_telegram"] = raw
    return result


def _board_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔎 Смотреть объявления", callback_data="board:browse")],
        [InlineKeyboardButton(text="➕ Подать объявление", callback_data="board:new")],
        [InlineKeyboardButton(text="🗂 Мои объявления", callback_data="board:my")],
    ])


def _category_kb(prefix: str) -> InlineKeyboardMarkup:
    buttons = [InlineKeyboardButton(text=label, callback_data=f"{prefix}:{key}")
               for key, label in CATEGORIES]
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    rows.append([InlineKeyboardButton(text="🧰 Услуги (в Контакт-гайде)",
                                      callback_data=f"svcguide:{prefix}")])
    if prefix == "ncat":
        rows.append([InlineKeyboardButton(text="❌ Отменить", callback_data="lcancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _intent_kb(category: str) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=label, callback_data=f"lintent:{key}")]
            for key, label in INTENTS.get(category, [])]
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="lnav:category")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _nav_kb(back: str, *, skip: tuple[str, str] | None = None) -> InlineKeyboardMarkup:
    rows = []
    if skip:
        rows.append([InlineKeyboardButton(text=skip[0], callback_data=skip[1])])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"lnav:{back}")])
    rows.append([InlineKeyboardButton(text="❌ Отменить", callback_data="lcancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _city_kb(back: str = "price") -> InlineKeyboardMarkup:
    buttons = [InlineKeyboardButton(text=city, callback_data=f"lcity:{city}")
               for city in POPULAR_CITIES]
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    rows += [
        [InlineKeyboardButton(text="🌍 Онлайн / вся страна", callback_data="lcity:__all__")],
        [InlineKeyboardButton(text="✏️ Другой город", callback_data="lcity:__other__")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"lnav:{back}")],
        [InlineKeyboardButton(text="❌ Отменить", callback_data="lcancel")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _contact_hub_kb(data: dict) -> InlineKeyboardMarkup:
    buttons = []
    for kind, (field, title, icon) in _CONTACT_FIELDS.items():
        marker = "✅" if data.get(field) else icon
        buttons.append(InlineKeyboardButton(text=f"{marker} {title}",
                                             callback_data=f"lcontact:add:{kind}"))
    rows = [buttons[:2], buttons[2:4], buttons[4:]]
    if _build_contacts(data):
        rows.append([InlineKeyboardButton(text="Продолжить →", callback_data="lcontact:done")])
    rows += [
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="lnav:photo")],
        [InlineKeyboardButton(text="❌ Отменить", callback_data="lcancel")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _contact_input_kb(kind: str, has_value: bool) -> InlineKeyboardMarkup:
    rows = []
    if has_value:
        rows.append([InlineKeyboardButton(text="🗑 Удалить контакт",
                                          callback_data=f"lcontact:remove:{kind}")])
    rows.append([InlineKeyboardButton(text="⬅️ К контактам", callback_data="lcontact:hub")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _review_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Отправить на проверку", callback_data="lpub")],
        [InlineKeyboardButton(text="✏️ Изменить данные", callback_data="ledit:menu")],
        [InlineKeyboardButton(text="❌ Отменить", callback_data="lcancel")],
    ])


def _edit_kb(data: dict) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="Категория / тип", callback_data="ledit:category"),
         InlineKeyboardButton(text="Заголовок", callback_data="ledit:title")],
        [InlineKeyboardButton(text="Описание", callback_data="ledit:description"),
         InlineKeyboardButton(text="Цена / условия", callback_data="ledit:price")],
        [InlineKeyboardButton(text="Город", callback_data="ledit:city"),
         InlineKeyboardButton(text="Фото", callback_data="ledit:photo")],
        [InlineKeyboardButton(text="Контакты", callback_data="ledit:contact")],
        [InlineKeyboardButton(text="⬅️ К предпросмотру", callback_data="ledit:back")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _status(l: Listing, now: datetime | None = None) -> str:
    if l.status == "approved" and l.expires_at and l.expires_at <= (now or datetime.utcnow()):
        return "expired"
    return l.status


def _status_label(l: Listing) -> str:
    labels = {
        "awaiting_payment": "💳 ждёт оплаты", "pending": "🕒 на проверке",
        "approved": "✅ опубликовано", "rejected": "❌ отклонено",
        "closed": "🗑 закрыто", "expired": "⌛ срок истёк", "archived": "📦 в архиве",
    }
    return labels.get(_status(l), _status(l))


def _card_text(l: Listing, with_status: bool = False,
               show_contact_values: bool = False) -> str:
    parts = [CATEGORY_LABELS.get(l.category, "📦 Разное")]
    intent = INTENT_LABELS.get((l.category, getattr(l, "intent", None)))
    if intent:
        parts.append(f"<i>{html.escape(intent)}</i>")
    parts += ["", f"<b>{html.escape(l.title)}</b>"]
    if l.price:
        parts.append(f"💶 {html.escape(l.price)}")
    where = "по всей стране / онлайн" if l.is_nationwide else l.city
    if where:
        parts.append(f"📍 {html.escape(where)}")
    if l.description:
        parts += ["", html.escape(l.description)]
    links = parse_contact_links(l.contact)
    usable = any(x["type"] in TELEGRAM_TYPES or (
        x["type"] in {"phone", "email"} and config.WEBHOOK_BASE_URL
    ) for x in links)
    if l.contact and (show_contact_values or not usable):
        parts += ["", f"✍️ Контакты: {html.escape(l.contact)}"]
    if l.category == "housing":
        parts += ["", "⚠️ Не переводите предоплату до проверки жилья и договора."]
    if with_status:
        parts += ["", f"<i>Статус: {_status_label(l)}</i>"]
        if _status(l) == "approved" and l.expires_at:
            parts.append(f"<i>Размещено до: {l.expires_at:%d.%m.%Y}</i>")
    return "\n".join(parts)


def _listing_contact_rows(l: Listing) -> list[list[InlineKeyboardButton]]:
    buttons = []
    for link in parse_contact_links(l.contact):
        if link["type"] in TELEGRAM_TYPES:
            url = link["url"]
        elif link["type"] in {"phone", "email"} and config.WEBHOOK_BASE_URL and l.id:
            url = (f"{config.WEBHOOK_BASE_URL.rstrip('/')}/listing-contact/"
                   f"{l.id}/{link['type']}")
        else:
            continue
        buttons.append(InlineKeyboardButton(text=link["label"], url=url))
    return [buttons[i:i + 2] for i in range(0, len(buttons), 2)]


def _contact_url(contact: str | None) -> str | None:
    """Совместимость со старыми местами показа: возвращает первую HTTPS-ссылку."""
    raw = (contact or "").strip()
    if raw.startswith("@") and re.fullmatch(r"@[A-Za-z][A-Za-z0-9_]{4,31}", raw):
        return f"https://t.me/{raw[1:]}"
    return next((x["url"] for x in parse_contact_links(contact)
                 if x["type"] in TELEGRAM_TYPES), None)


async def _safe_send(bot, chat_id, text, reply_markup=None) -> bool:
    try:
        await bot.send_message(chat_id, text, reply_markup=reply_markup,
                               disable_web_page_preview=True)
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("Доска: не удалось отправить %s: %s", chat_id, exc)
        return False


@router.message(Command("board"))
@router.message(F.text == BTN_BOARD)
async def board_open(message: Message, state: FSMContext) -> None:
    await state.clear()
    price = f" Жильё — {config.BOARD_HOUSING_PRICE} {config.LISTING_CURRENCY}." if _housing_paid() else ""
    await message.answer(
        "📋 <b>Доска объявлений</b>\n\n"
        "Жильё, работа, вещи, попутчики и частные объявления по Нидерландам. "
        f"Обычное размещение бесплатно.{price}\n\n"
        f"Объявление показывается <b>{config.BOARD_LISTING_DAYS} дней</b> после проверки. "
        "Услуги специалистов размещаются отдельно — в Контакт-гайде.",
        reply_markup=_board_menu_kb(),
    )


@router.callback_query(F.data == "board:menu")
async def board_menu_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.answer("📋 <b>Доска объявлений</b> — выберите действие:",
                                  reply_markup=_board_menu_kb())
    await callback.answer()


@router.callback_query(F.data.startswith("svcguide:"))
async def services_to_guide(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    prefix = callback.data.split(":", 1)[1]
    if prefix == "ncat":
        text = ("🧰 Услуги размещаются в <b>Контакт-гайде специалистов</b>. "
                "Там карточки ищут по категории и городу.\n\n"
                f"Добавить себя: «{BTN_SELF_ADD}» в меню или /selfadd.")
    else:
        text = ("🧰 Специалистов ищите в Контакт-гайде.\n\n"
                f"Откройте «{BTN_CONTACTS}» в главном меню.")
    await callback.message.answer(text, reply_markup=main_menu())
    await callback.answer()


async def _ask_category(message: Message, state: FSMContext) -> None:
    await state.set_state(ListingForm.category)
    await message.answer("Выберите категорию объявления:", reply_markup=_category_kb("ncat"))


async def _ask_intent(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await state.set_state(ListingForm.intent)
    await message.answer("Что именно вы хотите сделать?", reply_markup=_intent_kb(data["l_cat"]))


async def _ask_title(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    examples = {
        ("housing", "offer"): "Например: Сдаю комнату в Utrecht",
        ("housing", "seek"): "Например: Ищу студию в Rotterdam",
        ("jobs", "offer"): "Например: Ищем помощника на кухню",
        ("jobs", "seek"): "Например: Ищу работу водителем",
    }
    await state.set_state(ListingForm.title)
    await message.answer(
        "Напишите короткий и понятный заголовок.\n"
        f"<i>{examples.get((data.get('l_cat'), data.get('l_intent')), 'Например: Продам велосипед')}</i>",
        reply_markup=_nav_kb("intent" if data.get("l_cat") in INTENTS else "category"),
    )


async def _ask_description(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    prompts = {
        "housing": "Укажите район, условия, доступную дату и важные требования.",
        "jobs": "Опишите задачи, график, опыт и условия работы.",
        "goods": "Опишите состояние, характеристики и способ передачи.",
        "rides": "Укажите дату, время, маршрут, места и багаж.",
    }
    await state.set_state(ListingForm.description)
    await message.answer(
        "Добавьте подробности.\n" + prompts.get(data.get("l_cat"), "Напишите всё, что важно знать читателю."),
        reply_markup=_nav_kb("title"),
    )


async def _ask_price(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    if data.get("l_cat") == "free":
        await state.update_data(l_price="Даром")
        if data.get("l_editing"):
            await state.update_data(l_editing=None)
            await _show_review(message, state)
        else:
            await _ask_city(message, state)
        return
    prompts = {
        "housing": "Укажите цену аренды / продажи или ваш бюджет.",
        "jobs": "Укажите зарплату, ставку или желаемую оплату.",
        "rides": "Укажите стоимость поездки или разделение расходов.",
        "goods": "Укажите цену или бюджет.",
    }
    await state.set_state(ListingForm.price)
    await message.answer(
        prompts.get(data.get("l_cat"), "Укажите цену или условия оплаты.") +
        "\nНапример: <b>€50</b>, <b>€18/час</b>, <b>договорная</b>.",
        reply_markup=_nav_kb("description", skip=("Без цены", "lprice:skip")),
    )


async def _ask_city(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await state.set_state(ListingForm.city)
    back = "description" if data.get("l_cat") == "free" else "price"
    await message.answer("Где актуально объявление?", reply_markup=_city_kb(back))


async def _ask_photo(message: Message, state: FSMContext) -> None:
    await state.set_state(ListingForm.photo)
    await message.answer(
        "Пришлите одно фото. Оно необязательно, но помогает быстрее получить отклик.",
        reply_markup=_nav_kb("city", skip=("Продолжить без фото", "lphoto:skip")),
    )


async def _ask_contacts(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await state.set_state(ListingForm.contact)
    await state.update_data(l_contact_field=None)
    await message.answer(
        "Как с вами связаться?\n\nВыберите и заполните любые подходящие контакты. "
        "Нужен минимум один — в объявлении он станет кнопкой.",
        reply_markup=_contact_hub_kb(data),
    )


def _preview_listing(data: dict) -> Listing:
    return Listing(
        id=data.get("l_existing_id"), category=data["l_cat"], intent=data.get("l_intent"),
        title=data["l_title"], description=data.get("l_desc"), price=data.get("l_price"),
        city=data.get("l_city", ""), is_nationwide=data.get("l_nationwide", False),
        contact=_build_contacts(data), photo_file_id=data.get("l_photo"),
    )


async def _show_review(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    required = ("l_cat", "l_title", "l_desc")
    if not all(data.get(key) for key in required) or not _build_contacts(data):
        await message.answer("Не все данные сохранились. Вернитесь к анкете.",
                             reply_markup=_category_kb("ncat"))
        return
    await state.set_state(ListingForm.review)
    preview = _preview_listing(data)
    await message.answer("Проверьте будущее объявление:")
    caption = _card_text(preview, show_contact_values=True)
    if data.get("l_photo"):
        try:
            await message.answer_photo(data["l_photo"], caption=caption)
        except Exception:  # noqa: BLE001
            await message.answer(caption, disable_web_page_preview=True)
    else:
        await message.answer(caption, disable_web_page_preview=True)
    fee = (f" После подтверждения будет оплата {config.BOARD_HOUSING_PRICE} "
           f"{config.LISTING_CURRENCY}." if data.get("l_cat") == "housing" and _housing_paid()
           and not data.get("l_housing_paid") else "")
    await message.answer(
        f"Всё верно? Объявление отправится на модерацию и будет размещено на "
        f"{config.BOARD_LISTING_DAYS} дней.{fee}", reply_markup=_review_kb(),
    )


async def _finish_field(message: Message, state: FSMContext, next_step) -> None:
    data = await state.get_data()
    if data.get("l_editing"):
        await state.update_data(l_editing=None)
        await _show_review(message, state)
    else:
        await next_step(message, state)


@router.callback_query(F.data == "board:new")
async def new_start(callback: CallbackQuery, state: FSMContext) -> None:
    await start_new_listing(callback.message, state, callback.from_user.id)
    await callback.answer()


async def start_new_listing(message: Message, state: FSMContext, uid: int) -> None:
    await state.clear()
    now = datetime.utcnow()
    async with get_session() as session:
        active = await session.scalar(select(func.count()).select_from(Listing).where(
            Listing.submitter_user_id == uid,
            Listing.status.in_(["awaiting_payment", "pending", "approved"]),
            or_(Listing.expires_at.is_(None), Listing.expires_at > now),
        )) or 0
    if active >= config.BOARD_MAX_ACTIVE:
        await message.answer(
            f"У вас уже {active} активных объявлений — максимум {config.BOARD_MAX_ACTIVE}. "
            "Управлять ими можно в «🗂 Мои объявления».", reply_markup=main_menu(),
        )
        return
    conditions = [
        "• обычные объявления — бесплатно;",
        f"• жильё — {config.BOARD_HOUSING_PRICE} {config.LISTING_CURRENCY};" if _housing_paid()
        else "• размещение жилья сейчас бесплатно;",
        f"• срок после модерации — {config.BOARD_LISTING_DAYS} дней;",
        "• услуги специалистов — только в Контакт-гайде.",
    ]
    await message.answer("➕ <b>Новое объявление</b>\n\n" + "\n".join(conditions))
    await _ask_category(message, state)


@router.callback_query(F.data.startswith("ncat:"))
async def new_category(callback: CallbackQuery, state: FSMContext) -> None:
    category = callback.data.split(":", 1)[1]
    if category not in CATEGORY_LABELS:
        await callback.answer("Неизвестная категория", show_alert=True)
        return
    previous = await state.get_data()
    price_update = {}
    if category == "free":
        price_update["l_price"] = "Даром"
    elif previous.get("l_cat") == "free":
        price_update["l_price"] = None
    await state.update_data(l_cat=category, l_intent=None, **price_update)
    data = await state.get_data()
    await callback.answer()
    if category in INTENTS:
        await _ask_intent(callback.message, state)
    elif data.get("l_editing"):
        await state.update_data(l_editing=None)
        await _show_review(callback.message, state)
    else:
        await _ask_title(callback.message, state)


@router.callback_query(F.data.startswith("lintent:"))
async def new_intent(callback: CallbackQuery, state: FSMContext) -> None:
    value = callback.data.split(":", 1)[1]
    data = await state.get_data()
    if value not in dict(INTENTS.get(data.get("l_cat"), [])):
        await callback.answer("Неизвестный вариант", show_alert=True)
        return
    await state.update_data(l_intent=value)
    await callback.answer()
    if data.get("l_editing"):
        await state.update_data(l_editing=None)
        await _show_review(callback.message, state)
    else:
        await _ask_title(callback.message, state)


@router.message(ListingForm.title)
async def new_title(message: Message, state: FSMContext) -> None:
    value = _clean(message.text or "")
    if not _valid_title(value):
        await message.answer("Заголовок должен быть понятным: от 5 до 100 символов.")
        return
    await state.update_data(l_title=value)
    await _finish_field(message, state, _ask_description)


@router.message(ListingForm.description)
async def new_description(message: Message, state: FSMContext) -> None:
    value = _clean(message.text or "")
    if not _valid_description(value):
        await message.answer("Добавьте минимум несколько содержательных слов — от 20 до 600 символов.")
        return
    await state.update_data(l_desc=value)
    await _finish_field(message, state, _ask_price)


@router.message(ListingForm.price)
async def new_price(message: Message, state: FSMContext) -> None:
    value = _clean(message.text or "")
    if not _valid_price(value):
        await message.answer("Укажите цену или условия коротким текстом.")
        return
    await state.update_data(l_price=value)
    await _finish_field(message, state, _ask_city)


@router.callback_query(F.data == "lprice:skip")
async def price_skip(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(l_price=None)
    await callback.answer()
    await _finish_field(callback.message, state, _ask_city)


@router.callback_query(F.data.startswith("lcity:"))
async def city_choose(callback: CallbackQuery, state: FSMContext) -> None:
    value = callback.data.split(":", 1)[1]
    await callback.answer()
    if value == "__other__":
        await state.set_state(ListingForm.city)
        await callback.message.answer("Напишите город:", reply_markup=_nav_kb("city"))
        return
    if value == "__all__":
        await state.update_data(l_city="", l_nationwide=True)
    elif value in POPULAR_CITIES:
        await state.update_data(l_city=value, l_nationwide=False)
    else:
        return
    await _finish_field(callback.message, state, _ask_photo)


@router.message(ListingForm.city)
async def city_typed(message: Message, state: FSMContext) -> None:
    value = _clean(message.text or "")
    if value.lower() in ONLINE_WORDS:
        await state.update_data(l_city="", l_nationwide=True)
    elif _valid_city(value):
        await state.update_data(l_city=value, l_nationwide=False)
    else:
        await message.answer("Проверьте название города и отправьте его ещё раз.")
        return
    await _finish_field(message, state, _ask_photo)


@router.message(ListingForm.photo)
async def new_photo(message: Message, state: FSMContext) -> None:
    if not message.photo:
        await message.answer("Пришлите фото как изображение или нажмите «Продолжить без фото».")
        return
    await state.update_data(l_photo=message.photo[-1].file_id)
    await _finish_field(message, state, _ask_contacts)


@router.callback_query(F.data == "lphoto:skip")
async def photo_skip(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(l_photo=None)
    await callback.answer()
    await _finish_field(callback.message, state, _ask_contacts)


@router.callback_query(F.data.startswith("lcontact:"))
async def contact_action(callback: CallbackQuery, state: FSMContext) -> None:
    parts = callback.data.split(":")
    action = parts[1] if len(parts) > 1 else ""
    kind = parts[2] if len(parts) > 2 else ""
    data = await state.get_data()
    await callback.answer()
    if action == "hub":
        await _ask_contacts(callback.message, state)
        return
    if action == "done":
        if not _build_contacts(data):
            await callback.message.answer("Добавьте хотя бы один способ связи.")
            return
        await state.update_data(l_contact=_build_contacts(data), l_contact_field=None)
        if data.get("l_editing"):
            await state.update_data(l_editing=None)
        await _show_review(callback.message, state)
        return
    if kind not in _CONTACT_FIELDS:
        return
    field, title, _icon = _CONTACT_FIELDS[kind]
    if action == "remove":
        await state.update_data(**{field: None, "l_contact_field": None})
        await _ask_contacts(callback.message, state)
        return
    if action != "add":
        return
    examples = {
        "instagram": "@username или instagram.com/username",
        "telegram": "@username или t.me/username",
        "whatsapp": "+31 6 12345678",
        "email": "mail@example.com",
        "phone": "+31 6 12345678",
    }
    await state.update_data(l_contact_field=kind)
    await state.set_state(ListingForm.contact)
    await callback.message.answer(
        f"<b>{html.escape(title)}</b>\n\nОтправьте {examples[kind]}. Бот проверит значение.",
        reply_markup=_contact_input_kb(kind, bool(data.get(field))),
    )


@router.message(ListingForm.contact)
async def contact_value(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    kind = data.get("l_contact_field")
    if kind not in _CONTACT_FIELDS:
        await _ask_contacts(message, state)
        return
    value = _normalize_contact(kind, message.text or "")
    if not value:
        await message.answer("Проверьте формат контакта и отправьте ещё раз.")
        return
    await state.update_data(**{_CONTACT_FIELDS[kind][0]: value, "l_contact_field": None})
    await message.answer("Контакт сохранён ✅")
    await _ask_contacts(message, state)


@router.callback_query(F.data.startswith("lnav:"))
async def form_back(callback: CallbackQuery, state: FSMContext) -> None:
    target = callback.data.split(":", 1)[1]
    data = await state.get_data()
    await callback.answer()
    actions = {
        "category": _ask_category, "intent": _ask_intent, "title": _ask_title,
        "description": _ask_description, "price": _ask_price, "city": _ask_city,
        "photo": _ask_photo, "contact": _ask_contacts,
    }
    if target == "intent" and data.get("l_cat") not in INTENTS:
        target = "category"
    action = actions.get(target)
    if action:
        await action(callback.message, state)


@router.callback_query(F.data.startswith("ledit:"))
async def edit_field(callback: CallbackQuery, state: FSMContext) -> None:
    field = callback.data.split(":", 1)[1]
    await callback.answer()
    if field == "menu":
        await callback.message.answer("Что нужно изменить?", reply_markup=_edit_kb(await state.get_data()))
        return
    if field == "back":
        await state.update_data(l_editing=None)
        await _show_review(callback.message, state)
        return
    actions = {
        "category": _ask_category, "title": _ask_title, "description": _ask_description,
        "price": _ask_price, "city": _ask_city, "photo": _ask_photo, "contact": _ask_contacts,
    }
    action = actions.get(field)
    if action:
        await state.update_data(l_editing=field)
        await action(callback.message, state)


@router.callback_query(F.data == "lcancel")
async def new_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.answer("Анкета отменена — ничего не опубликовано.", reply_markup=main_menu())
    await callback.answer()


def _apply_form(listing: Listing, data: dict) -> None:
    listing.category = data["l_cat"]
    listing.intent = data.get("l_intent")
    listing.title = data["l_title"]
    listing.description = data.get("l_desc")
    listing.price = data.get("l_price")
    listing.city = data.get("l_city", "")
    listing.is_nationwide = data.get("l_nationwide", False)
    listing.photo_file_id = data.get("l_photo")
    listing.contact = _build_contacts(data)


async def _notify_admins(bot, listing_id: int, heading: str) -> None:
    async with get_session() as session:
        listing = await session.get(Listing, listing_id)
    if not listing:
        return
    for admin_id in config.ADMIN_IDS:
        await _safe_send(bot, admin_id, heading)
        await _send_admin_card(bot, admin_id, listing)


async def _request_listing_payment(message: Message, uid: int, listing_id: int) -> bool:
    async with get_session() as session:
        listing = await session.get(Listing, listing_id)
        if not listing or listing.submitter_user_id != uid or listing.status != "awaiting_payment":
            await message.answer("Это объявление уже оплачено или больше недоступно.",
                                 reply_markup=main_menu())
            return False
        title = listing.title
    payment = await create_payment(
        f"{DESC_LISTING}: {title}", {"listing_id": listing_id, "kind": "listing"},
        config.BOARD_HOUSING_PRICE,
    )
    if not payment or not payment.get("checkout_url"):
        await message.answer(
            "Не получилось создать ссылку на оплату. Анкета сохранена — попробуйте ещё раз позже.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Повторить оплату", callback_data=f"lpay:{listing_id}")],
                [InlineKeyboardButton(text="🗂 Мои объявления", callback_data="board:my")],
            ]),
        )
        return False
    async with get_session() as session:
        listing = await session.get(Listing, listing_id)
        if listing:
            listing.payment_id = payment["id"]
            await session.commit()
    await message.answer(
        f"Анкета сохранена. Размещение жилья — <b>{config.BOARD_HOUSING_PRICE} "
        f"{config.LISTING_CURRENCY}</b>. После оплаты объявление отправится на модерацию.\n\n"
        "Автоматического продления нет.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
            text=f"💳 Оплатить {config.BOARD_HOUSING_PRICE} {config.LISTING_CURRENCY}",
            url=payment["checkout_url"],
        )]]),
    )
    return True


@router.callback_query(F.data == "lpub")
async def new_publish(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if not data.get("l_title") or not _build_contacts(data):
        await callback.answer("Данные анкеты потерялись", show_alert=True)
        return
    existing_id = data.get("l_existing_id")
    needs_payment = data["l_cat"] == "housing" and _housing_paid() and not data.get("l_housing_paid")
    async with get_session() as session:
        listing = await session.get(Listing, existing_id) if existing_id else None
        if existing_id and (not listing or listing.submitter_user_id != callback.from_user.id):
            await callback.answer("Объявление не найдено", show_alert=True)
            return
        if listing is None:
            listing = Listing(submitter_user_id=callback.from_user.id,
                              submitter_username=callback.from_user.username)
            session.add(listing)
        _apply_form(listing, data)
        listing.expires_at = None
        listing.bumped_at = None
        listing.status = "awaiting_payment" if needs_payment else "pending"
        if needs_payment:
            listing.payment_id = None
        await session.commit()
        await session.refresh(listing)
        listing_id = listing.id
    await state.clear()
    await callback.answer()
    if needs_payment:
        await _request_listing_payment(callback.message, callback.from_user.id, listing_id)
        return
    await callback.message.answer(
        "Готово 🙌 Объявление отправлено на проверку. Сообщу после публикации.",
        reply_markup=main_menu(),
    )
    await _notify_admins(callback.bot, listing_id, "🆕 <b>Объявление на проверку</b>")


@router.callback_query(F.data.startswith("lpay:"))
async def retry_listing_payment(callback: CallbackQuery) -> None:
    listing_id = int(callback.data.split(":", 1)[1])
    await callback.answer()
    await _request_listing_payment(callback.message, callback.from_user.id, listing_id)


async def on_listing_paid(bot, payment_id: str, payment: dict) -> None:
    meta = payment.get("metadata") or {}
    listing_id = meta.get("listing_id")
    if not listing_id or payment.get("status") != "paid":
        return
    async with get_session() as session:
        if await session.get(Meta, f"pay:{payment_id}"):
            return
        listing = await session.get(Listing, int(listing_id))
        if listing is None:
            return
        if listing.status != "awaiting_payment":
            session.add(Meta(key=f"pay:{payment_id}", value="duplicate"))
            await session.commit()
            for admin_id in config.ADMIN_IDS:
                await _safe_send(bot, admin_id,
                                 f"⚠️ Повторная оплата объявления #{listing.id}: {payment_id}")
            return
        listing.status = "pending"
        listing.payment_id = payment_id
        session.add(Meta(key=f"pay:{payment_id}", value="done"))
        await session.commit()
        uid, listing_id = listing.submitter_user_id, listing.id
    await log_event("payment", "listing")
    await _notify_admins(bot, listing_id, "🆕 <b>Оплаченное объявление о жилье</b>")
    if uid:
        await _safe_send(bot, uid, "Оплата получена ✅ Объявление отправлено на проверку.")


async def _send_admin_card(bot, chat_id: int, listing: Listing) -> None:
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Опубликовать", callback_data=f"lstok:{listing.id}"),
        InlineKeyboardButton(text="❌ Отклонить", callback_data=f"lstno:{listing.id}"),
    ]])
    caption = _card_text(listing, show_contact_values=True)
    if listing.photo_file_id:
        try:
            await bot.send_photo(chat_id, listing.photo_file_id, caption=caption, reply_markup=kb)
            return
        except Exception:  # noqa: BLE001
            pass
    await _safe_send(bot, chat_id, caption, kb)


@router.callback_query(F.data.startswith("lstok:"), F.from_user.id.in_(config.ADMIN_IDS))
async def listing_approve(callback: CallbackQuery) -> None:
    listing_id = int(callback.data.split(":", 1)[1])
    async with get_session() as session:
        listing = await session.get(Listing, listing_id)
        if not listing or listing.status != "pending":
            await callback.answer("Объявление уже обработано", show_alert=True)
            return
        listing.status = "approved"
        listing.expires_at = datetime.utcnow() + timedelta(days=config.BOARD_LISTING_DAYS)
        await session.commit()
        uid, title = listing.submitter_user_id, listing.title
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:  # noqa: BLE001
        pass
    await callback.message.answer(f"✅ Опубликовано: «{html.escape(title)}»")
    await callback.answer("Опубликовано")
    if uid:
        await _safe_send(callback.bot, uid,
                         f"🎉 Объявление «{title}» опубликовано на {config.BOARD_LISTING_DAYS} дней.",
                         InlineKeyboardMarkup(inline_keyboard=[[
                             InlineKeyboardButton(text="🗂 Управлять", callback_data="board:my")
                         ]]))


@router.callback_query(F.data.startswith("lstno:"), F.from_user.id.in_(config.ADMIN_IDS))
async def listing_reject(callback: CallbackQuery) -> None:
    listing_id = int(callback.data.split(":", 1)[1])
    async with get_session() as session:
        listing = await session.get(Listing, listing_id)
        if not listing:
            await callback.answer("Не найдено", show_alert=True)
            return
        listing.status = "rejected"
        await session.commit()
        uid, title = listing.submitter_user_id, listing.title
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:  # noqa: BLE001
        pass
    await callback.message.answer(f"❌ Отклонено: «{html.escape(title)}»")
    await callback.answer("Отклонено")
    if uid:
        await _safe_send(callback.bot, uid,
                         f"Объявление «{title}» не прошло проверку. Его можно исправить в «Моих объявлениях».",
                         InlineKeyboardMarkup(inline_keyboard=[[
                             InlineKeyboardButton(text="🗂 Открыть", callback_data="board:my")
                         ]]))


def _browse_city_kb(category: str, saved_city: str = "") -> InlineKeyboardMarkup:
    rows = []
    if saved_city:
        rows.append([InlineKeyboardButton(text=f"📍 Мой город: {saved_city}"[:60],
                                          callback_data=f"bcity:{category}:saved")])
    buttons = [InlineKeyboardButton(text=city, callback_data=f"bcity:{category}:{city}")
               for city in POPULAR_CITIES]
    rows += [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    rows += [
        [InlineKeyboardButton(text="🌍 Все города", callback_data=f"bcity:{category}:__all__")],
        [InlineKeyboardButton(text="✏️ Другой город", callback_data=f"bcityx:{category}")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data == "board:browse")
async def browse_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.answer("Что ищете?", reply_markup=_category_kb("bcat"))
    await callback.answer()


@router.callback_query(F.data.startswith("bcat:"))
async def browse_category(callback: CallbackQuery, state: FSMContext) -> None:
    category = callback.data.split(":", 1)[1]
    if category not in CATEGORY_LABELS:
        await callback.answer()
        return
    async with get_session() as session:
        pref = await session.get(DigestPreference, callback.from_user.id)
    saved_city = (pref.city if pref else "") or ""
    await state.update_data(b_cat=category, b_saved_city=saved_city)
    await callback.message.answer("Выберите город или покажите всю страну:",
                                  reply_markup=_browse_city_kb(category, saved_city))
    await callback.answer()


@router.callback_query(F.data.startswith("bcityx:"))
async def browse_city_other(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(ListingBrowse.waiting_city)
    await state.update_data(b_cat=callback.data.split(":", 1)[1])
    await callback.message.answer("Напишите город:")
    await callback.answer()


@router.message(ListingBrowse.waiting_city)
async def browse_city_typed(message: Message, state: FSMContext) -> None:
    city = _clean(message.text or "")
    if not _valid_city(city):
        await message.answer("Проверьте название города и отправьте ещё раз.")
        return
    await _browse_collect(message, state, (await state.get_data()).get("b_cat", "other"), city)


@router.callback_query(F.data.startswith("bcity:"))
async def browse_city_btn(callback: CallbackQuery, state: FSMContext) -> None:
    _, category, city = callback.data.split(":", 2)
    data = await state.get_data()
    if city == "saved":
        city = data.get("b_saved_city", "")
    elif city == "__all__":
        city = ""
    await callback.answer()
    await _browse_collect(callback.message, state, category, city)


async def _browse_collect(message: Message, state: FSMContext, category: str, city: str) -> None:
    now = datetime.utcnow()
    query = select(Listing).where(
        Listing.status == "approved", Listing.category == category,
        or_(Listing.expires_at.is_(None), Listing.expires_at > now),
    )
    if city:
        query = query.where(or_(Listing.is_nationwide.is_(True), Listing.city.ilike(f"%{city}%")))
    query = query.order_by(Listing.bumped_at.is_(None), Listing.bumped_at.desc(),
                           Listing.created_at.desc())
    async with get_session() as session:
        rows = (await session.scalars(query)).all()
    await state.clear()
    if not rows:
        where = f" в {html.escape(city)}" if city else ""
        await message.answer(
            f"Пока нет объявлений {CATEGORY_LABELS.get(category, category)}{where}.",
            reply_markup=_board_menu_kb(),
        )
        return
    await state.update_data(lst_ids=[row.id for row in rows])
    await log_event("board_view", category)
    where = f" · {html.escape(city)}" if city else " · все города"
    await message.answer(f"Найдено: <b>{len(rows)}</b>{where}")
    await _browse_show(message, state, 0, replace=False)


def _browse_kb(listing: Listing, index: int, total: int) -> InlineKeyboardMarkup:
    rows = _listing_contact_rows(listing)
    rows.append([InlineKeyboardButton(text="♡ Сохранить",
                                      callback_data=f"save:listing:{listing.id}")])
    rows.append([InlineKeyboardButton(text="🚩 Пожаловаться",
                                      callback_data=f"lrep:{listing.id}")])
    if total > 1:
        rows.append([
            InlineKeyboardButton(text="◀️", callback_data=f"lbv:{(index - 1) % total}"),
            InlineKeyboardButton(text=f"{index + 1}/{total}", callback_data="lb_noop"),
            InlineKeyboardButton(text="▶️", callback_data=f"lbv:{(index + 1) % total}"),
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _browse_show(message: Message, state: FSMContext, index: int, replace: bool) -> None:
    ids = (await state.get_data()).get("lst_ids") or []
    if not ids:
        await message.answer("Список устарел — откройте доску заново.", reply_markup=main_menu())
        return
    index %= len(ids)
    async with get_session() as session:
        listing = await session.get(Listing, ids[index])
    if not listing or _status(listing) != "approved":
        await message.answer("Объявление больше не активно.", reply_markup=main_menu())
        return
    if replace:
        try:
            await message.delete()
        except Exception:  # noqa: BLE001
            pass
    kb = _browse_kb(listing, index, len(ids))
    if listing.photo_file_id:
        try:
            await message.bot.send_photo(message.chat.id, listing.photo_file_id,
                                         caption=_card_text(listing), reply_markup=kb)
            return
        except Exception:  # noqa: BLE001
            pass
    await message.bot.send_message(message.chat.id, _card_text(listing), reply_markup=kb,
                                   disable_web_page_preview=True)


@router.callback_query(F.data.startswith("lbv:"))
async def browse_nav(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        index = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer()
        return
    await callback.answer()
    await _browse_show(callback.message, state, index, replace=True)


@router.callback_query(F.data == "lb_noop")
async def browse_noop(callback: CallbackQuery) -> None:
    await callback.answer()


REPORT_REASONS = {
    "scam": "Похоже на мошенничество", "outdated": "Уже не актуально",
    "duplicate": "Дубликат", "prohibited": "Запрещённый контент", "other": "Другая причина",
}


@router.callback_query(F.data.startswith("lrep:"))
async def listing_report(callback: CallbackQuery) -> None:
    listing_id = int(callback.data.split(":", 1)[1])
    rows = [[InlineKeyboardButton(text=label, callback_data=f"lrepreason:{listing_id}:{key}")]
            for key, label in REPORT_REASONS.items()]
    await callback.message.answer("Почему вы хотите пожаловаться?",
                                  reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await callback.answer()


@router.callback_query(F.data.startswith("lrepreason:"))
async def listing_report_reason(callback: CallbackQuery) -> None:
    _, listing_id, reason = callback.data.split(":", 2)
    if reason not in REPORT_REASONS:
        await callback.answer()
        return
    who = f"@{callback.from_user.username}" if callback.from_user.username else f"id {callback.from_user.id}"
    for admin_id in config.ADMIN_IDS:
        await _safe_send(callback.bot, admin_id,
                         f"🚩 Жалоба на объявление #{listing_id}\nПричина: {REPORT_REASONS[reason]}\nОт: {who}\n/listing {listing_id}")
    await callback.answer("Спасибо! Передал на проверку.", show_alert=True)
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:  # noqa: BLE001
        pass


async def _expire_user_listings(uid: int) -> None:
    now = datetime.utcnow()
    async with get_session() as session:
        rows = (await session.scalars(select(Listing).where(
            Listing.submitter_user_id == uid, Listing.status == "approved",
            Listing.expires_at.is_not(None), Listing.expires_at <= now,
        ))).all()
        for row in rows:
            row.status = "expired"
        if rows:
            await session.commit()


@router.callback_query(F.data == "board:my")
async def my_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await _expire_user_listings(callback.from_user.id)
    async with get_session() as session:
        rows = (await session.scalars(select(Listing).where(
            Listing.submitter_user_id == callback.from_user.id,
        ).order_by(Listing.created_at.desc()).limit(20))).all()
    await callback.answer()
    if not rows:
        await callback.message.answer("У вас пока нет объявлений.", reply_markup=_board_menu_kb())
        return
    await state.update_data(my_ids=[row.id for row in rows])
    await callback.message.answer(f"🗂 Ваши объявления: <b>{len(rows)}</b>")
    await _my_show(callback.message, state, 0, replace=False)


def _my_kb(listing: Listing, index: int, total: int) -> InlineKeyboardMarkup:
    status = _status(listing)
    rows = []
    if status == "awaiting_payment":
        rows.append([InlineKeyboardButton(text="💳 Продолжить оплату",
                                          callback_data=f"lpay:{listing.id}")])
    if status in {"awaiting_payment", "pending", "approved", "rejected"}:
        rows.append([InlineKeyboardButton(text="✏️ Изменить",
                                          callback_data=f"leditlisting:{listing.id}")])
    if status == "approved":
        rows.append([InlineKeyboardButton(
            text=f"📌 Поднять ({config.BOARD_BUMP_PRICE} {config.LISTING_CURRENCY})",
            callback_data=f"lbump:{listing.id}",
        )])
    if status in {"expired", "closed"}:
        rows.append([InlineKeyboardButton(text="🔁 Опубликовать снова",
                                          callback_data=f"lrepublish:{listing.id}")])
    if status not in {"closed", "expired"}:
        rows.append([InlineKeyboardButton(text="🗑 Закрыть",
                                          callback_data=f"lcloseask:{listing.id}")])
    if total > 1:
        rows.append([
            InlineKeyboardButton(text="◀️", callback_data=f"lmv:{(index - 1) % total}"),
            InlineKeyboardButton(text=f"{index + 1}/{total}", callback_data="lb_noop"),
            InlineKeyboardButton(text="▶️", callback_data=f"lmv:{(index + 1) % total}"),
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _my_show(message: Message, state: FSMContext, index: int, replace: bool) -> None:
    ids = (await state.get_data()).get("my_ids") or []
    if not ids:
        await message.answer("Откройте «Мои объявления» заново.", reply_markup=main_menu())
        return
    index %= len(ids)
    async with get_session() as session:
        listing = await session.get(Listing, ids[index])
    if not listing:
        await message.answer("Объявление не найдено.", reply_markup=main_menu())
        return
    if replace:
        try:
            await message.delete()
        except Exception:  # noqa: BLE001
            pass
    kb = _my_kb(listing, index, len(ids))
    caption = _card_text(listing, with_status=True, show_contact_values=True)
    if listing.photo_file_id:
        try:
            await message.bot.send_photo(message.chat.id, listing.photo_file_id,
                                         caption=caption, reply_markup=kb)
            return
        except Exception:  # noqa: BLE001
            pass
    await message.bot.send_message(message.chat.id, caption, reply_markup=kb,
                                   disable_web_page_preview=True)


@router.callback_query(F.data.startswith("lmv:"))
async def my_nav(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await _my_show(callback.message, state, int(callback.data.split(":", 1)[1]), replace=True)


@router.callback_query(F.data.startswith("leditlisting:"))
async def my_edit(callback: CallbackQuery, state: FSMContext) -> None:
    listing_id = int(callback.data.split(":", 1)[1])
    async with get_session() as session:
        listing = await session.get(Listing, listing_id)
        if not listing or listing.submitter_user_id != callback.from_user.id:
            await callback.answer("Не найдено", show_alert=True)
            return
        data = {
            "l_existing_id": listing.id, "l_existing_status": listing.status,
            "l_cat": listing.category, "l_intent": listing.intent,
            "l_title": listing.title, "l_desc": listing.description,
            "l_price": listing.price, "l_city": listing.city,
            "l_nationwide": listing.is_nationwide, "l_photo": listing.photo_file_id,
            "l_housing_paid": bool(listing.category == "housing" and
                                   listing.status in {"pending", "approved", "rejected"}),
            **_contact_data(listing.contact),
        }
    await state.clear()
    await state.update_data(**data)
    await callback.answer()
    await _show_review(callback.message, state)


@router.callback_query(F.data.startswith("lcloseask:"))
async def my_close_ask(callback: CallbackQuery) -> None:
    listing_id = int(callback.data.split(":", 1)[1])
    await callback.message.answer(
        "Закрыть объявление? Оно сразу исчезнет из доски.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Да, закрыть", callback_data=f"lcloseyes:{listing_id}")],
            [InlineKeyboardButton(text="Нет, оставить", callback_data="lclosecancel")],
        ]),
    )
    await callback.answer()


@router.callback_query(F.data == "lclosecancel")
async def my_close_cancel(callback: CallbackQuery) -> None:
    try:
        await callback.message.delete()
    except Exception:  # noqa: BLE001
        pass
    await callback.answer("Оставлено")


@router.callback_query(F.data.startswith("lcloseyes:"))
async def my_close(callback: CallbackQuery) -> None:
    listing_id = int(callback.data.split(":", 1)[1])
    async with get_session() as session:
        listing = await session.get(Listing, listing_id)
        if not listing or listing.submitter_user_id != callback.from_user.id:
            await callback.answer("Не найдено", show_alert=True)
            return
        listing.status = "closed"
        await session.commit()
        title = listing.title
    await callback.message.answer(f"🗑 Закрыто: «{html.escape(title)}»", reply_markup=_board_menu_kb())
    await callback.answer("Закрыто")


@router.callback_query(F.data.startswith("lrepublish:"))
async def my_republish(callback: CallbackQuery) -> None:
    listing_id = int(callback.data.split(":", 1)[1])
    async with get_session() as session:
        listing = await session.get(Listing, listing_id)
        if (not listing or listing.submitter_user_id != callback.from_user.id
                or _status(listing) not in {"closed", "expired"}):
            await callback.answer("Объявление нельзя опубликовать повторно", show_alert=True)
            return
        paid = listing.category == "housing" and _housing_paid()
        listing.status = "awaiting_payment" if paid else "pending"
        listing.expires_at = None
        listing.bumped_at = None
        listing.payment_id = None
        await session.commit()
    await callback.answer()
    if paid:
        await _request_listing_payment(callback.message, callback.from_user.id, listing_id)
    else:
        await callback.message.answer("Объявление снова отправлено на проверку ✅",
                                      reply_markup=main_menu())
        await _notify_admins(callback.bot, listing_id, "🔁 <b>Повторная публикация</b>")


@router.callback_query(F.data.startswith("lbump:"))
async def my_bump(callback: CallbackQuery) -> None:
    listing_id = int(callback.data.split(":", 1)[1])
    if not config.payments_enabled():
        await callback.answer("Оплата сейчас недоступна", show_alert=True)
        return
    async with get_session() as session:
        listing = await session.get(Listing, listing_id)
        if (not listing or listing.submitter_user_id != callback.from_user.id
                or _status(listing) != "approved"):
            await callback.answer("Поднять можно только активное объявление", show_alert=True)
            return
        title = listing.title
    payment = await create_payment(f"{DESC}: {title}",
                                   {"listing_id": listing_id, "kind": "bump"},
                                   config.BOARD_BUMP_PRICE)
    if not payment or not payment.get("checkout_url"):
        await callback.answer("Не вышло создать оплату, попробуйте позже", show_alert=True)
        return
    async with get_session() as session:
        listing = await session.get(Listing, listing_id)
        if listing:
            listing.payment_id = payment["id"]
            await session.commit()
    await callback.message.answer(
        f"📌 Поднять «{html.escape(title)}» — {config.BOARD_BUMP_PRICE} {config.LISTING_CURRENCY}.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
            text=f"💳 Оплатить {config.BOARD_BUMP_PRICE} {config.LISTING_CURRENCY}",
            url=payment["checkout_url"],
        )]]),
    )
    await callback.answer()


async def on_bump_paid(bot, payment_id: str, payment: dict) -> None:
    meta = payment.get("metadata") or {}
    listing_id = meta.get("listing_id")
    if not listing_id or payment.get("status") != "paid":
        return
    async with get_session() as session:
        if await session.get(Meta, f"pay:{payment_id}"):
            return
        listing = await session.get(Listing, int(listing_id))
        if not listing:
            return
        now = datetime.utcnow()
        if _status(listing, now) != "approved":
            session.add(Meta(key=f"pay:{payment_id}", value="inactive_bump"))
            await session.commit()
            uid = listing.submitter_user_id
            if uid:
                await _safe_send(bot, uid, "Оплата получена, но объявление уже не активно. Напишите /contact.")
            for admin_id in config.ADMIN_IDS:
                await _safe_send(bot, admin_id,
                                 f"⚠️ Оплачено поднятие неактивного объявления #{listing.id}: {payment_id}")
            return
        listing.bumped_at = now
        listing.expires_at = now + timedelta(days=config.BOARD_LISTING_DAYS)
        session.add(Meta(key=f"pay:{payment_id}", value="done"))
        await session.commit()
        uid, title = listing.submitter_user_id, listing.title
    await log_event("payment", "bump")
    if uid:
        await _safe_send(bot, uid, f"📌 Объявление «{title}» поднято и продлено на {config.BOARD_LISTING_DAYS} дней.")


async def send_listing_expiry_reminders(bot, *, now: datetime | None = None) -> int:
    """Раз в срок напоминает владельцу за три дня до окончания объявления."""
    current = now or datetime.utcnow()
    start, end = current + timedelta(days=2), current + timedelta(days=4)
    async with get_session() as session:
        rows = (await session.scalars(select(Listing).where(
            Listing.status == "approved", Listing.submitter_user_id.is_not(None),
            Listing.expires_at >= start, Listing.expires_at < end,
        ))).all()
    sent = 0
    for listing in rows:
        key = f"listing-expiry:{listing.id}:{listing.expires_at:%Y%m%d}"
        async with get_session() as session:
            exists = (await session.scalars(select(NotificationDelivery).where(
                NotificationDelivery.user_id == listing.submitter_user_id,
                NotificationDelivery.delivery_key == key,
                NotificationDelivery.status == "sent",
            ))).first()
        if exists:
            continue
        try:
            message = await bot.send_message(
                listing.submitter_user_id,
                f"⌛ Объявление «{html.escape(listing.title)}» закончится "
                f"{listing.expires_at:%d.%m.%Y}. Можно поднять его сейчас или опубликовать снова после окончания.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="🗂 Управлять", callback_data="board:my")
                ]]),
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("Не отправлено напоминание об объявлении #%s: %s", listing.id, exc)
            continue
        async with get_session() as session:
            session.add(NotificationDelivery(
                user_id=listing.submitter_user_id, delivery_key=key,
                kind="listing_expiry", status="sent",
                telegram_message_id=getattr(message, "message_id", None),
            ))
            await session.commit()
        sent += 1
    return sent


@router.message(Command("listing"), F.from_user.id.in_(config.ADMIN_IDS))
async def admin_listing(message: Message, state: FSMContext) -> None:
    await state.clear()
    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer("Использование: <code>/listing ID</code>", reply_markup=main_menu())
        return
    async with get_session() as session:
        listing = await session.get(Listing, int(parts[1]))
    if not listing:
        await message.answer("Объявление не найдено.", reply_markup=main_menu())
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🗑 Снять / отклонить", callback_data=f"lstno:{listing.id}")
    ]])
    caption = _card_text(listing, with_status=True, show_contact_values=True)
    if listing.photo_file_id:
        try:
            await message.answer_photo(listing.photo_file_id, caption=caption, reply_markup=kb)
            return
        except Exception:  # noqa: BLE001
            pass
    await message.answer(caption, reply_markup=kb, disable_web_page_preview=True)
