"""Приём заявок от пользователей: истории, вопросы, видео, реклама."""
from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, User

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

# Тёплые подтверждения после отправки — для каждого типа заявки своё
THANKS = {
    "story": (
        "История у нас! 🤫 Спасибо, что поделился(ась).\n\n"
        "Мы её прочитаем, и если всё ок — она появится в нашем Instagram "
        "<b>анонимно</b>. Я напишу тебе, как только будет решение 😉"
    ),
    "question": (
        "Вопрос принят! 📨 Передаю его команде — как только посмотрим, "
        "я дам тебе знать. Обычно это не занимает много времени 😊"
    ),
    "video": (
        "Видео получил, спасибо! 🎬 Команда посмотрит его, и я сразу "
        "напишу тебе ответ. Удачи! 🍀"
    ),
    "ad": (
        "Спасибо за интерес к сотрудничеству! 📢 Я передал заявку команде — "
        "мы свяжемся с тобой в ближайшее время 🤝"
    ),
}


# --- Шаг 1: пользователь нажал кнопку — просим прислать содержимое ----------

@router.message(F.text == BTN_STORY)
async def ask_story(message: Message, state: FSMContext) -> None:
    await state.set_state(StoryForm.waiting_for_content)
    await message.answer(
        "Ооо, обожаю истории! 🤫 Рассказывай — одним сообщением.\n\n"
        "Не переживай: публикуем <b>полностью анонимно</b>, никто не узнает, "
        "что это от тебя. Можно приложить фото, если есть.",
        reply_markup=cancel_menu(),
    )


@router.message(F.text == BTN_QUESTION)
async def ask_question(message: Message, state: FSMContext) -> None:
    await state.set_state(QuestionForm.waiting_for_content)
    await message.answer(
        "Конечно! Напиши свой вопрос одним сообщением — я передам его "
        "в предложку 📨 Спрашивай о чём угодно про жизнь в Нидерландах.",
        reply_markup=cancel_menu(),
    )


@router.message(F.text == BTN_VIDEO)
async def ask_video(message: Message, state: FSMContext) -> None:
    await state.set_state(VideoForm.waiting_for_content)
    await message.answer(
        "Класс, ждём твоё видео! 🎬 Пришли его одним сообщением. "
        "Если хочешь что-то рассказать о нём — добавь текст в подпись к видео.",
        reply_markup=cancel_menu(),
    )


@router.message(F.text == BTN_AD)
async def ask_ad(message: Message, state: FSMContext) -> None:
    await state.set_state(AdForm.waiting_for_content)
    await message.answer(
        "Отлично, давай обсудим! 📢 Расскажи одним сообщением:\n\n"
        "• что хочешь прорекламировать;\n"
        "• как с тобой связаться (телефон / @username / почта).\n\n"
        "Команда посмотрит и обязательно ответит 🤝",
        reply_markup=cancel_menu(),
    )


# --- Сохранение заявки (используется и кнопками меню, и свободным чатом) ----

def extract_content(message: Message) -> tuple[str | None, str | None, str | None]:
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


async def create_submission(
    bot: Bot,
    user: User,
    sub_type: str,
    text: str | None,
    file_id: str | None = None,
    file_type: str | None = None,
) -> Submission:
    """Сохраняет заявку в базу и рассылает админам на модерацию."""
    async with get_session() as session:
        submission = Submission(
            type=sub_type,
            user_id=user.id,
            username=user.username,
            text=text,
            file_id=file_id,
            file_type=file_type,
        )
        session.add(submission)
        await session.commit()
        await session.refresh(submission)

    await send_to_admins(bot, submission)
    return submission


async def _save_and_notify(
    message: Message, state: FSMContext, sub_type: str
) -> None:
    """Сохраняет заявку, шлёт админам и тепло отвечает пользователю."""
    text, file_id, file_type = extract_content(message)

    if not text and not file_id:
        await message.answer(
            "Кажется, сообщение пришло пустым 🙈 Попробуй ещё раз, пожалуйста."
        )
        return

    await create_submission(
        message.bot, message.from_user, sub_type, text, file_id, file_type
    )
    await state.clear()
    await message.answer(THANKS[sub_type], reply_markup=main_menu())


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
        await message.answer(
            "Хм, это не похоже на видео 🙈 Пришли, пожалуйста, видеофайл — "
            "или нажми «❌ Отмена», если передумал(а)."
        )
        return
    await _save_and_notify(message, state, "video")


@router.message(AdForm.waiting_for_content)
async def receive_ad(message: Message, state: FSMContext) -> None:
    await _save_and_notify(message, state, "ad")
