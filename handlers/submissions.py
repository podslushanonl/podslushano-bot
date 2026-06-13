"""Приём заявок от пользователей: истории, вопросы, видео, реклама."""
from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, User

from database.db import get_session
from database.models import Submission
from keyboards.menus import (
    BTN_AD,
    BTN_QUESTION,
    BTN_STORY,
    BTN_VIDEO,
    ad_format_menu,
    cancel_menu,
    main_menu,
)
from states.forms import AdForm, QuestionForm, StoryForm, VideoForm
from utils.analytics import log_event
from utils.notify import send_to_admins

router = Router()
# Приём заявок — только в личных чатах
router.message.filter(F.chat.type == ChatType.PRIVATE)

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
        "Обожаю истории! 🤫 Расскажи свою — одним сообщением.\n\n"
        "Публикуем <b>анонимно</b>, имя нигде не появится. Можно приложить фото.\n"
        "<i>Например: «Сегодня в трамвае в Гааге случилось такое…»</i>",
        reply_markup=cancel_menu(),
    )


@router.message(F.text == BTN_QUESTION)
async def ask_question(message: Message, state: FSMContext) -> None:
    await state.set_state(QuestionForm.waiting_for_content)
    await message.answer(
        "Давай спросим у сообщества! 📨 Напиши вопрос <b>с деталями</b> — так тебе "
        "ответят по делу. Добавь контекст: город, свою ситуацию, что именно важно.\n\n"
        "<i>🙅 Не очень: «Кто ездил в Гаагу?»\n"
        "👍 Хорошо: «Едем в Гаагу с детьми 4 и 7 лет на выходные в июле — посоветуйте "
        "тихие пляжи и места без толп?»</i>",
        reply_markup=cancel_menu(),
    )


@router.message(F.text == BTN_VIDEO)
async def ask_video(message: Message, state: FSMContext) -> None:
    await state.set_state(VideoForm.waiting_for_content)
    await message.answer(
        "Класс, ждём твоё видео! 🎬 Пришли его одним сообщением. "
        "Хочешь что-то добавить — напиши в подписи к видео.\n"
        "<i>Например: рилс про переезд, лайфхаки или обзор города</i>",
        reply_markup=cancel_menu(),
    )


# --- Реклама: пошаговая анкета ----------------------------------------------

@router.message(F.text == BTN_AD)
async def ask_ad(message: Message, state: FSMContext) -> None:
    await state.set_state(AdForm.waiting_for_subject)
    await message.answer(
        "Здорово, что хотите разместиться у нас! 📢\n\n"
        "Задам пару коротких вопросов, чтобы команда сразу всё поняла и "
        "ответила предметно.\n\n"
        "<b>1/4.</b> Что рекламируем? Опишите товар, услугу или бренд "
        "в двух-трёх словах.\n"
        "<i>Например: «Салон маникюра в Роттердаме» или «Доставка русских продуктов»</i>",
        reply_markup=cancel_menu(),
    )


@router.message(AdForm.waiting_for_subject)
async def ad_subject(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("Напишите, пожалуйста, текстом — что рекламируем? 🙂")
        return
    await state.update_data(ad_subject=message.text.strip())
    await state.set_state(AdForm.waiting_for_format)
    await message.answer(
        "<b>2/4.</b> В каком формате хотите разместиться? "
        "Выберите вариант ниже или напишите свой.",
        reply_markup=ad_format_menu(),
    )


@router.message(AdForm.waiting_for_format)
async def ad_format(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("Выберите формат кнопкой ниже или напишите словами 🙂")
        return
    await state.update_data(ad_format=message.text.strip())
    await state.set_state(AdForm.waiting_for_timing)
    await message.answer(
        "<b>3/4.</b> Когда хотели бы запуститься? "
        "Например: «как можно скорее», «в этом месяце» или конкретная дата.",
        reply_markup=cancel_menu(),
    )


@router.message(AdForm.waiting_for_timing)
async def ad_timing(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("Напишите, пожалуйста, желаемые сроки текстом 🙂")
        return
    await state.update_data(ad_timing=message.text.strip())
    await state.set_state(AdForm.waiting_for_contact)
    await message.answer(
        "<b>4/4.</b> И последнее — как с вами связаться? "
        "Оставьте телефон, @username или e-mail.",
        reply_markup=cancel_menu(),
    )


@router.message(AdForm.waiting_for_contact)
async def ad_contact(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("Оставьте, пожалуйста, контакт текстом 🙂")
        return
    data = await state.get_data()
    contact = message.text.strip()
    summary = (
        "📢 <b>Заявка на рекламу</b>\n\n"
        f"• <b>Что рекламируют:</b> {data.get('ad_subject', '—')}\n"
        f"• <b>Формат:</b> {data.get('ad_format', '—')}\n"
        f"• <b>Сроки:</b> {data.get('ad_timing', '—')}\n"
        f"• <b>Контакт:</b> {contact}"
    )
    await create_submission(message.bot, message.from_user, "ad", summary)
    await state.clear()
    await message.answer(THANKS["ad"], reply_markup=main_menu())


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
    await log_event("submission", sub_type)
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


def _too_short_question(text: str) -> bool:
    """Слишком короткий/пустой вопрос — отвечать будет не на что."""
    return len(text.split()) < 6


@router.message(QuestionForm.waiting_for_content)
async def receive_question(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    data = await state.get_data()
    # Один раз мягко просим добавить деталей, если вопрос совсем короткий
    if text and _too_short_question(text) and not data.get("q_nudged"):
        await state.update_data(q_nudged=True)
        await message.answer(
            "Чуть подробнее? 🙂 Так подписчикам будет на что ответить.\n"
            "Добавь контекст: город, твою ситуацию, что именно интересует.\n\n"
            "<i>Например: вместо «кто ездил в Гаагу?» → «едем в Гаагу с детьми на "
            "выходные в июле, посоветуйте тихие пляжи и что посмотреть рядом?»</i>\n\n"
            "Или пришли как есть ещё раз — опубликуем 👌",
            reply_markup=cancel_menu(),
        )
        return
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
