"""Рубрика #pnl_истории: публикация историй в канал и модерация."""
import html
import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import config
from database.db import get_session
from database.models import Submission

log = logging.getLogger(__name__)
router = Router()

STORY_HASHTAG = "#pnl_истории"

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


def _story_button(bot_username: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✍️ Рассказать свою историю",
                    url=f"https://t.me/{bot_username}?start=story",
                )
            ]
        ]
    )


async def _publish_story(bot, submission: Submission | None = None, *, text: str | None = None):
    channel = config.ANNOUNCE_CHANNEL
    if not channel:
        return None

    me = await bot.me()
    keyboard = _story_button(me.username)

    if submission is None:
        body = text or ""
        return await bot.send_message(
            channel,
            body,
            reply_markup=keyboard,
            disable_web_page_preview=True,
        )

    story_text = html.escape(submission.text or "")
    body = (
        "<b>История от нашего подписчика</b>\n\n"
        f"{story_text}\n\n"
        "©️ Анонимно\n\n"
        "А у вас случалось что-то похожее? Пишите в комментариях 👇\n\n"
        "Если история была интересной — поддержите её реакцией ❤️\n\n"
        f"{STORY_HASHTAG}"
    )

    if submission.file_id and submission.file_type == "photo":
        return await bot.send_photo(
            channel,
            submission.file_id,
            caption=body,
            reply_markup=keyboard,
        )
    if submission.file_id and submission.file_type == "video":
        return await bot.send_video(
            channel,
            submission.file_id,
            caption=body,
            reply_markup=keyboard,
        )
    return await bot.send_message(
        channel,
        body,
        reply_markup=keyboard,
        disable_web_page_preview=True,
    )


@router.message(CommandStart(deep_link=True), F.text.endswith(" story"))
async def story_deep_link(message: Message, state: FSMContext) -> None:
    """Кнопка из поста сразу открывает форму отправки истории."""
    from handlers.submissions import ask_story

    await state.clear()
    await ask_story(message, state)


@router.message(Command("publish_story_open_windows"))
async def publish_first_story(message: Message) -> None:
    """Одноразовая админ-команда для публикации первой истории рубрики."""
    if message.from_user is None or message.from_user.id not in config.ADMIN_IDS:
        return
    try:
        posted = await _publish_story(message.bot, text=FIRST_STORY_TEXT)
    except Exception as exc:  # noqa: BLE001
        log.exception("Не удалось опубликовать первую историю")
        await message.answer(f"❌ Не удалось опубликовать: {html.escape(str(exc))}")
        return
    if posted is None:
        await message.answer("❌ Не задан ANNOUNCE_CHANNEL.")
        return
    await message.answer("✅ История опубликована ботом с кнопкой.")


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
        await callback.message.edit_caption(
            caption=callback.message.caption + note,
            reply_markup=None,
        )
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
        await callback.bot.send_message(
            submission.user_id,
            "Твоя история опубликована в рубрике #pnl_истории! 🎉",
        )
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
        await callback.bot.send_message(
            submission.user_id,
            "Спасибо за историю! К сожалению, в этот раз мы её не опубликуем 🙏",
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("Не удалось уведомить автора истории %s: %s", submission.user_id, exc)
    await callback.answer("История отклонена")
