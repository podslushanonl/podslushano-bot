"""Allo Walks — запись и оплата прогулок через бота.

Флоу: ссылка ?start=allo → рассказ → выбор прогулки (или абонемента на 3) →
правила + согласие → e-mail → оплата Mollie → подтверждение + уведомление
админам. Оплата идёт через общий webhook (on_payment_paid, kind="allo").
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
from database.models import AlloBooking
from keyboards.menus import cancel_menu, main_menu
from states.forms import AlloBook
from utils.payments import create_payment

router = Router()
router.message.filter(F.chat.type == ChatType.PRIVATE)

log = logging.getLogger(__name__)

# Место брони держится за «pending» не дольше часа — потом слот снова свободен
_HOLD_MINUTES = 60


ALLO_INTRO = (
    "🚶 <b>Allo Walks</b> — прогулки для своих от Podslushano.nl 🇳🇱\n\n"
    "Небольшая группа (до {cap} человек), спокойный разговорный темп, красивые "
    "маршруты по Нидерландам. Без «круга знакомств» и давления: идём рядом, "
    "разговариваем, меняемся собеседниками, а в конце — кофе для тех, кто хочет "
    "остаться.\n\n"
    "Выбери прогулку 👇 Можно взять одну (€{single}) или абонемент на все три "
    "(€{pass_})."
)

ALLO_TERMS = (
    "📜 <b>Правила Allo Walks</b>\n\n"
    "<b>1. Что это.</b> Allo Walks — групповые прогулки на конкретную дату, "
    "организованные {company} (KVK {kvk}). Оплачивая запись, вы принимаете эти правила.\n\n"
    "<b>2. Цена и оплата.</b> €{single} за одну прогулку или €{pass_} за абонемент "
    "на три (все текущие даты). Цены включают BTW 21%. Оплата через Mollie (iDEAL, "
    "Visa, Mastercard). Место закрепляется после оплаты; в группе ограниченное число "
    "мест ({cap}).\n\n"
    "<b>3. Отмена и возврат.</b> Если вы предупредите об отмене <b>не позднее чем за "
    "24 часа</b> до начала — вернём деньги. Если предупредите позже или не придёте — "
    "возврат не делаем. После состоявшейся прогулки возврат невозможен. Это досуговая "
    "услуга на конкретную дату, поэтому 14-дневное право отзыва по закону не применяется "
    "(ст. 6:230p BW).\n\n"
    "<b>4. Если отменяем мы.</b> Если прогулку отменяет организатор (погода, слишком "
    "мало участников, форс-мажор) — предложим другую дату или вернём деньги полностью.\n\n"
    "<b>5. Абонемент на 3.</b> Даёт участие во всех трёх текущих прогулках. Именной, "
    "не передаётся. Пропущенная по вине участника прогулка не переносится и не "
    "компенсируется.\n\n"
    "<b>6. Ответственность и безопасность.</b> Участие добровольное, вы отвечаете за "
    "своё здоровье и снаряжение (удобная обувь, вода, одежда по погоде). Маршрут без "
    "спортивной нагрузки, но часть пути может идти по песку/грунтовым тропам. "
    "Организатор не несёт ответственности за травмы и утрату вещей, кроме случаев своей "
    "вины. Дети — под ответственностью сопровождающего взрослого.\n\n"
    "<b>7. Поведение.</b> Уважение к участникам и природе. Организатор вправе отказать "
    "в участии за грубое нарушение без возврата.\n\n"
    "<b>8. Данные.</b> Обрабатываем имя, e-mail и данные оплаты для брони и чека "
    "(оплату — через Mollie). Подробнее — Политика конфиденциальности.\n\n"
    "<b>9. Право и контакт.</b> Применяется право Нидерландов. Вопросы и отмены — "
    "{email}."
)


def _terms_text() -> str:
    return ALLO_TERMS.format(
        company=config.COMPANY_NAME, kvk=config.COMPANY_KVK,
        single=_p(config.ALLO_PRICE_SINGLE), pass_=_p(config.ALLO_PRICE_PASS),
        cap=config.ALLO_WALK_CAPACITY, email=config.COMPANY_EMAIL,
    )


def _p(price: str) -> str:
    """«35.00» → «35», «34.50» → «34.50» (убираем лишние нули)."""
    try:
        f = float(price)
        return str(int(f)) if f == int(f) else f"{f:.2f}"
    except ValueError:
        return price


async def _taken(session, walk_key: str) -> int:
    """Сколько мест занято на прогулке: оплаченные + свежие неоплаченные брони.

    Абонемент («pass») занимает место в каждой прогулке.
    """
    cutoff = datetime.utcnow() - timedelta(minutes=_HOLD_MINUTES)
    live = or_(
        AlloBooking.status == "paid",
        and_(AlloBooking.status == "pending", AlloBooking.created_at >= cutoff),
    )
    return await session.scalar(
        select(func.count()).select_from(AlloBooking).where(
            or_(AlloBooking.walk_key == walk_key, AlloBooking.walk_key == "pass"),
            live,
        )
    ) or 0


async def _remaining(session, walk_key: str) -> int:
    return max(0, config.ALLO_WALK_CAPACITY - await _taken(session, walk_key))


def _menu_kb(remaining: dict, pass_ok: bool) -> InlineKeyboardMarkup:
    rows = []
    for w in config.ALLO_WALKS:
        left = remaining.get(w["key"], 0)
        if left > 0:
            txt = f"📅 {w['date'].split(' · ')[0]} · {w['title']} · €{_p(config.ALLO_PRICE_SINGLE)}"
            rows.append([InlineKeyboardButton(text=txt, callback_data=f"allo:pick:{w['key']}")])
        else:
            rows.append([InlineKeyboardButton(
                text=f"🚫 {w['date'].split(' · ')[0]} · {w['title']} — мест нет",
                callback_data="allo:full")])
    if pass_ok:
        rows.append([InlineKeyboardButton(
            text=f"🎟 Все 3 прогулки (абонемент) · €{_p(config.ALLO_PRICE_PASS)}",
            callback_data="allo:pick:pass")])
    rows.append([InlineKeyboardButton(text="📜 Правила Allo Walks", callback_data="allo:terms")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def show_allo(message: Message, state: FSMContext) -> None:
    """Экран Allo Walks — открывается по ссылке ?start=allo или команде /allo."""
    await state.clear()
    if not config.payments_enabled():
        await message.answer("Запись временно недоступна 🙏 Напиши нам через /contact.",
                             reply_markup=main_menu())
        return
    async with get_session() as session:
        remaining = {w["key"]: await _remaining(session, w["key"])
                     for w in config.ALLO_WALKS}
    pass_ok = all(v > 0 for v in remaining.values()) and bool(remaining)
    await message.answer(
        ALLO_INTRO.format(cap=config.ALLO_WALK_CAPACITY,
                          single=_p(config.ALLO_PRICE_SINGLE),
                          pass_=_p(config.ALLO_PRICE_PASS)),
        reply_markup=_menu_kb(remaining, pass_ok),
        disable_web_page_preview=True,
    )


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


@router.callback_query(F.data == "allo:terms")
async def allo_terms(callback: CallbackQuery) -> None:
    await callback.message.answer(_terms_text(), disable_web_page_preview=True)
    await callback.answer()


def _walk_title(key: str) -> str:
    if key == "pass":
        return "Абонемент на 3 прогулки"
    w = config.allo_walk(key)
    return f"{w['date']} · {w['title']}" if w else key


def _pick_text(key: str) -> str:
    if key == "pass":
        lines = ["🎟 <b>Абонемент Allo Walks — 3 прогулки</b>",
                 f"Цена: <b>€{_p(config.ALLO_PRICE_PASS)}</b> (с BTW), участие во всех трёх:"]
        for w in config.ALLO_WALKS:
            lines.append(f"• {w['date']} — {w['title']} ({w['meet']})")
        lines.append("\nОплачивая, ты принимаешь Правила Allo Walks.")
        return "\n".join(lines)
    w = config.allo_walk(key)
    return (
        f"📅 <b>{w['date']}</b>\n<b>Allo Walks: {w['title']}</b>\n\n"
        f"📍 Сбор: {w['meet']}\n🏁 Финиш: {w['finish']}\n⏱ Длительность: {w['dur']}\n"
        f"👥 Группа: до {config.ALLO_WALK_CAPACITY} человек · Цена: "
        f"<b>€{_p(config.ALLO_PRICE_SINGLE)}</b> (с BTW)\n\n{w['desc']}\n\n"
        "Оплачивая, ты принимаешь Правила Allo Walks."
    )


def _pick_kb(key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Принять правила и записаться",
                              callback_data=f"allo:agree:{key}")],
        [InlineKeyboardButton(text="📜 Правила", callback_data="allo:terms"),
         InlineKeyboardButton(text="⬅️ Назад", callback_data="allo:menu")],
    ])


@router.callback_query(F.data.startswith("allo:pick:"))
async def allo_pick(callback: CallbackQuery, state: FSMContext) -> None:
    key = callback.data.split(":", 2)[2]
    if key != "pass" and not config.allo_walk(key):
        await callback.answer("Прогулка не найдена", show_alert=True)
        return
    # Проверяем места
    async with get_session() as session:
        if key == "pass":
            ok = all(await _remaining(session, w["key"]) > 0 for w in config.ALLO_WALKS)
        else:
            ok = await _remaining(session, key) > 0
    if not ok:
        await callback.answer("Мест уже нет 😔 Выбери другую дату.", show_alert=True)
        await show_allo(callback.message, state)
        return
    await callback.message.answer(_pick_text(key), reply_markup=_pick_kb(key),
                                  disable_web_page_preview=True)
    await callback.answer()


@router.callback_query(F.data.startswith("allo:agree:"))
async def allo_agree(callback: CallbackQuery, state: FSMContext) -> None:
    key = callback.data.split(":", 2)[2]
    await state.set_state(AlloBook.waiting_email)
    await state.update_data(allo_walk=key)
    await callback.message.answer(
        "Отлично! Остался один шаг: на какой <b>e-mail</b> прислать подтверждение и "
        "чек?\n<i>Например: mail@example.com</i>",
        reply_markup=cancel_menu(),
    )
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
    if key != "pass" and not config.allo_walk(key):
        await message.answer("Прогулка не найдена — начни заново: /allo",
                             reply_markup=main_menu())
        return
    plan = "pass" if key == "pass" else "single"
    amount = config.ALLO_PRICE_PASS if plan == "pass" else config.ALLO_PRICE_SINGLE

    # Ещё раз проверяем места (могли разобрать, пока человек вводил e-mail)
    async with get_session() as session:
        if plan == "pass":
            ok = all(await _remaining(session, w["key"]) > 0 for w in config.ALLO_WALKS)
        else:
            ok = await _remaining(session, key) > 0
        if not ok:
            await message.answer("Пока ты вводил e-mail, места закончились 😔 "
                                 "Выбери другую дату: /allo", reply_markup=main_menu())
            return
        booking = AlloBooking(
            walk_key=key, plan=plan, user_id=message.from_user.id,
            username=message.from_user.username, first_name=message.from_user.first_name,
            email=email, amount=amount, status="pending", agreed=True,
        )
        session.add(booking)
        await session.commit()
        await session.refresh(booking)
        bid = booking.id

    desc = f"Allo Walks: {_walk_title(key)}"
    payment = await create_payment(
        desc,
        {"kind": "allo", "walk": key, "plan": plan,
         "booking_id": bid, "user_id": message.from_user.id, "email": email},
        amount,
    )
    if not payment or not payment.get("checkout_url"):
        await message.answer("Не удалось создать оплату 🙁 Попробуй позже или напиши "
                             "нам через /contact.", reply_markup=main_menu())
        return
    async with get_session() as session:
        b = await session.get(AlloBooking, bid)
        if b:
            b.payment_id = payment["id"]
            await session.commit()
    await message.answer(
        f"К оплате: <b>€{_p(amount)}</b> — {_walk_title(key)}.\n"
        "После оплаты пришлём подтверждение сюда и чек на e-mail. 👇",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=f"💳 Оплатить €{_p(amount)}",
                                 url=payment["checkout_url"])]]),
    )


# --- Подтверждение оплаты (вызывается из webhook через on_payment_paid) ------

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
            try:
                await bot.send_message(
                    booking.user_id,
                    "Оплата не прошла 🙈 Место не забронировано. Попробовать снова: /allo")
            except Exception:  # noqa: BLE001
                pass
            return
        if status != "paid":
            return
        if booking.status == "paid":
            return  # уже обработано (webhook мог прийти повторно)
        booking.status = "paid"
        booking.paid_at = datetime.utcnow()
        key, plan, email, uid = (booking.walk_key, booking.plan,
                                 booking.email, booking.user_id)
        amount = booking.amount
        first = booking.first_name
        await session.commit()

    from utils.analytics import log_event
    await log_event("allo_paid", plan)

    # Подтверждение участнику
    if key == "pass":
        details = "\n".join(
            f"• {w['date']} — {w['title']}\n   📍 {w['meet']}" for w in config.ALLO_WALKS)
        body = ("✅ <b>Оплата прошла — ты в деле!</b>\n\n"
                f"🎟 Абонемент Allo Walks на 3 прогулки:\n{details}\n\n"
                "Перед каждой прогулкой напомним детали. Возьми удобную обувь, воду и "
                "одежду по погоде. До встречи! 🚶")
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

    # Счёт на e-mail
    if email:
        try:
            from utils.invoices import send_invoice
            paid = (payment.get("amount") or {}).get("value") or amount
            await send_invoice(email, first or "Гость",
                               f"Allo Walks: {_walk_title(key)}", paid)
        except Exception as e:  # noqa: BLE001
            log.warning("Счёт Allo не отправлен: %s", e)

    # Уведомление админам
    who = f"@{booking.username}" if booking else ""
    for admin_id in config.ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"🚶 <b>Новая запись Allo Walks</b>\n{_walk_title(key)}\n"
                f"{first or ''} {who} · {email} · €{_p(amount or '')}")
        except Exception:  # noqa: BLE001
            pass


# --- Админ: список записей --------------------------------------------------

@router.message(Command("allobookings"),
                F.from_user.id.in_(config.ADMIN_IDS))
async def cmd_allobookings(message: Message, state: FSMContext) -> None:
    await state.clear()
    async with get_session() as session:
        rows = (await session.scalars(
            select(AlloBooking).where(AlloBooking.status == "paid")
            .order_by(AlloBooking.walk_key, AlloBooking.paid_at))).all()
    if not rows:
        await message.answer("Оплаченных записей на Allo Walks пока нет.")
        return
    by_walk: dict[str, list] = {}
    for r in rows:
        by_walk.setdefault(r.walk_key, []).append(r)
    lines = [f"🚶 <b>Записи Allo Walks — оплачено: {len(rows)}</b>"]
    # Считаем занятость по датам (учитывая абонементы)
    async with get_session() as session:
        for w in config.ALLO_WALKS:
            taken = await _taken(session, w["key"])
            lines.append(f"\n<b>{w['date']} · {w['title']}</b> — занято {taken}/"
                         f"{config.ALLO_WALK_CAPACITY}")
            for r in by_walk.get(w["key"], []):
                who = f"@{r.username}" if r.username else ""
                lines.append(f"  • {r.first_name or ''} {who} · {r.email}")
        if by_walk.get("pass"):
            lines.append("\n<b>🎟 Абонементы (все 3):</b>")
            for r in by_walk["pass"]:
                who = f"@{r.username}" if r.username else ""
                lines.append(f"  • {r.first_name or ''} {who} · {r.email}")
    text = "\n".join(lines)
    for i in range(0, len(text), 3800):
        await message.answer(text[i:i + 3800], disable_web_page_preview=True)
