"""Платная «Афиша месяца»: организаторы добавляют мероприятие, оплачивают,
после проверки админом оно попадает в афишу и экспортируется для Instagram.

Поток: /afisha_add → анкета (название, описание, дата, город, ссылка, постер,
e-mail) → выбор месяца → оплата Mollie → webhook → заявка приходит админам на
проверку → /afisha_export собирает готовый материал для публикации.

Переиспользует платёжную связку из selfadd (create_payment + общий webhook):
обработчик оплаты вызывается из on_payment_paid по metadata kind="afisha".
"""
import html
import logging
from datetime import date

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
from database.models import EventListing, Meta
from keyboards.menus import cancel_menu, main_menu
from states.forms import AfishaSubmit
from utils.analytics import log_event
from utils.payments import create_payment

log = logging.getLogger(__name__)

router = Router()
router.message.filter(F.chat.type == ChatType.PRIVATE)

# Описание платежа (видно в Mollie/банке) — на нидерландском
DESC = "Plaatsing evenement in Podslushano-afisha"

ONLINE_WORDS = {"онлайн", "online", "по всей стране", "вся страна"}

RU_MONTHS = [
    "", "январь", "февраль", "март", "апрель", "май", "июнь",
    "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь",
]


def _month_key(y: int, m: int) -> str:
    return f"{y:04d}-{m:02d}"


def _month_label(key: str) -> str:
    """«2026-07» → «июль 2026»."""
    try:
        y, m = key.split("-")
        return f"{RU_MONTHS[int(m)]} {y}"
    except (ValueError, IndexError):
        return key


def _month_options() -> list[tuple[str, str]]:
    """Текущий и следующий месяц — обычно афишу готовят на следующий."""
    today = date.today()
    cur = (today.year, today.month)
    nxt = (today.year + (today.month // 12), today.month % 12 + 1)
    return [
        (_month_key(*cur), _month_label(_month_key(*cur))),
        (_month_key(*nxt), _month_label(_month_key(*nxt))),
    ]


def _next_month_key() -> str:
    return _month_options()[1][0]


def _month_kb() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=f"📅 {label.capitalize()}", callback_data=f"afm:{key}")]
        for key, label in _month_options()
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _pay_kb(checkout_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(
            text=f"💳 Оплатить {config.AFISHA_PRICE} {config.LISTING_CURRENCY}",
            url=checkout_url)]]
    )


def _review_kb(ev_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="✅ Опубликовать", callback_data=f"afok:{ev_id}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"afno:{ev_id}"),
        ]]
    )


def _where(ev: EventListing) -> str:
    return "по всей стране" if ev.is_nationwide else (ev.city or "—")


def _card_text(ev: EventListing) -> str:
    """Подпись-карточка мероприятия (для модерации и экспорта)."""
    lines = [f"📅 <b>{html.escape(ev.title)}</b>"]
    if ev.event_date:
        lines.append(f"🗓 {html.escape(ev.event_date)}")
    lines.append(f"📍 {html.escape(_where(ev))}")
    if ev.description:
        lines.append("")
        lines.append(html.escape(ev.description))
    if ev.link:
        lines.append("")
        lines.append(f"🔗 {html.escape(ev.link)}")
    return "\n".join(lines)


async def _safe_send(bot, chat_id, text, reply_markup=None) -> None:
    try:
        await bot.send_message(chat_id, text, reply_markup=reply_markup,
                               disable_web_page_preview=True)
    except Exception as e:  # noqa: BLE001
        log.warning("Афиша: не удалось отправить сообщение %s: %s", chat_id, e)


async def _safe_send_card(bot, chat_id, ev: EventListing, reply_markup=None) -> None:
    """Шлёт карточку мероприятия постером с подписью (или текстом, если фото нет)."""
    caption = _card_text(ev)
    try:
        if ev.photo_file_id:
            await bot.send_photo(chat_id, ev.photo_file_id, caption=caption,
                                 reply_markup=reply_markup)
            return
    except Exception as e:  # noqa: BLE001
        log.warning("Афиша: не удалось отправить постер %s: %s", chat_id, e)
    await _safe_send(bot, chat_id, caption, reply_markup)


# --- Анкета организатора -----------------------------------------------------

@router.message(Command("afisha_add"))
async def afisha_add_start(message: Message, state: FSMContext) -> None:
    if not config.payments_enabled():
        await message.answer(
            "Размещение в афише пока недоступно — скоро включим 🙌", reply_markup=main_menu()
        )
        return
    await state.set_state(AfishaSubmit.title)
    await message.answer(
        "Отлично, давайте добавим ваше мероприятие в афишу! 🎉\n\n"
        f"Размещение — <b>{config.AFISHA_PRICE} {config.LISTING_CURRENCY}</b> за одно "
        "мероприятие на месяц, с проверкой нашей командой.\n\n"
        "Шаг 1/7. Название мероприятия?",
        reply_markup=cancel_menu(),
    )


@router.message(AfishaSubmit.title)
async def afisha_title(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("Напишите название текстом 🙂")
        return
    await state.update_data(af_title=message.text.strip()[:200])
    await state.set_state(AfishaSubmit.description)
    await message.answer(
        "Шаг 2/7. Короткое описание (что за событие, чем интересно)?",
        reply_markup=cancel_menu(),
    )


@router.message(AfishaSubmit.description)
async def afisha_description(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("Напишите описание текстом 🙂")
        return
    await state.update_data(af_desc=message.text.strip())
    await state.set_state(AfishaSubmit.date)
    await message.answer(
        "Шаг 3/7. Дата или период проведения? Напр. <b>12–14 июля</b> или "
        "<b>каждую субботу июля</b>.",
        reply_markup=cancel_menu(),
    )


@router.message(AfishaSubmit.date)
async def afisha_date(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("Напишите дату текстом 🙂")
        return
    await state.update_data(af_date=message.text.strip()[:120])
    await state.set_state(AfishaSubmit.city)
    await message.answer(
        "Шаг 4/7. Город проведения? Или напишите <b>по всей стране</b>, если "
        "мероприятие онлайн/в нескольких городах.",
        reply_markup=cancel_menu(),
    )


@router.message(AfishaSubmit.city)
async def afisha_city(message: Message, state: FSMContext) -> None:
    loc = (message.text or "").strip()
    if not loc:
        await message.answer("Напишите город или «по всей стране» 🙂")
        return
    if loc.lower() in ONLINE_WORDS:
        await state.update_data(af_city="", af_nationwide=True)
    else:
        await state.update_data(af_city=loc[:100], af_nationwide=False)
    await state.set_state(AfishaSubmit.link)
    await message.answer(
        "Шаг 5/7. Ссылка на билеты или соцсети мероприятия? (или «-», чтобы пропустить)",
        reply_markup=cancel_menu(),
    )


@router.message(AfishaSubmit.link)
async def afisha_link(message: Message, state: FSMContext) -> None:
    link = (message.text or "").strip()
    await state.update_data(af_link=None if link == "-" else link[:500])
    await state.set_state(AfishaSubmit.photo)
    await message.answer(
        "Шаг 6/7. Пришлите <b>постер</b> мероприятия — картинкой (одним фото). "
        "Качественный постер обязателен 🙏",
        reply_markup=cancel_menu(),
    )


@router.message(AfishaSubmit.photo)
async def afisha_photo(message: Message, state: FSMContext) -> None:
    if not message.photo:
        await message.answer(
            "Нужен постер именно картинкой (фото) 🙂 Пришлите изображение одним фото."
        )
        return
    await state.update_data(af_photo=message.photo[-1].file_id)
    await state.set_state(AfishaSubmit.email)
    await message.answer(
        "Шаг 7/7. На какой <b>e-mail</b> прислать счёт (factuur) после оплаты?\n"
        "<i>Например: mail@example.com</i>",
        reply_markup=cancel_menu(),
    )


@router.message(AfishaSubmit.email)
async def afisha_email(message: Message, state: FSMContext) -> None:
    email = (message.text or "").strip()
    if "@" not in email or "." not in email or " " in email:
        await message.answer("Похоже, это не e-mail 🙂 Напишите адрес вида mail@example.com")
        return
    await state.update_data(af_email=email)
    await state.set_state(AfishaSubmit.month)
    await message.answer(
        "Почти готово! В афишу какого месяца разместить мероприятие?",
        reply_markup=_month_kb(),
    )


@router.callback_query(AfishaSubmit.month, F.data.startswith("afm:"))
async def afisha_month(callback: CallbackQuery, state: FSMContext) -> None:
    month_key = callback.data.split(":", 1)[1]
    valid = {k for k, _ in _month_options()}
    if month_key not in valid:
        month_key = _next_month_key()
    data = await state.get_data()
    async with get_session() as session:
        ev = EventListing(
            title=data["af_title"],
            description=data.get("af_desc"),
            link=data.get("af_link"),
            photo_file_id=data.get("af_photo"),
            city=data.get("af_city", ""),
            is_nationwide=data.get("af_nationwide", False),
            event_date=data.get("af_date"),
            month_key=month_key,
            submitter_user_id=callback.from_user.id,
            invoice_email=data.get("af_email"),
            status="awaiting_payment",
        )
        session.add(ev)
        await session.commit()
        await session.refresh(ev)
        ev_id, title = ev.id, ev.title
    await state.clear()

    payment = await create_payment(
        f"{DESC}: {title}",
        {"event_id": ev_id, "kind": "afisha"},
        config.AFISHA_PRICE,
    )
    if not payment or not payment.get("checkout_url"):
        await callback.message.answer(
            "Не получилось создать ссылку на оплату 😔 Попробуйте позже или напишите нам.",
            reply_markup=main_menu(),
        )
        await callback.answer()
        return
    async with get_session() as session:
        ev = await session.get(EventListing, ev_id)
        if ev:
            ev.payment_id = payment["id"]
            await session.commit()
    await callback.message.answer(
        f"Почти готово! 🎉 Размещение в афише на <b>{_month_label(month_key)}</b> — "
        f"<b>{config.AFISHA_PRICE} {config.LISTING_CURRENCY}</b>.\n\n"
        "После оплаты мы проверим мероприятие и добавим его в афишу — я напишу вам ✅\n\n"
        f'Оплачивая, вы соглашаетесь с <a href="{config.terms_url()}">Условиями</a> '
        f'и <a href="{config.privacy_url()}">Политикой конфиденциальности</a>.',
        reply_markup=main_menu(),
        disable_web_page_preview=True,
    )
    await callback.message.answer("👇 Кнопка для оплаты:", reply_markup=_pay_kb(payment["checkout_url"]))
    await callback.answer()


# --- Подтверждение оплаты (вызывается из webhook через on_payment_paid) ------

async def on_afisha_payment_paid(bot, payment_id: str, payment: dict) -> None:
    """Обрабатывает оплаченное размещение мероприятия в афише."""
    status = payment.get("status")
    meta = payment.get("metadata") or {}
    ev_id = meta.get("event_id")
    if not ev_id:
        return
    if status in ("failed", "canceled", "expired"):
        async with get_session() as session:
            if await session.get(Meta, f"payfail:{payment_id}"):
                return
            ev = await session.get(EventListing, int(ev_id))
            session.add(Meta(key=f"payfail:{payment_id}", value=status))
            await session.commit()
            sub = ev.submitter_user_id if ev else None
        if sub:
            await _safe_send(
                bot, sub,
                "Оплата за размещение в афише не прошла 😕 Это бывает — "
                "попробуйте ещё раз через /afisha_add.",
            )
        return
    if status != "paid":
        return  # open/pending — ждём финального статуса

    async with get_session() as session:
        if await session.get(Meta, f"pay:{payment_id}"):
            return  # webhook мог прийти повторно
        ev = await session.get(EventListing, int(ev_id))
        if ev is None:
            return
        ev.status = "pending"  # оплачено, ждёт проверки
        session.add(Meta(key=f"pay:{payment_id}", value="done"))
        await session.commit()
        sub, title, inv_email = ev.submitter_user_id, ev.title, ev.invoice_email
        ev_obj_id, month_key = ev.id, ev.month_key
    await log_event("payment", "afisha")

    # Счёт (factuur) на e-mail
    if inv_email:
        try:
            from utils.invoices import send_invoice
            desc = f"Plaatsing evenement '{title}' in Podslushano-afisha ({_month_label(month_key)})"
            ok, _ = await send_invoice(inv_email, title, desc, config.AFISHA_PRICE)
        except Exception as e:  # noqa: BLE001
            ok = False
            log.warning("Афиша: не удалось отправить счёт: %s", e)
        if not ok:
            for admin_id in config.ADMIN_IDS:
                await _safe_send(
                    bot, admin_id,
                    f"⚠️ Счёт за мероприятие «{title}» (id {ev_obj_id}) не отправлен на "
                    f"{inv_email}. Проверь Resend / дошли вручную.",
                )

    # Заявка админам на проверку — постером с кнопками
    async with get_session() as session:
        ev = await session.get(EventListing, ev_obj_id)
    for admin_id in config.ADMIN_IDS:
        await _safe_send(
            bot, admin_id,
            f"💳 <b>Оплачено мероприятие в афишу</b> ({_month_label(month_key)}) — "
            "нужна проверка:",
        )
        await _safe_send_card(bot, admin_id, ev, _review_kb(ev_obj_id))
    if sub:
        await _safe_send(
            bot, sub,
            "Оплата получена, спасибо! 🙌 Мы проверим мероприятие и добавим его в "
            "афишу — я напишу, как только всё готово ✅",
        )


# --- Модерация (только админы) ----------------------------------------------

@router.callback_query(F.data.startswith("afok:"), F.from_user.id.in_(config.ADMIN_IDS))
async def afisha_approve(callback: CallbackQuery) -> None:
    ev_id = int(callback.data.split(":", 1)[1])
    async with get_session() as session:
        ev = await session.get(EventListing, ev_id)
        if ev is None:
            await callback.answer("Мероприятие не найдено", show_alert=True)
            return
        ev.status = "approved"
        await session.commit()
        sub, title, month_key = ev.submitter_user_id, ev.title, ev.month_key
    await callback.answer("Опубликовано")
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:  # noqa: BLE001
        pass
    await callback.message.answer(f"✅ «{html.escape(title)}» в афише на {_month_label(month_key)}.")
    if sub:
        await _safe_send(
            callback.bot, sub,
            f"🎉 Готово! Ваше мероприятие «{title}» добавлено в афишу на "
            f"{_month_label(month_key)}. Спасибо!",
        )


@router.callback_query(F.data.startswith("afno:"), F.from_user.id.in_(config.ADMIN_IDS))
async def afisha_reject(callback: CallbackQuery) -> None:
    ev_id = int(callback.data.split(":", 1)[1])
    async with get_session() as session:
        ev = await session.get(EventListing, ev_id)
        if ev is None:
            await callback.answer("Мероприятие не найдено", show_alert=True)
            return
        ev.status = "rejected"
        await session.commit()
        sub, title = ev.submitter_user_id, ev.title
    await callback.answer("Отклонено")
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:  # noqa: BLE001
        pass
    await callback.message.answer(f"❌ «{html.escape(title)}» отклонено.")
    if sub:
        await _safe_send(
            callback.bot, sub,
            f"К сожалению, мероприятие «{title}» мы не добавили в афишу. "
            "Оплату вернём 🙏\n\n" + config.support_block(),
        )


# --- Экспорт афиши для Instagram (только админы) -----------------------------

@router.message(Command("afisha_export"), F.from_user.id.in_(config.ADMIN_IDS))
async def afisha_export(message: Message, state: FSMContext) -> None:
    await state.clear()
    parts = (message.text or "").split()
    month_key = parts[1] if len(parts) > 1 else _next_month_key()
    async with get_session() as session:
        rows = (
            await session.scalars(
                select(EventListing)
                .where(EventListing.month_key == month_key, EventListing.status == "approved")
                .order_by(EventListing.is_nationwide, EventListing.city, EventListing.id)
            )
        ).all()
    if not rows:
        await message.answer(
            f"За {_month_label(month_key)} одобренных мероприятий нет.\n"
            "Использование: <code>/afisha_export 2026-07</code>",
            reply_markup=main_menu(),
        )
        return
    await message.answer(
        f"🗓 <b>Афиша на {_month_label(month_key)}</b> — {len(rows)} мероприятий.\n"
        "Ниже карточки с постерами — готово для публикации в Instagram 👇"
    )
    for ev in rows:
        await _safe_send_card(message.bot, message.chat.id, ev)
