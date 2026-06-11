"""Приём заявок от пользователей: истории, вопросы, видео, реклама."""
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from database.db import get_session
from database.models import Submission
from keyboards.menus import (
    BTN_AD,
    BTN_QUESTION,
    BTN_STORY,
    BTN_VIDEO,
    cancel_menu,
    main_menu,
)
from states.forms import AdForm, QuestionForm, StoryForm, VideoForm
from utils.notify import send_to_admins

router = Router()


# --- Шаг 1: пользователь нажал кнопку — просим прислать содержимое ----------

@router.message(F.text == BTN_STORY)
async def ask_story(message: Message, state: FSMContext) -> None:
    await state.set_state(StoryForm.waiting_for_content)
    await message.answer(
        "Напиши свою историю или сплетню одним сообщением. "
        "Она будет опубликована <b>анонимно</b> 🤫\n\n"
        "Можно приложить фото.",
        reply_markup=cancel_menu(),
    )


@router.message(F.text == BTN_QUESTION)
async def ask_question(message: Message, state: FSMContext) -> None:
    await state.set_state(QuestionForm.waiting_for_content)
    await message.answer(
        "Напиши свой вопрос одним сообщением — мы передадим его в предложку 📨",
        reply_markup=cancel_menu(),
    )


@router.message(F.text == BTN_VIDEO)
async def ask_video(message: Message, state: FSMContext) -> None:
    await state.set_state(VideoForm.waiting_for_content)
    await message.answer(
        "Пришли видео одним сообщением 🎬 Можно добавить описание в подписи.",
        reply_markup=cancel_menu(),
    )


@router.message(F.text == BTN_AD)
async def ask_ad(message: Message, state: FSMContext) -> None:
    await state.set_state(AdForm.waiting_for_content)
    await message.answer(
        "Расскажи о рекламе или сотрудничестве: что предлагаешь и как с тобой "
        "связаться 📢",
        reply_markup=cancel_menu(),
    )


# --- Вспомогательное: вытащить содержимое из сообщения ----------------------

def _extract(message: Message) -> tuple[str | None, str | None, str | None]:
    """Возвращает (текст, file_id, file_type) из сообщения пользователя."""
    text = message.text or message.caption
    if message.video:
        return text, message.video.file_id, "video"
    if message.photo:
        # У фото несколько размеров — берём самый крупный (последний)
        return text, message.photo[-1].file_id, "photo"
    if message.document:
        return text, message.document.file_id, "document"
    return text, None, None


async def _save_and_notify(
    message: Message, state: FSMContext, sub_type: str
) -> None:
    """Сохраняет заявку в базу, шлёт админам и благодарит пользователя."""
    text, file_id, file_type = _extract(message)

    if not text and not file_id:
        await message.answer("Кажется, сообщение пустое. Попробуй ещё раз 🙏")
        return

    async with get_session() as session:
        submission = Submission(
            type=sub_type,
            user_id=message.from_user.id,
            username=message.from_user.username,
            text=text,
            file_id=file_id,
            file_type=file_type,
        )
        session.add(submission)
        await session.commit()
        await session.refresh(submission)

    await send_to_admins(message.bot, submission)
    await state.clear()
    await message.answer(
        "Спасибо! ✅ Заявка принята и отправлена на модерацию.",
        reply_markup=main_menu(),
    )


# --- Шаг 2: принимаем содержимое для каждого типа заявки --------------------

@router.message(StoryForm.waiting_for_content)
async def receive_story(message: Message, state: FSMContext) -> None:
    await _save_and_notify(message, state, "story")


@router.message(QuestionForm.waiting_for_content)
async def receive_question(message: Message, state: FSMContext) -> None:
    await _save_and_notify(message, state, "question")


@router.message(VideoForm.waiting_for_content)
async def receive_video(message: Message, state: FSMContext) -> None:
    if not (message.video or message.document):
        await message.answer("Пожалуйста, пришли именно видеофайл 🎬")
        return
    await _save_and_notify(message, state, "video")


@router.message(AdForm.waiting_for_content)
async def receive_ad(message: Message, state: FSMContext) -> None:
    await _save_and_notify(message, state, "ad")
