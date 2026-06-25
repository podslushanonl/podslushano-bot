"""Бронь рекламных слотов с сайта (страница /ads) + управление датами в боте.

Поток: на странице /ads человек выбирает формат и свободную дату → оплата Mollie
→ webhook помечает слот оплаченным, шлёт счёт и уведомляет админов. Админ
закрывает/открывает даты командами /closeslot, /openslot, /slots.
"""
import logging
import re
from datetime import date, datetime, timedelta

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import select

import config
from database.db import get_session
from database.models import AdBooking, Meta
from utils.payments import create_payment, get_payment

log = logging.getLogger(__name__)

router = Router()
router.message.filter(F.chat.type == ChatType.PRIVATE)

BOOK_AHEAD_DAYS = 90
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_BLOCKING = ("pending", "paid", "closed")  # статусы, которые занимают дату

_MONTHS = ["", "января", "февраля", "марта", "апреля", "мая", "июня", "июля",
           "августа", "сентября", "октября", "ноября", "декабря"]
_WD = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]


def _is_admin(uid: int) -> bool:
    return uid in config.ADMIN_IDS


def _valid_date(s: str) -> date | None:
    if not _DATE_RE.match(s or ""):
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


_CYR = re.compile("[а-яёА-ЯЁ]")


def _has_cyrillic(s: str) -> bool:
    return bool(_CYR.search(s or ""))


def _parse_flexible(s: str) -> date | None:
    """Дата из гибких форматов: ГГГГ-ММ-ДД, ДД-ММ-ГГГГ, ДД-ММ (год подбираем)."""
    s = (s or "").strip().replace(".", "-").replace("/", "-")
    today = date.today()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d-%m"):
        try:
            d = datetime.strptime(s, fmt).date()
        except ValueError:
            continue
        if fmt == "%d-%m":
            d = d.replace(year=today.year)
            if d < today:
                d = d.replace(year=today.year + 1)
        return d
    return None


def _label(d: date) -> str:
    return f"{_WD[d.weekday()]}, {d.day} {_MONTHS[d.month]} {d.year}"


async def _taken() -> set[str]:
    """Множество занятых дат (бронь/ожидание/закрыто админом)."""
    async with get_session() as session:
        rows = (
            await session.scalars(
                select(AdBooking.date).where(AdBooking.status.in_(_BLOCKING))
            )
        ).all()
    return set(rows)


async def free_date_options() -> list[tuple[str, str]]:
    """Свободные даты на ближайшие 90 дней: [(YYYY-MM-DD, человекочитаемо)]."""
    taken = await _taken()
    out: list[tuple[str, str]] = []
    today = date.today()
    for i in range(1, BOOK_AHEAD_DAYS + 1):
        d = today + timedelta(days=i)
        s = d.isoformat()
        if s not in taken:
            out.append((s, _label(d)))
    return out


async def book_and_pay(fmt: str, opt: str, date_str: str, fields: dict) -> tuple[str | None, str]:
    """Создаёт бронь (pending) и платёж Mollie. Возвращает (checkout_url, ошибка)."""
    info = config.AD_FORMATS.get(fmt)
    option = config.ad_option(fmt, opt)
    if not info or not option:
        return None, "Неизвестный формат или длительность."
    d = _valid_date(date_str)
    today = date.today()
    if not d or d <= today or d > today + timedelta(days=BOOK_AHEAD_DAYS):
        return None, "Выберите корректную дату из ближайших 3 месяцев."
    if not fields.get("terms"):
        return None, "Подтвердите согласие с условиями сотрудничества."
    ctype = fields.get("client_type")
    if ctype not in ("person", "business"):
        return None, "Выберите тип плательщика (физлицо или компания)."
    email = (fields.get("email") or "").strip()
    if "@" not in email or "." not in email or " " in email:
        return None, "Укажите корректный e-mail для счёта."
    address = (fields.get("address") or "").strip()
    if not address:
        return None, "Укажите адрес для счёта."
    name = (fields.get("buyer_name") or "").strip()
    company = (fields.get("company") or "").strip()
    postcode = (fields.get("postcode") or "").strip()
    if ctype == "person" and not name:
        return None, "Укажите имя и фамилию."
    if ctype == "business":
        miss = [lbl for key, lbl in (
            ("company", "название компании"), ("postcode", "почтовый индекс"),
        ) if not (fields.get(key) or "").strip()]
        if miss:
            return None, "Для бизнес-счёта заполните: " + ", ".join(miss) + "."
    # Данные для счёта — только латиницей (как в документах)
    for lbl, val in (("имя/название", name or company), ("адрес", address),
                     ("индекс", postcode)):
        if val and _has_cyrillic(val):
            return None, ("Данные для счёта вводите латиницей, как в документах "
                          f"(напр. Alex Mair). Поле «{lbl}» — на английском.")
    if not config.payments_enabled():
        return None, "Оплата временно недоступна. Напишите нам напрямую."

    async with get_session() as session:
        busy = (await session.scalars(
            select(AdBooking).where(
                AdBooking.date == date_str, AdBooking.status.in_(_BLOCKING)
            )
        )).first()
        if busy:
            return None, "Эта дата уже занята — выберите другую."
        booking = AdBooking(
            date=date_str, fmt=fmt, opt=opt, status="pending",
            client_type=ctype, email=email, address=address,
            buyer_name=name or None,
            company=(fields.get("company") or "").strip() or None,
            btw=(fields.get("btw") or "").strip() or None,
            kvk=(fields.get("kvk") or "").strip() or None,
            postcode=(fields.get("postcode") or "").strip() or None,
            phone=(fields.get("phone") or "").strip() or None,
        )
        session.add(booking)
        await session.commit()
        await session.refresh(booking)
        bid = booking.id

    payment = await create_payment(
        f"Реклама «{info['name']}» ({option['label']}) — {date_str}",
        {"kind": "ad", "booking_id": bid},
        option["price"],
    )
    if not payment or not payment.get("checkout_url"):
        async with get_session() as session:
            b = await session.get(AdBooking, bid)
            if b:
                b.status = "canceled"
                await session.commit()
        return None, "Не удалось создать оплату. Попробуйте позже."
    async with get_session() as session:
        b = await session.get(AdBooking, bid)
        if b:
            b.payment_id = payment["id"]
            await session.commit()
    return payment["checkout_url"], ""


async def on_ad_payment_paid(bot, payment_id: str, payment: dict) -> None:
    """Webhook: оплата рекламного слота — подтверждаем или освобождаем."""
    meta = payment.get("metadata") or {}
    bid = meta.get("booking_id")
    status = payment.get("status")
    if not bid:
        return
    async with get_session() as session:
        if await session.get(Meta, f"adpay:{payment_id}"):
            return  # уже обработан
        b = await session.get(AdBooking, int(bid))
        if b is None:
            return
        if status in ("failed", "canceled", "expired"):
            b.status = "canceled"  # освобождаем дату
            session.add(Meta(key=f"adpay:{payment_id}", value=status))
            await session.commit()
            return
        if status != "paid":
            return  # open/pending — ждём финального статуса
        b.status = "paid"
        session.add(Meta(key=f"adpay:{payment_id}", value="done"))
        await session.commit()
        fmt, opt, dt, email, ct = b.fmt, b.opt, b.date, b.email, b.client_type
        b_name, b_co, b_btw = b.buyer_name, b.company, b.btw
        b_kvk, b_addr, b_post, b_phone = b.kvk, b.address, b.postcode, b.phone

    info = config.AD_FORMATS.get(fmt, {"name": fmt})
    option = config.ad_option(fmt, opt) or {"label": "", "price": "0"}
    paid_amount = (payment.get("amount") or {}).get("value") or option.get("price", "0")

    # Реквизиты покупателя для фактуры
    if ct == "business":
        buyer_name = b_co or "—"
        buyer_lines = [b_co, b_addr, b_post, f"BTW: {b_btw}", f"KVK: {b_kvk}", email, b_phone]
    else:
        buyer_name = b_name or "—"
        buyer_lines = [b_name, b_addr, email]
    buyer_lines = [ln for ln in buyer_lines if ln]
    desc = f"Реклама «{info['name']}» ({option['label']}) — {dt}"

    if email:
        try:
            from utils.invoices import send_invoice
            await send_invoice(email, buyer_name, desc, paid_amount, buyer_lines=buyer_lines)
        except Exception as e:  # noqa: BLE001
            log.warning("Счёт за рекламу не отправлен: %s", e)

    who = (b_co or b_name or "—")
    for admin_id in config.ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"💳 <b>Оплачена реклама</b>\n\nФормат: {info['name']} ({option['label']})\n"
                f"Дата: {dt}\nКлиент: {who} ({'бизнес' if ct == 'business' else 'физлицо'})\n"
                f"E-mail: {email or '—'}\nСумма: {paid_amount} {config.LISTING_CURRENCY}",
            )
        except Exception as e:  # noqa: BLE001
            log.warning("Не уведомил админа о рекламе: %s", e)


# --- Админ-команды управления датами ----------------------------------------

@router.message(Command("closeslot"))
async def cmd_closeslot(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        return
    tokens = (message.text or "").split()[1:]
    if not tokens:
        await message.answer(
            "Закрыть даты (можно сразу несколько):\n"
            "<code>/closeslot 26-06 27-06 2026-07-14</code>")
        return
    closed, skipped = [], []
    async with get_session() as session:
        for tok in tokens:
            d = _parse_flexible(tok)
            if not d:
                skipped.append(f"{tok} (не дата)")
                continue
            ds = d.isoformat()
            busy = (await session.scalars(select(AdBooking).where(
                AdBooking.date == ds, AdBooking.status.in_(_BLOCKING)))).first()
            if busy:
                skipped.append(f"{ds} (уже занято)")
                continue
            session.add(AdBooking(date=ds, fmt="closed", status="closed"))
            closed.append(ds)
        await session.commit()
    lines = []
    if closed:
        lines.append(f"🔒 Закрыто ({len(closed)}): " + ", ".join(sorted(closed)))
    if skipped:
        lines.append("⏭ Пропущено: " + ", ".join(skipped))
    await message.answer("\n".join(lines) or "Нечего закрывать.")


@router.message(Command("openslot"))
async def cmd_openslot(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        return
    tokens = (message.text or "").split()[1:]
    if not tokens:
        await message.answer("Открыть даты: <code>/openslot 26-06 2026-07-14</code>")
        return
    opened, total = [], 0
    async with get_session() as session:
        for tok in tokens:
            d = _parse_flexible(tok)
            if not d:
                continue
            ds = d.isoformat()
            rows = (await session.scalars(select(AdBooking).where(
                AdBooking.date == ds, AdBooking.status.in_(("closed", "pending"))))).all()
            for r in rows:
                r.status = "canceled"
            if rows:
                opened.append(ds)
                total += len(rows)
        await session.commit()
    await message.answer(
        f"🔓 Открыто: {', '.join(sorted(opened))} (снято {total}).\n"
        "<i>Оплаченные брони не трогаются.</i>" if opened
        else "Нечего открывать (свободно или есть оплаченные брони)."
    )


@router.message(Command("slots"))
async def cmd_slots(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        return
    today = date.today().isoformat()
    async with get_session() as session:
        rows = (await session.scalars(
            select(AdBooking).where(
                AdBooking.status.in_(_BLOCKING), AdBooking.date >= today
            ).order_by(AdBooking.date)
        )).all()
    if not rows:
        await message.answer("Занятых дат на ближайшее время нет — всё свободно.")
        return
    lines = ["📅 <b>Занятые даты</b>:"]
    for r in rows:
        if r.status == "closed":
            lines.append(f"• {r.date} — 🔒 закрыто")
        else:
            nm = config.AD_FORMATS.get(r.fmt, {}).get("name", r.fmt)
            mark = "✅ оплачено" if r.status == "paid" else "⏳ ждёт оплаты"
            lines.append(f"• {r.date} — {nm} ({mark})")
    lines.append("\nЗакрыть: <code>/closeslot ГГГГ-ММ-ДД</code> · "
                 "Открыть: <code>/openslot ГГГГ-ММ-ДД</code>")
    await message.answer("\n".join(lines))
