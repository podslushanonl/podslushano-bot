"""Глобальный перехват ошибок — «краш-репорт».

Любая необработанная ошибка в боте: записывается в лог, автоматически уходит
админам (кто/что делал + трассировка), а пользователю показывается дружелюбное
сообщение с кнопкой «🐞 Рассказать, что случилось» (откроет форму отчёта).
"""
import html
import logging
import traceback

from aiogram import Bot, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import ErrorEvent, InlineKeyboardButton, InlineKeyboardMarkup

import config

log = logging.getLogger(__name__)
router = Router()

# Безобидные «гонки интерфейса»: callback устарел, сообщение не изменилось или
# уже удалено/недоступно. Пользователь обычно УЖЕ получил результат, поэтому
# пугать его «что-то пошло не так» и спамить админов не нужно — просто логируем.
_BENIGN_TELEGRAM = (
    "query is too old",
    "message is not modified",
    "message to edit not found",
    "message can't be edited",
    "message to delete not found",
    "message to be replied not found",
    "message can't be deleted",
)


@router.errors()
async def on_error(event: ErrorEvent, bot: Bot) -> None:
    exc = event.exception
    update = event.update

    if isinstance(exc, TelegramBadRequest) and any(
        s in str(exc).lower() for s in _BENIGN_TELEGRAM
    ):
        log.info("Безобидная ошибка Telegram (игнорируем): %s", exc)
        return

    log.exception("Необработанная ошибка: %s", exc)

    # Кто и что делал (для письма админам и для ответа пользователю)
    user = None
    action = "—"
    chat_id = None
    if update.message is not None:
        user = update.message.from_user
        action = update.message.text or update.message.caption or "[медиа]"
        chat_id = update.message.chat.id
    elif update.callback_query is not None:
        user = update.callback_query.from_user
        action = "кнопка: " + (update.callback_query.data or "")
        if update.callback_query.message:
            chat_id = update.callback_query.message.chat.id

    uinfo = "—"
    if user is not None:
        uname = f"@{user.username}" if user.username else "—"
        uinfo = f"{html.escape(user.full_name)} ({uname}, id <code>{user.id}</code>)"

    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))[-1500:]
    report = (
        "🛠 <b>Ошибка у пользователя</b>\n"
        f"От: {uinfo}\n"
        f"Действие: <code>{html.escape(action[:200])}</code>\n\n"
        f"<pre>{html.escape(tb)}</pre>"
    )
    for admin_id in config.ADMIN_IDS:
        try:
            await bot.send_message(admin_id, report)
        except Exception:  # noqa: BLE001 — оповещение не должно падать само
            pass

    # Дружелюбно сообщаем пользователю и даём низкий порог пожаловаться
    if chat_id is not None:
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🐞 Рассказать, что случилось", callback_data="report_bug")
        ]])
        try:
            await bot.send_message(
                chat_id,
                "Упс, что-то пошло не так на нашей стороне 😞\n"
                "Мы уже получили сигнал и разберёмся. Если хочешь — опиши, что ты "
                "делал, это поможет починить быстрее 👇",
                reply_markup=kb,
            )
        except Exception:  # noqa: BLE001
            pass
