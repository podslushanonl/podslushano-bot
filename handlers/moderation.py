"""Обработка кнопок модерации в личке у админов."""
import html
import logging

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import config
from database.db import get_session
from database.models import Meta, Submission
from keyboards.menus import cancel_menu
from states.forms import SupportReply

log = logging.getLogger(__name__)

router = Router()


@router.message(Command("setmodchat"))
async def set_mod_chat(message: Message) -> None:
    """Запустить ВНУТРИ группы/канала: заявки начнут приходить сюда."""
    if message.from_user is None or message.from_user.id not in config.ADMIN_IDS:
        return
    async with get_session() as session:
        await session.merge(Meta(key="mod_chat", value=str(message.chat.id)))
        await session.commit()
    await message.answer(
        f"✅ Готово! Заявки (вопросы/истории/видео/реклама) теперь приходят сюда "
        f"(chat id <code>{message.chat.id}</code>).\n\n"
        "Бот должен оставаться <b>администратором</b> этого чата. Чтобы кнопка "
        "«✍️ Ответить автору» работала в группе — отключите боту приватность в "
        "@BotFather (/setprivacy → Disable). Вернуть заявки в личку: /modchat_off"
    )


@router.message(Command("modchat_off"))
async def mod_chat_off(message: Message) -> None:
    if message.from_user is None or message.from_user.id not in config.ADMIN_IDS:
        return
    async with get_session() as session:
        m = await session.get(Meta, "mod_chat")
        if m:
            await session.delete(m)
            await session.commit()
    await message.answer("↩️ Заявки снова будут приходить админам в личку.")

# Что показываем пользователю, когда его заявку одобрили/отклонили
USER_APPROVED = {
    "story": "Твоя история одобрена и скоро появится в нашем Instagram! 🎉",
    "question": "Твой вопрос принят — скоро ответим 🙌",
    "video": "Твоё видео одобрено, спасибо! 🎬",
    "ad": "Спасибо за заявку! Мы свяжемся с тобой по поводу сотрудничества 📢",
}
USER_REJECTED = "Спасибо за заявку! К сожалению, в этот раз мы её не опубликуем 🙏"


PREDLOZHKA_HASHTAG = "#pnl_предложка"


async def _publish_question(bot, question_text: str):
    """Публикует одобрённый вопрос анонимно в канал-предложку. Возвращает Message или None.

    Важно: БЕЗ inline-кнопок — иначе Telegram не показывает кнопку «Комментировать».
    Призыв «Задать свой вопрос» делаем ссылкой прямо в тексте.
    """
    channel = config.ANNOUNCE_CHANNEL
    if not channel or not question_text:
        return None
    me = await bot.me()
    ask_link = f"https://t.me/{me.username}?start=ask"
    body = (
        "❓ <b>Вопрос от подписчика</b>\n\n"
        f"{html.escape(question_text)}\n\n"
        "💬 Знаете ответ или есть опыт? Поделитесь в комментариях 👇\n\n"
        f'👉 <a href="{ask_link}">Задать вопрос в предложку</a>\n'
        f"{PREDLOZHKA_HASHTAG}"
    )
    try:
        return await bot.send_message(channel, body, disable_web_page_preview=True)
    except Exception as e:  # noqa: BLE001
        log.warning("Не удалось опубликовать вопрос в канал: %s", e)
        return None


def _post_link(channel: str, message_id: int) -> str | None:
    if channel and channel.startswith("@"):
        return f"https://t.me/{channel[1:]}/{message_id}"
    return None


@router.message(Command("repost"))
async def cmd_repost(message: Message) -> None:
    """/repost <номер заявки> — переопубликовать вопрос в канал-предложку."""
    if message.from_user.id not in config.ADMIN_IDS:
        return
    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer("Использование: <code>/repost НОМЕР</code> (номер заявки-вопроса).")
        return
    async with get_session() as session:
        sub = await session.get(Submission, int(parts[1]))
    if sub is None or sub.type != "question":
        await message.answer("Вопрос с таким номером не найден.")
        return
    posted = await _publish_question(message.bot, sub.text or "")
    if posted is None:
        await message.answer(
            "Не удалось опубликовать. Проверь, что задан ANNOUNCE_CHANNEL и бот — админ канала."
        )
        return
    link = _post_link(config.ANNOUNCE_CHANNEL, posted.message_id)
    await message.answer("✅ Опубликовал заново." + (f"\n{link}" if link else ""),
                         disable_web_page_preview=True)


async def _update_status(submission_id: int, status: str) -> Submission | None:
    async with get_session() as session:
        submission = await session.get(Submission, submission_id)
        if submission is None:
            return None
        submission.status = status
        await session.commit()
        await session.refresh(submission)
        return submission


@router.callback_query(F.data.startswith("approve:"))
async def approve(callback: CallbackQuery) -> None:
    await _handle(callback, "approved")


@router.callback_query(F.data.startswith("reject:"))
async def reject(callback: CallbackQuery) -> None:
    await _handle(callback, "rejected")


@router.callback_query(F.data.startswith("subreply:"))
async def sub_reply_start(callback: CallbackQuery, state: FSMContext) -> None:
    """«Ответить автору» под заявкой — админ пишет, бот пересылает автору."""
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("Только для администраторов", show_alert=True)
        return
    try:
        sid = int(callback.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer()
        return
    async with get_session() as session:
        sub = await session.get(Submission, sid)
    if sub is None:
        await callback.answer("Заявка не найдена", show_alert=True)
        return
    await state.set_state(SupportReply.waiting_text)
    await state.update_data(reply_to=sub.user_id)
    # В группе reply-клавиатуру не шлём (она для всех); в личке — удобно.
    kb = cancel_menu() if callback.message.chat.type == ChatType.PRIVATE else None
    await callback.message.answer(
        f"Напиши ответ автору заявки №{sid} — я перешлю его. "
        "Можно текст, фото или файл.",
        reply_markup=kb,
    )
    await callback.answer()


@router.message(SupportReply.waiting_text, F.chat.type != ChatType.PRIVATE)
async def mod_reply_send(message: Message, state: FSMContext) -> None:
    """Ответ админа автору заявки из ГРУППЫ (в личке это делает support.py)."""
    data = await state.get_data()
    uid = data.get("reply_to")
    await state.clear()
    if not uid:
        await message.answer("Не нашёл, кому отвечать 🤔")
        return
    try:
        await message.bot.send_message(uid, "💬 <b>Ответ от команды «Подслушано»:</b>")
        await message.copy_to(uid)
        await message.answer("✅ Отправил пользователю.")
    except Exception as e:  # noqa: BLE001
        await message.answer(f"❌ Не удалось отправить: {html.escape(str(e))}")


async def _handle(callback: CallbackQuery, status: str) -> None:
    # На всякий случай проверяем, что нажал именно админ
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("Только для администраторов", show_alert=True)
        return

    submission_id = int(callback.data.split(":", 1)[1])
    submission = await _update_status(submission_id, status)

    if submission is None:
        await callback.answer("Заявка не найдена", show_alert=True)
        return

    admin = f"@{callback.from_user.username}" if callback.from_user.username else "админ"
    mark = "✅ ОДОБРЕНО" if status == "approved" else "❌ ОТКЛОНЕНО"
    note = f"\n\n— {mark} ({admin})"

    # Дописываем отметку к сообщению и убираем кнопки
    if callback.message.text:
        await callback.message.edit_text(callback.message.text + note, reply_markup=None)
    elif callback.message.caption:
        await callback.message.edit_caption(
            caption=callback.message.caption + note, reply_markup=None
        )
    else:
        await callback.message.edit_reply_markup(reply_markup=None)

    # Одобренный вопрос — публикуем в канал-предложку (ответы в комментариях)
    post_link = None
    if status == "approved" and submission.type == "question":
        posted = await _publish_question(callback.bot, submission.text or "")
        if posted is not None:
            post_link = _post_link(config.ANNOUNCE_CHANNEL, posted.message_id)

    # Сообщаем пользователю результат
    try:
        if status == "approved" and submission.type == "question":
            text = (
                "Твой вопрос опубликован в нашем канале! 🙌 Ответы подписчиков "
                "появятся в комментариях."
            )
            if post_link:
                text += f"\n👉 {post_link}"
        elif status == "approved":
            text = USER_APPROVED.get(submission.type, "Твоя заявка одобрена! 🎉")
        else:
            text = USER_REJECTED
        await callback.bot.send_message(submission.user_id, text, disable_web_page_preview=True)
    except Exception as e:  # noqa: BLE001 — пользователь мог заблокировать бота
        log.warning("Не удалось уведомить пользователя %s: %s", submission.user_id, e)

    await callback.answer("Готово")
