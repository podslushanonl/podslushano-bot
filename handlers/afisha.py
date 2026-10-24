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
import os
import re
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

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
DESC = "Plaatsing evenement in podslushano.nl-afisha"

ONLINE_WORDS = {"онлайн", "online", "по всей стране", "вся страна"}
# Рубрики афиши на сайте (как у событий в теме сайта)
SITE_CATEGORIES = ("концерт", "стендап", "театр", "фестиваль", "выставка", "встреча",
                   "для детей", "ярмарка", "вечеринка", "мастер-класс", "спорт", "другое")

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
    """Текущий и три следующих месяца — тот же горизонт, что у общей афиши."""
    today = date.today()
    months: list[tuple[str, str]] = []
    for offset in range(4):
        absolute = today.year * 12 + today.month - 1 + offset
        key = _month_key(absolute // 12, absolute % 12 + 1)
        months.append((key, _month_label(key)))
    return months


def _next_month_key() -> str:
    return _month_options()[1][0]


def _event_period(raw: str) -> tuple[datetime, datetime] | None:
    """Разбирает 12.08.2026 или 12–14.08.2026 в точные UTC-границы."""
    value = re.sub(r"\s+", "", (raw or "").strip()).replace("—", "-").replace("–", "-")
    single = re.fullmatch(r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})", value)
    period = re.fullmatch(
        r"(\d{1,2})-(\d{1,2})[./](\d{1,2})[./](\d{4})", value
    )
    try:
        if period:
            first, last, month, year = map(int, period.groups())
            start_day, end_day = date(year, month, first), date(year, month, last)
        elif single:
            day, month, year = map(int, single.groups())
            start_day = end_day = date(year, month, day)
        else:
            return None
    except ValueError:
        return None
    if end_day < start_day:
        return None
    tz = ZoneInfo("Europe/Amsterdam")
    starts = datetime.combine(start_day, time.min, tz).astimezone(timezone.utc).replace(tzinfo=None)
    ends = datetime.combine(end_day, time.max, tz).astimezone(timezone.utc).replace(tzinfo=None)
    return starts, ends


def _month_kb(only_key: str | None = None) -> InlineKeyboardMarkup:
    options = [
        (key, label) for key, label in _month_options()
        if only_key is None or key == only_key
    ]
    rows = [
        [InlineKeyboardButton(text=f"📅 {label.capitalize()}", callback_data=f"afm:{key}")]
        for key, label in options
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
        lines.append(f"🗓 {html.escape(ev.event_date)}"
                     + (f", {html.escape(ev.event_time)}" if ev.event_time else ""))
    lines.append(f"📍 {html.escape(_where(ev))}" + (f" · {html.escape(ev.venue)}" if ev.venue else ""))
    if ev.category:
        lines.append(f"🏷 {html.escape(ev.category)}")
    if ev.source == "site":
        lines.append(f"🌐 заявка с сайта · {html.escape(ev.invoice_email or '')}")
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
        from utils.afisha_site import poster_path
        path = poster_path(ev.id)
        if os.path.exists(path):
            from aiogram.types import BufferedInputFile
            with open(path, "rb") as fh:
                msg = await bot.send_photo(chat_id, BufferedInputFile(fh.read(), filename="poster.jpg"),
                                           caption=caption, reply_markup=reply_markup)
            if msg.photo:  # дальше шлём тот же файл по file_id
                ev.photo_file_id = msg.photo[-1].file_id
                async with get_session() as session:
                    row = await session.get(EventListing, ev.id)
                    if row:
                        row.photo_file_id = ev.photo_file_id
                        await session.commit()
            return
    except Exception as e:  # noqa: BLE001
        log.warning("Афиша: не удалось отправить постер %s: %s", chat_id, e)
    await _safe_send(bot, chat_id, caption, reply_markup)


async def _email(to: str, built: tuple[str, str, str]) -> None:
    """Письмо организатору, который подал событие с сайта (у него нет чата с ботом)."""
    try:
        from utils.invoices import send_email_message
        subject, html_body, text_body = built
        await send_email_message(to, subject, html_body, text_body)
    except Exception as e:  # noqa: BLE001
        log.warning("Афиша: письмо организатору не ушло: %s", e)


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


@router.message(Command("afisha_new"), F.from_user.id.in_(config.ADMIN_IDS))
async def afisha_manual_start(message: Message, state: FSMContext) -> None:
    """Ручное добавление мероприятия админом — без оплаты, сразу в афишу."""
    await state.set_state(AfishaSubmit.title)
    await state.update_data(af_manual=True)
    await message.answer(
        "🆕 <b>Ручное добавление в афишу</b> (без оплаты — сразу опубликуется).\n\n"
        "Название мероприятия?",
        reply_markup=cancel_menu(),
    )


@router.callback_query(F.data == "admin:afishanew", F.from_user.id.in_(config.ADMIN_IDS))
async def afisha_manual_btn(callback: CallbackQuery, state: FSMContext) -> None:
    await afisha_manual_start(callback.message, state)
    await callback.answer()


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
        "Шаг 3/7. Укажите точную дату: <b>12.08.2026</b>.\n"
        "Если событие длится несколько дней: <b>12–14.08.2026</b>.\n\n"
        "Точная дата нужна, чтобы прошедшее мероприятие автоматически исчезло из афиши.",
        reply_markup=cancel_menu(),
    )


@router.message(AfishaSubmit.date)
async def afisha_date(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    period = _event_period(raw)
    if not period:
        await message.answer(
            "Не получилось распознать дату. Напишите в формате "
            "<b>12.08.2026</b> или <b>12–14.08.2026</b> 🙂"
        )
        return
    starts_at, ends_at = period
    if ends_at <= datetime.utcnow():
        await message.answer("Эта дата уже прошла. Укажите будущую дату мероприятия 🙂")
        return
    if starts_at.date() > date.today() + timedelta(days=120) and not (await state.get_data()).get("af_manual"):
        await message.answer("Сейчас можно добавить событие максимум на четыре месяца вперёд 🙂")
        return
    await state.update_data(
        af_date=raw[:120],
        af_starts_at=starts_at.isoformat(),
        af_ends_at=ends_at.isoformat(),
    )
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
    if (await state.get_data()).get("af_manual"):
        await state.set_state(AfishaSubmit.time)
        await message.answer("Во сколько начало? Например, <b>19:30</b>. Или «-», если времени нет.",
                             reply_markup=cancel_menu())
        return
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
    data = await state.get_data()
    if data.get("af_manual"):
        # Ручное добавление админом — без e-mail и оплаты: последний шаг, рубрика в афише сайта
        await state.set_state(AfishaSubmit.category)
        await message.answer("Последний шаг: рубрика события на сайте.", reply_markup=_cat_kb())
        return
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
    data = await state.get_data()
    await state.set_state(AfishaSubmit.month)
    await message.answer(
        "Почти готово! Подтвердите месяц мероприятия:",
        reply_markup=_month_kb(data["af_starts_at"][:7]),
    )


@router.callback_query(AfishaSubmit.month, F.data.startswith("afm:"))
async def afisha_month(callback: CallbackQuery, state: FSMContext) -> None:
    month_key = callback.data.split(":", 1)[1]
    valid = {k for k, _ in _month_options()}
    if month_key not in valid:
        month_key = _next_month_key()
    data = await state.get_data()
    month_key = data["af_starts_at"][:7]
    manual = bool(data.get("af_manual"))
    async with get_session() as session:
        ev = EventListing(
            title=data["af_title"],
            description=data.get("af_desc"),
            link=data.get("af_link"),
            photo_file_id=data.get("af_photo"),
            city=data.get("af_city", ""),
            is_nationwide=data.get("af_nationwide", False),
            event_date=data.get("af_date"),
            starts_at=datetime.fromisoformat(data["af_starts_at"]),
            ends_at=datetime.fromisoformat(data["af_ends_at"]),
            month_key=month_key,
            submitter_user_id=None if manual else callback.from_user.id,
            invoice_email=data.get("af_email"),
            status="approved" if manual else "awaiting_payment",
        )
        session.add(ev)
        await session.commit()
        await session.refresh(ev)
        ev_id, title = ev.id, ev.title
    await state.clear()

    if manual:
        await callback.message.answer(
            f"✅ Добавлено в афишу на <b>{_month_label(month_key)}</b>: «{html.escape(title)}».\n"
            f"Собрать афишу месяца: <code>/afisha_export {month_key}</code>",
            reply_markup=main_menu(),
        )
        await callback.answer()
        return

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


# --- Ручное добавление: время, место, рубрика ---------------------------------

def _cat_kb() -> InlineKeyboardMarkup:
    rows, row = [], []
    for i, c in enumerate(SITE_CATEGORIES):
        row.append(InlineKeyboardButton(text=c, callback_data=f"afc:{i}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(AfishaSubmit.time)
async def afisha_time(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip().replace(".", ":")
    if raw != "-" and not re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", raw):
        await message.answer("Напишите время как <b>19:30</b> или «-» 🙂")
        return
    await state.update_data(af_time="" if raw == "-" else raw.zfill(5))
    await state.set_state(AfishaSubmit.venue)
    await message.answer("Где проходит? Площадка и адрес, например <b>Paradiso, Weteringschans 6</b>. "
                         "Или «-».", reply_markup=cancel_menu())


@router.message(AfishaSubmit.venue)
async def afisha_venue(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    if not raw:
        await message.answer("Напишите место текстом или «-» 🙂")
        return
    await state.update_data(af_venue="" if raw == "-" else raw[:200])
    await state.set_state(AfishaSubmit.link)
    await message.answer("Ссылка на билеты или страницу события? (или «-», чтобы пропустить)",
                         reply_markup=cancel_menu())


@router.callback_query(AfishaSubmit.category, F.data.startswith("afc:"), F.from_user.id.in_(config.ADMIN_IDS))
async def afisha_category(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        cat = SITE_CATEGORIES[int(callback.data.split(":", 1)[1])]
    except (ValueError, IndexError):
        await callback.answer()
        return
    data = await state.get_data()
    async with get_session() as session:
        ev = EventListing(
            title=data["af_title"], description=data.get("af_desc"), link=data.get("af_link"),
            photo_file_id=data.get("af_photo"), city=data.get("af_city", ""),
            is_nationwide=data.get("af_nationwide", False), event_date=data.get("af_date"),
            starts_at=datetime.fromisoformat(data["af_starts_at"]),
            ends_at=datetime.fromisoformat(data["af_ends_at"]),
            month_key=data["af_starts_at"][:7], status="approved", source="admin",
            event_time=data.get("af_time") or None, venue=data.get("af_venue") or None, category=cat,
        )
        session.add(ev)
        await session.commit()
        await session.refresh(ev)
        ev_id, title = ev.id, ev.title
    await state.clear()
    await callback.answer("Добавлено")
    from utils import wordpress as wp
    refreshed = await wp.refresh_site()
    url = f"{config.SITE_URL.rstrip('/')}/events/u{ev_id}/"
    await callback.message.answer(
        f"✅ «{html.escape(title)}» добавлено в афишу.\n"
        + (f"На сайте: {url}" if refreshed else
           f"На сайте появится в течение 10 минут: {url}")
        + "\n\nВсе события и удаление: /afisha_site",
        reply_markup=main_menu(), disable_web_page_preview=True,
    )


# --- Афиша на сайте: список, убрать, вернуть (только админы) ---------------------

def _short(e: dict) -> str:
    d = e.get("date", "")
    dm = f"{d[8:10]}.{d[5:7]}" if len(d) >= 10 else ""
    return f"{dm} {e.get('h', '')}".strip()[:48]


async def _site_list(message: Message) -> None:
    from utils import afisha_manage as am
    items = await am.upcoming()
    gone = await am.removed()
    rows = [[InlineKeyboardButton(text=f"✕ {_short(e)}", callback_data=f"afx:{e['key']}"[:64])] for e in items[:90]]
    rows.append([InlineKeyboardButton(text="➕ Добавить событие", callback_data="admin:afishanew")])
    if gone:
        rows.append([InlineKeyboardButton(text=f"↩ Убранные ({len(gone)})", callback_data="afhid")])
    await message.answer(
        f"🎭 <b>Афиша на сайте</b>. Будущих событий: {len(items)}.\n"
        "Нажмите на событие, чтобы убрать его с сайта. Прошедшие события уходят сами.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.message(Command("afisha_site"), F.from_user.id.in_(config.ADMIN_IDS))
async def afisha_site_cmd(message: Message, state: FSMContext) -> None:
    await state.clear()
    await _site_list(message)


@router.callback_query(F.data == "admin:afishasite", F.from_user.id.in_(config.ADMIN_IDS))
async def afisha_site_btn(callback: CallbackQuery) -> None:
    await callback.answer()
    await _site_list(callback.message)


@router.callback_query(F.data.startswith("afx:"), F.from_user.id.in_(config.ADMIN_IDS))
async def afisha_remove_ask(callback: CallbackQuery) -> None:
    from utils import afisha_manage as am
    key = callback.data.split(":", 1)[1]
    item = next((e for e in await am.upcoming() if e["key"] == key), None)
    if not item:
        await callback.answer("Этого события уже нет в афише", show_alert=True)
        return
    await callback.answer()
    await callback.message.answer(
        f"Убрать с сайта «{html.escape(item['h'])}» ({_short(item)[:5]})?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="Да, убрать", callback_data=f"afxy:{key}"[:64]),
            InlineKeyboardButton(text="Отмена", callback_data="afxn"),
        ]]),
    )


@router.callback_query(F.data == "afxn", F.from_user.id.in_(config.ADMIN_IDS))
async def afisha_remove_no(callback: CallbackQuery) -> None:
    await callback.answer("Оставили")
    try:
        await callback.message.delete()
    except Exception:  # noqa: BLE001
        pass


@router.callback_query(F.data.startswith("afxy:"), F.from_user.id.in_(config.ADMIN_IDS))
async def afisha_remove_yes(callback: CallbackQuery) -> None:
    from utils import afisha_manage as am
    key = callback.data.split(":", 1)[1]
    item = next((e for e in await am.upcoming() if e["key"] == key), None)
    if not item or not await am.remove(item):
        await callback.answer("Этого события уже нет в афише", show_alert=True)
        return
    await callback.answer("Убрано")
    await callback.message.edit_text(
        f"🗑 «{html.escape(item['h'])}» убрано с сайта. Вернуть можно в /afisha_site → «Убранные».")


@router.callback_query(F.data == "afhid", F.from_user.id.in_(config.ADMIN_IDS))
async def afisha_hidden_list(callback: CallbackQuery) -> None:
    from utils import afisha_manage as am
    gone = await am.removed()
    await callback.answer()
    if not gone:
        await callback.message.answer("Убранных событий нет.")
        return
    rows = [[InlineKeyboardButton(text=f"↩ {_short(e)}", callback_data=f"afr:{e['key']}"[:64])] for e in gone[:90]]
    await callback.message.answer("Убранные события. Нажмите, чтобы вернуть на сайт:",
                                  reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("afr:"), F.from_user.id.in_(config.ADMIN_IDS))
async def afisha_restore(callback: CallbackQuery) -> None:
    from utils import afisha_manage as am
    key = callback.data.split(":", 1)[1]
    if not await am.restore(key):
        await callback.answer("Это событие уже в афише", show_alert=True)
        return
    await callback.answer("Вернули")
    await callback.message.answer("↩ Событие снова в афише на сайте.")


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
            desc = f"Plaatsing evenement '{title}' in podslushano.nl-afisha ({_month_label(month_key)})"
            ok, _ = await send_invoice(inv_email, title, desc, config.AFISHA_PRICE,
                                      kind="afisha", item=f"«{title}»")
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
        site_email = ev.invoice_email if ev.source == "site" else None
        ev_key = f"u{ev.id}"
    await callback.answer("Опубликовано")
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:  # noqa: BLE001
        pass
    await callback.message.answer(f"✅ «{html.escape(title)}» в афише на {_month_label(month_key)}.")
    from utils import wordpress as wp
    await wp.refresh_site()
    if site_email:
        from utils.email_templates import afisha_published
        await _email(site_email, afisha_published(title=title, url=f"{config.SITE_URL.rstrip('/')}/events/{ev_key}/"))
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
        site_email = ev.invoice_email if ev.source == "site" else None
    await callback.answer("Отклонено")
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:  # noqa: BLE001
        pass
    await callback.message.answer(f"❌ «{html.escape(title)}» отклонено.")
    if site_email:
        from utils.email_templates import afisha_rejected
        await _email(site_email, afisha_rejected(title=title, contact=config.COMPANY_EMAIL))
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
