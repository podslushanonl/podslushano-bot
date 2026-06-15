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
import re

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from handlers.contacts import is_howto_question, process_query
from handlers.submissions import THANKS, create_submission, extract_content
from keyboards.menus import main_menu
from utils.ai import reply_with_ai
from utils.geo import detect_category

router = Router()
# Свободный чат / ИИ-диалог — только в личных чатах (в группе своя логика)
router.message.filter(F.chat.type == ChatType.PRIVATE)

GREETING_WORDS = (
    "привет", "здравствуй", "здрасте", "добрый день", "добрый вечер",
    "доброе утро", "доброй ночи", "hi", "hello", "hey", "hoi", "хай",
    "салют", "ку",
)
THANKS_WORDS = ("спасибо", "благодарю", "thanks", "thank you", "bedankt", "мерси", "спс")
HOW_ARE_YOU = ("как дела", "как ты", "как жизнь", "что нового", "how are you")
BYE_WORDS = ("пока", "до свидания", "удачи", "bye", "доброй ночи", "спокойной ночи")
# Слова-намёки на поиск специалиста — даже без точного названия профессии
SEARCH_HINTS = (
    "нужен", "нужна", "нужно", "найди", "найти", "ищу", "ищем", "посоветуй",
    "порекоменд", "контакт", "специалист", "мастер", "кто может", "подскажи кого",
)

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


def _matches_word(text: str, patterns: tuple[str, ...]) -> bool:
    """Совпадение по ЦЕЛОМУ слову/фразе (а не по подстроке).

    Нужно для коротких приветствий вроде «ку», «хай», «hi» — иначе они ловятся
    внутри обычных слов («автомой<b>ку</b>» → ложное приветствие)."""
    return any(
        re.search(rf"(?<!\w){re.escape(p)}(?!\w)", text) for p in patterns
    )


@router.message(F.text)
async def free_chat(message: Message, state: FSMContext) -> None:
    """Любое текстовое сообщение вне меню и диалогов."""
    text = message.text.strip()
    low = text.lower()
    name = message.from_user.first_name or "друг"

    # Короткие реплики-приветствия и вежливости
    if len(low) < 35:
        if _matches_word(low, HOW_ARE_YOU):
            await message.answer(random.choice(HOW_ARE_YOU_REPLIES), reply_markup=main_menu())
            return
        if _matches_word(low, GREETING_WORDS):
            await message.answer(
                random.choice(GREETING_REPLIES).format(name=name)
                + "\n\nЧем могу помочь? Выбери в меню или просто напиши 👇",
                reply_markup=main_menu(),
            )
            return
        if _matches_word(low, THANKS_WORDS):
            await message.answer(random.choice(THANKS_REPLIES), reply_markup=main_menu())
            return
        if _matches_word(low, BYE_WORDS):
            await message.answer(random.choice(BYE_REPLIES), reply_markup=main_menu())
            return

    # «Как записаться к huisarts», «как оформить zorgtoeslag», «как открыть
    # bankrekening» — это просьба объяснить ПРОЦЕСС. На неё отвечает ИИ по
    # официальным источникам, а не поиск специалиста. Ловим до быстрого пути,
    # иначе «huisarts» примется за профессию «врач» и бот спросит город.
    if is_howto_question(text) and await reply_with_ai(message, state):
        return

    # Запрос специалиста: либо явно названа профессия (быстрый путь без ИИ),
    # либо есть слова-намёки («нужен», «посоветуй», «ищу»…) — тогда категорию
    # и город разберёт ИИ внутри process_query (синонимы, опечатки). Если там
    # окажется не про специалиста — process_query сам передаст вопрос ИИ.
    if detect_category(text) or _matches(low, SEARCH_HINTS):
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
        prompt = "Получил фото 📸 Что мне с ним сделать?"

    rows = []
    # Для фото предлагаем разобрать официальное письмо
    if file_type == "photo":
        rows.append([InlineKeyboardButton(
            text="📩 Объяснить письмо (по-русски)", callback_data="letter:explain")])
    if file_type == "video":
        rows.append([InlineKeyboardButton(text="🎬 Да, это видео в предложку", callback_data="chat:video")])
    rows.append([InlineKeyboardButton(text="📰 Это к истории — анонимно", callback_data="chat:story")])
    rows.append([InlineKeyboardButton(text="❌ Ничего, я случайно", callback_data="chat:menu")])
    await message.answer(prompt, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.message()
async def anything_else(message: Message) -> None:
    """Стикеры, голосовые и прочее — отвечаем тепло, а не сухо."""
    if message.sticker:
        reply = random.choice([
            "Классный стикер! 😄 А по делу — задай вопрос о жизни в NL или выбери пункт меню 👇",
            "Принял стикер 😎 Чем могу помочь? Напиши вопрос или загляни в меню 👇",
        ])
    elif message.voice or message.video_note or message.audio:
        reply = (
            "Голосовые я пока не расшифровываю 🙈 Но если напишешь вопрос "
            "<b>текстом</b> — отвечу на что угодно про жизнь в Нидерландах! 👇"
        )
    else:
        reply = (
            "Получил! 📩 С таким форматом я пока не работаю, но напиши мне "
            "<b>текстом</b> — помогу с любым вопросом или подберу специалиста 👇"
        )
    await message.answer(reply, reply_markup=main_menu())


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
    await callback.answer("Отправлено!")
