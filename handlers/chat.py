"""Живое общение: бот отвечает на ЛЮБОЕ сообщение, даже вне меню.

Этот роутер подключается ПОСЛЕДНИМ и ловит всё, что не поймали остальные:
- здоровается в ответ на приветствие;
- понимает «спасибо», «как дела» и т.п.;
- если человек просто пишет «нужен стоматолог в Гааге» — сразу запускает поиск;
- если прислал видео без кнопки — предлагает отправить его в предложку;
- любое другое сообщение — предлагает, что с ним сделать (вопрос/история),
  чтобы человек никогда не оставался без ответа.
"""
import random

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import config
from handlers.contacts import process_query
from handlers.submissions import THANKS, create_submission, extract_content
from keyboards.menus import main_menu
from utils.ai import reply_with_ai
from utils.geo import detect_category
from utils.stickers import send_sticker

router = Router()

GREETING_WORDS = (
    "привет", "здравствуй", "здрасте", "добрый день", "добрый вечер",
    "доброе утро", "доброй ночи", "hi", "hello", "hey", "hoi", "хай",
    "салют", "ку",
)
THANKS_WORDS = ("спасибо", "благодарю", "thanks", "thank you", "bedankt", "мерси", "спс")
HOW_ARE_YOU = ("как дела", "как ты", "как жизнь", "что нового", "how are you")
BYE_WORDS = ("пока", "до свидания", "удачи", "bye", "доброй ночи", "спокойной ночи")

GREETING_REPLIES = [
    "Привет, {name}! 👋 Рад тебя видеть!",
    "Привет-привет, {name}! 😊",
    "Хой, {name}! 🇳🇱 (мы же в Нидерландах 😄)",
]
THANKS_REPLIES = [
    "Всегда пожалуйста! 😊",
    "Обращайся в любое время! 🤗",
    "Рад был помочь! Если что — я тут 👋",
]
HOW_ARE_YOU_REPLIES = [
    "У меня всё супер — целыми днями читаю ваши истории! 🤫 А у тебя как?",
    "Отлично! Погода в Нидерландах как всегда непредсказуемая, а я стабильно на связи 😄",
]
BYE_REPLIES = [
    "Пока-пока! Возвращайся, если что-то понадобится 👋",
    "До встречи! Я всегда тут 😊",
]

# Куда «пристроить» свободное сообщение
WHAT_TO_DO_KB = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="❓ Это вопрос — отправить в предложку", callback_data="chat:question")],
        [InlineKeyboardButton(text="📰 Это история — опубликуйте анонимно", callback_data="chat:story")],
        [InlineKeyboardButton(text="📋 Ничего, просто покажи меню", callback_data="chat:menu")],
    ]
)


def _matches(text: str, patterns: tuple[str, ...]) -> bool:
    return any(p in text for p in patterns)


@router.message(F.text)
async def free_chat(message: Message, state: FSMContext) -> None:
    """Любое текстовое сообщение вне меню и диалогов."""
    text = message.text.strip()
    low = text.lower()
    name = message.from_user.first_name or "друг"

    # Короткие реплики-приветствия и вежливости
    if len(low) < 35:
        if _matches(low, HOW_ARE_YOU):
            await message.answer(random.choice(HOW_ARE_YOU_REPLIES), reply_markup=main_menu())
            return
        if _matches(low, GREETING_WORDS):
            await message.answer(
                random.choice(GREETING_REPLIES).format(name=name)
                + "\n\nЧем могу помочь? Выбери в меню или просто напиши 👇",
                reply_markup=main_menu(),
            )
            return
        if _matches(low, THANKS_WORDS):
            await message.answer(random.choice(THANKS_REPLIES), reply_markup=main_menu())
            return
        if _matches(low, BYE_WORDS):
            await message.answer(random.choice(BYE_REPLIES), reply_markup=main_menu())
            return

    # Явный запрос специалиста — только если назван род занятий (стоматолог,
    # юрист…). Просто упоминание города (кафе/вопрос «в Гааге») — это НЕ поиск,
    # такое уходит к ИИ. Контакты отдаём только из проверенной базы.
    if detect_category(text):
        await process_query(message, state, text)
        return

    # Умный ответ на свободный вопрос — отдаём модели Claude
    if await reply_with_ai(message, state):
        return

    # ИИ выключен или не ответил — мягко уточняем, что сделать с сообщением
    await state.update_data(chat_text=text)
    looks_like_question = "?" in text
    if looks_like_question:
        intro = f"{name}, похоже, у тебя вопрос! 🤔"
    else:
        intro = f"{name}, я получил твоё сообщение 📩"
    await message.answer(
        f"{intro} Подскажи, что мне с ним сделать?",
        reply_markup=WHAT_TO_DO_KB,
    )


@router.message(F.video | F.photo | F.document)
async def free_media(message: Message, state: FSMContext) -> None:
    """Видео/фото без кнопки меню — предлагаем отправить в предложку."""
    text, file_id, file_type = extract_content(message)
    await state.update_data(chat_text=text, chat_file_id=file_id, chat_file_type=file_type)

    if file_type == "video":
        prompt = "Вижу видео! 🎬 Отправить его в предложку для нашего Instagram?"
    else:
        prompt = "Получил файл 📎 Что мне с ним сделать?"

    await message.answer(
        prompt,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🎬 Да, это видео в предложку", callback_data="chat:video")],
                [InlineKeyboardButton(text="📰 Это к истории — анонимно", callback_data="chat:story")],
                [InlineKeyboardButton(text="❌ Ничего, я случайно", callback_data="chat:menu")],
            ]
        ),
    )


@router.message(F.sticker)
async def on_sticker(message: Message) -> None:
    """Стикеры: админу показываем данные пака (для настройки), остальным — ответ."""
    if message.from_user and message.from_user.id in config.ADMIN_IDS:
        s = message.sticker
        await message.answer(
            "🛠 Данные стикера (для настройки бота):\n"
            f"<b>set_name:</b> <code>{s.set_name}</code>\n"
            f"<b>file_id:</b> <code>{s.file_id}</code>\n\n"
            "Чтобы бот слал стикеры из этого пака, добавь в Railway переменную "
            "<code>STICKER_SET_NAME</code> со значением из <b>set_name</b>."
        )
        return
    await message.answer(
        "Классный стикер! 😄 Я пока общаюсь текстом — "
        "напиши словами или загляни в меню 👇",
        reply_markup=main_menu(),
    )


@router.message()
async def anything_else(message: Message) -> None:
    """Голосовые и прочее — отвечаем, а не молчим."""
    await message.answer(
        "Принято! 😄 Правда, с таким форматом я пока не работаю — "
        "напиши мне текстом или выбери пункт меню 👇",
        reply_markup=main_menu(),
    )


@router.callback_query(F.data.startswith("chat:"))
async def chat_action(callback: CallbackQuery, state: FSMContext) -> None:
    """Человек выбрал, что сделать со свободным сообщением."""
    action = callback.data.split(":", 1)[1]
    data = await state.get_data()
    await state.clear()

    if action == "menu":
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer(
            "Хорошо! Вот меню — выбирай 👇", reply_markup=main_menu()
        )
        await callback.answer()
        return

    text = data.get("chat_text")
    file_id = data.get("chat_file_id")
    file_type = data.get("chat_file_type")

    if not text and not file_id:
        # Состояние потерялось (например, бот перезапускался) — просим заново
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer(
            "Ой, я потерял твоё сообщение 🙈 Пришли его ещё раз, пожалуйста!",
            reply_markup=main_menu(),
        )
        await callback.answer()
        return

    await create_submission(
        callback.bot, callback.from_user, action, text, file_id, file_type
    )
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(THANKS[action], reply_markup=main_menu())
    await send_sticker(callback.bot, callback.message.chat.id, "thanks")
    await callback.answer("Отправлено!")
