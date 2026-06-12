"""Команда /start и показ главного меню."""
from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

import config
from keyboards.menus import BTN_CANCEL, BTN_STICKERS, main_menu, stickers_button

router = Router()
# Всё «личное» меню работает только в личных чатах, не в группах
router.message.filter(F.chat.type == ChatType.PRIVATE)

WELCOME = (
    "Привет, {name}! 👋\n\n"
    "Я — голос «Подслушано в Нидерландах». Считай меня местным знакомым, "
    "который уже разобрался с BSN, налогами и вечными очередями в gemeente "
    "и теперь помогает тебе 🇳🇱\n\n"
    "С чем я пригожусь:\n"
    "📰 <b>История / сплетня</b> — расскажи анонимно, опубликуем в Instagram\n"
    "❓ <b>Вопрос</b> — закинем в предложку, ответят живые люди\n"
    "🎬 <b>Видео</b> — для авторов: твой ролик может попасть к нам\n"
    "📢 <b>Реклама</b> — соберу заявку и передам команде\n"
    "🔍 <b>Найти специалиста</b> — подберу контакт из проверенного гайда\n\n"
    "Можно жать кнопки внизу — а можно просто написать мне своими словами, "
    "я пойму. Например: <i>«ищу стоматолога в Амстердаме»</i> или "
    "<i>«как получить DigiD?»</i> 😉"
) + f"\n\n🌐 Наш сайт: {config.SITE_URL}"


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


@router.message(Command("privacy", "terms"))
async def cmd_legal(message: Message) -> None:
    """Ссылки на политику конфиденциальности и условия размещения."""
    await message.answer(
        "📄 Документы:\n"
        f"• Privacybeleid: {config.privacy_url()}\n"
        f"• Algemene voorwaarden (условия): {config.terms_url()}",
        reply_markup=main_menu(),
        disable_web_page_preview=True,
    )


@router.message(F.text == BTN_STICKERS)
async def show_stickers(message: Message) -> None:
    """Кнопка «Наши стикеры» — даём ссылку на стикерпак."""
    if not config.STICKER_PACK_URL:
        return
    await message.answer(
        "Лови наши стикеры! 🎨 Жми кнопку — добавятся в один тап 👇",
        reply_markup=stickers_button(),
    )


@router.message(F.text == BTN_CANCEL)
async def cancel(message: Message, state: FSMContext) -> None:
    """Кнопка «Отмена» — выходим из любого диалога в главное меню."""
    await state.clear()
    await message.answer(
        "Без проблем, отменил! Если передумаешь — я тут 😊",
        reply_markup=main_menu(),
    )
