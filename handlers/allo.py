"""Allo Walks — запись и оплата прогулок через бота.

Разовая прогулка (€ single) или абонемент (€ pass = N прогулок на выбор в
течение ALLO_PASS_VALID_DAYS дней). Абонемент — это кредиты: купил, потом
списываешь на любые даты. Оплата — через общий webhook (kind="allo").
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import and_, func, or_, select

import config
from database.db import get_session
from database.models import AlloBooking, AlloReferral
from keyboards.menus import cancel_menu, main_menu
from states.forms import AlloBook
from utils.payments import create_payment

router = Router()
router.message.filter(F.chat.type == ChatType.PRIVATE)

log = logging.getLogger(__name__)

_HOLD_MINUTES = 60          # сколько держится неоплаченная бронь
_SEAT_PLANS = ("single", "use")  # что занимает место на прогулке


def _p(price: str) -> str:
    try:
        f = float(price)
        return str(int(f)) if f == int(f) else f"{f:.2f}"
    except (TypeError, ValueError):
        return str(price)


ALLO_INTRO = (
    "🚶 <b>Allo Walks</b> — прогулки для своих от Podslushano.nl 🇳🇱\n\n"
    "Неспешные прогулки по красивым местам Нидерландов в небольшой компании "
    "(до {cap} человек). Приезжаешь на поезде, встречаемся у станции — и уже через "
    "10–15 минут идём среди зелени, знакомимся и общаемся. В конце — кофе для тех, "
    "кто хочет остаться подольше.\n\n"
    "<b>Как это работает:</b>\n"
    "1️⃣ Выбираешь прогулку ниже.\n"
    "2️⃣ Оплачиваешь картой или iDEAL.\n"
    "3️⃣ Получаешь подтверждение — и приходишь в назначенный день.\n\n"
    "💶 <b>€{single}</b> за прогулку. Или <b>абонемент</b>: {credits} прогулки за "
    "<b>€{pass_}</b> — на любые даты в течение 2 месяцев.\n\n"
    "🌟 Allo Walks — только начало нашего нового проекта Allo (закрытый клуб). "
    "Абонемент сейчас зачтётся в будущее членство клуба — подробнее в абонементе.\n\n"
    "Выбирай 👇"
)

ALLO_TERMS = (
    "📜 <b>Правила Allo Walks</b>\n\n"
    "<b>1. Организатор и предмет.</b> Прогулки Allo Walks организует {company} "
    "(KVK {kvk}). Настоящие Правила регулируют условия участия. Совершая оплату, "
    "участник подтверждает согласие с ними.\n\n"
    "<b>2. Стоимость и оплата.</b> Стоимость участия составляет €{single} за одну "
    "прогулку либо €{pass_} за абонемент на {credits} прогулки. Цены включают BTW "
    "21%. Оплата производится через сервис Mollie. Место закрепляется за участником "
    "после поступления оплаты. Число мест ограничено ({cap} участников на прогулку).\n\n"
    "<b>3. Абонемент.</b> Абонемент даёт право на участие в {credits} прогулках по "
    "выбору участника в течение {days} дней с даты оплаты. Абонемент именной и не "
    "подлежит передаче третьим лицам. Неиспользованные прогулки по истечении срока "
    "действия не возвращаются и не компенсируются.\n\n"
    "<b>4. Отмена участником и возврат.</b> При уведомлении об отмене не позднее чем "
    "за 24 часа до начала прогулки уплаченная сумма подлежит возврату. При "
    "уведомлении менее чем за 24 часа, а также при неявке участника возврат не "
    "производится. После состоявшейся прогулки возврат не производится. Поскольку "
    "услуга оказывается в согласованную дату и относится к организации досуга, право "
    "на отзыв договора в течение 14 дней не применяется (ст. 6:230p ГК Нидерландов).\n\n"
    "<b>5. Отмена организатором.</b> Организатор вправе отменить прогулку (в том числе "
    "при неблагоприятной погоде, недостаточном числе участников или форс-мажоре). В "
    "этом случае участнику предлагается перенос на другую дату либо полный возврат.\n\n"
    "<b>6. Формат и участие детей.</b> Прогулки рассчитаны на взрослых участников и "
    "общение в группе. Участие с детьми возможно по предварительному согласованию с "
    "организатором.\n\n"
    "<b>7. Ответственность.</b> Участие добровольное. Участник самостоятельно отвечает "
    "за состояние здоровья и наличие подходящей экипировки (удобная обувь, вода, "
    "одежда по погоде). Маршрут не предполагает спортивной нагрузки, однако часть "
    "пути может проходить по песчаным и грунтовым тропам. Организатор не отвечает за "
    "вред здоровью и утрату имущества участника, кроме случаев, когда вред причинён "
    "по вине организатора.\n\n"
    "<b>8. Правила поведения.</b> Участники проявляют уважение к другим участникам и "
    "к природе. Организатор вправе отказать в участии лицу, грубо нарушающему правила, "
    "без возврата уплаченной суммы.\n\n"
    "<b>9. Персональные данные.</b> Организатор обрабатывает имя, e-mail и платёжные "
    "данные участника для оформления записи и выставления чека; обработку платежей "
    "осуществляет Mollie. Подробнее — в Политике конфиденциальности.\n\n"
    "<b>10. Применимое право и контакты.</b> Применяется право Нидерландов. Вопросы "
    "записи, отмены и возврата: {email}."
)


def _terms_text() -> str:
    return ALLO_TERMS.format(
        company=config.COMPANY_NAME, kvk=config.COMPANY_KVK,
        single=_p(config.ALLO_PRICE_SINGLE), pass_=_p(config.ALLO_PRICE_PASS),
        credits=config.ALLO_PASS_CREDITS, days=config.ALLO_PASS_VALID_DAYS,
        cap=config.ALLO_WALK_CAPACITY, email=config.COMPANY_EMAIL,
    )


# --- Учёт мест и абонементов -------------------------------------------------

async def _taken(session, walk_key: str) -> int:
    """Занятые места на прогулке: разовые + списания абонемента (оплаченные и
    свежие неоплаченные брони)."""
    cutoff = datetime.utcnow() - timedelta(minutes=_HOLD_MINUTES)
    live = or_(
        AlloBooking.status == "paid",
        and_(AlloBooking.status == "pending", AlloBooking.created_at >= cutoff),
    )
    return await session.scalar(
        select(func.count()).select_from(AlloBooking).where(
            AlloBooking.walk_key == walk_key,
            AlloBooking.plan.in_(_SEAT_PLANS), live)
    ) or 0


async def _remaining(session, walk_key: str) -> int:
    return max(0, config.ALLO_WALK_CAPACITY - await _taken(session, walk_key))


async def _active_pass(session, uid: int):
    """Действующий абонемент пользователя: (booking, осталось, действует_до) или
    (None, 0, None)."""
    p = (await session.scalars(
        select(AlloBooking).where(
            AlloBooking.user_id == uid, AlloBooking.plan == "pass",
            AlloBooking.status == "paid").order_by(AlloBooking.paid_at.desc()))).first()
    if not p or not p.paid_at:
        return None, 0, None
    valid_until = p.paid_at + timedelta(days=config.ALLO_PASS_VALID_DAYS)
    if datetime.utcnow() > valid_until:
        return None, 0, None
    used = await session.scalar(
        select(func.count()).select_from(AlloBooking).where(
            AlloBooking.user_id == uid, AlloBooking.plan == "use",
            AlloBooking.status == "paid", AlloBooking.created_at >= p.paid_at)) or 0
    remaining = config.ALLO_PASS_CREDITS - used
    return (p, remaining, valid_until) if remaining > 0 else (None, 0, None)


async def _user_booked_dates(session, uid: int) -> set:
    """Даты, на которые пользователь уже записан (разово или абонементом)."""
    rows = (await session.scalars(
        select(AlloBooking.walk_key).where(
            AlloBooking.user_id == uid, AlloBooking.plan.in_(_SEAT_PLANS),
            AlloBooking.status.in_(("paid", "pending"))))).all()
    return set(rows)


# --- Реферальная программа («приведи друга») ---------------------------------

def _referral_link(uid: int) -> str:
    return f"https://t.me/{config.bot_username()}?start=alloref_{uid}"


async def register_referral(referrer_uid: int, referred_uid: int) -> None:
    """Фиксируем, что referred пришёл по ссылке referrer (до первой оплаты).

    Учитываем только новых: нельзя привести себя, уже приведённого или того,
    кто уже платил за прогулки.
    """
    if not referrer_uid or referrer_uid == referred_uid:
        return
    async with get_session() as session:
        exists = await session.scalar(
            select(func.count()).select_from(AlloReferral).where(
                AlloReferral.referred_uid == referred_uid))
        if exists:
            return  # этого человека уже кто-то привёл (первая ссылка побеждает)
        paid = await session.scalar(
            select(func.count()).select_from(AlloBooking).where(
                AlloBooking.user_id == referred_uid, AlloBooking.status == "paid"))
        if paid:
            return  # уже участник — не считаем за реферала
        session.add(AlloReferral(referrer_uid=referrer_uid,
                                 referred_uid=referred_uid, status="pending"))
        await session.commit()


async def _referral_credits(session, uid: int) -> int:
    """Сколько доступных €-бонусов (earned) у приводящего."""
    return await session.scalar(
        select(func.count()).select_from(AlloReferral).where(
            AlloReferral.referrer_uid == uid, AlloReferral.status == "earned")) or 0


async def _maybe_earn_referral(bot, referred_uid: int) -> None:
    """Приведённый впервые оплатил → приводящий получает €-бонус."""
    async with get_session() as session:
        ref = (await session.scalars(select(AlloReferral).where(
            AlloReferral.referred_uid == referred_uid,
            AlloReferral.status == "pending"))).first()
        if ref is None:
            return
        ref.status = "earned"
        referrer = ref.referrer_uid
        await session.commit()
        bal = await _referral_credits(session, referrer)
    total = bal * config.ALLO_REFERRAL_BONUS
    try:
        await bot.send_message(
            referrer,
            f"🎉 Твой друг записался на Allo Walks — тебе бонус "
            f"<b>+€{config.ALLO_REFERRAL_BONUS}</b>!\nНакоплено: <b>€{total}</b> — "
            "спишутся автоматически при следующей оплате прогулки.")
    except Exception:  # noqa: BLE001
        pass


async def _reserve_credits(session, uid: int, amount: str, booking_id: int):
    """Резервирует бонусы под оплату. Возвращает (сумма_к_оплате_str, скидка_int)."""
    try:
        amt = float(amount)
    except (TypeError, ValueError):
        return amount, 0
    have = await _referral_credits(session, uid)
    if have <= 0:
        return amount, 0
    room = max(0, int((amt - config.ALLO_MIN_CHARGE) // config.ALLO_REFERRAL_BONUS))
    k = min(have, room)
    if k <= 0:
        return amount, 0
    rows = (await session.scalars(select(AlloReferral).where(
        AlloReferral.referrer_uid == uid, AlloReferral.status == "earned")
        .limit(k))).all()
    for r in rows:
        r.status = "reserved"
        r.booking_id = booking_id
    await session.commit()
    discount = k * config.ALLO_REFERRAL_BONUS
    return f"{amt - discount:.2f}", discount


async def _settle_credits(session, booking_id: int, paid: bool) -> None:
    """После оплаты reserved→spent; при отмене reserved→earned (вернуть)."""
    rows = (await session.scalars(select(AlloReferral).where(
        AlloReferral.booking_id == booking_id,
        AlloReferral.status == "reserved"))).all()
    for r in rows:
        if paid:
            r.status = "spent"
        else:
            r.status = "earned"
            r.booking_id = None
    if rows:
        await session.commit()


# --- Экран Allo Walks --------------------------------------------------------

def _short_date(w: dict) -> str:
    return w["date"].split(" · ")[0]


async def show_allo(message: Message, state: FSMContext) -> None:
    await state.clear()
    if not config.payments_enabled():
        await message.answer("Запись временно недоступна 🙏 Напиши нам через /contact.",
                             reply_markup=main_menu())
        return
    uid = message.from_user.id
    async with get_session() as session:
        pass_b, remaining, valid_until = await _active_pass(session, uid)
        rem = {w["key"]: await _remaining(session, w["key"]) for w in config.ALLO_WALKS}
        booked = await _user_booked_dates(session, uid)

    if pass_b:
        rows = []
        for w in config.ALLO_WALKS:
            label = f"📅 {_short_date(w)} · {w['title']}"
            if w["key"] in booked:
                rows.append([InlineKeyboardButton(text=f"✅ {label} — ты записан",
                                                  callback_data="allo:booked")])
            elif rem[w["key"]] > 0:
                rows.append([InlineKeyboardButton(text=label,
                                                  callback_data=f"allo:use:{w['key']}")])
            else:
                rows.append([InlineKeyboardButton(text=f"🚫 {label} — мест нет",
                                                  callback_data="allo:full")])
        rows.append([InlineKeyboardButton(text="📜 Правила", callback_data="allo:terms")])
        await message.answer(
            f"🎟 <b>Твой абонемент Allo Walks</b>\nОсталось прогулок: "
            f"<b>{remaining} из {config.ALLO_PASS_CREDITS}</b> · действует до "
            f"{valid_until:%d.%m.%Y}\n\nВыбери прогулку — спишем одну из абонемента 👇",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
            disable_web_page_preview=True)
        return

    rows = []
    for w in config.ALLO_WALKS:
        label = f"📅 {_short_date(w)} · {w['title']} · €{_p(config.ALLO_PRICE_SINGLE)}"
        if w["key"] in booked:
            rows.append([InlineKeyboardButton(text=f"✅ {_short_date(w)} · {w['title']} — ты записан",
                                              callback_data="allo:booked")])
        elif rem[w["key"]] > 0:
            rows.append([InlineKeyboardButton(text=label, callback_data=f"allo:pick:{w['key']}")])
        else:
            rows.append([InlineKeyboardButton(text=f"🚫 {_short_date(w)} · {w['title']} — мест нет",
                                              callback_data="allo:full")])
    rows.append([InlineKeyboardButton(
        text=f"🎟 Абонемент · {config.ALLO_PASS_CREDITS} прогулки · €{_p(config.ALLO_PRICE_PASS)}",
        callback_data="allo:pick:pass")])
    rows.append([InlineKeyboardButton(
        text=f"🎁 Привести друга (+€{config.ALLO_REFERRAL_BONUS} тебе)",
        callback_data="allo:invite")])
    rows.append([InlineKeyboardButton(text="📜 Правила Allo Walks", callback_data="allo:terms")])
    await message.answer(
        ALLO_INTRO.format(cap=config.ALLO_WALK_CAPACITY,
                          single=_p(config.ALLO_PRICE_SINGLE),
                          pass_=_p(config.ALLO_PRICE_PASS),
                          credits=config.ALLO_PASS_CREDITS),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        disable_web_page_preview=True)


@router.message(Command("allo"))
async def cmd_allo(message: Message, state: FSMContext) -> None:
    await show_allo(message, state)


@router.callback_query(F.data == "allo:menu")
async def allo_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await show_allo(callback.message, state)


@router.callback_query(F.data == "allo:full")
async def allo_full(callback: CallbackQuery) -> None:
    await callback.answer("На эту прогулку мест уже нет 😔 Выбери другую дату.",
                          show_alert=True)


@router.callback_query(F.data == "allo:booked")
async def allo_booked(callback: CallbackQuery) -> None:
    await callback.answer("Ты уже записан на эту прогулку ✅", show_alert=True)


@router.callback_query(F.data == "allo:terms")
async def allo_terms(callback: CallbackQuery) -> None:
    await callback.message.answer(_terms_text(), disable_web_page_preview=True)
    await callback.answer()


@router.callback_query(F.data == "allo:invite")
async def allo_invite(callback: CallbackQuery) -> None:
    uid = callback.from_user.id
    async with get_session() as session:
        credits = await _referral_credits(session, uid)
    bal = credits * config.ALLO_REFERRAL_BONUS
    link = _referral_link(uid)
    bonus = config.ALLO_REFERRAL_BONUS
    text = (f"🎁 <b>Приведи друга — получи €{bonus}</b>\n\n"
            "Поделись своей ссылкой. Когда друг запишется и оплатит прогулку, тебе "
            f"начислится <b>€{bonus}</b> — они спишутся автоматически при твоей "
            "следующей оплате.\n\n"
            f"Твоя ссылка:\n{link}")
    if bal:
        text += f"\n\n💰 Уже накоплено: <b>€{bal}</b>."
    await callback.message.answer(text, disable_web_page_preview=True,
                                  reply_markup=main_menu())
    await callback.answer()


def _walk_title(key: str) -> str:
    if key == "pass":
        return f"Абонемент на {config.ALLO_PASS_CREDITS} прогулки"
    w = config.allo_walk(key)
    return f"{w['date']} · {w['title']}" if w else key


def _walk_card(key: str) -> str:
    w = config.allo_walk(key)
    return (f"📅 <b>{w['date']}</b>\n<b>Allo Walks: {w['title']}</b>\n\n"
            f"📍 Сбор: {w['meet']}\n🏁 Финиш: {w['finish']}\n⏱ Длительность: {w['dur']}\n"
            f"👥 Группа: до {config.ALLO_WALK_CAPACITY} человек\n\n{w['desc']}")


# --- Списание прогулки из абонемента ----------------------------------------

@router.callback_query(F.data.startswith("allo:use:"))
async def allo_use(callback: CallbackQuery, state: FSMContext) -> None:
    key = callback.data.split(":", 2)[2]
    if not config.allo_walk(key):
        await callback.answer("Прогулка не найдена", show_alert=True)
        return
    uid = callback.from_user.id
    async with get_session() as session:
        pass_b, remaining, _vu = await _active_pass(session, uid)
        booked = await _user_booked_dates(session, uid)
        free = await _remaining(session, key) > 0
    if not pass_b:
        await callback.answer("Абонемент не активен", show_alert=True)
        return
    if key in booked:
        await callback.answer("Ты уже записан на эту прогулку ✅", show_alert=True)
        return
    if not free:
        await callback.answer("Мест уже нет 😔", show_alert=True)
        return
    await callback.message.answer(
        _walk_card(key) + f"\n\nСписать одну прогулку из абонемента "
        f"(останется {remaining - 1})?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Записаться (списать 1)",
                                  callback_data=f"allo:useok:{key}")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="allo:menu")]]),
        disable_web_page_preview=True)
    await callback.answer()


@router.callback_query(F.data.startswith("allo:useok:"))
async def allo_useok(callback: CallbackQuery, state: FSMContext) -> None:
    key = callback.data.split(":", 2)[2]
    uid = callback.from_user.id
    if not config.allo_walk(key):
        await callback.answer("Прогулка не найдена", show_alert=True)
        return
    async with get_session() as session:
        pass_b, remaining, _vu = await _active_pass(session, uid)
        booked = await _user_booked_dates(session, uid)
        free = await _remaining(session, key) > 0
        if not pass_b or key in booked or not free:
            await callback.answer(
                "Не получилось: абонемент/место недоступны. Обнови /allo.",
                show_alert=True)
            return
        session.add(AlloBooking(
            walk_key=key, plan="use", user_id=uid,
            username=callback.from_user.username, first_name=callback.from_user.first_name,
            email=pass_b.email, amount="0.00", status="paid", agreed=True,
            paid_at=datetime.utcnow()))
        await session.commit()
    await callback.answer("Записал ✅")
    w = config.allo_walk(key)
    await callback.message.answer(
        f"✅ Записал по абонементу!\n\n📅 {w['date']} — <b>{w['title']}</b>\n"
        f"📍 Сбор: {w['meet']}\n\nБлиже к дате напомним детали. До встречи! 🚶",
        reply_markup=main_menu(), disable_web_page_preview=True)
    await _notify_admins(callback.bot,
                         f"🚶 Списание абонемента: {_walk_title(key)}\n"
                         f"{callback.from_user.first_name or ''} "
                         f"@{callback.from_user.username or '—'} · осталось {remaining - 1}")


# --- Покупка (разовая или абонемент) ----------------------------------------

def _pick_kb(key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Принять правила и записаться",
                              callback_data=f"allo:agree:{key}")],
        [InlineKeyboardButton(text="📜 Правила", callback_data="allo:terms"),
         InlineKeyboardButton(text="⬅️ Назад", callback_data="allo:menu")]])


def _pass_card() -> str:
    return (f"🎟 <b>Абонемент Allo Walks</b>\n\n"
            f"{config.ALLO_PASS_CREDITS} прогулки за <b>€{_p(config.ALLO_PRICE_PASS)}</b> "
            "(с BTW). Прогулки — на твой выбор из доступных дат, потратить можно в "
            f"течение 2 месяцев с оплаты.\n\nПосле оплаты открой Allo Walks и выбирай "
            "даты — за каждую спишется одна прогулка.\n\n"
            "🌟 <b>Allo Walks — это только начало</b> нашего нового проекта <b>Allo</b> — "
            "закрытый клуб, больше чем прогулки. Поэтому в первые 2 месяца действует "
            f"особый бонус: <b>€{_p(config.ALLO_PRICE_PASS)} за абонемент зачтём в будущее "
            "членство клуба «Всё включено».</b> Возьмёшь абонемент сейчас — считай, уже "
            "вложился в клуб.\n\n"
            "Оплачивая, ты принимаешь Правила Allo Walks.")


@router.callback_query(F.data.startswith("allo:pick:"))
async def allo_pick(callback: CallbackQuery, state: FSMContext) -> None:
    key = callback.data.split(":", 2)[2]
    if key != "pass" and not config.allo_walk(key):
        await callback.answer("Прогулка не найдена", show_alert=True)
        return
    if key == "pass":
        await callback.message.answer(_pass_card(), reply_markup=_pick_kb(key),
                                      disable_web_page_preview=True)
        await callback.answer()
        return
    async with get_session() as session:
        free = await _remaining(session, key) > 0
        booked = key in await _user_booked_dates(session, callback.from_user.id)
    if booked:
        await callback.answer("Ты уже записан на эту прогулку ✅", show_alert=True)
        return
    if not free:
        await callback.answer("Мест уже нет 😔 Выбери другую дату.", show_alert=True)
        await show_allo(callback.message, state)
        return
    await callback.message.answer(
        _walk_card(key) + f"\n\n💶 <b>€{_p(config.ALLO_PRICE_SINGLE)}</b> (с BTW). "
        "Оплачивая, ты принимаешь Правила Allo Walks.",
        reply_markup=_pick_kb(key), disable_web_page_preview=True)
    await callback.answer()


@router.callback_query(F.data.startswith("allo:agree:"))
async def allo_agree(callback: CallbackQuery, state: FSMContext) -> None:
    key = callback.data.split(":", 2)[2]
    await state.set_state(AlloBook.waiting_email)
    await state.update_data(allo_walk=key)
    await callback.message.answer(
        "Отлично! Остался один шаг: на какой <b>e-mail</b> прислать подтверждение и "
        "чек?\n<i>Например: mail@example.com</i>", reply_markup=cancel_menu())
    await callback.answer("Правила приняты ✅")


@router.message(AlloBook.waiting_email)
async def allo_email(message: Message, state: FSMContext) -> None:
    email = (message.text or "").strip()
    if "@" not in email or "." not in email or " " in email:
        await message.answer("Похоже, это не e-mail 🙂 Напиши адрес вида mail@example.com")
        return
    data = await state.get_data()
    key = data.get("allo_walk")
    await state.clear()
    is_pass = key == "pass"
    if not is_pass and not config.allo_walk(key):
        await message.answer("Прогулка не найдена — начни заново: /allo",
                             reply_markup=main_menu())
        return
    plan = "pass" if is_pass else "single"
    amount = config.ALLO_PRICE_PASS if is_pass else config.ALLO_PRICE_SINGLE

    async with get_session() as session:
        if not is_pass and not await _remaining(session, key) > 0:
            await message.answer("Пока ты вводил e-mail, места закончились 😔 "
                                 "Выбери другую дату: /allo", reply_markup=main_menu())
            return
        booking = AlloBooking(
            walk_key=key, plan=plan, user_id=message.from_user.id,
            username=message.from_user.username, first_name=message.from_user.first_name,
            email=email, amount=amount, status="pending", agreed=True)
        session.add(booking)
        await session.commit()
        await session.refresh(booking)
        bid = booking.id
        # Списываем реферальные бонусы (если есть) — уменьшаем сумму к оплате
        pay_amount, discount = await _reserve_credits(
            session, message.from_user.id, amount, bid)

    payment = await create_payment(
        f"Allo Walks: {_walk_title(key)}",
        {"kind": "allo", "walk": key, "plan": plan,
         "booking_id": bid, "user_id": message.from_user.id, "email": email},
        pay_amount)
    if not payment or not payment.get("checkout_url"):
        # Оплата не создалась — вернём зарезервированные бонусы
        async with get_session() as session:
            await _settle_credits(session, bid, paid=False)
        await message.answer("Не удалось создать оплату 🙁 Попробуй позже или напиши "
                             "нам через /contact.", reply_markup=main_menu())
        return
    async with get_session() as session:
        b = await session.get(AlloBooking, bid)
        if b:
            b.payment_id = payment["id"]
            b.amount = pay_amount
            await session.commit()
    disc = f"\n🎁 Скидка за друзей: −€{discount}." if discount else ""
    await message.answer(
        f"К оплате: <b>€{_p(pay_amount)}</b> — {_walk_title(key)}.{disc}\n"
        "После оплаты пришлём подтверждение сюда и чек на e-mail. 👇",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=f"💳 Оплатить €{_p(pay_amount)}",
                                 url=payment["checkout_url"])]]))


# --- Подтверждение оплаты (из webhook через on_payment_paid) -----------------

async def _notify_admins(bot, text: str) -> None:
    for admin_id in config.ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, disable_web_page_preview=True)
        except Exception:  # noqa: BLE001
            pass


async def on_allo_payment_paid(bot, payment_id: str, payment: dict) -> None:
    status = payment.get("status")
    meta = payment.get("metadata") or {}
    try:
        bid = int(meta.get("booking_id"))
    except (TypeError, ValueError):
        return
    async with get_session() as session:
        booking = await session.get(AlloBooking, bid)
        if booking is None:
            return
        if status in ("failed", "canceled", "expired"):
            if booking.status == "pending":
                booking.status = "canceled"
                await session.commit()
            await _settle_credits(session, bid, paid=False)  # вернуть бонусы
            uid = booking.user_id
            try:
                await bot.send_message(
                    uid, "Оплата не прошла 🙈 Место не забронировано. Снова: /allo")
            except Exception:  # noqa: BLE001
                pass
            return
        if status != "paid" or booking.status == "paid":
            return
        booking.status = "paid"
        booking.paid_at = datetime.utcnow()
        key, plan, email = booking.walk_key, booking.plan, booking.email
        uid, first, uname = booking.user_id, booking.first_name, booking.username
        amount = booking.amount
        await session.commit()
        await _settle_credits(session, bid, paid=True)  # списать использованные бонусы

    from utils.analytics import log_event
    await log_event("allo_paid", plan)
    # Приведённый впервые оплатил → приводящий получает бонус
    await _maybe_earn_referral(bot, uid)

    if plan == "pass":
        until = (datetime.utcnow()
                 + timedelta(days=config.ALLO_PASS_VALID_DAYS))
        body = ("✅ <b>Абонемент Allo Walks активен!</b>\n\n"
                f"У тебя {config.ALLO_PASS_CREDITS} прогулки на выбор, действуют до "
                f"{until:%d.%m.%Y}. 🌟 А ещё эти €{_p(amount or config.ALLO_PRICE_PASS)} "
                "зачтутся в будущее членство закрытого клуба Allo — ты уже вложился.\n\n"
                "Открой Allo Walks (кнопка «Подробнее» или /allo) и "
                "выбери даты — за каждую спишется одна прогулка. До встречи! 🚶")
    else:
        w = config.allo_walk(key)
        body = ("✅ <b>Оплата прошла — ты записан(а)!</b>\n\n"
                f"📅 {w['date']} — <b>{w['title']}</b>\n📍 Сбор: {w['meet']}\n"
                f"🏁 Финиш: {w['finish']}\n⏱ {w['dur']}\n\n"
                "Ближе к дате напомним детали. Возьми удобную обувь, воду и одежду по "
                "погоде. До встречи! 🚶")
    try:
        await bot.send_message(uid, body, disable_web_page_preview=True)
    except Exception as e:  # noqa: BLE001
        log.warning("Не удалось отправить подтверждение Allo: %s", e)

    if email:
        try:
            from utils.invoices import send_invoice
            paid = (payment.get("amount") or {}).get("value") or amount
            await send_invoice(email, first or "Гость",
                               f"Allo Walks: {_walk_title(key)}", paid)
        except Exception as e:  # noqa: BLE001
            log.warning("Счёт Allo не отправлен: %s", e)

    await _notify_admins(
        bot, f"🚶 <b>Оплата Allo Walks</b>\n{_walk_title(key)}\n"
             f"{first or ''} @{uname or '—'} · {email} · €{_p(amount or '')}")


# --- Админ: список записей --------------------------------------------------

@router.message(Command("allobookings"), F.from_user.id.in_(config.ADMIN_IDS))
async def cmd_allobookings(message: Message, state: FSMContext) -> None:
    await state.clear()
    async with get_session() as session:
        lines = ["🚶 <b>Записи Allo Walks</b>"]
        for w in config.ALLO_WALKS:
            taken = await _taken(session, w["key"])
            rows = (await session.scalars(
                select(AlloBooking).where(
                    AlloBooking.walk_key == w["key"],
                    AlloBooking.plan.in_(_SEAT_PLANS),
                    AlloBooking.status == "paid"))).all()
            lines.append(f"\n<b>{w['date']} · {w['title']}</b> — {taken}/"
                         f"{config.ALLO_WALK_CAPACITY}")
            for r in rows:
                tag = "🎟" if r.plan == "use" else "💶"
                lines.append(f"  {tag} {r.first_name or ''} @{r.username or '—'} · {r.email}")
        passes = (await session.scalars(
            select(AlloBooking).where(AlloBooking.plan == "pass",
                                      AlloBooking.status == "paid"))).all()
        if passes:
            lines.append(f"\n<b>🎟 Куплено абонементов: {len(passes)}</b>")
    text = "\n".join(lines)
    for i in range(0, len(text), 3800):
        await message.answer(text[i:i + 3800], disable_web_page_preview=True)
