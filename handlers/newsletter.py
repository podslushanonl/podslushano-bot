"""Команды e-mail подписки и административный контроль выпусков."""
from __future__ import annotations

import html

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import config
from database.models import NewsletterSubscriber
from keyboards.menus import BTN_NEWSLETTER
from utils.invoices import send_email_message
from utils.newsletter import (
    DEFAULT_TOPICS,
    FREQUENCIES,
    build_content,
    campaign_stats,
    render_email,
    send_campaign,
    topics_csv,
)

router = Router()
router.message.filter(F.chat.type == ChatType.PRIVATE)


def _is_admin(user_id: int) -> bool:
    return user_id in config.ADMIN_IDS


@router.message(Command("newsletter", "email"))
@router.message(F.text == BTN_NEWSLETTER)
async def newsletter_page(message: Message) -> None:
    await message.answer(
        "✉️ <b>Письма Podslushano.nl</b>\n\n"
        "Главное в Нидерландах, афиша, полезные гайды и важные анонсы — "
        "раз в неделю или раз в месяц. Темы можно выбрать самостоятельно.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="Настроить e-mail подписку", url=config.newsletter_url())
        ]]),
    )


@router.message(Command("newsletterstats"))
async def newsletter_stats(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        return
    stats = await campaign_stats()
    await message.answer(
        "✉️ <b>E-mail подписка</b>\n\n"
        f"Активные · еженедельно: <b>{stats['active_weekly']}</b>\n"
        f"Активные · ежемесячно: <b>{stats['active_monthly']}</b>\n"
        f"Ждут подтверждения: {stats['pending']}\n"
        f"Отписались: {stats['unsubscribed']}\n\n"
        f"Страница: {config.newsletter_url()}"
    )


def _frequency_from_message(message: Message) -> str:
    parts = (message.text or "").split()
    candidate = parts[1].casefold() if len(parts) > 1 else "weekly"
    return candidate if candidate in FREQUENCIES else "weekly"


@router.message(Command("newsletterpreview"))
async def newsletter_preview(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        return
    frequency = _frequency_from_message(message)
    await message.answer("Собираю выпуск и отправляю предпросмотр на рабочую почту…")
    content = await build_content(frequency)
    preview = NewsletterSubscriber(
        email=config.COMPANY_EMAIL,
        name="Алекс",
        status="active",
        frequency=frequency,
        topics_csv=topics_csv(DEFAULT_TOPICS),
        manage_token="preview-only",
    )
    html_body, text_body = render_email(preview, content)
    ok, error = await send_email_message(
        config.COMPANY_EMAIL,
        f"[ПРЕДПРОСМОТР] {content.subject}",
        html_body,
        text_body,
        from_email=config.NEWSLETTER_FROM_EMAIL,
    )
    if ok:
        await message.answer(
            f"✅ Предпросмотр «{FREQUENCIES[frequency]}» отправлен на "
            f"<code>{html.escape(config.COMPANY_EMAIL)}</code>."
        )
    else:
        await message.answer(f"❌ Не удалось отправить: {html.escape(error[:700])}")


@router.message(Command("newslettersend"))
async def newsletter_send_ask(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        return
    frequency = _frequency_from_message(message)
    stats = await campaign_stats()
    recipients = stats[f"active_{frequency}"]
    await message.answer(
        f"Отправить выпуск «<b>{FREQUENCIES[frequency]}</b>»\n"
        f"активным подписчикам: <b>{recipients}</b>?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=f"✅ Отправить {recipients} получателям",
                callback_data=f"newsletter:send:{frequency}",
            )],
            [InlineKeyboardButton(text="Отмена", callback_data="newsletter:cancel")],
        ]),
    )


@router.callback_query(F.data == "newsletter:cancel")
async def newsletter_cancel(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Только для администраторов", show_alert=True)
        return
    await callback.answer("Отменено")
    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=None)


@router.callback_query(F.data.startswith("newsletter:send:"))
async def newsletter_send_confirm(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Только для администраторов", show_alert=True)
        return
    frequency = callback.data.rsplit(":", 1)[1]
    if frequency not in FREQUENCIES:
        await callback.answer("Некорректный выпуск", show_alert=True)
        return
    await callback.answer("Отправка началась")
    if callback.message:
        await callback.message.edit_text("✉️ Отправляю выпуск…")
    result = await send_campaign(frequency)
    if callback.message:
        await callback.message.edit_text(
            f"✅ <b>Рассылка завершена</b>\n\n"
            f"Получателей: {result['recipients']}\n"
            f"Отправлено: {result['sent']}\n"
            f"Ошибок: {result['failed']}\n"
            f"Пропущено как уже отправленные: {result['skipped']}"
        )
