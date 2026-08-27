"""Единый админ-центр: рабочая навигация без необходимости помнить slash-команды."""
from datetime import date, datetime

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select

import config
from database.db import get_session
from database.models import AdBooking

router = Router()
router.message.filter(F.chat.type == ChatType.PRIVATE, F.from_user.id.in_(config.ADMIN_IDS))
router.callback_query.filter(F.from_user.id.in_(config.ADMIN_IDS))

_BLOCKING = ("pending", "paid", "closed")


class AdminCenterInput(StatesGroup):
    close_dates = State()
    open_dates = State()


def _kb(rows):
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _home_kb():
    return _kb([
        [InlineKeyboardButton(text="📝 Контент", callback_data="ac:content"), InlineKeyboardButton(text="💰 Реклама", callback_data="ac:ads")],
        [InlineKeyboardButton(text="🎭 Афиша", callback_data="ac:events"), InlineKeyboardButton(text="📋 Гайд и объявления", callback_data="ac:guide")],
        [InlineKeyboardButton(text="👥 Пользователи", callback_data="ac:users"), InlineKeyboardButton(text="📊 Статистика", callback_data="ac:stats")],
        [InlineKeyboardButton(text="🛠 Система", callback_data="ac:system")],
        [InlineKeyboardButton(text="⚡ Быстрые действия", callback_data="ac:quick")],
    ])


def _nav():
    return [InlineKeyboardButton(text="← Назад", callback_data="ac:home"), InlineKeyboardButton(text="🏠 Админ-центр", callback_data="ac:home")]


async def _show(message: Message, text: str, markup: InlineKeyboardMarkup):
    try:
        await message.edit_text(text, reply_markup=markup)
    except Exception:
        await message.answer(text, reply_markup=markup)


@router.message(Command("admin"))
async def admin_center(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "⚙️ <b>Админ-центр</b>\n\nЗдесь только рабочие разделы. Технические команды спрятаны в «Система».",
        reply_markup=_home_kb(),
    )


@router.callback_query(F.data == "ac:home")
async def home(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await _show(callback.message, "⚙️ <b>Админ-центр</b>\n\nВыберите раздел:", _home_kb())
    await callback.answer()


@router.callback_query(F.data == "ac:quick")
async def quick(callback: CallbackQuery):
    await _show(callback.message, "⚡ <b>Быстрые действия</b>", _kb([
        [InlineKeyboardButton(text="👀 Предпросмотр постов", callback_data="ac:editorial")],
        [InlineKeyboardButton(text="📋 Заявки на рекламу", callback_data="ac:adleads")],
        [InlineKeyboardButton(text="📅 Календарь рекламы", callback_data="ac:slots")],
        [InlineKeyboardButton(text="🚫 Закрыть дату рекламы", callback_data="ac:close")],
        [InlineKeyboardButton(text="🎭 Управление афишей", callback_data="ac:events")],
        _nav(),
    ]))
    await callback.answer()


@router.callback_query(F.data == "ac:content")
async def content(callback: CallbackQuery):
    await _show(callback.message, "📝 <b>Контент</b>", _kb([
        [InlineKeyboardButton(text="🗓 Контент-план", callback_data="content:plan")],
        [InlineKeyboardButton(text="👀 Редакционные посты", callback_data="ac:editorial")],
        [InlineKeyboardButton(text="📝 Пост в канал", callback_data="admin:post")],
        [InlineKeyboardButton(text="📣 Рассылка-анонс", callback_data="admin:broadcast")],
        [InlineKeyboardButton(text="📸 Instagram-карусель", callback_data="admin:ig")],
        _nav(),
    ]))
    await callback.answer()


@router.callback_query(F.data == "ac:editorial")
async def editorial(callback: CallbackQuery):
    from utils.editorial_overrides import preview_menu
    # Используем существующий рабочий экран предпросмотра, не дублируем генератор.
    await callback.message.answer("👀 <b>Редакционные посты</b>", reply_markup=preview_menu())
    await callback.answer()


@router.callback_query(F.data == "ac:ads")
async def ads(callback: CallbackQuery):
    await _show(callback.message, "💰 <b>Реклама</b>", _kb([
        [InlineKeyboardButton(text="📋 Заявки / CRM", callback_data="ac:adleads")],
        [InlineKeyboardButton(text="📅 Занятые даты", callback_data="ac:slots")],
        [InlineKeyboardButton(text="🚫 Закрыть даты", callback_data="ac:close"), InlineKeyboardButton(text="🔓 Открыть даты", callback_data="ac:open")],
        [InlineKeyboardButton(text="📊 Статистика заявок", callback_data="ac:adstats")],
        _nav(),
    ]))
    await callback.answer()


@router.callback_query(F.data == "ac:adleads")
async def adleads(callback: CallbackQuery):
    from handlers.ad_crm import _render_dashboard
    await _render_dashboard(callback.message)
    await callback.answer()


@router.callback_query(F.data == "ac:adstats")
async def adstats(callback: CallbackQuery):
    from handlers.ad_crm import _stats_text
    await callback.message.answer(await _stats_text(), reply_markup=_kb([_nav()]))
    await callback.answer()


async def _slots_text():
    today = date.today().isoformat()
    async with get_session() as session:
        rows = (await session.scalars(select(AdBooking).where(
            AdBooking.status.in_(_BLOCKING), AdBooking.date >= today
        ).order_by(AdBooking.date))).all()
    if not rows:
        return "📅 <b>Календарь рекламы</b>\n\nВсе ближайшие даты свободны."
    lines = ["📅 <b>Календарь рекламы · занятые даты</b>"]
    for r in rows:
        if r.status == "closed":
            lines.append(f"• {r.date} — 🔒 закрыто")
        else:
            name = config.AD_FORMATS.get(r.fmt, {}).get("name", r.fmt)
            status = "✅ оплачено" if r.status == "paid" else "⏳ ждёт оплаты"
            lines.append(f"• {r.date} — {name} ({status})")
    return "\n".join(lines)


@router.callback_query(F.data == "ac:slots")
async def slots(callback: CallbackQuery):
    await callback.message.answer(await _slots_text(), reply_markup=_kb([
        [InlineKeyboardButton(text="🚫 Закрыть даты", callback_data="ac:close"), InlineKeyboardButton(text="🔓 Открыть даты", callback_data="ac:open")],
        _nav(),
    ]))
    await callback.answer()


def _parse_date(token: str):
    token = token.strip().replace(".", "-").replace("/", "-")
    today = date.today()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d-%m"):
        try:
            d = datetime.strptime(token, fmt).date()
            if fmt == "%d-%m":
                d = d.replace(year=today.year)
                if d < today:
                    d = d.replace(year=today.year + 1)
            return d
        except ValueError:
            pass
    return None


@router.callback_query(F.data == "ac:close")
async def close_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminCenterInput.close_dates)
    await callback.message.answer("🚫 <b>Закрыть даты рекламы</b>\n\nОтправьте одну или несколько дат через пробел.\nНапример: <code>08.09 22.09 07.10</code>", reply_markup=_kb([_nav()]))
    await callback.answer()


@router.message(AdminCenterInput.close_dates)
async def close_dates(message: Message, state: FSMContext):
    tokens = (message.text or "").split()
    closed, skipped = [], []
    async with get_session() as session:
        for token in tokens:
            d = _parse_date(token)
            if not d:
                skipped.append(token)
                continue
            ds = d.isoformat()
            busy = (await session.scalars(select(AdBooking).where(AdBooking.date == ds, AdBooking.status.in_(_BLOCKING)))).first()
            if busy:
                skipped.append(f"{token} (уже занято)")
                continue
            session.add(AdBooking(date=ds, fmt="closed", status="closed"))
            closed.append(ds)
        await session.commit()
    await state.clear()
    text = ("🔒 Закрыто: " + ", ".join(closed) if closed else "Новых закрытых дат нет.")
    if skipped:
        text += "\n⏭ Пропущено: " + ", ".join(skipped)
    await message.answer(text, reply_markup=_kb([[InlineKeyboardButton(text="📅 Календарь рекламы", callback_data="ac:slots")], _nav()]))


@router.callback_query(F.data == "ac:open")
async def open_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminCenterInput.open_dates)
    await callback.message.answer("🔓 <b>Открыть даты рекламы</b>\n\nОтправьте даты через пробел. Оплаченные брони не будут изменены.", reply_markup=_kb([_nav()]))
    await callback.answer()


@router.message(AdminCenterInput.open_dates)
async def open_dates(message: Message, state: FSMContext):
    opened = []
    async with get_session() as session:
        for token in (message.text or "").split():
            d = _parse_date(token)
            if not d:
                continue
            ds = d.isoformat()
            rows = (await session.scalars(select(AdBooking).where(AdBooking.date == ds, AdBooking.status.in_(("closed", "pending"))))).all()
            for row in rows:
                row.status = "canceled"
            if rows:
                opened.append(ds)
        await session.commit()
    await state.clear()
    await message.answer("🔓 Открыто: " + ", ".join(opened) if opened else "Нечего открывать.", reply_markup=_kb([_nav()]))


@router.callback_query(F.data == "ac:events")
async def events(callback: CallbackQuery):
    await _show(callback.message, "🎭 <b>Афиша</b>", _kb([
        [InlineKeyboardButton(text="📅 Афиша в канал", callback_data="admin:afisha")],
        [InlineKeyboardButton(text="🆕 Добавить вручную", callback_data="admin:afishanew")],
        _nav(),
    ])); await callback.answer()


@router.callback_query(F.data == "ac:guide")
async def guide(callback: CallbackQuery):
    await _show(callback.message, "📋 <b>Гайд и объявления</b>", _kb([
        [InlineKeyboardButton(text="➕ Добавить специалиста", callback_data="admin:add")],
        [InlineKeyboardButton(text="🔎 Найти и удалить", callback_data="admin:find")],
        [InlineKeyboardButton(text="📇 Выгрузка гайда", callback_data="admin:guideexport")],
        [InlineKeyboardButton(text="📨 Напоминания продления", callback_data="admin:renewals")],
        _nav(),
    ])); await callback.answer()


@router.callback_query(F.data == "ac:users")
async def users(callback: CallbackQuery):
    await _show(callback.message, "👥 <b>Пользователи и коммуникации</b>", _kb([
        [InlineKeyboardButton(text="📣 Рассылка-анонс", callback_data="admin:broadcast")],
        [InlineKeyboardButton(text="⭐ Отзывы", callback_data="admin:reviews")],
        _nav(),
    ])); await callback.answer()


@router.callback_query(F.data == "ac:stats")
async def stats(callback: CallbackQuery):
    await _show(callback.message, "📊 <b>Статистика</b>", _kb([
        [InlineKeyboardButton(text="📊 Общая статистика", callback_data="admin:stats")],
        [InlineKeyboardButton(text="📈 Продуктовая аналитика", callback_data="admin:productstats")],
        [InlineKeyboardButton(text="💰 Рекламные заявки", callback_data="ac:adstats")],
        _nav(),
    ])); await callback.answer()


@router.callback_query(F.data == "ac:system")
async def system(callback: CallbackQuery):
    await _show(callback.message, "🛠 <b>Система</b>\n\nРедко используемые проверки. Основная работа вынесена из этого раздела.", _kb([
        [InlineKeyboardButton(text="🩺 Editorial Health", callback_data="ac:healthhelp")],
        [InlineKeyboardButton(text="📖 Технические команды", callback_data="ac:commands")],
        _nav(),
    ])); await callback.answer()


@router.callback_query(F.data == "ac:healthhelp")
async def healthhelp(callback: CallbackQuery):
    await callback.message.answer("🩺 Проверка редакционной системы: <code>/editorialhealth</code>\nКоманда SAFE и не делает платный запрос к Anthropic.", reply_markup=_kb([_nav()]))
    await callback.answer()


@router.callback_query(F.data == "ac:commands")
async def commands(callback: CallbackQuery):
    await callback.message.answer(
        "📖 <b>Технические команды</b>\n\n"
        "Они оставлены как резерв. Для ежедневной работы используйте кнопки Админ-центра.\n\n"
        "<code>/editorialhealth</code> — диагностика редакции\n"
        "<code>/closeslot</code>, <code>/openslot</code>, <code>/slots</code> — резерв управления рекламными датами\n"
        "<code>/wptest</code> — связь с WordPress\n"
        "<code>/digeststats</code> — диагностика подборок",
        reply_markup=_kb([_nav()]),
    ); await callback.answer()
