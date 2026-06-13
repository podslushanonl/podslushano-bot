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
from aiogram.types import CallbackQuery, Message

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
    await state.update_data(kind="support")
    await message.answer(
        "Опишите одним сообщением ваш вопрос или проблему — я передам команде, "
        "и мы ответим 🙌\n\n"
        "Можно и напрямую:\n" + config.support_block(),
        reply_markup=cancel_menu(),
        disable_web_page_preview=True,
    )


@router.message(Command("report"))
async def report_start(message: Message, state: FSMContext) -> None:
    """«Сообщить об ошибке» — командой /report."""
    await _ask_bug(message, state)


@router.callback_query(F.data == "report_bug")
async def report_callback(callback: CallbackQuery, state: FSMContext) -> None:
    """«Сообщить об ошибке» — по кнопке (в т.ч. из краш-репорта)."""
    await _ask_bug(callback.message, state)
    await callback.answer()


async def _ask_bug(message: Message, state: FSMContext) -> None:
    await state.set_state(SupportContact.waiting_message)
    await state.update_data(kind="bug")
    await message.answer(
        "Опишите одним сообщением, что пошло не так и на каком шаге 🐞 "
        "(можно приложить скриншот) — я передам команде, и мы починим.",
        reply_markup=cancel_menu(),
    )


@router.message(SupportContact.waiting_message)
async def contact_relay(message: Message, state: FSMContext) -> None:
    kind = (await state.get_data()).get("kind", "support")
    await state.clear()
    u = message.from_user
    uname = f"@{u.username}" if u and u.username else "—"
    title = "🐞 <b>Сообщение об ошибке</b>" if kind == "bug" else "📨 <b>Обращение в поддержку</b>"
    header = (
        f"{title}\n"
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
