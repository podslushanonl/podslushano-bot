"""Приём заявок от пользователей: истории, вопросы, видео, реклама."""
import html
import json
from datetime import datetime, timezone

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    User,
)

from database.db import get_session
from database.models import Submission
from keyboards.menus import (
    ANSWER_FOOTER,
    BTN_AD,
    BTN_QUESTION,
    BTN_STORY,
    BTN_SUBMIT,
    BTN_VIDEO,
    ad_format_menu,
    cancel_menu,
    main_menu,
)
from states.forms import AdForm, QuestionForm, StoryForm, VideoForm
from utils.ai import ai_enabled, ai_reply
from utils.analytics import log_event, log_product_event
from utils.limits import allow_ai
from utils.notify import send_to_admins
from utils.video_submissions import (
    CONSENT_VERSION,
    MAX_ORIGINAL_VIDEO_BYTES,
    credit_text,
    is_video_document,
    normalize_instagram,
)

router = Router()
# Приём заявок — только в личных чатах
router.message.filter(F.chat.type == ChatType.PRIVATE)

VIDEO_FILE_INSTRUCTIONS = (
    "📎 <b>Нужно отправить видео именно файлом</b>\n\n"
    "Не выбирай обычную отправку через «Фото или видео» — Telegram сожмёт ролик "
    "и ухудшит качество.\n\n"
    "<b>На iPhone:</b> открой видео в «Фото» → «Поделиться» → «Сохранить в Файлы». "
    "Затем вернись сюда → нажми скрепку → «Файл» → выбери сохранённое видео.\n\n"
    "<b>На Android:</b> нажми скрепку → «Файл» → выбери видео в памяти телефона.\n\n"
    "Перед отправкой должна быть видна карточка файла с названием и размером, "
    "а не обычное превью видео. Максимальный размер — 200 МБ."
)

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
        "Готово — видео отправлено на проверку 🎬\n\n"
        "Если мы добавим его в контент-банк или опубликуем, бот сообщит тебе "
        "отдельно. Авторство укажем именно так, как ты выбрал(а)."
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
        "Опиши свой вопрос <b>подробно</b> — одним сообщением 🙏\n\n"
        "Чтобы и я, и подписчики могли реально помочь, добавь:\n"
        "• 📍 город / провинцию\n"
        "• 🧩 твою ситуацию и контекст\n"
        "• ❓ что именно хочешь узнать\n\n"
        "<i>Не «посоветуйте врача», а: «Ищу русскоязычного терапевта в Утрехте, "
        "недавно переехали, нужна запись по страховке — к кому обращались?»</i>\n\n"
        "Короткие вопросы из 2–3 слов почти никто не комментирует — пара предложений "
        "сильно повышают шанс на хороший ответ 👍",
        reply_markup=cancel_menu(),
    )


@router.message(F.text == BTN_VIDEO)
async def ask_video(message: Message, state: FSMContext) -> None:
    await state.set_state(VideoForm.waiting_for_content)
    await message.answer(
        "🎬 <b>Пришли видео о Нидерландах</b>\n\n"
        "Это может быть красивое место, необычная ситуация, событие, полезное "
        "наблюдение или просто живой момент из жизни здесь.\n\n"
        "Лучше всего подходит оригинальное вертикальное видео без чужих "
        "водяных знаков и наложенной музыки.\n\n"
        + VIDEO_FILE_INSTRUCTIONS
        + "\n\nПосле загрузки останется несколько коротких шагов — займёт меньше минуты.",
        reply_markup=cancel_menu(),
    )


# --- Объединённая кнопка «Спросить / поделиться» -----------------------------

@router.message(F.text == BTN_SUBMIT)
@router.message(F.text == "✍️ Спросить / поделиться")  # старая надпись: пока у
# пользователя не обновилось меню (до /start), кнопка всё равно работает
async def submit_menu(message: Message, state: FSMContext) -> None:
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❓ Задать вопрос (предложка)", callback_data="submit:question")],
        [InlineKeyboardButton(text="📰 История / сплетня (анонимно)", callback_data="submit:story")],
        [InlineKeyboardButton(text="🎬 Прислать видео", callback_data="submit:video")],
    ])
    await message.answer("Что хочешь отправить? Выбери 👇", reply_markup=kb)


@router.callback_query(F.data == "submit:question")
async def submit_question(callback: CallbackQuery, state: FSMContext) -> None:
    await ask_question(callback.message, state)
    await callback.answer()


@router.callback_query(F.data == "submit:story")
async def submit_story(callback: CallbackQuery, state: FSMContext) -> None:
    await ask_story(callback.message, state)
    await callback.answer()


@router.callback_query(F.data == "submit:video")
async def submit_video(callback: CallbackQuery, state: FSMContext) -> None:
    await ask_video(callback.message, state)
    await callback.answer()


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
    details: dict | None = None,
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
            details=json.dumps(details, ensure_ascii=False) if details else None,
        )
        session.add(submission)
        await session.commit()
        await session.refresh(submission)

    await send_to_admins(bot, submission)
    await log_event("submission", sub_type)
    await log_product_event(
        user.id,
        "submission_created",
        entity_type=sub_type,
        entity_id=submission.id,
    )
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


def _community_kb() -> InlineKeyboardMarkup:
    """Кнопки после ответа ИИ: отправлять ли вопрос ещё и в сообщество."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🗣 Спросить ещё и у сообщества", callback_data="q:community")],
            [InlineKeyboardButton(text="👍 Спасибо, всё понятно", callback_data="q:done")],
        ]
    )


async def _question_to_community(
    message: Message, state: FSMContext, data: dict, text: str
) -> None:
    """Отправляет вопрос в предложку (с одной мягкой просьбой добавить деталей)."""
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


@router.message(QuestionForm.waiting_for_content)
async def receive_question(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    _, file_id, _ = extract_content(message)
    data = await state.get_data()

    # Вопрос с вложением, без ИИ или от «исчерпавшего лимит» — сразу в сообщество
    # (фото/видео ИИ не разберёт, а лимит бережём). Иначе пробуем ответить сами.
    if file_id or not text or not ai_enabled() or not allow_ai(message.from_user.id):
        await _question_to_community(message, state, data, text)
        return

    # Сначала отвечает ИИ: большинство «вопросов» — фактические, и человеку не
    # нужно ждать сообщество. Только если ИИ не справился — уводим в предложку.
    await message.bot.send_chat_action(message.chat.id, action="typing")
    answer = await ai_reply(text)
    if not answer:
        await _question_to_community(message, state, data, text)
        return

    await log_event("ai")
    await state.set_state(QuestionForm.deciding)
    await state.update_data(q_text=text)
    await message.answer(answer + ANSWER_FOOTER, reply_markup=main_menu(), parse_mode=None)
    await message.answer(
        "Это мой ответ 🤖 Если хочешь услышать <b>живой опыт подписчиков</b> — "
        "отправлю твой вопрос в сообщество. Или этого достаточно?",
        reply_markup=_community_kb(),
    )


@router.callback_query(F.data == "q:community")
async def q_to_community(callback: CallbackQuery, state: FSMContext) -> None:
    """Человек всё же хочет спросить сообщество — отправляем вопрос в предложку."""
    data = await state.get_data()
    text = data.get("q_text")
    await state.clear()
    await callback.message.edit_reply_markup(reply_markup=None)
    if not text:
        await callback.message.answer(
            "Не нашёл твой вопрос 🙈 Напиши его заново через «❓ Задать вопрос».",
            reply_markup=main_menu(),
        )
        await callback.answer()
        return
    await create_submission(callback.bot, callback.from_user, "question", text)
    await callback.message.answer(THANKS["question"], reply_markup=main_menu())
    await callback.answer("Отправил сообществу!")


@router.callback_query(F.data == "q:done")
async def q_done(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        "Отлично! Если будет ещё вопрос — просто напиши 🙌", reply_markup=main_menu()
    )
    await callback.answer()


@router.message(VideoForm.waiting_for_content)
async def receive_video(message: Message, state: FSMContext) -> None:
    if message.video:
        await message.answer(
            "⚠️ <b>Это видео отправлено с обычным сжатием Telegram, поэтому я не "
            "добавил его в заявку.</b>\n\n" + VIDEO_FILE_INSTRUCTIONS,
            reply_markup=cancel_menu(),
        )
        return
    if not is_video_document(message.document):
        await message.answer(
            "Это не видеофайл. Подойдут файлы MP4, MOV, M4V или WEBM.\n\n"
            + VIDEO_FILE_INSTRUCTIONS,
            reply_markup=cancel_menu(),
        )
        return

    media = message.document
    if media.file_size and media.file_size > MAX_ORIGINAL_VIDEO_BYTES:
        size_mb = round(media.file_size / 1024 / 1024, 1)
        await message.answer(
            f"Файл весит {size_mb} МБ, а максимальный размер — 200 МБ. "
            "Можно обрезать лишнее начало или конец либо экспортировать ролик в "
            "1080p с высоким качеством, затем снова отправить именно файлом.",
            reply_markup=cancel_menu(),
        )
        return
    media_data = {
        "file_id": media.file_id,
        "file_unique_id": media.file_unique_id,
        "file_name": getattr(media, "file_name", None),
        "mime_type": getattr(media, "mime_type", None) or "video/mp4",
        "file_size": getattr(media, "file_size", None),
        "duration": getattr(media, "duration", None),
        "width": getattr(media, "width", None),
        "height": getattr(media, "height", None),
        "telegram_type": "document",
    }
    await state.update_data(video_media=media_data)

    size_text = (
        f" · {round(media.file_size / 1024 / 1024, 1)} МБ"
        if media.file_size else ""
    )
    await message.answer(
        "✅ <b>Оригинал получен без сжатия</b>\n"
        f"{html.escape(media.file_name or 'Видеофайл')}{size_text}"
    )

    supplied_context = (message.caption or "").strip()
    if len(supplied_context) >= 10:
        await state.update_data(video_context=supplied_context[:700])
        await _ask_video_credit(message, state)
        return

    await state.set_state(VideoForm.waiting_for_context)
    await message.answer(
        "📍 <b>Что снято и где?</b>\n\n"
        "Напиши одним сообщением, чтобы нам не пришлось угадывать контекст. "
        "Например: <i>«Парад цветов в Зюндерте, снято сегодня днём»</i>.",
        reply_markup=cancel_menu(),
    )


@router.message(VideoForm.waiting_for_context)
async def receive_video_context(message: Message, state: FSMContext) -> None:
    context = (message.text or "").strip()
    if len(context) < 10:
        await message.answer(
            "Добавь немного конкретики: что происходит и в каком городе или месте это снято."
        )
        return
    await state.update_data(video_context=context[:700])
    data = await state.get_data()
    if data.get("video_consent"):
        await _show_video_preview(message, state)
    else:
        await _ask_video_credit(message, state)


def _video_credit_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📷 Указать Instagram", callback_data="videoform:credit:instagram")],
        [InlineKeyboardButton(text="✍️ Указать имя", callback_data="videoform:credit:name")],
    ])


async def _ask_video_credit(message: Message, state: FSMContext) -> None:
    await state.set_state(VideoForm.choosing_credit)
    await message.answer(
        "🎥 <b>Как указать авторство?</b>\n\n"
        "При публикации отметим Instagram автора или подпишем видео указанным именем.",
        reply_markup=_video_credit_kb(),
    )


@router.callback_query(VideoForm.choosing_credit, F.data == "videoform:credit:instagram")
async def video_credit_instagram(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(VideoForm.waiting_for_instagram)
    await callback.message.answer(
        "Отправь @username автора в Instagram или ссылку на профиль.",
        reply_markup=cancel_menu(),
    )
    await callback.answer()


@router.callback_query(VideoForm.choosing_credit, F.data == "videoform:credit:name")
async def video_credit_name(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(VideoForm.waiting_for_name)
    await callback.message.answer(
        "Напиши имя или название, которое нужно указать под видео.",
        reply_markup=cancel_menu(),
    )
    await callback.answer()


@router.message(VideoForm.waiting_for_instagram)
async def receive_video_instagram(message: Message, state: FSMContext) -> None:
    handle = normalize_instagram(message.text or "")
    if not handle:
        await message.answer(
            "Не получилось распознать профиль. Пришли его в формате "
            "<code>@username</code> или <code>instagram.com/username</code>."
        )
        return
    await state.update_data(video_credit={"type": "instagram", "value": handle})
    await _ask_video_rights(message, state)


@router.message(VideoForm.waiting_for_name)
async def receive_video_name(message: Message, state: FSMContext) -> None:
    name = " ".join((message.text or "").split())
    if len(name) < 2 or len(name) > 80:
        await message.answer("Укажи имя или название длиной от 2 до 80 символов.")
        return
    await state.update_data(video_credit={"type": "name", "value": name})
    await _ask_video_rights(message, state)


def _video_rights_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтверждаю и разрешаю", callback_data="videoform:rights:yes")],
        [InlineKeyboardButton(text="← Изменить авторство", callback_data="videoform:credit:change")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="videoform:cancel")],
    ])


async def _ask_video_rights(message: Message, state: FSMContext) -> None:
    await state.set_state(VideoForm.confirming_rights)
    await message.answer(
        "<b>Последнее: права на видео</b>\n\n"
        "Подтверди, что видео снято тобой или у тебя есть разрешение автора. "
        "Также в нём не должно быть чужих личных данных или кадров, нарушающих "
        "частную жизнь людей. "
        "Ты разрешаешь Podslushano.nl бесплатно отредактировать его — обрезать, "
        "добавить текст или субтитры — и опубликовать в Instagram @podslushano.nl "
        "с выбранным авторством. До публикации разрешение можно отозвать через поддержку.",
        reply_markup=_video_rights_kb(),
    )


@router.callback_query(F.data == "videoform:credit:change")
async def change_video_credit(callback: CallbackQuery, state: FSMContext) -> None:
    await _ask_video_credit(callback.message, state)
    await callback.answer()


def _video_preview_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Отправить на проверку", callback_data="videoform:submit")],
        [
            InlineKeyboardButton(text="✏️ Изменить описание", callback_data="videoform:context:change"),
            InlineKeyboardButton(text="🎥 Авторство", callback_data="videoform:credit:change"),
        ],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="videoform:cancel")],
    ])


async def _show_video_preview(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    media = data.get("video_media") or {}
    details = {"credit": data.get("video_credit") or {}}
    caption = (
        "<b>Проверь перед отправкой</b>\n\n"
        f"📍 {html.escape(str(data.get('video_context') or '—'))}\n\n"
        f"🎥 Автор: <b>{html.escape(credit_text(details))}</b>\n"
        "✅ Разрешение на публикацию подтверждено"
    )
    await state.set_state(VideoForm.confirming_submission)
    try:
        if media.get("telegram_type") == "document":
            await message.bot.send_document(
                message.chat.id, media["file_id"], caption=caption,
                reply_markup=_video_preview_kb(),
            )
        else:
            await message.bot.send_video(
                message.chat.id, media["file_id"], caption=caption,
                reply_markup=_video_preview_kb(),
            )
    except Exception:
        await message.answer(caption, reply_markup=_video_preview_kb())


@router.callback_query(VideoForm.confirming_rights, F.data == "videoform:rights:yes")
async def confirm_video_rights(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(video_consent={
        "version": CONSENT_VERSION,
        "accepted": True,
        "accepted_at": datetime.now(timezone.utc).isoformat(),
    })
    await _show_video_preview(callback.message, state)
    await callback.answer()


@router.callback_query(F.data == "videoform:context:change")
async def change_video_context(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(VideoForm.waiting_for_context)
    await callback.message.answer(
        "Напиши новое описание: что снято, где и, если важно, когда.",
        reply_markup=cancel_menu(),
    )
    await callback.answer()


@router.callback_query(F.data == "videoform:cancel")
async def cancel_video_form(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.answer("Отправка видео отменена.", reply_markup=main_menu())
    await callback.answer()


@router.callback_query(VideoForm.confirming_submission, F.data == "videoform:submit")
async def submit_video_form(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    media = data.get("video_media") or {}
    context = str(data.get("video_context") or "").strip()
    credit = data.get("video_credit") or {}
    consent = data.get("video_consent") or {}
    if not media.get("file_id") or not context or not credit.get("value") or not consent.get("accepted"):
        await callback.answer("Не все данные сохранились — начни отправку заново", show_alert=True)
        return

    details = {
        "context": context,
        "credit": credit,
        "media": media,
        "consent": consent,
    }
    await create_submission(
        callback.bot,
        callback.from_user,
        "video",
        context,
        media["file_id"],
        "document" if media.get("telegram_type") == "document" else "video",
        details,
    )
    await state.clear()
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.message.answer(THANKS["video"], reply_markup=main_menu())
    await callback.answer("Отправлено")
