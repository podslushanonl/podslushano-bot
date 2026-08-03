"""Платное само-добавление специалистов в гайд (через Mollie).

Поток: пользователь жмёт «➕ Добавить себя в гайд» → анкета → ссылка на оплату
Mollie → после оплаты (webhook) заявка приходит админам на проверку → админ
публикует. Перед окончанием года бот напоминает о продлении.
"""
import asyncio
import html
import logging
import re
from datetime import datetime, timedelta
from urllib.parse import urlsplit, urlunsplit

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
from sqlalchemy import select

import config
from database.db import get_session
from database.models import Meta, Specialist, SpecialistReminderLog
from keyboards.menus import BTN_SELF_ADD, cancel_menu, main_menu
from states.forms import ClaimPay, SelfAddSpecialist
from utils.ai import extract_specialist_query
from utils.analytics import log_event
from utils.geo import CATEGORIES, NEIGHBORS, THEMES, detect_category, detect_city
from utils.payments import create_payment, get_payment

log = logging.getLogger(__name__)

router = Router()
router.message.filter(F.chat.type == ChatType.PRIVATE)

ONLINE_WORDS = {"онлайн", "online", "по всей стране"}
SELFADD_PLANS = ("month", "year", "month_premium", "6m_premium", "year_premium")
_EMAIL_RE = re.compile(
    r"^[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9-]+(?:\.[A-Z0-9-]+)+$",
    re.IGNORECASE,
)

# Описание платежа (видно в Mollie/банке) — на нидерландском
DESC_NEW = "Vermelding in Podslushano-gids"
DESC_RENEW = "Verlenging vermelding Podslushano-gids"


def _price_str(plan: str) -> str:
    info = config.plan_info(plan)
    try:
        price = f"€{float(info['price']):.2f}".replace(".", ",")
    except (TypeError, ValueError):
        price = f"€{info['price']}"
    return f"{price} · {info['title']}"


def _format_euro(value: str) -> str:
    """Показывает цену привычно для NL/RU-интерфейса, не меняя значение Mollie."""
    try:
        return f"€{float(value):.2f}".replace(".", ",")
    except (TypeError, ValueError):
        return f"€{value}"


def _clean_text(value: str) -> str:
    return " ".join(value.split())


def _valid_name(value: str) -> bool:
    return 2 <= len(value) <= 80 and len(re.findall(r"[A-Za-zА-Яа-яЁё0-9]", value)) >= 2


def _valid_description(value: str) -> bool:
    words = re.findall(r"[A-Za-zА-Яа-яЁё0-9]+", value)
    letters = re.findall(r"[A-Za-zА-Яа-яЁё]", value)
    return 20 <= len(value) <= 500 and len(words) >= 3 and len(letters) >= 12


def _valid_contact(value: str) -> bool:
    """Принимает телефон, Telegram, e-mail или ссылку, но не случайный текст."""
    if not 5 <= len(value) <= 300:
        return False
    has_phone = len(re.sub(r"\D", "", value)) >= 7
    has_username = bool(re.search(r"(?<!\w)@[A-Za-z0-9_]{5,32}\b", value))
    has_email = any(_EMAIL_RE.fullmatch(part.strip(" ,;()<>")) for part in value.split())
    has_url = bool(re.search(
        r"(?:https?://|www\.)\S+|\b[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+\b",
        value,
        re.IGNORECASE,
    ))
    return has_phone or has_username or has_email or has_url


def _valid_email(value: str) -> bool:
    return len(value) <= 200 and bool(_EMAIL_RE.fullmatch(value))


_CONTACT_FIELDS = {
    "instagram": ("sp_contact_instagram", "Instagram", "📷"),
    "telegram": ("sp_contact_telegram", "Telegram", "✈️"),
    "email": ("sp_contact_email", "Почта", "✉️"),
    "website": ("sp_contact_website", "Сайт", "🌐"),
    "phone": ("sp_contact_phone", "Телефон", "📞"),
}


def _normalize_public_contact(kind: str, value: str) -> str | None:
    """Проверяет один явно выбранный контакт и возвращает каноничное значение."""
    value = _clean_text(value).strip(" ,;")
    if kind == "instagram":
        match = re.fullmatch(
            r"(?:https?://)?(?:www\.)?instagram\.com/([A-Za-z0-9._]{1,30})/?(?:\?.*)?",
            value,
            re.IGNORECASE,
        )
        handle = match.group(1) if match else value.lstrip("@")
        if not re.fullmatch(r"[A-Za-z0-9._]{1,30}", handle):
            return None
        return f"@{handle}"
    if kind == "telegram":
        match = re.fullmatch(
            r"(?:https?://)?(?:www\.)?t\.me/([A-Za-z][A-Za-z0-9_]{4,31})/?(?:\?.*)?",
            value,
            re.IGNORECASE,
        )
        handle = match.group(1) if match else value.lstrip("@")
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{4,31}", handle):
            return None
        return f"@{handle}"
    if kind == "email":
        value = value.lower()
        return value if _valid_email(value) else None
    if kind == "website":
        if not re.match(r"^https?://", value, re.IGNORECASE):
            value = "https://" + value.removeprefix("www.")
        try:
            parsed = urlsplit(value)
        except ValueError:
            return None
        host = parsed.hostname or ""
        if parsed.scheme not in ("http", "https") or "." not in host or " " in value:
            return None
        return urlunsplit((parsed.scheme.lower(), parsed.netloc, parsed.path or "", parsed.query, ""))
    if kind == "phone":
        digits = re.sub(r"\D", "", value)
        if digits.startswith("00"):
            digits = digits[2:]
        elif value.startswith("0") and not value.startswith("00"):
            digits = "31" + digits[1:]
        if not 8 <= len(digits) <= 15:
            return None
        return f"+{digits}"
    return None


def _build_public_contacts(data: dict) -> str:
    """Собирает совместимую со старыми карточками строку из отдельных полей."""
    labels = {
        "instagram": "Instagram",
        "telegram": "Telegram",
        "email": "E-mail",
        "website": "Сайт",
        "phone": "Телефон",
    }
    parts = []
    for kind, (field, _title, _icon) in _CONTACT_FIELDS.items():
        value = data.get(field)
        if value:
            parts.append(f"{labels[kind]}: {value}")
    return " · ".join(parts)


def _public_contact_lines(data: dict) -> list[str]:
    lines = []
    for _kind, (field, title, icon) in _CONTACT_FIELDS.items():
        if data.get(field):
            lines.append(f"{icon} <b>{title}:</b> {html.escape(data[field])}")
    return lines


def _contact_hub_kb(data: dict) -> InlineKeyboardMarkup:
    buttons = []
    for kind, (field, title, icon) in _CONTACT_FIELDS.items():
        marker = "✅" if data.get(field) else icon
        buttons.append(InlineKeyboardButton(
            text=f"{marker} {title}", callback_data=f"selfcontact:add:{kind}"
        ))
    rows = [buttons[:2], buttons[2:4], buttons[4:]]
    if _build_public_contacts(data):
        rows.append([InlineKeyboardButton(
            text="Продолжить →", callback_data="selfcontact:done"
        )])
    rows.append([InlineKeyboardButton(
        text="⬅️ Назад", callback_data=_back_for(data, "description")
    )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _contact_input_kb(kind: str, *, has_value: bool) -> InlineKeyboardMarkup:
    rows = []
    if has_value:
        rows.append([InlineKeyboardButton(
            text="🗑 Удалить этот контакт", callback_data=f"selfcontact:remove:{kind}"
        )])
    rows.append([InlineKeyboardButton(
        text="⬅️ К контактам", callback_data="selfcontact:hub"
    )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _category_groups_kb(back_callback: str = "selfnav:name") -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=title, callback_data=f"selfcatgroup:{index}")]
        for index, title in enumerate(THEMES)
    ]
    rows.append([InlineKeyboardButton(text="✍️ Моей категории нет", callback_data="selfcatcustom")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=back_callback)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _category_options_kb(group_index: int) -> InlineKeyboardMarkup:
    categories = list(THEMES.values())[group_index]
    rows = [
        [InlineKeyboardButton(text=category.capitalize(), callback_data=f"selfcat:{category}")]
        for category in categories
    ]
    rows.append([InlineKeyboardButton(text="⬅️ К разделам", callback_data="selfcatgroups")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _nav_kb(back_callback: str, *, online: bool = False) -> InlineKeyboardMarkup:
    rows = []
    if online:
        rows.append([InlineKeyboardButton(
            text="🌍 Онлайн / по всей стране", callback_data="selfloc:online"
        )])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=back_callback)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _form_review_kb(has_plan: bool = False) -> InlineKeyboardMarkup:
    primary_text = "✅ Сохранить и вернуться к заказу" if has_plan else "✅ Всё верно — выбрать тариф"
    primary_callback = "selfreview:confirm" if has_plan else "selfreview:plans"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=primary_text, callback_data=primary_callback)],
        [InlineKeyboardButton(text="✏️ Изменить данные", callback_data="selfreview:edit")],
    ])


def _edit_fields_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Имя / название", callback_data="selfedit:name"),
            InlineKeyboardButton(text="Категория", callback_data="selfedit:category"),
        ],
        [
            InlineKeyboardButton(text="Город / онлайн", callback_data="selfedit:location"),
            InlineKeyboardButton(text="Описание", callback_data="selfedit:description"),
        ],
        [
            InlineKeyboardButton(text="Контакты", callback_data="selfedit:contact"),
            InlineKeyboardButton(text="E-mail для factuur", callback_data="selfedit:email"),
        ],
        [InlineKeyboardButton(text="⬅️ К анкете", callback_data="selfedit:back")],
    ])


def _tier_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Стандарт", callback_data="selftier:standard")],
        [InlineKeyboardButton(text="🌟 Премиум", callback_data="selftier:premium")],
        [InlineKeyboardButton(text="⬅️ К анкете", callback_data="selftier:back")],
    ])


def _saving_suffix(plan: str) -> str:
    comparisons = {
        "year": (config.LISTING_PRICE_MONTH, 12),
        "6m_premium": (config.LISTING_PRICE_MONTH_PREMIUM, 6),
        "year_premium": (config.LISTING_PRICE_MONTH_PREMIUM, 12),
    }
    if plan not in comparisons:
        return ""
    monthly, months = comparisons[plan]
    try:
        saving = float(monthly) * months - float(config.plan_info(plan)["price"])
    except (TypeError, ValueError):
        return ""
    return f" · экономия {_format_euro(f'{saving:.2f}')}" if saving > 0 else ""


def _plan_duration_kb(tier: str, *, referral: bool = False) -> InlineKeyboardMarkup:
    plans = ("month", "year") if tier == "standard" else (
        "month_premium", "6m_premium", "year_premium"
    )
    labels = {
        "month": "1 месяц",
        "year": "12 месяцев",
        "month_premium": "1 месяц",
        "6m_premium": "6 месяцев",
        "year_premium": "12 месяцев",
    }
    rows = []
    for plan in plans:
        price = config.plan_info(plan)["price"]
        if referral and plan in ("year", "year_premium"):
            price = config.discounted_price(price)
            suffix = " · ваша скидка 20%"
        else:
            suffix = _saving_suffix(plan)
        rows.append([InlineKeyboardButton(
            text=f"{labels[plan]} — {_format_euro(price)}{suffix}",
            callback_data=f"selfplan:{plan}",
        )])
    rows.append([InlineKeyboardButton(text="⬅️ Сравнить тарифы", callback_data="selfplanback")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Создать ссылку на оплату", callback_data="selfconfirm:pay")],
        [InlineKeyboardButton(text="↔️ Изменить тариф", callback_data="selfconfirm:plan")],
        [InlineKeyboardButton(text="✏️ Изменить анкету", callback_data="selfconfirm:edit")],
    ])


def _preview_text(data: dict) -> str:
    where = "Онлайн / по всей стране" if data.get("sp_online") else data.get("sp_city", "—")
    contacts = "\n".join(_public_contact_lines(data)) or html.escape(
        data.get("sp_contact") or "—"
    )
    return (
        "<b>Проверьте будущую карточку</b>\n\n"
        f"<b>Имя / название:</b> {html.escape(data.get('sp_name', '—'))}\n"
        f"<b>Категория:</b> {html.escape(data.get('sp_category', '—'))}\n"
        f"<b>Где работаете:</b> {html.escape(where)}\n"
        f"<b>Описание:</b> {html.escape(data.get('sp_description') or '—')}\n"
        f"<b>Контакты:</b>\n{contacts}\n\n"
        f"<b>E-mail для factuur:</b> {html.escape(data.get('sp_email', '—'))}\n"
        "<i>E-mail нужен только для счёта и не публикуется в карточке, если вы "
        "не указали его отдельно в контактах.</i>"
    )


def _plan_title(plan: str) -> str:
    titles = {
        "month": "Стандарт · 1 месяц",
        "year": "Стандарт · 12 месяцев",
        "month_premium": "Премиум · 1 месяц",
        "6m_premium": "Премиум · 6 месяцев",
        "year_premium": "Премиум · 12 месяцев",
    }
    return titles[plan]


def _actual_plan_amount(plan: str, *, referral: bool) -> str:
    price = config.plan_info(plan)["price"]
    return config.discounted_price(price) if referral and plan in ("year", "year_premium") else price


def _where(sp: Specialist) -> str:
    if sp.is_online:
        return "онлайн"
    return sp.city or sp.province or "—"


def _card_text(sp: Specialist) -> str:
    lines = [f"<b>{html.escape(sp.name)}</b> — {html.escape(sp.category)}, {html.escape(_where(sp))}"]
    if sp.description:
        lines.append(html.escape(sp.description))
    if sp.contact:
        lines.append(f"📞 {html.escape(sp.contact)}")
    return "\n".join(lines)


def _review_kb(spec_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Опубликовать", callback_data=f"specok:{spec_id}"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"specno:{spec_id}"),
            ]
        ]
    )


def _pay_kb(checkout_url: str, plan: str, amount: str | None = None) -> InlineKeyboardMarkup:
    price = amount or config.plan_info(plan)["price"]
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(
            text=f"💳 Оплатить {_format_euro(price)}", url=checkout_url)]]
    )


# --- Анкета ------------------------------------------------------------------

async def _has_referral(uid: int) -> bool:
    async with get_session() as session:
        ref_meta = await session.get(Meta, f"spref:{uid}")
        return bool(ref_meta and ref_meta.value.isdigit())


async def _return_or_continue(message: Message, state: FSMContext, field: str,
                              next_prompt) -> None:
    data = await state.get_data()
    if data.get("sp_editing") == field:
        await state.update_data(sp_editing=None)
        await _show_review(message, state)
        return
    await next_prompt(message, state)


def _back_for(data: dict, normal_target: str) -> str:
    return "selfedit:back" if data.get("sp_editing") else f"selfnav:{normal_target}"


async def _ask_name(message: Message, state: FSMContext) -> None:
    await state.set_state(SelfAddSpecialist.name)
    await message.answer(
        "<b>1/6 · Имя или название</b>\n\n"
        "Как указать вас в гайде? Напишите имя, название бренда или компании.",
        reply_markup=cancel_menu(),
    )


async def _ask_category(message: Message, state: FSMContext) -> None:
    await state.set_state(SelfAddSpecialist.category)
    await state.update_data(sp_custom_category_mode=False)
    data = await state.get_data()
    await message.answer(
        "<b>2/6 · Категория</b>\n\n"
        "Выберите раздел, а затем свою специализацию. Если подходящего варианта нет, "
        "можно указать собственную категорию.",
        reply_markup=_category_groups_kb(_back_for(data, "name")),
    )


async def _ask_location(message: Message, state: FSMContext) -> None:
    await state.set_state(SelfAddSpecialist.location)
    data = await state.get_data()
    await message.answer(
        "<b>3/6 · Где вы работаете?</b>\n\n"
        "Напишите один основной город, например <b>Amsterdam</b>. Если принимаете "
        "клиентов по всей стране или работаете удалённо, нажмите кнопку ниже.\n\n"
        "<i>Другие города можно указать в описании.</i>",
        reply_markup=_nav_kb(_back_for(data, "category"), online=True),
    )


async def _ask_description(message: Message, state: FSMContext) -> None:
    await state.set_state(SelfAddSpecialist.description)
    data = await state.get_data()
    await message.answer(
        "<b>4/6 · Что вы предлагаете?</b>\n\n"
        "Коротко опишите основные услуги, формат работы и важные детали. От 20 до "
        "500 символов.\n\n"
        "<i>Например: Маникюр, педикюр и наращивание. Принимаю в домашней студии, "
        "работаю по записи.</i>",
        reply_markup=_nav_kb(_back_for(data, "location")),
    )


async def _ask_contact(message: Message, state: FSMContext) -> None:
    await state.set_state(SelfAddSpecialist.contact)
    await state.update_data(sp_contact_field=None)
    data = await state.get_data()
    filled = _public_contact_lines(data)
    current = "\n".join(filled) if filled else "Пока ничего не добавлено."
    await message.answer(
        "<b>5/6 · Контакты для клиентов</b>\n\n"
        "Выберите, какие кнопки показать в вашей карточке. Каждый контакт заполняется "
        "по желанию, но для публикации нужен хотя бы один.\n\n"
        f"{current}",
        reply_markup=_contact_hub_kb(data),
    )


async def _ask_email(message: Message, state: FSMContext) -> None:
    await state.set_state(SelfAddSpecialist.email)
    data = await state.get_data()
    await message.answer(
        "<b>6/6 · E-mail для счёта</b>\n\n"
        "После успешной оплаты мы автоматически отправим factuur на этот адрес. "
        "В самой карточке он не появится.\n\n"
        "<i>Например: mail@example.com</i>",
        reply_markup=_nav_kb(_back_for(data, "contact")),
    )


async def _show_review(message: Message, state: FSMContext) -> None:
    await state.set_state(SelfAddSpecialist.review)
    data = await state.get_data()
    await message.answer(
        _preview_text(data),
        reply_markup=_form_review_kb(has_plan=data.get("sp_plan") in SELFADD_PLANS),
    )


async def _save_category(message: Message, state: FSMContext, category: str,
                         *, custom: bool = False) -> None:
    await state.update_data(
        sp_category=category,
        sp_custom_category=custom,
        sp_custom_category_mode=False,
    )
    await _return_or_continue(message, state, "category", _ask_location)


async def _save_location(message: Message, state: FSMContext, *, online: bool,
                         city: str = "", province: str = "") -> None:
    await state.update_data(
        sp_online=online,
        sp_city=city,
        sp_province=province,
        sp_pending_city=None,
    )
    await _return_or_continue(message, state, "location", _ask_description)

@router.message(Command("selfadd", "addme"))
@router.message(F.text == BTN_SELF_ADD)
async def self_start(message: Message, state: FSMContext) -> None:
    if not config.payments_enabled():
        await message.answer(
            "Само-добавление пока недоступно — скоро включим 🙌", reply_markup=main_menu()
        )
        return
    await state.clear()
    referral = await _has_referral(message.from_user.id)
    await state.update_data(sp_referral=referral)
    await message.answer(
        "<b>Добавление в Контакт-гайд Podslushano.nl</b>\n\n"
        "Заполнение займёт около 3 минут. Перед оплатой вы увидите будущую карточку, "
        "сможете изменить данные и сравнить тарифы.\n\n"
        "После оплаты мы проверим анкету и сообщим, когда карточка появится в поиске. "
        "Factuur придёт на e-mail автоматически.\n\n"
        f"Размещение — от <b>{_format_euro(config.LISTING_PRICE_MONTH)} в месяц</b>. "
        "Оплата разовая, без автоматического продления."
    )
    await _ask_name(message, state)


@router.message(SelfAddSpecialist.name)
async def self_name(message: Message, state: FSMContext) -> None:
    name = _clean_text(message.text or "")
    if not _valid_name(name):
        await message.answer(
            "Не получилось распознать имя или название. Напишите от 2 до 80 символов, "
            "например: <b>Anna Nails</b> или <b>Studio Noord</b>."
        )
        return
    await state.update_data(sp_name=name)
    await _return_or_continue(message, state, "name", _ask_category)


@router.callback_query(SelfAddSpecialist.category, F.data.startswith("selfcatgroup:"))
async def self_category_group(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        group_index = int(callback.data.split(":", 1)[1])
        title = list(THEMES)[group_index]
    except (ValueError, IndexError):
        await callback.answer("Раздел не найден", show_alert=True)
        return
    await callback.message.edit_text(
        f"<b>{html.escape(title)}</b>\n\nВыберите специализацию:",
        reply_markup=_category_options_kb(group_index),
    )
    await callback.answer()


@router.callback_query(SelfAddSpecialist.category, F.data == "selfcatgroups")
async def self_category_groups(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await callback.message.edit_text(
        "<b>2/6 · Категория</b>\n\nВыберите раздел:",
        reply_markup=_category_groups_kb(_back_for(data, "name")),
    )
    await callback.answer()


@router.callback_query(SelfAddSpecialist.category, F.data.startswith("selfcat:"))
async def self_category_button(callback: CallbackQuery, state: FSMContext) -> None:
    category = callback.data.split(":", 1)[1]
    if category not in CATEGORIES:
        await callback.answer("Категория не найдена", show_alert=True)
        return
    await callback.answer()
    await _save_category(callback.message, state, category)


@router.callback_query(SelfAddSpecialist.category, F.data == "selfcatcustom")
async def self_category_custom(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(sp_custom_category_mode=True)
    await callback.message.answer(
        "Напишите свою категорию коротко и понятно — так, как её будут искать клиенты.\n\n"
        "<i>Например: страховой консультант</i>"
    )
    await callback.answer()


@router.message(SelfAddSpecialist.category)
async def self_category(message: Message, state: FSMContext) -> None:
    text = _clean_text(message.text or "")
    data = await state.get_data()
    custom_mode = bool(data.get("sp_custom_category_mode"))
    if not text:
        await message.answer("Напишите категорию текстом или выберите её кнопками.")
        return
    cat = detect_category(text) or next((c for c in CATEGORIES if c.lower() == text.lower()), None)
    if not cat and not custom_mode:
        try:
            extracted = await extract_specialist_query(
                text, list(CATEGORIES.keys()), list(NEIGHBORS.keys())
            )
        except Exception:  # noqa: BLE001
            extracted = {}
        ai_cat = extracted.get("category")
        if ai_cat and ai_cat in CATEGORIES:
            cat = ai_cat
    if cat:
        await _save_category(message, state, cat)
        return
    if not custom_mode:
        await message.answer(
            "Не удалось определить категорию. Выберите её кнопками или нажмите "
            "«Моей категории нет», чтобы добавить свой вариант.",
            reply_markup=_category_groups_kb(_back_for(data, "name")),
        )
        return
    if not 3 <= len(text) <= 50 or len(re.findall(r"[A-Za-zА-Яа-яЁё]", text)) < 3:
        await message.answer(
            "Категория должна быть коротким понятным названием от 3 до 50 символов. "
            "Например: <b>страховой консультант</b>."
        )
        return
    await _save_category(message, state, text.lower(), custom=True)


@router.message(SelfAddSpecialist.location)
async def self_location(message: Message, state: FSMContext) -> None:
    loc = _clean_text(message.text or "")
    if not loc:
        await message.answer("Напишите город или нажмите «Онлайн / по всей стране».")
        return
    if loc.lower() in ONLINE_WORDS:
        await _save_location(message, state, online=True)
        return
    known = detect_city(loc)
    if known:
        await _save_location(message, state, online=False, city=known[0], province=known[1])
        return
    if not 2 <= len(loc) <= 80 or len(re.findall(r"[A-Za-zА-Яа-яЁё]", loc)) < 2:
        await message.answer("Не получилось распознать город. Проверьте написание и попробуйте ещё раз.")
        return
    await state.update_data(sp_pending_city=loc)
    await message.answer(
        f"Города <b>{html.escape(loc)}</b> пока нет в нашем списке. Если название "
        "написано верно, его можно сохранить — мы проверим перед публикацией.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Сохранить этот город", callback_data="selfloc:confirm")],
            [InlineKeyboardButton(text="✏️ Ввести другой", callback_data="selfloc:retry")],
        ]),
    )


@router.callback_query(SelfAddSpecialist.location, F.data.startswith("selfloc:"))
async def self_location_button(callback: CallbackQuery, state: FSMContext) -> None:
    action = callback.data.split(":", 1)[1]
    data = await state.get_data()
    await callback.answer()
    if action == "online":
        await _save_location(callback.message, state, online=True)
    elif action == "confirm" and data.get("sp_pending_city"):
        await _save_location(
            callback.message, state, online=False, city=data["sp_pending_city"]
        )
    elif action == "retry":
        await state.update_data(sp_pending_city=None)
        await _ask_location(callback.message, state)


@router.message(SelfAddSpecialist.description)
async def self_description(message: Message, state: FSMContext) -> None:
    desc = _clean_text(message.text or "")
    if not _valid_description(desc):
        await message.answer(
            "Описание получилось слишком коротким или непонятным. Напишите 2–4 коротких "
            "предложения об услугах — от 20 до 500 символов."
        )
        return
    await state.update_data(sp_description=desc)
    await _return_or_continue(message, state, "description", _ask_contact)


@router.message(SelfAddSpecialist.contact)
async def self_contact(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    kind = data.get("sp_contact_field")
    if kind not in _CONTACT_FIELDS:
        await message.answer(
            "Сначала выберите кнопкой, какой контакт хотите добавить.",
            reply_markup=_contact_hub_kb(data),
        )
        return
    value = _normalize_public_contact(kind, message.text or "")
    if not value:
        examples = {
            "instagram": "<b>@username</b> или ссылку instagram.com/username",
            "telegram": "<b>@username</b> или ссылку t.me/username",
            "email": "<b>mail@example.com</b>",
            "website": "<b>example.nl</b> или полную ссылку",
            "phone": "номер с кодом страны, например <b>+31 6 12345678</b>",
        }
        await message.answer(f"Проверьте значение и отправьте {examples[kind]}.")
        return
    field = _CONTACT_FIELDS[kind][0]
    await state.update_data(**{field: value, "sp_contact_field": None})
    updated = await state.get_data()
    await state.update_data(sp_contact=_build_public_contacts(updated))
    await message.answer("Контакт сохранён ✅")
    await _ask_contact(message, state)


@router.callback_query(SelfAddSpecialist.contact, F.data.startswith("selfcontact:"))
async def self_contact_action(callback: CallbackQuery, state: FSMContext) -> None:
    parts = callback.data.split(":")
    action = parts[1] if len(parts) > 1 else ""
    kind = parts[2] if len(parts) > 2 else ""
    data = await state.get_data()
    await callback.answer()
    if action == "hub":
        await _ask_contact(callback.message, state)
        return
    if action == "done":
        contact = _build_public_contacts(data)
        if not contact:
            await callback.message.answer("Добавьте хотя бы один контакт для публикации карточки.")
            return
        await state.update_data(sp_contact=contact, sp_contact_field=None)
        await _return_or_continue(callback.message, state, "contact", _ask_email)
        return
    if kind not in _CONTACT_FIELDS:
        return
    field, title, _icon = _CONTACT_FIELDS[kind]
    if action == "remove":
        await state.update_data(**{field: None, "sp_contact_field": None})
        updated = await state.get_data()
        await state.update_data(sp_contact=_build_public_contacts(updated))
        await _ask_contact(callback.message, state)
        return
    if action != "add":
        return
    examples = {
        "instagram": "@username или https://instagram.com/username",
        "telegram": "@username или https://t.me/username",
        "email": "mail@example.com",
        "website": "example.nl или https://example.nl",
        "phone": "+31 6 12345678",
    }
    await state.update_data(sp_contact_field=kind)
    await callback.message.answer(
        f"<b>{html.escape(title)}</b>\n\nОтправьте {examples[kind]}. Бот проверит "
        "значение и подготовит рабочую кнопку.",
        reply_markup=_contact_input_kb(kind, has_value=bool(data.get(field))),
    )


@router.message(SelfAddSpecialist.email)
async def self_email(message: Message, state: FSMContext) -> None:
    email = _clean_text(message.text or "").lower()
    if not _valid_email(email):
        await message.answer("Проверьте e-mail и отправьте его в формате <b>mail@example.com</b>.")
        return
    await state.update_data(sp_email=email)
    await _return_or_continue(message, state, "email", _show_review)


@router.callback_query(SelfAddSpecialist.review, F.data.startswith("selfreview:"))
async def self_review_action(callback: CallbackQuery, state: FSMContext) -> None:
    action = callback.data.split(":", 1)[1]
    await callback.answer()
    if action == "edit":
        await callback.message.answer("Что нужно изменить?", reply_markup=_edit_fields_kb())
    elif action == "plans":
        await state.set_state(SelfAddSpecialist.plan)
        await _show_tiers(callback.message, state)
    elif action == "confirm":
        await _show_order_confirmation(callback.message, state)


@router.callback_query(F.data.startswith("selfedit:"))
async def self_edit_field(callback: CallbackQuery, state: FSMContext) -> None:
    field = callback.data.split(":", 1)[1]
    await callback.answer()
    if field == "back":
        await state.update_data(sp_editing=None)
        await _show_review(callback.message, state)
        return
    prompts = {
        "name": _ask_name,
        "category": _ask_category,
        "location": _ask_location,
        "description": _ask_description,
        "contact": _ask_contact,
        "email": _ask_email,
    }
    prompt = prompts.get(field)
    if not prompt:
        return
    await state.update_data(sp_editing=field)
    await prompt(callback.message, state)


@router.callback_query(F.data.startswith("selfnav:"))
async def self_navigate_back(callback: CallbackQuery, state: FSMContext) -> None:
    target = callback.data.split(":", 1)[1]
    prompts = {
        "name": _ask_name,
        "category": _ask_category,
        "location": _ask_location,
        "description": _ask_description,
        "contact": _ask_contact,
    }
    prompt = prompts.get(target)
    await callback.answer()
    if prompt:
        await prompt(callback.message, state)


async def _show_tiers(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    referral_note = (
        "\n\n🎁 По приглашению у вас действует скидка <b>20% на годовое размещение</b>."
        if data.get("sp_referral") else ""
    )
    await message.answer(
        "<b>Выберите формат размещения</b>\n\n"
        "<b>Стандарт</b>\n"
        "— имя, категория, город, описание и контакты\n"
        "— обычная позиция в результатах поиска\n"
        "— без фото\n\n"
        "🌟 <b>Премиум</b>\n"
        "— всё из Стандарта\n"
        "— фото или логотип\n"
        "— бейдж 🌟 и позиция выше стандартных карточек\n\n"
        "Оба формата проходят одинаковую проверку перед публикацией."
        f"{referral_note}",
        reply_markup=_tier_kb(),
    )


@router.callback_query(SelfAddSpecialist.plan, F.data.startswith("selftier:"))
async def self_tier(callback: CallbackQuery, state: FSMContext) -> None:
    tier = callback.data.split(":", 1)[1]
    await callback.answer()
    if tier == "back":
        await _show_review(callback.message, state)
        return
    if tier not in ("standard", "premium"):
        return
    data = await state.get_data()
    title = "Стандарт" if tier == "standard" else "🌟 Премиум"
    await callback.message.answer(
        f"<b>{title}: выберите срок размещения</b>\n\n"
        "Чем дольше срок, тем ниже стоимость одного месяца.",
        reply_markup=_plan_duration_kb(tier, referral=bool(data.get("sp_referral"))),
    )


@router.callback_query(SelfAddSpecialist.plan, F.data == "selfplanback")
async def self_plan_back(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await _show_tiers(callback.message, state)


@router.callback_query(SelfAddSpecialist.plan, F.data.startswith("selfplan:"))
async def self_plan(callback: CallbackQuery, state: FSMContext) -> None:
    plan = callback.data.split(":", 1)[1]
    if plan not in SELFADD_PLANS:
        await callback.answer("Тариф не найден", show_alert=True)
        return
    await state.update_data(sp_plan=plan)
    if config.plan_info(plan)["premium"]:
        await state.set_state(SelfAddSpecialist.photo)
        await callback.message.answer(
            "<b>Фото для Премиум-карточки</b>\n\n"
            "Пришлите одним сообщением фото или логотип, который увидят клиенты. "
            "Лучше использовать квадратное изображение хорошего качества.\n\n"
            "Можно продолжить без фото и добавить его позднее.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Продолжить без фото", callback_data="selfphoto:skip")],
                [InlineKeyboardButton(text="⬅️ Изменить тариф", callback_data="selfphoto:back")],
            ]),
        )
        await callback.answer()
        return
    await state.update_data(sp_photo_id=None)
    await _show_order_confirmation(callback.message, state)
    await callback.answer()


@router.message(SelfAddSpecialist.photo)
async def self_photo(message: Message, state: FSMContext) -> None:
    if message.photo:
        photo_id = message.photo[-1].file_id
    elif message.text and message.text.strip().lower() in ("-", "пропустить", "skip", "нет"):
        photo_id = None
    else:
        await message.answer("Пришлите изображение как фото или нажмите «Продолжить без фото».")
        return
    await state.update_data(sp_photo_id=photo_id)
    await _show_order_confirmation(message, state)


@router.callback_query(SelfAddSpecialist.photo, F.data.startswith("selfphoto:"))
async def self_photo_action(callback: CallbackQuery, state: FSMContext) -> None:
    action = callback.data.split(":", 1)[1]
    await callback.answer()
    if action == "skip":
        await state.update_data(sp_photo_id=None)
        await _show_order_confirmation(callback.message, state)
    elif action == "back":
        await state.set_state(SelfAddSpecialist.plan)
        await _show_tiers(callback.message, state)


async def _show_order_confirmation(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    plan = data.get("sp_plan")
    if plan not in SELFADD_PLANS:
        await state.set_state(SelfAddSpecialist.plan)
        await _show_tiers(message, state)
        return
    amount = _actual_plan_amount(plan, referral=bool(data.get("sp_referral")))
    photo_note = "\n<b>Фото:</b> добавлено" if data.get("sp_photo_id") else ""
    await state.set_state(SelfAddSpecialist.confirm)
    await message.answer(
        "<b>Заказ готов</b>\n\n"
        f"<b>Тариф:</b> {_plan_title(plan)}\n"
        f"<b>К оплате:</b> {_format_euro(amount)}\n"
        f"<b>Срок:</b> {config.plan_info(plan)['days']} дней"
        f"{photo_note}\n\n"
        "После оплаты:\n"
        f"1. Factuur придёт на <b>{html.escape(data.get('sp_email', ''))}</b>.\n"
        "2. Мы проверим данные и оформление карточки.\n"
        "3. Бот сообщит о публикации или необходимых исправлениях.\n\n"
        "Оплата разовая. Автоматического списания и продления нет.",
        reply_markup=_confirm_kb(),
    )


@router.callback_query(SelfAddSpecialist.confirm, F.data.startswith("selfconfirm:"))
async def self_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    action = callback.data.split(":", 1)[1]
    await callback.answer()
    if action == "plan":
        await state.set_state(SelfAddSpecialist.plan)
        await _show_tiers(callback.message, state)
    elif action == "edit":
        await _show_review(callback.message, state)
    elif action == "pay":
        data = await state.get_data()
        plan = data.get("sp_plan")
        if plan not in SELFADD_PLANS:
            await state.set_state(SelfAddSpecialist.plan)
            await _show_tiers(callback.message, state)
            return
        await callback.message.answer("Создаём безопасную ссылку на оплату…")
        await _create_listing_and_pay(
            callback.message,
            state,
            plan,
            data.get("sp_photo_id"),
            callback.from_user.id,
        )


async def _create_listing_and_pay(message, state: FSMContext, plan: str,
                                  photo_file_id: str | None, uid: int) -> None:
    """Создаёт карточку (awaiting_payment) и присылает ссылку на оплату."""
    info = config.plan_info(plan)
    data = await state.get_data()
    async with get_session() as session:
        # Пришёл ли пользователь по реф-ссылке специалиста (?start=spref_<id>)
        ref_meta = await session.get(Meta, f"spref:{uid}")
        ref_sid = int(ref_meta.value) if ref_meta and ref_meta.value.isdigit() else None
        existing_id = data.get("sp_listing_id")
        sp = await session.get(Specialist, existing_id) if existing_id else None
        if sp is None or sp.submitter_user_id != uid or sp.status != "awaiting_payment":
            sp = Specialist(status="awaiting_payment", source="self", submitter_user_id=uid)
            session.add(sp)
        sp.name = data["sp_name"]
        sp.category = data["sp_category"]
        sp.city = data.get("sp_city", "")
        sp.province = data.get("sp_province", "")
        sp.description = data.get("sp_description")
        sp.contact = _build_public_contacts(data) or data.get("sp_contact", "")
        sp.is_online = data.get("sp_online", False)
        sp.is_premium = info["premium"]
        sp.photo_file_id = photo_file_id
        sp.invoice_email = data.get("sp_email")
        sp.plan = plan
        sp.referred_by_specialist_id = ref_sid
        await session.commit()
        await session.refresh(sp)
        sid, name = sp.id, sp.name
    await state.update_data(sp_listing_id=sid)

    # Скидка -20% приглашённому на ГОДОВОЕ размещение (Стандарт/Премиум)
    referral_year = bool(ref_sid) and plan in ("year", "year_premium")
    amount = config.discounted_price(info["price"]) if referral_year else info["price"]

    payment = await create_payment(
        f"{DESC_NEW}: {name}",
        {"specialist_id": sid, "kind": "new", "plan": plan},
        amount,
    )
    if not payment or not payment.get("checkout_url"):
        await state.set_state(SelfAddSpecialist.confirm)
        await message.answer(
            "Ссылку на оплату сейчас создать не удалось. Данные анкеты сохранены — "
            "попробуйте ещё раз через минуту.",
            reply_markup=_confirm_kb(),
        )
        return
    async with get_session() as session:
        sp = await session.get(Specialist, sid)
        if sp:
            sp.payment_id = payment["id"]
            await session.commit()
    await state.clear()
    # Возвращаем обычное меню (убираем клавиатуру «Отмена» из анкеты)
    tariff = (
        f"<b>{_plan_title(plan)}</b> · <s>{_format_euro(info['price'])}</s> → "
        f"<b>{_format_euro(amount)}</b> (скидка 20% по приглашению)"
        if referral_year else f"<b>{_plan_title(plan)}</b> · <b>{_format_euro(amount)}</b>"
    )
    await message.answer(
        f"<b>Ссылка на оплату готова</b>\n\nТариф: {tariff}.\n\n"
        "После успешной оплаты factuur придёт на указанный e-mail, а анкета отправится "
        "нам на проверку. Бот сообщит, когда карточка будет опубликована.\n\n"
        f'Оплачивая, вы соглашаетесь с <a href="{config.terms_url()}">Условиями</a> '
        f'и <a href="{config.privacy_url()}">Политикой конфиденциальности</a>.',
        reply_markup=main_menu(),
        disable_web_page_preview=True,
    )
    await message.answer(
        "Нажмите кнопку, чтобы перейти к оплате:",
        reply_markup=_pay_kb(payment["checkout_url"], plan, amount),
    )


# --- Подтверждение оплаты (вызывается из webhook) ---------------------------

async def on_payment_paid(bot, payment_id: str) -> None:
    """Обрабатывает оплаченный платёж: публикация на проверку или продление."""
    payment = await get_payment(payment_id)
    if not payment:
        return
    status = payment.get("status")
    meta = payment.get("metadata") or {}
    kind = meta.get("kind", "new")
    # Платёж за мероприятие афиши — отдельный обработчик (своя таблица)
    if kind == "afisha":
        from handlers.afisha import on_afisha_payment_paid
        await on_afisha_payment_paid(bot, payment_id, payment)
        return
    # Платёж за рекламный слот с сайта (бронь даты) — отдельный обработчик
    if kind == "ad":
        from handlers.ads import on_ad_payment_paid
        await on_ad_payment_paid(bot, payment_id, payment)
        return
    # Платёж за «поднятие» объявления на доске — отдельный обработчик
    if kind == "bump":
        from handlers.board import on_bump_paid
        await on_bump_paid(bot, payment_id, payment)
        return
    # Платёж за прогулку Allo Walks — отдельный обработчик (своя таблица)
    if kind == "allo":
        from handlers.allo import on_allo_payment_paid
        await on_allo_payment_paid(bot, payment_id, payment)
        return
    # Платёж за платное размещение объявления (жильё) — отдельный обработчик
    if kind == "listing":
        from handlers.board import on_listing_paid
        await on_listing_paid(bot, payment_id, payment)
        return
    sid = meta.get("specialist_id")
    if not sid:
        return

    # Неуспешная оплата — мягко сообщаем и предлагаем повторить
    if status in ("failed", "canceled", "expired"):
        await _on_payment_failed(bot, int(sid), payment_id, kind, status)
        return
    if status != "paid":
        return  # open/pending — ждём финального статуса

    async with get_session() as session:
        if await session.get(Meta, f"pay:{payment_id}"):
            return  # этот платёж уже обработан (webhook мог прийти повторно)
        sp = await session.get(Specialist, int(sid))
        if sp is None:
            return
        now = datetime.utcnow()
        plan = meta.get("plan", sp.plan or "year")
        info = config.plan_info(plan)
        days = info["days"]
        sp.is_premium = info["premium"]
        if kind in ("renew", "claim"):
            base = sp.paid_until if sp.paid_until and sp.paid_until > now else now
            sp.paid_until = base + timedelta(days=days)
            sp.renewal_reminded = False
            sp.status = "active"
            if kind == "claim":
                # Старая карточка из гайда оплачена — дальше ей управляет владелец
                sp.source = "self"
        else:
            sp.paid_until = now + timedelta(days=days)
            sp.status = "pending"  # оплачено, ждёт проверки админом
            sp.plan = plan
        session.add(Meta(key=f"pay:{payment_id}", value="done"))
        await session.commit()
        sub, name, card = sp.submitter_user_id, sp.name, _card_text(sp)
        sp_id = sp.id
        inv_email = sp.invoice_email
        referred_by = sp.referred_by_specialist_id
        new_cat = sp.category if sp.category not in CATEGORIES else None
    await log_event("payment", f"{kind}:{plan}")

    # Сумма для счёта — фактически оплаченная (учитывает реф-скидку), а не по тарифу
    paid_amount = (payment.get("amount") or {}).get("value") or info["price"]

    # Счёт (factuur) на e-mail
    if inv_email:
        desc = f"{DESC_NEW if kind != 'renew' else DESC_RENEW}: {name} ({info['title']})"
        ok = False
        try:
            from utils.invoices import send_invoice
            ok, _ = await send_invoice(inv_email, name, desc, paid_amount)
        except Exception as e:  # noqa: BLE001
            log.warning("Не удалось отправить счёт: %s", e)
        if ok:
            if sub:
                await _safe_send(bot, sub, f"🧾 Счёт отправлен на {inv_email}.")
        else:
            # Не молчим: счёт нужен, но не ушёл — зовём админа дослать вручную
            for admin_id in config.ADMIN_IDS:
                await _safe_send(
                    bot, admin_id,
                    f"⚠️ Счёт не отправлен «{name}» (e-mail: {inv_email}). "
                    f"Проверь Resend и дошли вручную: /invoice {sp_id}",
                )
    else:
        # Оплата прошла, но e-mail для счёта не задан (напр. карточка добавлена
        # админом). Сигналим, чтобы ни один платёж не остался без фактуры.
        for admin_id in config.ADMIN_IDS:
            await _safe_send(
                bot, admin_id,
                f"⚠️ Оплачено без e-mail для счёта: «{name}» (id {sp_id}). "
                f"Счёт НЕ отправлен. Дошли вручную: <code>/invoice {sp_id} EMAIL</code>",
            )

    if kind in ("renew", "claim"):
        if sub:
            if kind == "claim":
                await _safe_send(
                    bot, sub,
                    f"✅ Оплата получена! Карточка «{name}» остаётся в гайде. "
                    "Спасибо, что с нами с самого начала 🧡",
                )
            else:
                await _safe_send(bot, sub, f"✅ Оплата получена! Размещение «{name}» продлено. Спасибо 🙌")
        return

    cat_note = (
        f"\n\n🆕 Новая категория «{html.escape(new_cat)}» — её нет в списке. Если "
        f"нужна, заведи в utils/geo.py или поправь: <code>/setcategory {sp_id} категория</code>."
        if new_cat else ""
    )
    for admin_id in config.ADMIN_IDS:
        await _safe_send(
            bot, admin_id,
            "💳 <b>Оплачено само-добавление</b> — нужна проверка:\n\n" + card + cat_note,
            _review_kb(sp_id),
        )
    if sub:
        await _safe_send(
            bot, sub,
            "Оплата получена, спасибо! 🙌 Анкета отправлена на проверку. Бот сообщит, "
            "когда карточка будет опубликована или если понадобятся исправления.",
        )

    # Реферальная награда: пригласивший получает бонусный Премиум на 3 месяца
    if referred_by:
        await _reward_referrer(bot, int(referred_by), sp_id, sub)


async def _safe_send(bot, chat_id, text, reply_markup=None) -> None:
    try:
        await bot.send_message(chat_id, text, reply_markup=reply_markup)
    except Exception as e:  # noqa: BLE001
        log.warning("Не удалось отправить сообщение %s: %s", chat_id, e)


def renewal_reminder_text(sp: Specialist) -> str:
    """Точный текст автоматического напоминания за 7 дней."""
    return (
        f"⏳ Размещение «{html.escape(sp.name)}» в гайде заканчивается "
        f"{sp.paid_until:%d.%m.%Y}.\n"
        f"Продлить ({_price_str(sp.plan or 'year')})?"
    )


def expiry_notice_text(sp: Specialist) -> str:
    """Точный текст уведомления после скрытия просроченной карточки."""
    return (
        f"❌ Срок размещения «{html.escape(sp.name)}» в гайде истёк, "
        f"и карточка скрыта из поиска.\n"
        f"Чтобы вернуть её в поиск, продлите размещение ({_price_str(sp.plan or 'year')}) 👇"
    )


def _renewal_kb(sid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="🔁 Продлить", callback_data=f"specrenew:{sid}")
        ]]
    )


async def _reminder_attempt_allowed(sp: Specialist, kind: str) -> bool:
    """Не дублирует успешную доставку и повторяет ошибку не чаще раза в сутки."""
    async with get_session() as session:
        last = (
            await session.scalars(
                select(SpecialistReminderLog)
                .where(
                    SpecialistReminderLog.specialist_id == sp.id,
                    SpecialistReminderLog.kind == kind,
                    SpecialistReminderLog.paid_until == sp.paid_until,
                )
                .order_by(SpecialistReminderLog.created_at.desc(),
                          SpecialistReminderLog.id.desc())
                .limit(1)
            )
        ).first()
    if last is None:
        return True
    if last.status == "sent":
        return False
    attempted = last.created_at or datetime.min
    return attempted <= datetime.utcnow() - timedelta(hours=24)


async def _notify_admin_reminder_result(bot, sp: Specialist, kind: str,
                                        sent: bool, message_id: int | None,
                                        error: str | None) -> None:
    label = "за 7 дней" if kind == "renewal" else "об окончании срока"
    if sent:
        text = (
            f"✅ <b>Telegram подтвердил отправку</b>\n"
            f"#{sp.id} {html.escape(sp.name)} · {label}\n"
            f"Telegram message ID: <code>{message_id}</code>"
        )
    else:
        text = (
            f"❌ <b>Telegram не отправил напоминание</b>\n"
            f"#{sp.id} {html.escape(sp.name)} · {label}\n"
            f"Причина: <code>{html.escape((error or 'неизвестная ошибка')[:500])}</code>\n"
            f"Повторить вручную: <code>/renewalsend {sp.id} {kind}</code>"
        )
    for admin_id in config.ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text)
        except Exception as e:  # noqa: BLE001
            log.warning("Не удалось отправить результат напоминания админу %s: %s",
                        admin_id, e)


async def send_specialist_reminder(bot, sp: Specialist, kind: str,
                                   *, force: bool = False) -> bool:
    """Отправляет, логирует результат и возвращает подтверждение Telegram API.

    ``force`` используется только админ-командой ручной повторной отправки.
    Автоматический цикл не дублирует уже доставленное сообщение и повторяет
    неудачную попытку максимум раз в 24 часа.
    """
    if kind not in ("renewal", "expiry"):
        raise ValueError(f"unknown reminder kind: {kind}")
    if not sp.submitter_user_id or not sp.paid_until:
        return False
    if not force and not await _reminder_attempt_allowed(sp, kind):
        return False

    text = renewal_reminder_text(sp) if kind == "renewal" else expiry_notice_text(sp)
    sent = False
    message_id = None
    error = None
    try:
        msg = await bot.send_message(
            sp.submitter_user_id,
            text,
            reply_markup=_renewal_kb(sp.id),
        )
        sent = True
        message_id = getattr(msg, "message_id", None)
    except Exception as e:  # noqa: BLE001
        error = f"{type(e).__name__}: {e}"
        log.warning("Не удалось доставить напоминание карточки #%s пользователю %s: %s",
                    sp.id, sp.submitter_user_id, error)

    async with get_session() as session:
        session.add(SpecialistReminderLog(
            specialist_id=sp.id,
            user_id=sp.submitter_user_id,
            kind=kind,
            paid_until=sp.paid_until,
            status="sent" if sent else "failed",
            message_text=text,
            telegram_message_id=message_id,
            error_text=error,
        ))
        current = await session.get(Specialist, sp.id)
        # Галочка означает только подтверждённую Telegram-доставку и только для
        # того же оплаченного периода (за время отправки карточку могли продлить).
        if (sent and kind == "renewal" and current
                and current.paid_until == sp.paid_until):
            current.renewal_reminded = True
        await session.commit()

    await _notify_admin_reminder_result(bot, sp, kind, sent, message_id, error)
    return sent


# --- Реферальная программа в гайде ------------------------------------------

async def start_specialist_referral(message: Message, ref_sid: int) -> None:
    """Пользователь пришёл по реф-ссылке специалиста ref_sid. Запоминаем это:
    при само-добавлении он получит -20% на годовое размещение, а реферер — премиум."""
    uid = message.from_user.id
    async with get_session() as session:
        ref = await session.get(Specialist, ref_sid)
        # ссылка должна вести на реальную карточку и нельзя пригласить самого себя
        valid = bool(ref and ref.submitter_user_id != uid)
        if valid:
            await session.merge(Meta(key=f"spref:{uid}", value=str(ref_sid)))
            await session.commit()
    name = message.from_user.first_name or "друг"
    if valid:
        await message.answer(
            f"Привет, {name}! 👋 Тебя пригласили в наш гайд специалистов.\n\n"
            "Как приглашённому — скидка <b>−20% на годовое размещение</b> "
            "(Стандарт или Премиум). Она применится сама на шаге оплаты.\n\n"
            "Нажми «➕ Добавить себя в гайд», чтобы разместиться 👇",
            reply_markup=main_menu(),
        )
    else:
        await message.answer(f"Привет, {name}! 👋", reply_markup=main_menu())


async def _reward_referrer(bot, referrer_sid: int, referred_sid: int,
                           referred_uid: int | None) -> None:
    """Начисляет пригласившему бонусный Премиум на REFERRAL_PREMIUM_DAYS дней."""
    async with get_session() as session:
        if await session.get(Meta, f"sprefdone:{referred_sid}"):
            return  # за эту карточку реферера уже наградили
        ref = await session.get(Specialist, referrer_sid)
        if ref is None or (referred_uid and ref.submitter_user_id == referred_uid):
            session.add(Meta(key=f"sprefdone:{referred_sid}", value="skip"))
            await session.commit()
            return
        now = datetime.utcnow()
        base = ref.premium_until if ref.premium_until and ref.premium_until > now else now
        ref.premium_until = base + timedelta(days=config.REFERRAL_PREMIUM_DAYS)
        ref.is_premium = True
        session.add(Meta(key=f"sprefdone:{referred_sid}", value="done"))
        await session.commit()
        owner, rname, until = ref.submitter_user_id, ref.name, ref.premium_until
    if owner:
        await _safe_send(
            bot, owner,
            f"🎉 По твоей ссылке в гайд добавился специалист! Карточка «{rname}» "
            f"получает Премиум до {until:%d.%m.%Y} — выше в выдаче и с бейджем. "
            "Спасибо, что приводишь своих 🧡",
        )


async def _revert_expired_premium(bot) -> None:
    """Снимает бонусный Премиум, когда его срок (premium_until) истёк.
    Не трогает карточки на премиум-тарифе (за них платят отдельно)."""
    now = datetime.utcnow()
    async with get_session() as session:
        rows = (
            await session.scalars(
                select(Specialist).where(
                    Specialist.premium_until.is_not(None),
                    Specialist.premium_until <= now,
                    Specialist.is_premium.is_(True),
                    Specialist.plan.notlike("%premium%"),
                )
            )
        ).all()
        for s in rows:
            s.is_premium = False
            s.premium_until = None
        await session.commit()


async def _on_payment_failed(bot, sid: int, payment_id: str, kind: str, status: str) -> None:
    """Сообщает о неуспешной оплате и предлагает повторить (для нового платежа)."""
    async with get_session() as session:
        if await session.get(Meta, f"payfail:{payment_id}"):
            return  # уже сообщали об этой неудаче
        sp = await session.get(Specialist, sid)
        if sp is None:
            return
        sub, name = sp.submitter_user_id, sp.name
        session.add(Meta(key=f"payfail:{payment_id}", value=status))
        await session.commit()
    if not sub:
        return
    if kind == "claim":
        await _safe_send(
            bot, sub,
            f"Оплата за «{name}» не прошла 😕 Это бывает — выбери вариант ещё раз 👇",
            _claim_plan_kb(sid),
        )
    elif kind == "renew":
        kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🔁 Повторить", callback_data=f"specrenew:{sid}")]]
        )
        await _safe_send(bot, sub, f"Оплата продления «{name}» не прошла 😕 Можно попробовать ещё раз.", kb)
    else:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🔁 Попробовать снова", callback_data=f"specretry:{sid}")]]
        )
        await _safe_send(
            bot, sub, f"Оплата за «{name}» не прошла 😕 Это бывает — можно попробовать ещё раз.", kb
        )


@router.callback_query(F.data.startswith("specretry:"))
async def spec_retry(callback: CallbackQuery) -> None:
    sid = int(callback.data.split(":", 1)[1])
    async with get_session() as session:
        sp = await session.get(Specialist, sid)
        if sp is None or sp.submitter_user_id != callback.from_user.id:
            await callback.answer("Карточка не найдена", show_alert=True)
            return
        name, plan = sp.name, sp.plan or "year"
    info = config.plan_info(plan)
    payment = await create_payment(
        f"{DESC_NEW}: {name}",
        {"specialist_id": sid, "kind": "new", "plan": plan},
        info["price"],
    )
    if not payment or not payment.get("checkout_url"):
        await callback.answer("Не удалось создать оплату, попробуй позже", show_alert=True)
        return
    async with get_session() as session:
        sp = await session.get(Specialist, sid)
        if sp:
            sp.payment_id = payment["id"]
            await session.commit()
    await callback.message.answer(
        "👇 Кнопка для оплаты:", reply_markup=_pay_kb(payment["checkout_url"], plan)
    )
    await callback.answer()


# --- Продление ---------------------------------------------------------------

@router.callback_query(F.data.startswith("specrenew:"))
async def spec_renew(callback: CallbackQuery) -> None:
    sid = int(callback.data.split(":", 1)[1])
    async with get_session() as session:
        sp = await session.get(Specialist, sid)
        if sp is None or sp.submitter_user_id != callback.from_user.id:
            await callback.answer("Карточка не найдена", show_alert=True)
            return
        name, plan = sp.name, sp.plan or "year"
    info = config.plan_info(plan)
    payment = await create_payment(
        f"{DESC_RENEW}: {name}",
        {"specialist_id": sid, "kind": "renew", "plan": plan},
        info["price"],
    )
    if not payment or not payment.get("checkout_url"):
        await callback.answer("Не удалось создать оплату, попробуй позже", show_alert=True)
        return
    await callback.message.answer(
        f"Продление размещения — <b>{_price_str(plan)}</b>. Жми кнопку 👇",
        reply_markup=_pay_kb(payment["checkout_url"], plan),
    )
    await callback.answer()


# --- Claim: оплата «старожилами» из старого бессрочного гайда ----------------

def _claim_plan_kb(sid: int) -> InlineKeyboardMarkup:
    cur = config.LISTING_CURRENCY
    y = config.plan_info("year_legacy")
    m = config.plan_info("month_legacy")
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"✅ Оставить на год · {y['price']} {cur}",
                                  callback_data=f"claimplan:{sid}:year_legacy")],
            [InlineKeyboardButton(text=f"📅 Помесячно · {m['price']} {cur}/мес",
                                  callback_data=f"claimplan:{sid}:month_legacy")],
        ]
    )


async def start_claim(message: Message, sid: int) -> None:
    """Открывается по ссылке t.me/<bot>?start=claim_<id> из рассылки старым специалистам."""
    async with get_session() as session:
        sp = await session.get(Specialist, sid)
        if sp is None:
            await message.answer(
                "Карточка не найдена 🤔 Возможно, ссылка устарела — напиши нам через /contact.",
                reply_markup=main_menu(),
            )
            return
        now = datetime.utcnow()
        name, card = sp.name, _card_text(sp)
        already = bool(sp.paid_until and sp.paid_until > now and sp.source == "self")
    if not config.payments_enabled():
        await message.answer(
            "Оплата временно недоступна 🙏 Напиши нам через /contact — поможем.",
            reply_markup=main_menu(),
        )
        return
    if already:
        await message.answer(
            f"Твоя карточка «{name}» уже оплачена и активна — всё в порядке! 🙌 Спасибо 🧡",
            reply_markup=main_menu(),
        )
        return
    cur = config.LISTING_CURRENCY
    y, m = config.plan_info("year_legacy"), config.plan_info("month_legacy")
    norm_y = config.plan_info("year")
    deadline = config.grandfather_deadline()
    await message.answer(
        f"Привет! 👋 Это твоя карточка из нашего гайда специалистов:\n\n{card}\n\n"
        "Когда ты размещался(ась), оплата была разовой. Чтобы поддерживать и "
        "развивать гайд (бот, поиск, отзывы, продвижение) и приводить тебе клиентов, "
        f"с <b>{deadline:%d.%m.%Y}</b> мы переходим на ежегодное размещение. Для тех, "
        "кто с нами с самого начала, — <b>особая цена в благодарность</b>:\n"
        f"• <b>{y['price']} {cur}/год</b> (обычная — {norm_y['price']} {cur})\n"
        f"• или {m['price']} {cur}/мес\n\n"
        "Чтобы карточка осталась в гайде — выбери вариант 👇",
        reply_markup=_claim_plan_kb(sid),
    )


@router.callback_query(F.data.startswith("claimplan:"))
async def claim_plan(callback: CallbackQuery, state: FSMContext) -> None:
    parts = callback.data.split(":")
    sid = int(parts[1])
    plan = parts[2] if len(parts) > 2 else "year_legacy"
    if plan not in ("year_legacy", "month_legacy"):
        plan = "year_legacy"
    async with get_session() as session:
        sp = await session.get(Specialist, sid)
        if sp is None:
            await callback.answer("Карточка не найдена", show_alert=True)
            return
        sp.submitter_user_id = callback.from_user.id  # привязываем карточку к плательщику
        sp.plan = plan
        await session.commit()
    # Спрашиваем e-mail для счёта ДО оплаты: иначе факту­ра не уйдёт (раньше так
    # и было — старые карточки без e-mail оставались без счёта).
    await state.set_state(ClaimPay.waiting_email)
    await state.update_data(claim_sid=sid, claim_plan=plan)
    await callback.message.answer(
        f"Отлично, тариф: <b>{_price_str(plan)}</b> 🙌\n\n"
        "Остался один шаг: на какой <b>e-mail</b> прислать счёт (factuur) после оплаты?\n"
        "<i>Например: mail@example.com</i>",
        reply_markup=cancel_menu(),
    )
    await callback.answer()


@router.message(ClaimPay.waiting_email)
async def claim_email(message: Message, state: FSMContext) -> None:
    email = (message.text or "").strip()
    if "@" not in email or "." not in email or " " in email:
        await message.answer("Похоже, это не e-mail 🙂 Напиши адрес вида mail@example.com")
        return
    data = await state.get_data()
    sid = data.get("claim_sid")
    plan = data.get("claim_plan", "year_legacy")
    await state.clear()
    info = config.plan_info(plan)
    async with get_session() as session:
        sp = await session.get(Specialist, sid)
        if sp is None:
            await message.answer(
                "Карточка не найдена 🤔 Напиши нам через /contact.", reply_markup=main_menu()
            )
            return
        sp.invoice_email = email
        name = sp.name
        await session.commit()
    payment = await create_payment(
        f"{DESC_RENEW}: {name}",
        {"specialist_id": sid, "kind": "claim", "plan": plan},
        info["price"],
    )
    if not payment or not payment.get("checkout_url"):
        await message.answer(
            "Не удалось создать оплату, попробуй позже 🙏", reply_markup=main_menu()
        )
        return
    async with get_session() as session:
        sp = await session.get(Specialist, sid)
        if sp:
            sp.payment_id = payment["id"]
            await session.commit()
    await message.answer(
        f"Готово! Счёт пришлём на <b>{email}</b> после оплаты.\n\n"
        f'Оплачивая, ты соглашаешься с <a href="{config.terms_url()}">Условиями</a> '
        f'и <a href="{config.privacy_url()}">Политикой конфиденциальности</a>.',
        reply_markup=main_menu(),
        disable_web_page_preview=True,
    )
    await message.answer(
        "👇 Кнопка для оплаты:", reply_markup=_pay_kb(payment["checkout_url"], plan)
    )


# --- Фоновые напоминания о продлении ----------------------------------------

async def reminder_loop(bot) -> None:
    """Раз в 12 часов напоминает о скором окончании размещения."""
    from utils.seasonal import check_seasonal
    while True:
        try:
            await _send_renewal_reminders(bot)
            await _send_expiry_notices(bot)
            await _hide_expired_grandfathered(bot)  # старый гайд: скрыть неоплаченные
            await _revert_expired_premium(bot)  # снять бонусный премиум, когда истёк
            await check_seasonal(bot)  # сезонные дедлайны NL (страховка, налоги)
        except Exception as e:  # noqa: BLE001
            log.warning("Ошибка в фоновых напоминаниях: %s", e)
        await asyncio.sleep(12 * 3600)


async def _hide_expired_grandfathered(bot) -> None:
    """После дедлайна скрывает неоплаченные карточки из старого гайда (source=seed,
    срок проставлен и истёк). Данные не удаляем — если оплатят позже, карточка вернётся."""
    now = datetime.utcnow()
    async with get_session() as session:
        rows = (
            await session.scalars(
                select(Specialist).where(
                    Specialist.source == "seed",
                    Specialist.status == "active",
                    Specialist.paid_until.is_not(None),
                    Specialist.paid_until <= now,
                )
            )
        ).all()
        n = len(rows)
        for s in rows:
            s.status = "expired"
        await session.commit()
    if n:
        for admin_id in config.ADMIN_IDS:
            await _safe_send(
                bot, admin_id,
                f"🗂 Гайд: скрыто {n} неоплаченных карточек из старого гайда (срок истёк).",
            )


async def _send_renewal_reminders(bot) -> None:
    now = datetime.utcnow()
    soon = now + timedelta(days=7)
    async with get_session() as session:
        rows = (
            await session.scalars(
                select(Specialist).where(
                    Specialist.source == "self",
                    Specialist.status == "active",
                    Specialist.paid_until.is_not(None),
                    Specialist.paid_until <= soon,
                    Specialist.paid_until > now,
                    Specialist.renewal_reminded.is_(False),
                    Specialist.submitter_user_id.is_not(None),
                )
            )
        ).all()
    for sp in rows:
        await send_specialist_reminder(bot, sp, "renewal")


async def _send_expiry_notices(bot) -> None:
    """Скрывает просроченные карточки и контролирует доставку уведомления.

    Неудачную доставку повторяем раз в сутки в течение 7 дней. Карточкам,
    которые были скрыты старой версией бота до появления журнала, ничего
    задним числом автоматически не отправляем: админ может сделать это явно
    командой /renewalsend.
    """
    now = datetime.utcnow()
    async with get_session() as session:
        rows = (
            await session.scalars(
                select(Specialist).where(
                    Specialist.source == "self",
                    Specialist.status == "active",
                    Specialist.paid_until.is_not(None),
                    Specialist.paid_until <= now,
                    Specialist.submitter_user_id.is_not(None),
                )
            )
        ).all()
        newly_expired_ids = {s.id for s in rows}
        for s in rows:
            s.status = "expired"
        await session.commit()

    async with get_session() as session:
        recent_expired = (
            await session.scalars(
                select(Specialist).where(
                    Specialist.source == "self",
                    Specialist.status == "expired",
                    Specialist.paid_until.is_not(None),
                    Specialist.paid_until <= now,
                    Specialist.paid_until >= now - timedelta(days=7),
                    Specialist.submitter_user_id.is_not(None),
                )
            )
        ).all()
    for sp in recent_expired:
        if sp.id in newly_expired_ids:
            await send_specialist_reminder(bot, sp, "expiry")
            continue
        # Повторяем только документированную неудачную попытку новой системы.
        # Отсутствие лога означает старую карточку — её не трогаем автоматически.
        async with get_session() as session:
            last = (
                await session.scalars(
                    select(SpecialistReminderLog)
                    .where(
                        SpecialistReminderLog.specialist_id == sp.id,
                        SpecialistReminderLog.kind == "expiry",
                        SpecialistReminderLog.paid_until == sp.paid_until,
                    )
                    .order_by(SpecialistReminderLog.created_at.desc(),
                              SpecialistReminderLog.id.desc())
                    .limit(1)
                )
            ).first()
        if last is not None and last.status == "failed":
            await send_specialist_reminder(bot, sp, "expiry")
