"""Платное само-добавление специалистов в гайд (через Mollie).

Поток: пользователь жмёт «➕ Добавить себя в гайд» → анкета → ссылка на оплату
Mollie → после оплаты (webhook) заявка приходит админам на проверку → админ
публикует. Перед окончанием года бот напоминает о продлении.
"""
import asyncio
import html
import logging
from datetime import datetime, timedelta

from aiogram import F, Router
from aiogram.filters import Command
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
from database.models import Meta, Specialist, SpecialistReminderLog
from keyboards.menus import BTN_SELF_ADD, cancel_menu, main_menu
from states.forms import ClaimPay, SelfAddSpecialist
from utils.ai import extract_specialist_query
from utils.analytics import log_event
from utils.geo import CATEGORIES, NEIGHBORS, detect_category, detect_city, province_of_city
from utils.payments import create_payment, get_payment

log = logging.getLogger(__name__)

router = Router()
router.message.filter(F.chat.type == ChatType.PRIVATE)

ONLINE_WORDS = {"онлайн", "online", "по всей стране"}

# Описание платежа (видно в Mollie/банке) — на нидерландском
DESC_NEW = "Vermelding in Podslushano-gids"
DESC_RENEW = "Verlenging vermelding Podslushano-gids"


def _price_str(plan: str) -> str:
    info = config.plan_info(plan)
    return f"{info['price']} {config.LISTING_CURRENCY} / {info['title']}"


def _plan_kb() -> InlineKeyboardMarkup:
    cur = config.LISTING_CURRENCY
    m, y = config.plan_info("month"), config.plan_info("year")
    mp, yp = config.plan_info("month_premium"), config.plan_info("year_premium")
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"📅 Обычное · {m['price']} {cur}/мес",
                                  callback_data="selfplan:month")],
            [InlineKeyboardButton(text=f"📅 Обычное · {y['price']} {cur}/год (выгоднее)",
                                  callback_data="selfplan:year")],
            [InlineKeyboardButton(text=f"🌟 Премиум · {mp['price']} {cur}/мес",
                                  callback_data="selfplan:month_premium")],
            [InlineKeyboardButton(text=f"🌟 Премиум · {yp['price']} {cur}/год",
                                  callback_data="selfplan:year_premium")],
        ]
    )


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
            text=f"💳 Оплатить {price} {config.LISTING_CURRENCY}", url=checkout_url)]]
    )


# --- Анкета ------------------------------------------------------------------

@router.message(Command("selfadd", "addme"))
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
        "Шаг 1/6. Имя или название (как показать в гайде)?",
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
        "Шаг 2/6. Категория? Напиши одну из списка ниже.\n"
        "<i>Например: стоматолог, юрист, мастер маникюра…</i>\n\n"
        f"{cats}",
        reply_markup=cancel_menu(),
    )


@router.message(SelfAddSpecialist.category)
async def self_category(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text:
        await message.answer("Напиши категорию текстом 🙂", reply_markup=cancel_menu())
        return
    # 1) Пробуем сопоставить с существующей категорией (ключевые слова / точное имя)
    cat = detect_category(text) or next((c for c in CATEGORIES if c.lower() == text.lower()), None)
    # 2) Не вышло — пробуем ИИ (синонимы/опечатки), но только если он вернёт нашу
    if not cat:
        try:
            extracted = await extract_specialist_query(
                text, list(CATEGORIES.keys()), list(NEIGHBORS.keys())
            )
        except Exception:  # noqa: BLE001
            extracted = {}
        ai_cat = extracted.get("category")
        if ai_cat and ai_cat in CATEGORIES:
            cat = ai_cat
    # 3) Ничего не подошло — НЕ блокируем клиента: принимаем его категорию как есть,
    # пометим как новую (админу прилетит подсказка добавить её в список)
    custom = False
    if not cat:
        cat = text.lower()[:50]
        custom = True
    await state.update_data(sp_category=cat, sp_custom_category=custom)
    await state.set_state(SelfAddSpecialist.location)
    note = " (добавим как есть, мы проверим)" if custom else ""
    await message.answer(
        f"Категория: <b>{html.escape(cat)}</b> ✅{note}\n\n"
        "Шаг 3/6. Город? Или напиши <b>онлайн</b>, если работаешь по всей стране.",
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
        "Шаг 4/6. Коротко опиши свои услуги (или поставь «-», чтобы пропустить).\n"
        "<i>Например: «Маникюр, педикюр, наращивание. Работаю на дому»</i>",
        reply_markup=cancel_menu(),
    )


@router.message(SelfAddSpecialist.description)
async def self_description(message: Message, state: FSMContext) -> None:
    desc = (message.text or "").strip()
    await state.update_data(sp_description=None if desc == "-" else desc)
    await state.set_state(SelfAddSpecialist.contact)
    await message.answer(
        "Шаг 5/6. Как с тобой связаться клиентам? Телефон, @username, e-mail или сайт.\n"
        "<i>Например: +31 6 12345678, @username, mail@example.com</i>",
        reply_markup=cancel_menu(),
    )


@router.message(SelfAddSpecialist.contact)
async def self_contact(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("Напиши контакты текстом 🙂")
        return
    await state.update_data(sp_contact=message.text.strip())
    await state.set_state(SelfAddSpecialist.email)
    await message.answer(
        "Шаг 6/6. На какой <b>e-mail</b> прислать счёт (factuur) после оплаты?\n"
        "<i>Например: mail@example.com</i>",
        reply_markup=cancel_menu(),
    )


@router.message(SelfAddSpecialist.email)
async def self_email(message: Message, state: FSMContext) -> None:
    email = (message.text or "").strip()
    if "@" not in email or "." not in email or " " in email:
        await message.answer("Похоже, это не e-mail 🙂 Напиши адрес вида mail@example.com")
        return
    await state.update_data(sp_email=email)
    await state.set_state(SelfAddSpecialist.plan)
    await message.answer(
        "Отлично, анкета готова! 🎉 Выбери тариф размещения:\n\n"
        "🌟 <b>Премиум</b> — карточка показывается <b>выше</b> в выдаче и с бейджем, "
        "тебя замечают первым.",
        reply_markup=_plan_kb(),
    )


@router.callback_query(SelfAddSpecialist.plan, F.data.startswith("selfplan:"))
async def self_plan(callback: CallbackQuery, state: FSMContext) -> None:
    plan = callback.data.split(":", 1)[1]
    if plan not in ("month", "year", "month_premium", "year_premium"):
        plan = "year"
    # Премиум показывает фото — попросим его перед оплатой
    if config.plan_info(plan)["premium"]:
        await state.update_data(sp_plan=plan)
        await state.set_state(SelfAddSpecialist.photo)
        await callback.message.answer(
            "🌟 <b>Премиум показывает фото</b> — пришли фото (логотип или твоё фото) "
            "одним сообщением. Или напиши «-», чтобы пропустить.",
            reply_markup=cancel_menu(),
        )
        await callback.answer()
        return
    await _create_listing_and_pay(callback.message, state, plan, None, callback.from_user.id)
    await callback.answer()


@router.message(SelfAddSpecialist.photo)
async def self_photo(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    plan = data.get("sp_plan", "year_premium")
    if message.photo:
        photo_id = message.photo[-1].file_id
    elif message.text and message.text.strip().lower() in ("-", "пропустить", "skip", "нет"):
        photo_id = None
    else:
        await message.answer("Пришли фото картинкой или «-», чтобы пропустить 🙂")
        return
    await _create_listing_and_pay(message, state, plan, photo_id, message.from_user.id)


async def _create_listing_and_pay(message, state: FSMContext, plan: str,
                                  photo_file_id: str | None, uid: int) -> None:
    """Создаёт карточку (awaiting_payment) и присылает ссылку на оплату."""
    info = config.plan_info(plan)
    data = await state.get_data()
    async with get_session() as session:
        # Пришёл ли пользователь по реф-ссылке специалиста (?start=spref_<id>)
        ref_meta = await session.get(Meta, f"spref:{uid}")
        ref_sid = int(ref_meta.value) if ref_meta and ref_meta.value.isdigit() else None
        sp = Specialist(
            name=data["sp_name"],
            category=data["sp_category"],
            city=data.get("sp_city", ""),
            province=data.get("sp_province", ""),
            description=data.get("sp_description"),
            contact=data.get("sp_contact", ""),
            is_online=data.get("sp_online", False),
            is_premium=info["premium"],
            photo_file_id=photo_file_id,
            status="awaiting_payment",
            source="self",
            submitter_user_id=uid,
            invoice_email=data.get("sp_email"),
            plan=plan,
            referred_by_specialist_id=ref_sid,
        )
        session.add(sp)
        await session.commit()
        await session.refresh(sp)
        sid, name = sp.id, sp.name
    await state.clear()

    # Скидка -20% приглашённому на ГОДОВОЕ размещение (Стандарт/Премиум)
    referral_year = bool(ref_sid) and plan in ("year", "year_premium")
    amount = config.discounted_price(info["price"]) if referral_year else info["price"]

    payment = await create_payment(
        f"{DESC_NEW}: {name}",
        {"specialist_id": sid, "kind": "new", "plan": plan},
        amount,
    )
    if not payment or not payment.get("checkout_url"):
        await message.answer(
            "Не получилось создать ссылку на оплату 😔 Попробуй позже или напиши нам.",
            reply_markup=main_menu(),
        )
        return
    async with get_session() as session:
        sp = await session.get(Specialist, sid)
        if sp:
            sp.payment_id = payment["id"]
            await session.commit()
    # Возвращаем обычное меню (убираем клавиатуру «Отмена» из анкеты)
    tariff = (
        f"<s>{info['price']}</s> → <b>{amount} {config.LISTING_CURRENCY}</b> "
        f"(−20% по приглашению, {info['title']})"
        if referral_year else f"<b>{_price_str(plan)}</b>"
    )
    await message.answer(
        f"Почти готово! 🎉 Тариф: {tariff}.\n\n"
        "После оплаты мы проверим анкету и опубликуем карточку — я напишу тебе ✅\n\n"
        f'Оплачивая, ты соглашаешься с <a href="{config.terms_url()}">Условиями</a> '
        f'и <a href="{config.privacy_url()}">Политикой конфиденциальности</a>.',
        reply_markup=main_menu(),
        disable_web_page_preview=True,
    )
    await message.answer(
        "👇 Кнопка для оплаты:",
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
            "Оплата получена, спасибо! 🙌 Мы проверим анкету и опубликуем карточку — "
            "я напишу, как только всё готово ✅",
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
        f"Хочешь вернуть её? Продли ({_price_str(sp.plan or 'year')}) 👇"
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
