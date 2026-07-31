"""Полный рекламный цикл: история, AI-продолжение, оплата и производство."""
from __future__ import annotations

import html
import json
import logging
import re
from datetime import datetime, timedelta

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import or_, select

import config
from database.ad_sales_models import AdConversationMessage, AdSalesPipeline
from database.db import get_session
from database.models import AdBooking, Submission
from utils.notify import get_mod_chat

log = logging.getLogger(__name__)
ADS_URL = "https://worker-production-ad76.up.railway.app/ads"
ACTIVE_SALES = {"pending", "contacted", "awaiting_payment"}
PRODUCTION_LABELS = {
    "waiting_materials": "📥 Ждём материалы",
    "materials_received": "📦 Материалы получены",
    "scheduled": "🗓 Запланировано",
    "published": "🚀 Опубликовано",
    "completed": "🏁 Завершено",
}


async def ensure_pipeline(submission: Submission) -> AdSalesPipeline:
    async with get_session() as session:
        row = await session.scalar(
            select(AdSalesPipeline).where(AdSalesPipeline.submission_id == submission.id)
        )
        if row is None:
            row = AdSalesPipeline(
                submission_id=submission.id,
                user_id=submission.user_id,
                sales_status=submission.status if submission.status != "pending" else "new",
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return row


async def record_message(
    submission_id: int,
    user_id: int,
    role: str,
    text: str,
    *,
    kind: str = "inbound",
    telegram_message_id: int | None = None,
) -> None:
    clean = (text or "").strip()
    if not clean:
        return
    async with get_session() as session:
        session.add(AdConversationMessage(
            submission_id=submission_id,
            user_id=user_id,
            role=role,
            kind=kind,
            text=clean,
            telegram_message_id=telegram_message_id,
        ))
        await session.commit()


async def conversation_history(submission_id: int, limit: int = 20) -> list[AdConversationMessage]:
    async with get_session() as session:
        rows = (await session.scalars(
            select(AdConversationMessage)
            .where(AdConversationMessage.submission_id == submission_id)
            .order_by(AdConversationMessage.id.desc())
            .limit(limit)
        )).all()
    return list(reversed(rows))


async def active_ad_submission(user_id: int) -> Submission | None:
    async with get_session() as session:
        return await session.scalar(
            select(Submission)
            .where(
                Submission.type == "ad",
                Submission.user_id == user_id,
                Submission.status.in_(list(ACTIVE_SALES)),
            )
            .order_by(Submission.id.desc())
        )


def _client():
    from anthropic import AsyncAnthropic
    return AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)


async def generate_sales_reply(submission: Submission, client_text: str) -> str | None:
    if not config.ANTHROPIC_API_KEY:
        return None
    history = await conversation_history(submission.id, 16)
    transcript = "\n".join(
        f"{ {'client':'Клиент','manager':'Менеджер','ai':'AI','system':'Система'}.get(m.role, m.role) }: {m.text}"
        for m in history
    )
    prompt = f"""Ты — менеджер по рекламе Podslushano.nl. Подготовь только готовый ответ клиенту на русском языке.
Цель — довести до подходящего размещения и оплаты, но без давления и выдуманных обещаний.
Страница форматов и оплаты: {ADS_URL}

Правила:
- 2–7 предложений, живо и профессионально;
- отвечай конкретно на вопрос/возражение;
- не придумывай охваты, скидки, даты и условия, которых нет в переписке;
- потенциальным конкурентам (медиа, сообщества, каналы, клубы встреч) не отправляй ссылку автоматически: предложи уточнить концепцию и аудиторию;
- если клиент готов — направь к оформлению;
- не говори, что ты AI.

Исходная заявка:
{submission.text or '—'}

История:
{transcript or '—'}

Новое сообщение клиента:
{client_text}
"""
    try:
        response = await _client().messages.create(
            model=config.AI_CHAT_MODEL,
            max_tokens=700,
            temperature=0.25,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(getattr(b, "text", "") for b in response.content).strip() or None
    except Exception as exc:  # noqa: BLE001
        log.warning("Не удалось подготовить ответ по рекламному лиду %s: %s", submission.id, exc)
        return None


def suggestion_keyboard(submission_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Отправить AI-ответ", callback_data=f"aicontsend:{submission_id}")],
        [InlineKeyboardButton(text="✍️ Ответить вручную", callback_data=f"subreply:{submission_id}")],
        [InlineKeyboardButton(text="🧾 История диалога", callback_data=f"aihistory:{submission_id}")],
        [
            InlineKeyboardButton(text="⏳ Ждём оплату", callback_data=f"aistatus:awaiting_payment:{submission_id}"),
            InlineKeyboardButton(text="✅ Оплачено", callback_data=f"aistatus:paid:{submission_id}"),
        ],
    ])


def production_keyboard(submission_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=label, callback_data=f"aiprod:{key}:{submission_id}")]
        for key, label in PRODUCTION_LABELS.items()
    ])


async def notify_new_client_message(bot: Bot, submission: Submission, client_text: str, suggestion: str | None) -> None:
    target = await get_mod_chat()
    targets = [target] if target else list(config.ADMIN_IDS)
    author = f"@{submission.username}" if submission.username else f"id {submission.user_id}"
    body = (
        f"💬 <b>Клиент ответил по рекламе · заявка №{submission.id}</b>\n"
        f"👤 {author}\n\n"
        f"<b>Сообщение клиента:</b>\n{html.escape(client_text)}"
    )
    if suggestion:
        body += f"\n\n🤖 <b>Предложенный ответ:</b>\n{html.escape(suggestion)}"
        await record_message(submission.id, submission.user_id, "ai", suggestion, kind="suggestion")
    else:
        body += "\n\n⚠️ AI не смог подготовить ответ — ответьте вручную."
    for chat_id in targets:
        try:
            await bot.send_message(chat_id, body, reply_markup=suggestion_keyboard(submission.id))
        except Exception as exc:  # noqa: BLE001
            log.warning("Не удалось уведомить о сообщении рекламного клиента: %s", exc)


async def latest_ai_suggestion(submission_id: int) -> AdConversationMessage | None:
    async with get_session() as session:
        return await session.scalar(
            select(AdConversationMessage)
            .where(
                AdConversationMessage.submission_id == submission_id,
                AdConversationMessage.role == "ai",
                AdConversationMessage.kind == "suggestion",
            )
            .order_by(AdConversationMessage.id.desc())
        )


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9@.+_-]{4,}", (text or "").lower()))


async def reconcile_paid_bookings(bot: Bot) -> None:
    """Связывает новые paid-брони с активными лидами по контактам/данным заявки."""
    async with get_session() as session:
        bookings = (await session.scalars(
            select(AdBooking).where(AdBooking.status == "paid").order_by(AdBooking.id.desc())
        )).all()
        linked_ids = set((await session.scalars(
            select(AdSalesPipeline.ad_booking_id).where(AdSalesPipeline.ad_booking_id.is_not(None))
        )).all())
        leads = (await session.scalars(
            select(Submission).where(
                Submission.type == "ad",
                Submission.status.in_(["pending", "contacted", "awaiting_payment"]),
                Submission.created_at >= datetime.utcnow() - timedelta(days=45),
            ).order_by(Submission.id.desc())
        )).all()

    for booking in bookings:
        if booking.id in linked_ids:
            continue
        booking_tokens = _tokens(" ".join(filter(None, [
            booking.email, booking.phone, booking.buyer_name, booking.company,
        ])))
        candidates = [lead for lead in leads if booking_tokens & _tokens(lead.text or "")]
        if len(candidates) != 1:
            continue
        lead = candidates[0]
        pipeline = await ensure_pipeline(lead)
        async with get_session() as session:
            row = await session.get(AdSalesPipeline, pipeline.id)
            row.sales_status = "paid"
            row.production_status = "waiting_materials"
            row.ad_booking_id = booking.id
            row.payment_id = booking.payment_id
            row.format_name = booking.fmt
            row.publish_dates = booking.dates_csv or booking.date
            row.paid_at = datetime.utcnow()
            lead_db = await session.get(Submission, lead.id)
            lead_db.status = "paid"
            await session.commit()
        await record_message(lead.id, lead.user_id, "system", f"Оплата сопоставлена автоматически: бронь №{booking.id}", kind="payment")
        target = await get_mod_chat()
        targets = [target] if target else list(config.ADMIN_IDS)
        text = (
            f"💳 <b>Оплата рекламы найдена автоматически</b>\n\n"
            f"Заявка №{lead.id} · бронь №{booking.id}\n"
            f"Формат: {html.escape(booking.fmt)}\n"
            f"Дата: {html.escape(booking.dates_csv or booking.date)}\n\n"
            "Лид переведён в производство: ждём материалы."
        )
        for chat_id in targets:
            await bot.send_message(chat_id, text, reply_markup=production_keyboard(lead.id))
