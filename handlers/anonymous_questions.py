"""Личные анонимные вопросы Алексу из Telegram-канала.

Сценарий изолирован от рабочей предложки Podslushano.nl. В БД не сохраняются
Telegram user_id, username, имя или ссылка на профиль отправителя.
"""
import hashlib
import hmac
import html
import logging
import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import func, select

import config
from database.anonymous_questions import AnonymousQuestion, AnonymousQuestionBlock
from database.db import get_session

log = logging.getLogger(__name__)
router = Router()
router.message.filter(F.chat.type == ChatType.PRIVATE)

MAX_QUESTIONS = 5
RATE_WINDOW_MINUTES = 30


class AnonymousQuestionForm(StatesGroup):
    waiting_text = State()


def sender_hash(user_id: int) -> str:
    """Необратимый идентификатор для лимитов/блокировки без хранения user_id."""
    key = config.BOT_TOKEN.encode("utf-8")
    payload = f"alex-anonymous-question:{user_id}".encode("utf-8")
    return hmac.new(key, payload, hashlib.sha256).hexdigest()


def question_target_chat_id() -> int | None:
    """Отдельный чат можно задать env; без него вопросы идут первому админу."""
    raw = os.getenv("ALEX_QUESTIONS_CHAT_ID", "").strip()
    if raw and raw.lstrip("-").isdigit():
        return int(raw)
    return config.ADMIN_IDS[0] if config.ADMIN_IDS else None


def _cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Отмена", callback_data="alexq:cancel")]
        ]
    )


def _after_submit_kb() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="Задать ещё вопрос", callback_data="alexq:new")]
    ]
    if config.BOT_URL:
        rows.append([InlineKeyboardButton(text="Вернуться в бот", url=config.BOT_URL)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _admin_kb(question_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📌 Сохранить вопрос", callback_data=f"alexq:answer:{question_id}"
                ),
                InlineKeyboardButton(
                    text="🗑 Пропустить", callback_data=f"alexq:skip:{question_id}"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🚫 Заблокировать отправителя",
                    callback_data=f"alexq:block:{question_id}",
                )
            ],
        ]
    )


async def _queue_kb() -> InlineKeyboardMarkup:
    async with get_session() as session:
        pending = (await session.scalars(select(AnonymousQuestion.id).where(
            AnonymousQuestion.status == "pending").order_by(AnonymousQuestion.id).limit(6))).all()
        selected = (await session.scalars(select(AnonymousQuestion.id).where(
            AnonymousQuestion.status == "selected").order_by(AnonymousQuestion.id.desc()).limit(6))).all()
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"Открыть вопрос #{qid}", callback_data=f"alexq:open:{qid}")]
            for qid in [*pending, *selected]
        ] + [
            [InlineKeyboardButton(text="🔄 Обновить", callback_data="alexq:queue")]
        ]
    )


def _status_title(status: str) -> str:
    return {
        "pending": "❓ Анонимный вопрос",
        "selected": "📌 Сохранённый вопрос",
        "skipped": "🗑 Пропущено",
    }.get(status, "❓ Анонимный вопрос")


def _created_local(value: datetime | None) -> str:
    if value is None:
        return datetime.now(ZoneInfo("Europe/Amsterdam")).strftime("%d.%m.%Y · %H:%M")
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(ZoneInfo("Europe/Amsterdam")).strftime("%d.%m.%Y · %H:%M")


def _admin_question_text(question: AnonymousQuestion) -> str:
    return (
        f"{_status_title(question.status)} <b>#{question.id}</b>\n\n"
        f"{html.escape(question.text)}\n\n"
        f"<code>{_created_local(question.created_at)}</code>"
    )


def _intro_text() -> str:
    return (
        "👀 <b>Анонимный вопрос</b>\n\n"
        "Здесь можно спросить меня абсолютно о чём угодно.\n\n"
        "Я увижу только текст вопроса — без имени, username и ссылки на "
        "Telegram-профиль.\n\n"
        "Напиши вопрос следующим сообщением 👇"
    )


@router.message(F.text.regexp(r"^/start(?:@\w+)?\s+ask_alex$"), flags={"anonymous_question": True})
async def start_anonymous_question(message: Message, state: FSMContext) -> None:
    """Deep-link: https://t.me/<bot>?start=ask_alex."""
    await state.clear()
    await state.set_state(AnonymousQuestionForm.waiting_text)
    await message.answer(_intro_text(), reply_markup=_cancel_kb())


@router.callback_query(F.data == "alexq:new", flags={"anonymous_question": True})
async def anonymous_question_again(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(AnonymousQuestionForm.waiting_text)
    await callback.message.answer(
        "Напиши следующий анонимный вопрос одним сообщением 👇",
        reply_markup=_cancel_kb(),
    )
    await callback.answer()


@router.callback_query(F.data == "alexq:cancel", flags={"anonymous_question": True})
async def anonymous_question_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.answer("Ок, вопрос не отправлен.", reply_markup=_after_submit_kb())
    await callback.answer()


async def _is_blocked(identity_hash: str) -> bool:
    async with get_session() as session:
        return await session.get(AnonymousQuestionBlock, identity_hash) is not None


async def _rate_limit_reached(identity_hash: str) -> bool:
    cutoff = datetime.utcnow() - timedelta(minutes=RATE_WINDOW_MINUTES)
    async with get_session() as session:
        count = await session.scalar(
            select(func.count(AnonymousQuestion.id)).where(
                AnonymousQuestion.sender_hash == identity_hash,
                AnonymousQuestion.created_at >= cutoff,
            )
        )
    return int(count or 0) >= MAX_QUESTIONS


async def _save_question(identity_hash: str, text: str) -> AnonymousQuestion:
    async with get_session() as session:
        question = AnonymousQuestion(sender_hash=identity_hash, text=text)
        session.add(question)
        await session.commit()
        await session.refresh(question)
        return question


async def _notify_admin(message: Message, question: AnonymousQuestion) -> bool:
    target = question_target_chat_id()
    if target is None:
        log.error("Anonymous question #%s saved, but no admin target is configured", question.id)
        return False
    try:
        await message.bot.send_message(
            target,
            _admin_question_text(question),
            reply_markup=_admin_kb(question.id),
        )
        return True
    except Exception as exc:  # вопрос уже сохранён; сбой Telegram не должен его потерять
        log.warning("Could not notify admin about anonymous question #%s (%s)", question.id, type(exc).__name__)
        return False


@router.message(
    AnonymousQuestionForm.waiting_text,
    lambda message: not (message.text or "").startswith("/"),
    flags={"anonymous_question": True},
)
async def receive_anonymous_question(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text:
        await message.answer(
            "Сейчас здесь принимаются только текстовые вопросы. Напиши вопрос "
            "одним сообщением 👇",
            reply_markup=_cancel_kb(),
        )
        return
    if len(text) < 2:
        await message.answer("Напиши сам вопрос чуть подробнее 👇", reply_markup=_cancel_kb())
        return
    # Leave room for the header/date, counting Telegram's UTF-16 code units.
    if len(text.encode("utf-16-le")) // 2 > 3500:
        await message.answer("Вопрос слишком длинный. Сократи его до 3500 символов 👇", reply_markup=_cancel_kb())
        return

    identity_hash = sender_hash(message.from_user.id)
    if await _is_blocked(identity_hash):
        await state.clear()
        await message.answer("Отправка анонимных вопросов для этого аккаунта недоступна.")
        return
    if await _rate_limit_reached(identity_hash):
        await state.clear()
        await message.answer(
            "Ты отправил(а) слишком много вопросов за короткое время 😅 "
            "Попробуй немного позже.",
            reply_markup=_after_submit_kb(),
        )
        return

    question = await _save_question(identity_hash, text)
    delivered = await _notify_admin(message, question)
    await state.clear()
    await message.answer(
        ("✅ <b>Вопрос отправлен анонимно</b>\n\nАлекс его получил.\n\n" if delivered else
         "✅ <b>Вопрос сохранён анонимно</b>\n\nУведомление пока не доставлено, но вопрос доступен Алексу в очереди.\n\n") +
        "Если захочется спросить что-нибудь ещё — можно отправить новый вопрос.",
        reply_markup=_after_submit_kb(),
    )


def _is_admin(user_id: int) -> bool:
    return user_id in config.ADMIN_IDS


async def _load_question(question_id: int) -> AnonymousQuestion | None:
    async with get_session() as session:
        return await session.get(AnonymousQuestion, question_id)


async def _set_status(question_id: int, status: str) -> AnonymousQuestion | None:
    async with get_session() as session:
        question = await session.get(AnonymousQuestion, question_id)
        if question is None:
            return None
        question.status = status
        await session.commit()
        await session.refresh(question)
        return question


def _callback_question_id(data: str | None) -> int | None:
    if not data:
        return None
    try:
        return int(data.rsplit(":", 1)[1])
    except (ValueError, IndexError):
        return None


@router.callback_query(F.data.startswith("alexq:answer:"))
async def admin_select_question(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Недоступно", show_alert=True)
        return
    question_id = _callback_question_id(callback.data)
    question = await _set_status(question_id or 0, "selected")
    if question is None:
        await callback.answer("Вопрос не найден", show_alert=True)
        return
    await callback.message.edit_text(
        _admin_question_text(question)
        + "\n\n📌 Вопрос сохранён. Найти его можно в /alexquestions.\n"
        "Ответ напиши отдельным постом в личном канале. "
        "Эта кнопка только сохраняет вопрос и ничего не публикует."
    )
    await callback.answer("Вопрос сохранён")


@router.callback_query(F.data.startswith("alexq:skip:"))
async def admin_skip_question(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Недоступно", show_alert=True)
        return
    question_id = _callback_question_id(callback.data)
    question = await _set_status(question_id or 0, "skipped")
    if question is None:
        await callback.answer("Вопрос не найден", show_alert=True)
        return
    await callback.message.edit_text(_admin_question_text(question))
    await callback.answer("Пропущено")


@router.callback_query(F.data.startswith("alexq:block:"))
async def admin_block_sender(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Недоступно", show_alert=True)
        return
    question_id = _callback_question_id(callback.data)
    if not question_id:
        await callback.answer("Вопрос не найден", show_alert=True)
        return

    async with get_session() as session:
        question = await session.get(AnonymousQuestion, question_id)
        if question is None:
            await callback.answer("Вопрос не найден", show_alert=True)
            return
        if await session.get(AnonymousQuestionBlock, question.sender_hash) is None:
            session.add(AnonymousQuestionBlock(sender_hash=question.sender_hash))
        question.status = "skipped"
        await session.commit()
        await session.refresh(question)

    await callback.message.edit_text(
        _admin_question_text(question) + "\n\n🚫 <b>Отправитель заблокирован.</b>"
    )
    await callback.answer("Заблокировано")


async def _queue_text() -> str:
    async with get_session() as session:
        pending = await session.scalar(
            select(func.count(AnonymousQuestion.id)).where(AnonymousQuestion.status == "pending")
        )
        selected = await session.scalar(
            select(func.count(AnonymousQuestion.id)).where(AnonymousQuestion.status == "selected")
        )
        skipped = await session.scalar(
            select(func.count(AnonymousQuestion.id)).where(AnonymousQuestion.status == "skipped")
        )
        selected_rows = (
            await session.scalars(
                select(AnonymousQuestion)
                .where(AnonymousQuestion.status == "selected")
                .order_by(AnonymousQuestion.created_at.desc())
                .limit(6)
            )
        ).all()
        pending_rows = (await session.scalars(select(AnonymousQuestion)
            .where(AnonymousQuestion.status == "pending")
            .order_by(AnonymousQuestion.id).limit(6))).all()

    lines = [
        "👀 <b>Анонимные вопросы Алексу</b>",
        "",
        f"Новые: <b>{int(pending or 0)}</b>",
        f"Для ответа: <b>{int(selected or 0)}</b>",
        f"Пропущено: <b>{int(skipped or 0)}</b>",
    ]
    for title, rows in [("Новые вопросы", pending_rows), ("Очередь для ответа", selected_rows)]:
        if not rows:
            continue
        lines.extend(["", f"<b>{title}:</b>"])
        for question in rows:
            preview = " ".join(question.text.split())
            if len(preview) > 120:
                preview = preview[:117] + "…"
            lines.extend(["", f"<b>#{question.id}</b> — {html.escape(preview)}"])
    if not pending_rows and not selected_rows:
        lines.extend(["", "Очередь пока пустая."])
    lines.extend(["", "<i>Личность отправителей в этой очереди не хранится.</i>"])
    return "\n".join(lines)


@router.message(Command("alexquestions"))
async def admin_questions_queue(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        return
    await message.answer(await _queue_text(), reply_markup=await _queue_kb())


@router.callback_query(F.data.startswith("alexq:open:"))
async def admin_open_question(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Недоступно", show_alert=True)
        return
    question = await _load_question(_callback_question_id(callback.data) or 0)
    if question is None:
        await callback.answer("Вопрос не найден", show_alert=True)
        return
    await callback.message.answer(_admin_question_text(question), reply_markup=_admin_kb(question.id))
    await callback.answer()


@router.callback_query(F.data == "alexq:queue")
async def admin_refresh_queue(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Недоступно", show_alert=True)
        return
    await callback.message.edit_text(await _queue_text(), reply_markup=await _queue_kb())
    await callback.answer("Обновлено")
