"""Админ-панель: управление базой специалистов прямо из бота.

Доступно только администраторам (config.ADMIN_IDS) и только в личке.
Команда /admin открывает панель: добавить специалиста, посмотреть добавленные
вручную, найти и удалить.
"""
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
from sqlalchemy import or_, select

import config
from database.db import get_session
from database.models import Specialist
from keyboards.menus import cancel_menu, main_menu
from states.forms import AdminAddSpecialist, AdminFind
from utils.ai import extract_specialist_query
from utils.geo import CATEGORIES, NEIGHBORS, detect_category, detect_city, province_of_city

router = Router()
# Только админы и только в личке
router.message.filter(F.chat.type == ChatType.PRIVATE, F.from_user.id.in_(config.ADMIN_IDS))
router.callback_query.filter(F.from_user.id.in_(config.ADMIN_IDS))

ONLINE_WORDS = {"онлайн", "online", "онлайн по всей стране", "по всей стране"}


def _admin_panel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Добавить специалиста", callback_data="admin:add")],
            [InlineKeyboardButton(text="📋 Добавленные вручную", callback_data="admin:list")],
            [InlineKeyboardButton(text="🔎 Найти и удалить", callback_data="admin:find")],
        ]
    )


def _del_button(spec_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🗑 Удалить", callback_data=f"admindel:{spec_id}")]]
    )


def _where(sp: Specialist) -> str:
    if sp.is_online:
        return "онлайн"
    return sp.city or sp.province or "—"


@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        "🛠 <b>Админ-панель.</b> Управление базой специалистов.\nЧто делаем?",
        reply_markup=_admin_panel(),
    )


# --- Добавление специалиста (пошагово) --------------------------------------

@router.callback_query(F.data == "admin:add")
async def add_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminAddSpecialist.name)
    await callback.message.answer(
        "➕ <b>Новый специалист.</b>\n\nШаг 1/5. Имя или название?",
        reply_markup=cancel_menu(),
    )
    await callback.answer()


@router.message(AdminAddSpecialist.name)
async def add_name(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("Напиши имя/название текстом 🙂")
        return
    await state.update_data(sp_name=message.text.strip())
    await state.set_state(AdminAddSpecialist.category)
    cats = ", ".join(CATEGORIES.keys())
    await message.answer(
        f"Шаг 2/5. Категория? Напиши одну из:\n\n{cats}",
        reply_markup=cancel_menu(),
    )


@router.message(AdminAddSpecialist.category)
async def add_category(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    cat = detect_category(text)
    if not cat:
        cat = next((c for c in CATEGORIES if c.lower() == text.lower()), None)
    if not cat:
        await message.answer(
            "Не распознал категорию 🤔 Напиши точнее, например «юрист» или «стоматолог».",
            reply_markup=cancel_menu(),
        )
        return
    await state.update_data(sp_category=cat)
    await state.set_state(AdminAddSpecialist.location)
    await message.answer(
        f"Категория: <b>{cat}</b> ✅\n\n"
        "Шаг 3/5. Город? Или напиши <b>онлайн</b>, если работает по всей стране.",
        reply_markup=cancel_menu(),
    )


@router.message(AdminAddSpecialist.location)
async def add_location(message: Message, state: FSMContext) -> None:
    loc = (message.text or "").strip()
    if not loc:
        await message.answer("Напиши город или «онлайн» 🙂")
        return
    if loc.lower() in ONLINE_WORDS:
        await state.update_data(sp_online=True, sp_city="", sp_province="")
    else:
        known = detect_city(loc)  # каноничное имя города + провинция
        if known:
            city, province = known
        else:
            city = loc
            extracted = await extract_specialist_query(
                loc, list(CATEGORIES.keys()), list(NEIGHBORS.keys())
            )
            province = extracted.get("province") or ""
        await state.update_data(sp_online=False, sp_city=city, sp_province=province)
    await state.set_state(AdminAddSpecialist.description)
    await message.answer(
        "Шаг 4/5. Короткое описание услуг? (или «-», чтобы пропустить)",
        reply_markup=cancel_menu(),
    )


@router.message(AdminAddSpecialist.description)
async def add_description(message: Message, state: FSMContext) -> None:
    desc = (message.text or "").strip()
    await state.update_data(sp_description=None if desc == "-" else desc)
    await state.set_state(AdminAddSpecialist.contact)
    await message.answer(
        "Шаг 5/5. Контакты? (телефон / @username / email / сайт)",
        reply_markup=cancel_menu(),
    )


@router.message(AdminAddSpecialist.contact)
async def add_contact(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("Напиши контакты текстом 🙂")
        return
    data = await state.get_data()
    async with get_session() as session:
        sp = Specialist(
            name=data["sp_name"],
            category=data["sp_category"],
            city=data.get("sp_city", ""),
            province=data.get("sp_province", ""),
            description=data.get("sp_description"),
            contact=message.text.strip(),
            is_online=data.get("sp_online", False),
            status="active",
            source="admin",
        )
        session.add(sp)
        await session.commit()
        await session.refresh(sp)
    await state.clear()
    await message.answer(
        f"✅ Добавлено в гайд (#{sp.id}):\n<b>{sp.name}</b> — {sp.category}, {_where(sp)}",
        reply_markup=main_menu(),
    )


# --- Список добавленных вручную ---------------------------------------------

@router.callback_query(F.data == "admin:list")
async def list_added(callback: CallbackQuery) -> None:
    await callback.answer()
    async with get_session() as session:
        rows = (
            await session.scalars(
                select(Specialist)
                .where(Specialist.source != "seed")
                .order_by(Specialist.id.desc())
                .limit(30)
            )
        ).all()
    if not rows:
        await callback.message.answer(
            "Пока нет специалистов, добавленных вручную или через само-добавление."
        )
        return
    await callback.message.answer(f"📋 Добавленные ({len(rows)}):")
    for sp in rows:
        await callback.message.answer(
            f"#{sp.id} <b>{sp.name}</b>\n{sp.category} · {_where(sp)}\n{sp.contact or ''}",
            reply_markup=_del_button(sp.id),
        )


# --- Поиск и удаление --------------------------------------------------------

@router.callback_query(F.data == "admin:find")
async def find_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminFind.waiting_query)
    await callback.message.answer(
        "Напиши имя или слово для поиска специалиста, которого нужно удалить:",
        reply_markup=cancel_menu(),
    )
    await callback.answer()


@router.message(AdminFind.waiting_query)
async def find_run(message: Message, state: FSMContext) -> None:
    # Остаёмся в режиме поиска: можно искать и удалять подряд, выход — «❌ Отмена»
    query = (message.text or "").strip()
    if not query:
        await message.answer("Напиши слово для поиска 🙂", reply_markup=cancel_menu())
        return
    like = f"%{query}%"
    async with get_session() as session:
        rows = (
            await session.scalars(
                select(Specialist)
                .where(
                    or_(
                        Specialist.name.ilike(like),
                        Specialist.category.ilike(like),
                        Specialist.description.ilike(like),
                        Specialist.city.ilike(like),
                    )
                )
                .limit(20)
            )
        ).all()
    if not rows:
        await message.answer(
            "Никого не нашёл. Попробуй другое слово (имя, категория, город) "
            "или нажми «❌ Отмена».",
            reply_markup=cancel_menu(),
        )
        return
    await message.answer(
        f"Нашёл ({len(rows)}). Жми «🗑 Удалить» под нужным. "
        "Можно искать дальше или «❌ Отмена»."
    )
    for sp in rows:
        await message.answer(
            f"#{sp.id} <b>{sp.name}</b>\n{sp.category} · {_where(sp)}",
            reply_markup=_del_button(sp.id),
        )


@router.callback_query(F.data.startswith("admindel:"))
async def delete_spec(callback: CallbackQuery) -> None:
    spec_id = int(callback.data.split(":", 1)[1])
    async with get_session() as session:
        sp = await session.get(Specialist, spec_id)
        if sp is None:
            await callback.answer("Уже удалено", show_alert=True)
            return
        name = sp.name
        await session.delete(sp)
        await session.commit()
    await callback.message.edit_text(f"🗑 Удалено: {name}")
    await callback.answer("Удалено")
