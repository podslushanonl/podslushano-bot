"""Поиск специалиста по гайду контактов (умный поиск по базе)."""
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


@router.message(F.text == BTN_CONTACTS)
async def ask_query(message: Message, state: FSMContext) -> None:
    await state.set_state(ContactSearch.waiting_for_query)
    categories = ", ".join(CATEGORIES.keys())
    await message.answer(
        "Кого ищешь и в каком городе? 🔍\n\n"
        "Например: <i>«нужен стоматолог в Амстердаме»</i>\n\n"
        f"Могу искать: {categories}.",
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
    text = message.text or ""
    category = detect_category(text)
    city_info = detect_city(text)

    # Не поняли категорию — подсказываем, что умеем искать
    if not category:
        categories = ", ".join(CATEGORIES.keys())
        await message.answer(
            "Не понял, какой специалист нужен 🤔\n"
            f"Я ищу по категориям: {categories}.\n\n"
            "Напиши, например: <i>«юрист в Роттердаме»</i>."
        )
        return

    # Категория есть, но город не указан — просим уточнить
    if not city_info:
        await message.answer(
            f"Понял — ищем «{category}». В каком городе? "
            "Напиши, пожалуйста, город."
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
                message, state, f"Вот кого нашёл — «{category}» в {city}:\n\n{body}"
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
                f"В городе {city} по запросу «{category}» пока никого нет, "
                f"но есть рядом в провинции {province}:\n\n{body}",
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
                    f"В {city} и провинции {province} по запросу «{category}» "
                    f"никого нет, но нашёл в соседних регионах:\n\n{body}",
                )
                return

    # 4) Совсем ничего не нашли — предлагаем гайд на сайте
    fallback = (
        f"К сожалению, по запросу «{category}» рядом с {city} пока никого нет "
        "в нашей базе 😔"
    )
    if config.GUIDE_URL:
        fallback += f"\n\nПосмотри полный гайд на сайте: {config.GUIDE_URL}"
    await _finish(message, state, fallback)


async def _finish(message: Message, state: FSMContext, text: str) -> None:
    """Отправляет результат и возвращает в главное меню."""
    await state.clear()
    await message.answer(text, reply_markup=main_menu(), disable_web_page_preview=True)
