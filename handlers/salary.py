"""Калькулятор чистой зарплаты (bruto → netto) для Нидерландов.

Расчёт делает ИИ с веб-поиском по актуальным официальным ставкам года
(belastingdienst.nl), поэтому цифры свежие. Результат — оценка (с дисклеймером).
"""
import re

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from keyboards.menus import BTN_SALARY, cancel_menu, main_menu
from states.forms import SalaryCalc
from utils.ai import ai_enabled, ai_salary
from utils.limits import allow_ai

router = Router()
router.message.filter(F.chat.type == ChatType.PRIVATE)


@router.message(Command("salary", "zarplata"))
@router.message(F.text == BTN_SALARY)
async def salary_start(message: Message, state: FSMContext) -> None:
    if not ai_enabled():
        await message.answer("Калькулятор сейчас недоступен 🙏", reply_markup=main_menu())
        return
    await state.set_state(SalaryCalc.waiting_amount)
    await message.answer(
        "🧮 Посчитаю чистую зарплату (netto).\n\n"
        "Напиши свою <b>брутто</b>-зарплату в <b>месяц</b> в евро — например <code>3500</code>.",
        reply_markup=cancel_menu(),
    )


@router.message(SalaryCalc.waiting_amount)
async def salary_amount(message: Message, state: FSMContext) -> None:
    m = re.search(r"\d[\d\s.,]*", message.text or "")
    if not m:
        await message.answer("Напиши сумму числом, например 3500 🙂")
        return
    try:
        gross = float(m.group(0).replace(" ", "").replace(",", "."))
    except ValueError:
        await message.answer("Не понял сумму 🙈 Напиши число, например 3500.")
        return
    if not (0 < gross <= 1_000_000):
        await message.answer("Похоже на опечатку 🙂 Напиши брутто в месяц, например 3500.")
        return
    await state.update_data(gross=gross)
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Обычная ставка", callback_data="salc:0"),
        InlineKeyboardButton(text="С 30%-ruling", callback_data="salc:1"),
    ]])
    await message.answer(
        f"Брутто {gross:.0f} €/мес. Применяется ли <b>30%-ruling</b> "
        "(налоговая льгота для приехавших специалистов)?",
        reply_markup=kb,
    )


@router.callback_query(SalaryCalc.waiting_amount, F.data.startswith("salc:"))
async def salary_calc(callback: CallbackQuery, state: FSMContext) -> None:
    ruling = callback.data.split(":", 1)[1] == "1"
    data = await state.get_data()
    await state.clear()
    gross = data.get("gross")
    if not gross:
        await callback.answer("Начни заново: /salary", show_alert=True)
        return
    if not allow_ai(callback.from_user.id):
        await callback.message.answer(
            "На сегодня уже много запросов 🙏 Загляни попозже.", reply_markup=main_menu()
        )
        await callback.answer()
        return
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.bot.send_chat_action(callback.message.chat.id, action="typing")
    result = await ai_salary(float(gross), ruling)
    if not result:
        await callback.message.answer(
            "Не получилось посчитать 😔 Попробуй позже.", reply_markup=main_menu()
        )
        await callback.answer()
        return
    await callback.message.answer(
        "🧮 <b>Расчёт зарплаты</b>\n\n" + result
        + "\n\n💬 Нужен точный расчёт под твой случай? Нажми «🔍 Найти специалиста» (бухгалтер).",
        reply_markup=main_menu(),
    )
    await callback.answer()
