"""Платное само-добавление специалистов в гайд (через Mollie).

Поток: пользователь жмёт «➕ Добавить себя в гайд» → анкета → ссылка на оплату
Mollie → после оплаты (webhook) заявка приходит админам на проверку → админ
публикует. Перед окончанием года бот напоминает о продлении.
"""
import asyncio
import logging
from datetime import datetime, timedelta

from aiogram import F, Router
from aiogram.enums import ChatType
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
from database.models import Meta, Specialist
from keyboards.menus import BTN_SELF_ADD, cancel_menu, main_menu
from states.forms import SelfAddSpecialist
from utils.ai import extract_specialist_query
from utils.geo import CATEGORIES, NEIGHBORS, detect_category, detect_city, province_of_city
from utils.payments import create_payment, get_payment

log = logging.getLogger(__name__)

router = Router()
router.message.filter(F.chat.type == ChatType.PRIVATE)

ONLINE_WORDS = {"онлайн", "online", "по всей стране"}


def _price_str(plan: str) -> str:
    info = config.plan_info(plan)
    return f"{info['price']} {config.LISTING_CURRENCY} / {info['title']}"


def _plan_kb() -> InlineKeyboardMarkup:
    m, y = config.plan_info("month"), config.plan_info("year")
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text=f"📅 {m['price']} {config.LISTING_CURRENCY} / месяц",
                callback_data="selfplan:month")],
            [InlineKeyboardButton(
                text=f"⭐ {y['price']} {config.LISTING_CURRENCY} / год (выгоднее)",
                callback_data="selfplan:year")],
        ]
    )


def _where(sp: Specialist) -> str:
    if sp.is_online:
        return "онлайн"
    return sp.city or sp.province or "—"


def _card_text(sp: Specialist) -> str:
    lines = [f"<b>{sp.name}</b> — {sp.category}, {_where(sp)}"]
    if sp.description:
        lines.append(sp.description)
    if sp.contact:
        lines.append(f"📞 {sp.contact}")
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


def _pay_kb(checkout_url: str, plan: str) -> InlineKeyboardMarkup:
    info = config.plan_info(plan)
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(
            text=f"💳 Оплатить {info['price']} {config.LISTING_CURRENCY}", url=checkout_url)]]
    )


# --- Анкета ------------------------------------------------------------------

@router.message(F.text == BTN_SELF_ADD)
async def self_start(message: Message, state: FSMContext) -> None:
    if not config.payments_enabled():
        await message.answer(
            "Само-добавление пока недоступно — скоро включим 🙌", reply_markup=main_menu()
        )
        return
    await state.set_state(SelfAddSpecialist.name)
    m, y = config.plan_info("month"), config.plan_info("year")
    await message.answer(
        "Отлично, давай добавим тебя в гайд! 🎉\n\n"
        f"Размещение — <b>{m['price']} {config.LISTING_CURRENCY}/мес</b> или "
        f"<b>{y['price']} {config.LISTING_CURRENCY}/год</b> (тариф выберешь в конце), "
        "с проверкой нашей командой.\n\n"
        "Шаг 1/5. Имя или название (как показать в гайде)?",
        reply_markup=cancel_menu(),
    )


@router.message(SelfAddSpecialist.name)
async def self_name(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("Напиши имя/название текстом 🙂")
        return
    await state.update_data(sp_name=message.text.strip())
    await state.set_state(SelfAddSpecialist.category)
    cats = ", ".join(CATEGORIES.keys())
    await message.answer(
        f"Шаг 2/5. Категория? Напиши одну из:\n\n{cats}", reply_markup=cancel_menu()
    )


@router.message(SelfAddSpecialist.category)
async def self_category(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    cat = detect_category(text) or next((c for c in CATEGORIES if c.lower() == text.lower()), None)
    if not cat:
        await message.answer(
            "Не распознал категорию 🤔 Напиши точнее, например «юрист».",
            reply_markup=cancel_menu(),
        )
        return
    await state.update_data(sp_category=cat)
    await state.set_state(SelfAddSpecialist.location)
    await message.answer(
        f"Категория: <b>{cat}</b> ✅\n\n"
        "Шаг 3/5. Город? Или напиши <b>онлайн</b>, если работаешь по всей стране.",
        reply_markup=cancel_menu(),
    )


@router.message(SelfAddSpecialist.location)
async def self_location(message: Message, state: FSMContext) -> None:
    loc = (message.text or "").strip()
    if not loc:
        await message.answer("Напиши город или «онлайн» 🙂")
        return
    if loc.lower() in ONLINE_WORDS:
        await state.update_data(sp_online=True, sp_city="", sp_province="")
    else:
        known = detect_city(loc)
        if known:
            city, province = known
        else:
            city = loc
            extracted = await extract_specialist_query(
                loc, list(CATEGORIES.keys()), list(NEIGHBORS.keys())
            )
            province = extracted.get("province") or province_of_city(loc) or ""
        await state.update_data(sp_online=False, sp_city=city, sp_province=province)
    await state.set_state(SelfAddSpecialist.description)
    await message.answer(
        "Шаг 4/5. Коротко опиши свои услуги (или «-», чтобы пропустить).",
        reply_markup=cancel_menu(),
    )


@router.message(SelfAddSpecialist.description)
async def self_description(message: Message, state: FSMContext) -> None:
    desc = (message.text or "").strip()
    await state.update_data(sp_description=None if desc == "-" else desc)
    await state.set_state(SelfAddSpecialist.contact)
    await message.answer(
        "Шаг 5/5. Контакты для клиентов (телефон / @username / email / сайт)?",
        reply_markup=cancel_menu(),
    )


@router.message(SelfAddSpecialist.contact)
async def self_contact(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("Напиши контакты текстом 🙂")
        return
    await state.update_data(sp_contact=message.text.strip())
    await state.set_state(SelfAddSpecialist.plan)
    await message.answer(
        "Отлично, анкета готова! 🎉 Осталось выбрать тариф размещения:",
        reply_markup=_plan_kb(),
    )


@router.callback_query(SelfAddSpecialist.plan, F.data.startswith("selfplan:"))
async def self_plan(callback: CallbackQuery, state: FSMContext) -> None:
    plan = callback.data.split(":", 1)[1]
    if plan not in ("month", "year"):
        plan = "year"
    info = config.plan_info(plan)
    data = await state.get_data()
    async with get_session() as session:
        sp = Specialist(
            name=data["sp_name"],
            category=data["sp_category"],
            city=data.get("sp_city", ""),
            province=data.get("sp_province", ""),
            description=data.get("sp_description"),
            contact=data.get("sp_contact", ""),
            is_online=data.get("sp_online", False),
            status="awaiting_payment",
            source="self",
            submitter_user_id=callback.from_user.id,
            plan=plan,
        )
        session.add(sp)
        await session.commit()
        await session.refresh(sp)
        sid, name = sp.id, sp.name
    await state.clear()

    payment = await create_payment(
        f"Размещение в гайде: {name}",
        {"specialist_id": sid, "kind": "new", "plan": plan},
        info["price"],
    )
    if not payment or not payment.get("checkout_url"):
        await callback.message.answer(
            "Не получилось создать ссылку на оплату 😔 Попробуй позже или напиши нам.",
            reply_markup=main_menu(),
        )
        await callback.answer()
        return
    async with get_session() as session:
        sp = await session.get(Specialist, sid)
        if sp:
            sp.payment_id = payment["id"]
            await session.commit()
    # Возвращаем обычное меню (убираем клавиатуру «Отмена» из анкеты)
    await callback.message.answer(
        f"Почти готово! 🎉 Тариф: <b>{_price_str(plan)}</b>.\n\n"
        "После оплаты мы проверим анкету и опубликуем карточку — я напишу тебе ✅",
        reply_markup=main_menu(),
    )
    await callback.message.answer(
        "👇 Кнопка для оплаты:",
        reply_markup=_pay_kb(payment["checkout_url"], plan),
    )
    await callback.answer()


# --- Подтверждение оплаты (вызывается из webhook) ---------------------------

async def on_payment_paid(bot, payment_id: str) -> None:
    """Обрабатывает оплаченный платёж: публикация на проверку или продление."""
    payment = await get_payment(payment_id)
    if not payment or payment.get("status") != "paid":
        return
    meta = payment.get("metadata") or {}
    sid = meta.get("specialist_id")
    kind = meta.get("kind", "new")
    if not sid:
        return

    async with get_session() as session:
        if await session.get(Meta, f"pay:{payment_id}"):
            return  # этот платёж уже обработан (webhook мог прийти повторно)
        sp = await session.get(Specialist, int(sid))
        if sp is None:
            return
        now = datetime.utcnow()
        plan = meta.get("plan", sp.plan or "year")
        days = config.plan_info(plan)["days"]
        if kind == "renew":
            base = sp.paid_until if sp.paid_until and sp.paid_until > now else now
            sp.paid_until = base + timedelta(days=days)
            sp.renewal_reminded = False
            sp.status = "active"
        else:
            sp.paid_until = now + timedelta(days=days)
            sp.status = "pending"  # оплачено, ждёт проверки админом
            sp.plan = plan
        session.add(Meta(key=f"pay:{payment_id}", value="done"))
        await session.commit()
        sub, name, card = sp.submitter_user_id, sp.name, _card_text(sp)
        sp_id = sp.id

    if kind == "renew":
        if sub:
            await _safe_send(bot, sub, f"✅ Оплата получена! Размещение «{name}» продлено. Спасибо 🙌")
        return

    for admin_id in config.ADMIN_IDS:
        await _safe_send(
            bot, admin_id,
            "💳 <b>Оплачено само-добавление</b> — нужна проверка:\n\n" + card,
            _review_kb(sp_id),
        )
    if sub:
        await _safe_send(
            bot, sub,
            "Оплата получена, спасибо! 🙌 Мы проверим анкету и опубликуем карточку — "
            "я напишу, как только всё готово ✅",
        )


async def _safe_send(bot, chat_id, text, reply_markup=None) -> None:
    try:
        await bot.send_message(chat_id, text, reply_markup=reply_markup)
    except Exception as e:  # noqa: BLE001
        log.warning("Не удалось отправить сообщение %s: %s", chat_id, e)


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
        f"Продление в гайде: {name}",
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


# --- Фоновые напоминания о продлении ----------------------------------------

async def reminder_loop(bot) -> None:
    """Раз в 12 часов напоминает о скором окончании размещения."""
    while True:
        try:
            await _send_renewal_reminders(bot)
        except Exception as e:  # noqa: BLE001
            log.warning("Ошибка в напоминаниях о продлении: %s", e)
        await asyncio.sleep(12 * 3600)


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
        targets = [(s.submitter_user_id, s.id, s.name, s.paid_until, s.plan or "year") for s in rows]
        for s in rows:
            s.renewal_reminded = True
        await session.commit()

    for uid, sid, name, until, plan in targets:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🔁 Продлить", callback_data=f"specrenew:{sid}")]]
        )
        await _safe_send(
            bot, uid,
            f"⏳ Размещение «{name}» в гайде заканчивается {until:%d.%m.%Y}.\n"
            f"Продлить ({_price_str(plan)})?",
            kb,
        )
