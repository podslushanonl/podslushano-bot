"""Compose, preview and explicitly publish answers to a separately connected channel."""
import html
import logging
import uuid

from aiogram import BaseMiddleware, F, Router
from aiogram.enums import ChatType, ChatMemberStatus
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import update

import config
from database.db import get_session
from database.models import Meta
from database.anonymous_questions import AnonymousAnswer, AnonymousQuestion

log = logging.getLogger(__name__)
router = Router()
router.message.filter(F.chat.type == ChatType.PRIVATE)
class PrivateReplyActions(BaseMiddleware):
    async def __call__(self, handler, event, data):
        if (event.data or "").startswith(("alexpub:", "alexq:reply:")) and (
            not event.message or event.message.chat.type != ChatType.PRIVATE
        ):
            text = ("Открой личный чат с ботом и команду /alexquestions, чтобы ответить."
                    if event.from_user.id in config.ADMIN_IDS else "Недоступно")
            await event.answer(text, show_alert=True)
            return
        return await handler(event, data)


router.callback_query.outer_middleware(PrivateReplyActions())
CHANNEL_KEY = "alex_answer_channel_id"


class ReplyForm(StatesGroup):
    channel = State()
    confirm_channel = State()
    answer = State()


def _admin(uid):
    return uid in config.ADMIN_IDS


def _kb(rows):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=text, callback_data=payload) for text, payload in row]
        for row in rows
    ])


def _cancel_kb():
    return _kb([[("Отмена", "alexpub:cancel")]])


async def _channel_id():
    async with get_session() as db:
        row = await db.get(Meta, CHANNEL_KEY)
        return int(row.value) if row else None


async def _check_channel(bot, channel_id, admin_id):
    chat = await bot.get_chat(channel_id)
    if chat.type != ChatType.CHANNEL:
        raise ValueError("Нужен именно канал, а не чат обсуждений.")
    if config.ANNOUNCE_CHANNEL:
        work = await bot.get_chat(config.ANNOUNCE_CHANNEL)
        if work.id == chat.id:
            raise ValueError("Это рабочий канал. Для личных ответов подключи свой личный канал.")
    for uid, label in [(bot.id, "бота"), (admin_id, "твоего аккаунта")]:
        member = await bot.get_chat_member(chat.id, uid)
        if member.status == ChatMemberStatus.CREATOR:
            continue
        if member.status != ChatMemberStatus.ADMINISTRATOR or not member.can_post_messages:
            raise ValueError(f"У {label} нет права публиковать в этом канале.")
    return chat


async def _setup(message, state):
    await state.set_state(ReplyForm.channel)
    await message.answer(
        "📣 <b>Подключение личного канала</b>\n\n"
        "1. Добавь этого бота администратором своего личного канала с правом публикации сообщений.\n"
        "2. Перешли сюда любой пост <b>из самого канала</b>, не из чата комментариев.\n\n"
        "Если пересылка запрещена, пришли @username канала или его числовой ID. "
        "Пригласительная ссылка для подключения не подходит.\n\n"
        "Перед подключением я покажу название канала для подтверждения.",
        reply_markup=_cancel_kb(),
    )


@router.message(Command("alexchannel"))
async def channel_command(message: Message, state: FSMContext):
    if not _admin(message.from_user.id):
        return
    await state.clear()
    await _setup(message, state)


@router.callback_query(F.data == "alexpub:setup")
async def channel_setup(callback: CallbackQuery, state: FSMContext):
    if not _admin(callback.from_user.id):
        await callback.answer("Недоступно", show_alert=True)
        return
    await callback.answer()
    await state.clear()
    await _setup(callback.message, state)


@router.message(ReplyForm.channel, lambda m: not (m.text or "").startswith("/"))
async def receive_channel(message: Message, state: FSMContext):
    if not _admin(message.from_user.id):
        return
    origin = message.forward_origin
    channel_id = getattr(getattr(origin, "chat", None), "id", None)
    if channel_id is None:
        text = (message.text or "").strip()
        if text.startswith("@"):
            channel_id = text
        elif text.startswith("-100") and text[1:].isdigit():
            channel_id = int(text)
    if channel_id is None:
        await message.answer("Перешли пост из канала или пришли его @username / числовой ID.")
        return
    try:
        chat = await _check_channel(message.bot, channel_id, message.from_user.id)
    except ValueError as exc:
        await message.answer(str(exc), reply_markup=_cancel_kb())
        return
    except Exception:
        await message.answer("Не удалось проверить канал. Проверь, что бот добавлен администратором с правом публикации, и перешли пост ещё раз.")
        return
    await state.update_data(candidate_channel=chat.id)
    await state.set_state(ReplyForm.confirm_channel)
    await message.answer(
        f"Публиковать ответы в канал <b>{html.escape(chat.title or str(chat.id))}</b>?\n"
        f"ID: <code>{chat.id}</code>",
        reply_markup=_kb([[("✅ Подключить этот канал", "alexpub:connect")], [("Отмена", "alexpub:cancel")]]),
    )


@router.callback_query(F.data == "alexpub:connect")
async def connect_channel(callback: CallbackQuery, state: FSMContext):
    if not _admin(callback.from_user.id):
        await callback.answer("Недоступно", show_alert=True)
        return
    data = await state.get_data()
    if await state.get_state() != ReplyForm.confirm_channel.state or not data.get("candidate_channel"):
        await callback.answer("Открой подключение заново: /alexchannel", show_alert=True)
        return
    await callback.answer()
    try:
        chat = await _check_channel(callback.bot, data["candidate_channel"], callback.from_user.id)
    except Exception:
        await callback.message.answer("Не удалось подтвердить права. Проверь их и повтори /alexchannel.")
        return
    async with get_session() as db:
        row = await db.get(Meta, CHANNEL_KEY)
        if row:
            row.value = str(chat.id)
        else:
            db.add(Meta(key=CHANNEL_KEY, value=str(chat.id)))
        await db.commit()
    qid = data.get("question_id")
    await state.clear()
    await callback.message.answer(f"✅ Подключён канал <b>{html.escape(chat.title or '')}</b>. Ответы публикуются только после предпросмотра и твоего нажатия «Опубликовать».")
    if qid:
        await _open_reply(callback.message, state, qid, callback.from_user.id)
    else:
        await callback.message.answer("Теперь открой /alexquestions, выбери вопрос и нажми «Ответить».")


@router.callback_query((F.data == "alexpub:cancel") | F.data.startswith("alexpub:cancel:"))
async def cancel(callback: CallbackQuery, state: FSMContext):
    if not _admin(callback.from_user.id):
        await callback.answer("Недоступно", show_alert=True)
        return
    data = await state.get_data()
    qid, version = data.get("preview_question"), data.get("preview_version")
    if callback.data.startswith("alexpub:cancel:"):
        try:
            _, _, raw_id, version = callback.data.split(":")
            qid = int(raw_id)
        except ValueError:
            await callback.answer("Некорректная кнопка", show_alert=True)
            return
    if qid and version:
        async with get_session() as db:
            row = await db.get(AnonymousAnswer, qid)
            if row and row.status != "draft":
                await callback.answer("Ответ уже отправляется или опубликован. Отменить отправку этой кнопкой нельзя.", show_alert=True)
                return
            result = await db.execute(update(AnonymousAnswer).where(
                AnonymousAnswer.question_id == qid,
                AnonymousAnswer.version == version,
                AnonymousAnswer.status == "draft",
            ).values(version=uuid.uuid4().hex))
            await db.commit()
            if not result.rowcount:
                await callback.answer("Предпросмотр уже неактуален или отправка началась. Проверь канал и очередь вопросов.", show_alert=True)
                return
    if callback.data == "alexpub:cancel" or (qid, version) == (data.get("preview_question"), data.get("preview_version")):
        await state.clear()
    await callback.answer()
    await callback.message.answer("Этот предпросмотр отменён. Черновик можно снова открыть через /alexquestions.")


async def _preview(message, qid, admin_id, state):
    channel_id = await _channel_id()
    if channel_id is None:
        await message.answer("Сначала подключи личный канал: /alexchannel.")
        return
    try:
        chat = await _check_channel(message.bot, channel_id, admin_id)
    except Exception:
        await message.answer("Не удалось проверить право публикации. Проверь права бота и повтори через /alexquestions.")
        return
    async with get_session() as db:
        draft = await db.get(AnonymousAnswer, qid)
        if not draft or draft.status != "draft":
            await message.answer("Этот вопрос уже опубликован или его отправка требует проверки.")
            return
        # Pin the destination and rotate the token: old preview buttons cannot publish.
        draft.channel_id = chat.id
        draft.version = uuid.uuid4().hex
        await db.commit()
        post, version = draft.post_html, draft.version
    await state.update_data(preview_question=qid, preview_version=version)
    await message.answer(f"Предпросмотр для канала <b>{html.escape(chat.title or '')}</b> 👇")
    await message.answer(post, parse_mode="HTML", reply_markup=_kb([
        [("📣 Опубликовать", f"alexpub:publish:{qid}:{version}")],
        [("✏️ Изменить ответ", f"alexpub:edit:{qid}"), ("Отмена", f"alexpub:cancel:{qid}:{version}")],
    ]))


async def _open_reply(message, state, qid, admin_id, edit=False):
    async with get_session() as db:
        question = await db.get(AnonymousQuestion, qid)
        draft = await db.get(AnonymousAnswer, qid)
        if question is None:
            await message.answer("Вопрос не найден.")
            return
        if draft and draft.status != "draft":
            text = "Этот ответ уже опубликован." if draft.status == "published" else "Отправка этого ответа уже начата или не подтверждена. Проверь канал; повторная отправка заблокирована, чтобы не создать дубль."
            await message.answer(text)
            return
        question_text = question.text
        has_draft = draft is not None
    await state.clear()
    await state.update_data(question_id=qid)
    if await _channel_id() is None:
        await _setup(message, state)
        return
    if has_draft and not edit:
        await _preview(message, qid, admin_id, state)
        return
    # Invalidate an older preview when editing begins.
    async with get_session() as db:
        await db.execute(update(AnonymousAnswer).where(
            AnonymousAnswer.question_id == qid, AnonymousAnswer.status == "draft"
        ).values(version=uuid.uuid4().hex))
        await db.commit()
    await state.set_state(ReplyForm.answer)
    await message.answer(
        f"✍️ <b>Ответ на вопрос #{qid}</b>\n\n<blockquote>{html.escape(question_text)}</blockquote>\n\n"
        "Напиши ответ следующим сообщением. Можно использовать жирный текст, курсив и ссылки. "
        "Сначала покажу предпросмотр; в канал пока ничего не отправится.", reply_markup=_cancel_kb(),
    )


@router.callback_query(F.data.startswith("alexq:reply:") | F.data.startswith("alexpub:edit:"))
async def open_reply(callback: CallbackQuery, state: FSMContext):
    if not _admin(callback.from_user.id):
        await callback.answer("Недоступно", show_alert=True)
        return
    try:
        qid = int(callback.data.rsplit(":", 1)[1])
    except ValueError:
        await callback.answer("Вопрос не найден")
        return
    await callback.answer()
    await _open_reply(callback.message, state, qid, callback.from_user.id, edit=callback.data.startswith("alexpub:edit:"))


@router.message(ReplyForm.answer, lambda m: not (m.text or "").startswith("/"))
async def receive_answer(message: Message, state: FSMContext):
    if not _admin(message.from_user.id):
        return
    if not message.text:
        await message.answer("Напиши ответ текстом. Форматирование и смайлики сохранятся.")
        return
    qid = (await state.get_data()).get("question_id")
    async with get_session() as db:
        question = await db.get(AnonymousQuestion, qid or 0)
        if not question:
            await state.clear()
            await message.answer("Открой вопрос заново через /alexquestions.")
            return
        plain = f"💬 Анонимный вопрос\n\n{question.text}\n\n{message.text}"
        if len(plain.encode("utf-16-le")) // 2 > 4000:
            await message.answer("Вопрос вместе с ответом не помещается в один пост. Сократи ответ и отправь снова; вопрос сохраняется целиком.")
            return
        post = f"💬 <b>Анонимный вопрос</b>\n\n<blockquote>{html.escape(question.text)}</blockquote>\n\n{message.html_text}"
        draft = await db.get(AnonymousAnswer, qid)
        if draft:
            result = await db.execute(update(AnonymousAnswer).where(
                AnonymousAnswer.question_id == qid, AnonymousAnswer.status == "draft"
            ).values(post_html=post, version=uuid.uuid4().hex, channel_id=None))
            if not result.rowcount:
                await message.answer("Этот ответ уже отправляется или опубликован. Изменения не сохранены.")
                return
        else:
            db.add(AnonymousAnswer(question_id=qid, post_html=post, version=uuid.uuid4().hex, status="draft"))
        question.status = "selected"
        await db.commit()
    await state.clear()
    await _preview(message, qid, message.from_user.id, state)


@router.callback_query(F.data.startswith("alexpub:publish:"))
async def publish(callback: CallbackQuery, state: FSMContext):
    if not _admin(callback.from_user.id):
        await callback.answer("Недоступно", show_alert=True)
        return
    try:
        _, _, qid, version = callback.data.split(":")
        qid = int(qid)
    except (ValueError, AttributeError):
        await callback.answer("Открой предпросмотр заново", show_alert=True)
        return
    await callback.answer()
    channel_id = await _channel_id()
    async with get_session() as db:
        draft = await db.get(AnonymousAnswer, qid)
        if not draft or draft.status != "draft" or draft.version != version or draft.channel_id != channel_id:
            await callback.message.answer("Этот предпросмотр уже неактуален или ответ уже отправляется/опубликован. Открой вопрос через /alexquestions.")
            return
        post = draft.post_html
    try:
        chat = await _check_channel(callback.bot, channel_id, callback.from_user.id)
    except Exception:
        await callback.message.answer("Публикация не выполнена: не удалось подтвердить права на канал. Проверь их и попробуй снова.")
        return
    # Atomic database claim survives restarts and prevents double-clicks/multiple admins.
    async with get_session() as db:
        result = await db.execute(update(AnonymousAnswer).where(
            AnonymousAnswer.question_id == qid, AnonymousAnswer.status == "draft",
            AnonymousAnswer.version == version, AnonymousAnswer.channel_id == channel_id,
        ).values(status="publishing"))
        await db.commit()
        if not result.rowcount:
            await callback.message.answer("Этот ответ уже отправляется или опубликован.")
            return
    try:
        sent = await callback.bot.send_message(chat.id, post, parse_mode="HTML")
    except (TelegramBadRequest, TelegramForbiddenError):
        async with get_session() as db:
            await db.execute(update(AnonymousAnswer).where(AnonymousAnswer.question_id == qid).values(status="draft"))
            await db.commit()
        await callback.message.answer("Telegram отклонил публикацию. Черновик сохранён. Проверь права и открой вопрос заново через /alexquestions.")
        return
    except Exception as exc:
        log.warning("Anonymous answer publication uncertain for question %s (%s)", qid, type(exc).__name__)
        async with get_session() as db:
            await db.execute(update(AnonymousAnswer).where(AnonymousAnswer.question_id == qid).values(status="uncertain"))
            await db.commit()
        await callback.message.answer("Не удалось подтвердить отправку. Проверь канал: пост мог появиться. Повторная отправка заблокирована, чтобы не создать дубль.")
        return
    async with get_session() as db:
        await db.execute(update(AnonymousAnswer).where(AnonymousAnswer.question_id == qid).values(status="published", message_id=sent.message_id))
        await db.execute(update(AnonymousQuestion).where(AnonymousQuestion.id == qid).values(status="published"))
        await db.commit()
    await state.clear()
    username = getattr(chat, "username", None)
    link = f"https://t.me/{username}/{sent.message_id}" if username else f"https://t.me/c/{str(chat.id).removeprefix('-100')}/{sent.message_id}"
    await callback.message.answer(f'✅ <a href="{link}">Ответ опубликован в личном канале</a>.', parse_mode="HTML")
