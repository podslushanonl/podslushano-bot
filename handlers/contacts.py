"""Поиск специалиста по гайду контактов (умный поиск по базе).

Бот ведёт живой диалог: если человек написал только профессию — спросит город
(и запомнит, кого ищем); если только город — спросит, кто нужен.
"""
import random
from datetime import datetime

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy import or_, select

import config
from database.db import get_session
from database.models import Specialist
from keyboards.menus import BTN_CONTACTS, cancel_menu, main_menu
from states.forms import ContactSearch
from utils.ai import extract_specialist_query, reply_with_ai
from utils.geo import CATEGORIES, NEIGHBORS, detect_category, detect_city

router = Router()
# Поиск специалистов — только в личных чатах
router.message.filter(F.chat.type == ChatType.PRIVATE)

FOUND_PHRASES = [
    "Отличные новости — нашёл! 🎉",
    "Есть такой человек! 😎",
    "Нашёл, держи 👌",
]


@router.message(F.text == BTN_CONTACTS)
async def ask_query(message: Message, state: FSMContext) -> None:
    await state.set_state(ContactSearch.waiting_for_query)
    name = message.from_user.first_name or "друг"
    categories = ", ".join(CATEGORIES.keys())
    await message.answer(
        f"{name}, кого ищем и в каком городе? 🔍\n\n"
        "Напиши обычными словами — я пойму.\n"
        "<i>Например: «нужен стоматолог в Амстердаме» или «юрист в Гааге»</i>\n\n"
        f"Ищу по категориям: {categories}.",
        reply_markup=cancel_menu(),
    )


def _format(spec: Specialist) -> str:
    """Красиво оформляет одного специалиста."""
    if spec.is_online:
        where = "онлайн"
    else:
        # У многих город не указан (работают по всей провинции) — тогда провинция.
        where = spec.city or spec.province
    line = f"• <b>{spec.name}</b>" + (f" ({where})" if where else "")
    if spec.description:
        line += f"\n  {spec.description}"
    if spec.contact:
        line += f"\n  📞 {spec.contact}"
    return line


def _render(specs) -> str:
    """Оформляет список специалистов, убирая дубли одного человека (имя+контакт)."""
    seen: set[tuple[str, str]] = set()
    lines: list[str] = []
    for s in specs:
        key = (s.name.strip().lower(), (s.contact or "").strip().lower())
        if key in seen:
            continue
        seen.add(key)
        lines.append(_format(s))
    return "\n\n".join(lines)


@router.message(ContactSearch.waiting_for_query)
async def receive_query(message: Message, state: FSMContext) -> None:
    await process_query(message, state, message.text or "")


async def process_query(message: Message, state: FSMContext, text: str) -> None:
    """Разбирает запрос и ищет специалиста. Вызывается и из свободного чата.

    Помнит контекст между сообщениями: если бот уже спросил «в каком городе?»,
    то следующее сообщение («в Гааге») продолжит тот же поиск.
    """
    data = await state.get_data()
    category = detect_category(text) or data.get("pending_category")
    city_info = detect_city(text)
    # Город мог прийти прошлым сообщением (уже разобранный)
    if not city_info and data.get("pending_province"):
        city_info = (data.get("pending_city") or data["pending_province"], data["pending_province"])

    # Если ключевые слова не дали категорию ИЛИ город — спросим ИИ. Он понимает
    # синонимы/опечатки и знает провинцию даже для маленьких городов (Oisterwijk).
    if not category or not city_info:
        extracted = await extract_specialist_query(
            text, list(CATEGORIES.keys()), list(NEIGHBORS.keys())
        )
        if not category and extracted.get("category"):
            category = extracted["category"]
        if not city_info:
            known = detect_city(extracted["city"]) if extracted.get("city") else None
            if known:
                city_info = known
            elif extracted.get("province"):
                city_info = (extracted.get("city") or extracted["province"], extracted["province"])

    # Совсем не про специалиста — передаём ИИ и выходим из режима поиска
    if not category and not city_info:
        if await reply_with_ai(message, state):
            return
        categories = ", ".join(CATEGORIES.keys())
        await state.set_state(ContactSearch.waiting_for_query)
        await message.answer(
            "Хм, я не совсем понял, кто нужен 🤔 Я ищу по категориям: "
            f"{categories}.\n\n"
            "Напиши, например: <i>«юрист в Роттердаме»</i> — и я поищу.",
            reply_markup=cancel_menu(),
        )
        return

    # Город есть, а кто нужен — нет
    if not category:
        city, province = city_info
        await state.set_state(ContactSearch.waiting_for_query)
        await state.update_data(pending_city=city, pending_province=province)
        await message.answer(
            f"Так, город понял — {city} 📍 А кто нужен? "
            "Например: стоматолог, юрист, парикмахер…",
            reply_markup=cancel_menu(),
        )
        return

    # Кто нужен — понятно, города нет
    if not city_info:
        await state.set_state(ContactSearch.waiting_for_query)
        await state.update_data(pending_category=category)
        await message.answer(
            f"Понял, ищем — <b>{category}</b> 👌 В каком городе ты находишься?",
            reply_markup=cancel_menu(),
        )
        return

    city, province = city_info
    neighbor_provinces = NEIGHBORS.get(province, [])

    now = datetime.utcnow()
    async with get_session() as session:
        async def fetch(*conds):
            result = await session.scalars(
                select(Specialist).where(
                    Specialist.category == category,
                    Specialist.status == "active",
                    # бессрочные (seed/admin) или ещё оплаченные
                    or_(Specialist.paid_until.is_(None), Specialist.paid_until > now),
                    *conds,
                )
            )
            return result.all()

        online = await fetch(Specialist.is_online.is_(True))
        in_province = await fetch(
            Specialist.is_online.is_(False), Specialist.province == province
        )
        in_neighbors = (
            await fetch(
                Specialist.is_online.is_(False),
                Specialist.province.in_(neighbor_provinces),
            )
            if neighbor_provinces
            else []
        )

    # Точные совпадения по городу — вперёд списка
    in_province = sorted(in_province, key=lambda s: 0 if (city and s.city == city) else 1)
    has_exact_city = any(city and s.city == city for s in in_province)

    blocks: list[str] = []
    if in_province:
        if has_exact_city:
            head = (
                f"{random.choice(FOUND_PHRASES)}\n\n"
                f"<b>{category.capitalize()}</b> — вот кто есть в {city} и провинции {province}:"
            )
        else:
            head = (
                f"Прямо в {city} пока никого, но по запросу «{category}» "
                f"в провинции {province} есть:"
            )
        blocks.append(head + "\n\n" + _render(in_province))
    elif in_neighbors:
        blocks.append(
            f"В {city} и провинции {province} по запросу «{category}» никого нет, "
            f"но в соседних провинциях есть:\n\n" + _render(in_neighbors)
        )

    if online:
        if blocks:
            blocks.append("🌐 А ещё работают онлайн (по всей стране):\n\n" + _render(online))
        else:
            blocks.append(
                f"По запросу «{category}» рядом с {city} в базе пока никого нет, "
                f"но есть онлайн-специалисты (работают по всей стране):\n\n" + _render(online)
            )

    if blocks:
        await _finish(
            message, state, "\n\n".join(blocks) + "\n\nЕсли что-то ещё нужно — я тут 😉"
        )
        return

    # Совсем ничего не нашли — предлагаем гайд на сайте
    fallback = (
        f"Эх, по запросу «{category}» рядом с {city} в моей базе пока "
        "пусто 😔 Но база пополняется!"
    )
    if config.GUIDE_URL:
        fallback += f"\n\nЗагляни в полный гайд на нашем сайте: {config.GUIDE_URL}"
    fallback += "\n\nИ попробуй спросить позже — вдруг появится 😉"
    await _finish(message, state, fallback)


async def _finish(message: Message, state: FSMContext, text: str) -> None:
    """Отправляет результат и возвращает в главное меню."""
    await state.clear()
    await message.answer(text, reply_markup=main_menu(), disable_web_page_preview=True)
