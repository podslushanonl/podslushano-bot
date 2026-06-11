"""Поиск специалиста по гайду контактов (умный поиск по базе).

Бот ведёт живой диалог: если человек написал только профессию — спросит город
(и запомнит, кого ищем); если только город — спросит, кто нужен.
"""
import random

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy import select

import config
from database.db import get_session
from database.models import Specialist
from keyboards.menus import BTN_CONTACTS, cancel_menu, main_menu
from states.forms import ContactSearch
from utils.geo import CATEGORIES, NEIGHBORS, detect_category, detect_city

router = Router()

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
        f"{name}, кого тебе найти и в каком городе? 🔍\n\n"
        "Напиши обычными словами, например: "
        "<i>«нужен стоматолог в Амстердаме»</i>\n\n"
        f"Сейчас я умею искать: {categories}.",
        reply_markup=cancel_menu(),
    )


def _format(spec: Specialist) -> str:
    """Красиво оформляет одного специалиста."""
    line = f"• <b>{spec.name}</b> ({spec.city})"
    if spec.description:
        line += f"\n  {spec.description}"
    if spec.contact:
        line += f"\n  📞 {spec.contact}"
    return line


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

    # Совсем ничего не поняли — мягко подсказываем
    if not category and not city_info:
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
        city, _ = city_info
        await state.set_state(ContactSearch.waiting_for_query)
        await state.update_data(pending_city=text)
        await message.answer(
            f"Так, город понял — {city} 📍 А кто нужен? "
            "Например: стоматолог, юрист, парикмахер…",
            reply_markup=cancel_menu(),
        )
        return

    # Кто нужен — понятно, города нет. Может, город был в прошлом сообщении?
    if not city_info and data.get("pending_city"):
        city_info = detect_city(data["pending_city"])

    if not city_info:
        await state.set_state(ContactSearch.waiting_for_query)
        await state.update_data(pending_category=category)
        await message.answer(
            f"Понял, ищем — <b>{category}</b> 👌 В каком городе ты находишься?",
            reply_markup=cancel_menu(),
        )
        return

    city, province = city_info

    async with get_session() as session:
        # 1) Ищем точно в нужном городе
        in_city = (
            await session.scalars(
                select(Specialist).where(
                    Specialist.category == category, Specialist.city == city
                )
            )
        ).all()

        if in_city:
            body = "\n\n".join(_format(s) for s in in_city)
            await _finish(
                message,
                state,
                f"{random.choice(FOUND_PHRASES)}\n\n"
                f"<b>{category.capitalize()}</b> в {city}:\n\n{body}\n\n"
                "Если что-то ещё нужно — я тут 😉",
            )
            return

        # 2) В городе никого — ищем в той же провинции (другие города)
        in_province = (
            await session.scalars(
                select(Specialist).where(
                    Specialist.category == category,
                    Specialist.province == province,
                    Specialist.city != city,
                )
            )
        ).all()

        if in_province:
            body = "\n\n".join(_format(s) for s in in_province)
            await _finish(
                message,
                state,
                f"Прямо в {city} по запросу «{category}» пока никого нет, "
                f"но совсем рядом, в той же провинции ({province}), есть:\n\n{body}\n\n"
                "Надеюсь, подойдёт! 🤞",
            )
            return

        # 3) Ищем в соседних провинциях
        neighbor_provinces = NEIGHBORS.get(province, [])
        if neighbor_provinces:
            in_neighbors = (
                await session.scalars(
                    select(Specialist).where(
                        Specialist.category == category,
                        Specialist.province.in_(neighbor_provinces),
                    )
                )
            ).all()

            if in_neighbors:
                body = "\n\n".join(_format(s) for s in in_neighbors)
                await _finish(
                    message,
                    state,
                    f"В {city} и окрестностях по запросу «{category}» никого "
                    f"не нашлось, но в соседних провинциях есть:\n\n{body}\n\n"
                    "Может, кто-то из них работает онлайн или стоит поездки 🚗",
                )
                return

    # 4) Совсем ничего не нашли — предлагаем гайд на сайте
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
