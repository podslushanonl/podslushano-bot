"""Команда /start и показ главного меню."""
from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from keyboards.menus import BTN_CANCEL, main_menu

router = Router()

WELCOME = (
    "Привет! 👋 Это бот-помощник по Нидерландам.\n\n"
    "Чем могу помочь? Выбери пункт меню 👇\n\n"
    "📰 <b>История / сплетня</b> — пришли анонимно, мы поделимся в Instagram\n"
    "❓ <b>Вопрос</b> — задай вопрос в предложку\n"
    "🎬 <b>Видео</b> — для авторов контента\n"
    "📢 <b>Реклама</b> — по поводу сотрудничества\n"
    "🔍 <b>Найти специалиста</b> — подберём контакт из гайда"
)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(WELCOME, reply_markup=main_menu())


@router.message(Command("menu"))
async def cmd_menu(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Главное меню 👇", reply_markup=main_menu())


@router.message(F.text == BTN_CANCEL)
async def cancel(message: Message, state: FSMContext) -> None:
    """Кнопка «Отмена» — выходим из любого диалога в главное меню."""
    await state.clear()
    await message.answer("Отменено. Возвращаю в меню 👇", reply_markup=main_menu())
