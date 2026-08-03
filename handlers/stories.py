"""Рубрика #pnl_истории: пошаговая отправка, предпросмотр и модерация."""
import html
import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import config
from database.db import get_session
from database.models import Submission
from keyboards.menus import BTN_STORY, main_menu

log = logging.getLogger(__name__)
router = Router()

STORY_HASHTAG = "#pnl_истории"
MIN_STORY_LENGTH = 250

FIRST_STORY_TEXT = (
    "<b>История от нашей подписчицы</b>\n\n"
    "<b>Как я перестала бояться открытых окон</b>\n\n"
    "Когда только переехала в Нидерланды, меня удивляло буквально всё. Но больше всего — окна.\n\n"
    "Иду вечером по улице, а у людей дома всё видно: кухня, диван, телевизор, кто-то ужинает, "
    "кто-то читает книгу, кто-то просто сидит с кружкой чая. И почти нигде нет плотных штор.\n\n"
    "Первые пару месяцев мне было очень неловко. Я закрывала свои шторы ещё до того, как включала "
    "свет. Казалось, что соседи обязательно будут заглядывать.\n\n"
    "Как-то разговорилась с коллегой-голландкой и спросила, почему у них так принято.\n\n"
    "Она улыбнулась и ответила:\n\n"
    "— «Если мне нечего скрывать, зачем мне закрываться?»\n\n"
    "Эта фраза почему-то очень запомнилась.\n\n"
    "Прошло уже несколько лет.\n\n"
    "Недавно поймала себя на мысли, что сама почти перестала закрывать шторы. Соседи проходят мимо "
    "моего окна, я прохожу мимо их окон — и никому до этого нет никакого дела.\n\n"
    "Иногда даже смешно вспоминать, как в первый месяц я чуть ли не пряталась в собственной квартире, "
    "чтобы меня случайно никто не увидел.\n\n"
    "Похоже, некоторые голландские привычки всё-таки становятся своими.\n\n"
    "©️ Анонимно\n\n"
    "А что вас больше всего удивило после переезда в Нидерланды? 🇳🇱\n\n"
    "Пишите в комментариях 👇\n\n"
    "Если история была интересной — поддержите её реакцией ❤️\n\n"
    f"{STORY_HASHTAG}"
)


class StoryWizard(StatesGroup):
    choosing_author = State()
    entering_name = State()
    entering_story = State()
    preview = State()


def _author_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🙈 Анонимно", callback_data="story_author:anonymous")],
        [InlineKeyboardButton(text="✍️ С указанием имени", callback_data="story_author:named")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="story_cancel")],
    ])


def _preview_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Отправить на проверку", callback_data="story_submit")],
        [InlineKeyboardButton(text="✏️ Изменить историю", callback_data="story_edit")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="story_cancel")],
    ])


def _story_button(bot_username: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="✍️ Рассказать свою историю",
            url=f"https://t.me/{bot_username}?start=story",
        )
    ]])


def _first_story_preview_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="✅ Опубликовать эту историю",
            callback_data="publish_first_story_confirm",
        )
    ]])


async def start_story_flow(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(StoryWizard.choosing_author)
    await message.answer(
        "Как хотите опубликовать историю?",
        reply_markup=_author_keyboard(),
    )


@router.message(CommandStart(deep_link=True), F.text.endswith(" story"))
async def story_deep_link(message: Message, state: FSMContext) -> None:
    await start_story_flow(message, state)


@router.message(F.text == BTN_STORY)
async def story_menu_button(message: Message, state: FSMContext) -> None:
    await start_story_flow(message, state)


@router.callback_query(F.data == "submit:story")
async def story_submit_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await start_story_flow(callback.message, state)
    await callback.answer()


@router.callback_query(F.data.startswith("story_author:"))
async def choose_story_author(callback: CallbackQuery, state: FSMContext) -> None:
    mode = callback.data.split(":", 1)[1]
    if mode == "anonymous":
        await state.update_data(author_mode="anonymous", author_name=None)
        await state.set_state(StoryWizard.entering_story)
        await callback.message.answer(
            "Напишите свою историю одним сообщением.\n\n"
            "Это может быть смешной случай, работа, знакомство с голландцами, поиск жилья, "
            "бюрократия, переезд, культурные различия или любой запомнившийся момент."
        )
    else:
        await state.update_data(author_mode="named")
        await state.set_state(StoryWizard.entering_name)
        await callback.message.answer("Какое имя указать под историей?")
    await callback.answer()


@router.message(StoryWizard.entering_name)
async def receive_story_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if len(name) < 2:
        await message.answer("Напишите имя, которое нужно указать под историей.")
        return
    await state.update_data(author_name=name[:80])
    await state.set_state(StoryWizard.entering_story)
    await message.answer(
        "Теперь напишите свою историю одним сообщением.\n\n"
        "Это может быть смешной случай, работа, знакомство с голландцами, поиск жилья, "
        "бюрократия, переезд, культурные различия или любой запомнившийся момент."
    )


@router.message(StoryWizard.entering_story)
async def receive_story_text(message: Message, state: FSMContext) -> None:
    text = (message.text or message.caption or "").strip()
    if not text:
        await message.answer("Пришлите историю текстом одним сообщением.")
        return
    if len(text) < MIN_STORY_LENGTH:
        await message.answer(
            "Расскажите чуть подробнее 🙂\n\n"
            "Добавьте детали: что произошло, где это было, что вы почувствовали и чем всё закончилось."
        )
        return

    await state.update_data(story_text=text)
    data = await state.get_data()
    signature = "Анонимно" if data.get("author_mode") == "anonymous" else data.get("author_name", "Без имени")
    preview = (
        "<b>Вот как будет выглядеть ваша история:</b>\n\n"
        f"{html.escape(text)}\n\n"
        f"©️ {html.escape(signature)}"
    )
    await state.set_state(StoryWizard.preview)
    await message.answer(preview, reply_markup=_preview_keyboard())


@router.callback_query(F.data == "story_edit")
async def edit_story(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(StoryWizard.entering_story)
    await callback.message.answer("Отправьте исправленный текст истории одним сообщением.")
    await callback.answer()


@router.callback_query(F.data == "story_cancel")
async def cancel_story(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.answer("Отправка истории отменена.", reply_markup=main_menu())
    await callback.answer()


@router.callback_query(F.data == "story_submit")
async def submit_story_for_moderation(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    text = data.get("story_text")
    if not text:
        await callback.answer("История не найдена, начните заново", show_alert=True)
        await state.clear()
        return

    signature = "Анонимно" if data.get("author_mode") == "anonymous" else data.get("author_name", "Без имени")
    stored_text = f"{text}\n\n©️ {signature}"

    from handlers.submissions import create_submission
    await create_submission(callback.bot, callback.from_user, "story", stored_text)
    await state.clear()
    await callback.message.answer(
        "Спасибо ❤️ История отправлена на проверку.\n\n"
        "После решения администратора бот сообщит, будет ли она опубликована.",
        reply_markup=main_menu(),
    )
    await callback.answer("Отправлено")


async def _publish_story(bot, submission: Submission | None = None, *, text: str | None = None):
    channel = config.ANNOUNCE_CHANNEL
    if not channel:
        return None
    me = await bot.me()
    keyboard = _story_button(me.username)

    if submission is None:
        return await bot.send_message(
            channel,
            text or "",
            reply_markup=keyboard,
            disable_web_page_preview=True,
        )

    story_text = html.escape(submission.text or "")
    body = (
        "<b>История от нашего подписчика</b>\n\n"
        f"{story_text}\n\n"
        "А у вас случалось что-то похожее? Пишите в комментариях 👇\n\n"
        "Если история была интересной — поддержите её реакцией ❤️\n\n"
        f"{STORY_HASHTAG}"
    )
    return await bot.send_message(
        channel,
        body,
        reply_markup=keyboard,
        disable_web_page_preview=True,
    )


@router.message(Command("publish_story_open_windows"))
async def preview_first_story(message: Message) -> None:
    """Админ-команда показывает предпросмотр и ничего не публикует без подтверждения."""
    if message.from_user is None or message.from_user.id not in config.ADMIN_IDS:
        return
    await message.answer(
        "<b>Предпросмотр публикации:</b>\n\n" + FIRST_STORY_TEXT,
        reply_markup=_first_story_preview_keyboard(),
        disable_web_page_preview=True,
    )


@router.callback_query(F.data == "publish_first_story_confirm")
async def publish_first_story_confirm(callback: CallbackQuery) -> None:
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("Только для администраторов", show_alert=True)
        return
    try:
        posted = await _publish_story(callback.bot, text=FIRST_STORY_TEXT)
    except Exception as exc:  # noqa: BLE001
        log.exception("Не удалось опубликовать первую историю")
        await callback.answer("Ошибка публикации", show_alert=True)
        await callback.message.answer(f"❌ Не удалось опубликовать: {html.escape(str(exc))}")
        return
    if posted is None:
        await callback.answer("Не задан ANNOUNCE_CHANNEL", show_alert=True)
        return
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("✅ История опубликована ботом с кнопкой.")
    await callback.answer("Опубликовано")


async def _get_story(submission_id: int) -> Submission | None:
    async with get_session() as session:
        submission = await session.get(Submission, submission_id)
        if submission is None or submission.type != "story":
            return None
        return submission


async def _set_status(submission_id: int, status: str) -> Submission | None:
    async with get_session() as session:
        submission = await session.get(Submission, submission_id)
        if submission is None or submission.type != "story":
            return None
        submission.status = status
        await session.commit()
        await session.refresh(submission)
        return submission


async def _finish_admin_message(callback: CallbackQuery, note: str) -> None:
    if callback.message.text:
        await callback.message.edit_text(callback.message.text + note, reply_markup=None)
    elif callback.message.caption:
        await callback.message.edit_caption(caption=callback.message.caption + note, reply_markup=None)
    else:
        await callback.message.edit_reply_markup(reply_markup=None)


@router.callback_query(F.data.startswith("story_approve:"))
async def approve_story(callback: CallbackQuery) -> None:
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("Только для администраторов", show_alert=True)
        return
    try:
        submission_id = int(callback.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("Некорректный номер заявки", show_alert=True)
        return
    submission = await _get_story(submission_id)
    if submission is None:
        await callback.answer("История не найдена", show_alert=True)
        return
    try:
        posted = await _publish_story(callback.bot, submission)
    except Exception as exc:  # noqa: BLE001
        log.exception("Не удалось опубликовать историю №%s", submission_id)
        await callback.answer("Ошибка публикации", show_alert=True)
        await callback.message.answer(f"❌ {html.escape(str(exc))}")
        return
    if posted is None:
        await callback.answer("Не задан ANNOUNCE_CHANNEL", show_alert=True)
        return
    await _set_status(submission_id, "approved")
    admin = f"@{callback.from_user.username}" if callback.from_user.username else "админ"
    await _finish_admin_message(callback, f"\n\n— ✅ ОПУБЛИКОВАНО ({admin})")
    try:
        await callback.bot.send_message(submission.user_id, "Твоя история опубликована в рубрике #pnl_истории! 🎉")
    except Exception as exc:  # noqa: BLE001
        log.warning("Не удалось уведомить автора истории %s: %s", submission.user_id, exc)
    await callback.answer("История опубликована")


@router.callback_query(F.data.startswith("story_reject:"))
async def reject_story(callback: CallbackQuery) -> None:
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("Только для администраторов", show_alert=True)
        return
    try:
        submission_id = int(callback.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("Некорректный номер заявки", show_alert=True)
        return
    submission = await _set_status(submission_id, "rejected")
    if submission is None:
        await callback.answer("История не найдена", show_alert=True)
        return
    admin = f"@{callback.from_user.username}" if callback.from_user.username else "админ"
    await _finish_admin_message(callback, f"\n\n— ❌ ОТКЛОНЕНО ({admin})")
    try:
        await callback.bot.send_message(submission.user_id, "Спасибо за историю! К сожалению, в этот раз мы её не опубликуем 🙏")
    except Exception as exc:  # noqa: BLE001
        log.warning("Не удалось уведомить автора истории %s: %s", submission.user_id, exc)
    await callback.answer("История отклонена")
