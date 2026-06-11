"""Команда /start и показ главного меню."""
from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from keyboards.menus import BTN_CANCEL, main_menu

router = Router()

WELCOME = (
    "Привет, {name}! 👋\n\n"
    "Я бот «Подслушано в Нидерландах» — твой помощник по жизни в NL 🇳🇱\n\n"
    "Вот что я умею:\n"
    "📰 <b>История / сплетня</b> — пришли анонимно, поделимся в Instagram\n"
    "❓ <b>Вопрос</b> — задай вопрос в предложку\n"
    "🎬 <b>Видео</b> — для авторов контента\n"
    "📢 <b>Реклама</b> — обсудим сотрудничество\n"
    "🔍 <b>Найти специалиста</b> — подберу контакт из нашего гайда\n\n"
    "Можно жать кнопки внизу, а можно просто написать мне как человеку — "
    "например: <i>«нужен стоматолог в Амстердаме»</i> 😉"
)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    name = message.from_user.first_name or "друг"
    await message.answer(WELCOME.format(name=name), reply_markup=main_menu())


@router.message(Command("menu"))
async def cmd_menu(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Вот меню — выбирай 👇", reply_markup=main_menu())


@router.message(Command("help"))
async def cmd_help(message: Message, state: FSMContext) -> None:
    await state.clear()
    name = message.from_user.first_name or "друг"
    await message.answer(WELCOME.format(name=name), reply_markup=main_menu())


@router.message(F.text == BTN_CANCEL)
async def cancel(message: Message, state: FSMContext) -> None:
    """Кнопка «Отмена» — выходим из любого диалога в главное меню."""
    await state.clear()
    await message.answer(
        "Без проблем, отменил! Если передумаешь — я тут 😊",
        reply_markup=main_menu(),
    )
