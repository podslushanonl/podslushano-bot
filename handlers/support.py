"""Связь с командой: кнопка «Связаться с нами» и /contact.

Пользователь пишет одно сообщение — бот пересылает его администраторам
(config.ADMIN_IDS) и подсказывает прямые контакты (e-mail/Telegram).
Это прозрачный канал для вопросов, проблем и возвратов.
"""
import html
import logging

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

import config
from keyboards.menus import BTN_CONTACT, cancel_menu, main_menu
from states.forms import SupportContact

log = logging.getLogger(__name__)

router = Router()
router.message.filter(F.chat.type == ChatType.PRIVATE)


@router.message(Command("contact", "support"))
@router.message(F.text == BTN_CONTACT)
async def contact_start(message: Message, state: FSMContext) -> None:
    await state.set_state(SupportContact.waiting_message)
    await message.answer(
        "Опишите одним сообщением ваш вопрос или проблему — я передам команде, "
        "и мы ответим 🙌\n\n"
        "Можно и напрямую:\n" + config.support_block(),
        reply_markup=cancel_menu(),
        disable_web_page_preview=True,
    )


@router.message(SupportContact.waiting_message)
async def contact_relay(message: Message, state: FSMContext) -> None:
    await state.clear()
    u = message.from_user
    uname = f"@{u.username}" if u and u.username else "—"
    header = (
        "📨 <b>Обращение в поддержку</b>\n"
        f"От: {html.escape(u.full_name)} ({uname}, id <code>{u.id}</code>)"
    )
    sent = False
    for admin_id in config.ADMIN_IDS:
        try:
            await message.bot.send_message(admin_id, header)
            await message.copy_to(admin_id)  # переносим текст/фото/файл как есть
            sent = True
        except Exception as e:  # noqa: BLE001
            log.warning("Не удалось переслать обращение админу %s: %s", admin_id, e)
    if sent:
        await message.answer(
            "Спасибо! Передал команде — ответим здесь или по e-mail 🙌",
            reply_markup=main_menu(),
        )
    else:
        await message.answer(
            "Не получилось передать сообщение автоматически 😔 Напишите нам напрямую:\n"
            + config.support_block(),
            reply_markup=main_menu(),
            disable_web_page_preview=True,
        )
