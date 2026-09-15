"""Admin comment copilot for a dedicated Telegram topic or private session.

The copilot never posts to Instagram. It analyses a screenshot/text, recommends
whether to reply at all, and learns the Podslushano.nl voice only from variants
the admin explicitly accepts.
"""
from __future__ import annotations

import base64
import json
import logging
import re
import uuid

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import BaseFilter
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select

import config
from database.db import get_session
from database.models import CommentReplyDraft, CommentReplyExample
from utils.ai import _get_client, ai_enabled
from utils.editorial_channel import _meta_get, _meta_set

log = logging.getLogger(__name__)
router = Router()


class CommentCopilot(StatesGroup):
    active = State()


class ConfiguredCommentTopic(BaseFilter):
    """Do not consume unrelated admin messages in other forum topics."""

    async def __call__(self, message: Message) -> bool:
        chat_id, topic_id = await _configured_topic()
        return bool(chat_id == message.chat.id and topic_id == message.message_thread_id)


VOICE_RULES = """
Ты редактор ответов Podslushano.nl в Instagram. Это живое русскоязычное медиа о Нидерландах,
а не служба поддержки. Нужна собственная узнаваемая манера: быстро, наблюдательно, остроумно,
иногда с лёгким абсурдом или самоиронией. Можно вдохновляться тем, как сильные бренды общаются
в комментариях, но запрещено копировать конкретные фразы, персонажей и голос Авиасейлс.

Правила голоса:
• обычно 2–12 слов; более длинный ответ допустим только для реального вопроса;
• не каждый комментарий требует ответа: иногда правильнее поставить лайк, промолчать или скрыть;
• шутка должна продолжать мысль человека или содержание поста, а не существовать отдельно;
• отвечай на языке комментария;
• максимум один уместный эмодзи, часто лучше без него;
• не используй канцелярит, «спасибо за ваше мнение», рекламные клише и ИИ-формулировки;
• не унижай человека, не шути над внешностью, происхождением, возрастом, здоровьем и уязвимостью;
• не разжигай политический конфликт и не спорь ради последнего слова;
• на фактический вопрос сначала дай точный ответ. Если данных поста недостаточно, прямо отметь,
  что редактору нужен контекст, и ничего не выдумывай;
• грубость без угроз можно спокойно обезоружить одной фразой или оставить без ответа;
• угрозы, травля, дискриминация и спам: recommend_action = hide, без остроумного ответа;
• цель не «пошутить любой ценой», а сделать аккаунт человечным и узнаваемым.

Ориентиры нужной механики, но не готовые шаблоны:
• человек продолжил шутку → подхвати и сделай ещё один поворот;
• написал тёплую реакцию → коротко ответь как знакомому;
• поправил факт → признай или уточни без защиты эго;
• задал вопрос → ответь по существу;
• оставил пустой смех/один эмодзи → чаще достаточно лайка;
• провоцирует → оцени, даст ли ответ пользу аудитории. Если нет, пропусти.
""".strip()

OUTPUT_RULES = """
Разбери до трёх комментариев, на которые действительно стоит обратить внимание. Верни только
валидный JSON без markdown:
{
  "post_context": "кратко, о чём пост; если не видно — неизвестно",
  "items": [
    {
      "comment": "точный текст комментария без username",
      "recommend_action": "reply|like|skip|hide|need_context",
      "reason": "одно короткое объяснение для редактора",
      "replies": ["основной фирменный вариант", "мягче", "смелее"]
    }
  ]
}
Для like, skip, hide и need_context массив replies должен быть пустым. Для reply дай ровно три
действительно разные формулировки. Основной вариант должен быть лучшим, а не самым безопасным.
""".strip()


def _close_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Закрыть режим", callback_data="comments:close")
    ]])


async def _examples(limit: int = 16) -> list[CommentReplyExample]:
    async with get_session() as session:
        rows = (await session.scalars(
            select(CommentReplyExample).order_by(CommentReplyExample.id.desc()).limit(limit)
        )).all()
    return list(reversed(rows))


def _examples_prompt(rows: list[CommentReplyExample]) -> str:
    if not rows:
        return "Пока нет подтверждённых примеров. Строго следуй правилам голоса."
    lines = ["Ниже решения редактора. Считай их обучающими примерами фирменного голоса:"]
    for row in rows:
        if row.action == "reply" and row.reply:
            lines.append(f"Комментарий: {row.source_comment}\nВыбранный ответ: {row.reply}")
        else:
            lines.append(f"Комментарий: {row.source_comment}\nВыбранное действие: {row.action}")
    return "\n\n".join(lines)


def _response_text(response) -> str:
    return "".join(
        getattr(block, "text", "")
        for block in getattr(response, "content", [])
        if getattr(block, "type", "") == "text"
    ).strip()


def _parse_payload(raw: str) -> dict | None:
    clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", (raw or "").strip())
    start, end = clean.find("{"), clean.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        payload = json.loads(clean[start:end + 1])
    except (TypeError, ValueError):
        return None
    items = payload.get("items")
    if not isinstance(items, list):
        return None
    normalized = []
    for item in items[:3]:
        if not isinstance(item, dict):
            continue
        comment = str(item.get("comment") or "").strip()[:1000]
        action = str(item.get("recommend_action") or "skip").strip()
        if action not in {"reply", "like", "skip", "hide", "need_context"}:
            action = "skip"
        replies = [str(value).strip()[:700] for value in item.get("replies", []) if str(value).strip()]
        if action == "reply" and len(replies) < 3:
            continue
        normalized.append({
            "comment": comment,
            "recommend_action": action,
            "reason": str(item.get("reason") or "").strip()[:500],
            "replies": replies[:3] if action == "reply" else [],
        })
    if not normalized:
        return None
    return {
        "post_context": str(payload.get("post_context") or "неизвестно").strip()[:1500],
        "items": normalized,
    }


async def _analyse(*, text: str = "", image_b64: str = "", media_type: str = "image/jpeg") -> dict | None:
    if not ai_enabled():
        return None
    examples = _examples_prompt(await _examples())
    instruction = (
        "Проанализируй присланный комментарий или скриншот комментариев Instagram. "
        "Учитывай видимый контекст поста, но не додумывай скрытый текст. "
        + OUTPUT_RULES
    )
    content = []
    if image_b64:
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": media_type, "data": image_b64},
        })
    content.append({"type": "text", "text": instruction + (f"\n\nДополнительный контекст редактора: {text}" if text else "")})
    try:
        response = await _get_client().messages.create(
            model=config.AI_VISION_MODEL,
            max_tokens=1500,
            system=VOICE_RULES + "\n\n" + examples,
            messages=[{"role": "user", "content": content}],
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("Comment copilot generation failed: %s", exc)
        return None
    return _parse_payload(_response_text(response))


async def _save_draft(payload: dict) -> str:
    draft_id = uuid.uuid4().hex[:12]
    async with get_session() as session:
        session.add(CommentReplyDraft(
            id=draft_id,
            post_context=payload.get("post_context", ""),
            payload_json=json.dumps(payload, ensure_ascii=False),
            status="pending",
        ))
        await session.commit()
    return draft_id


_ACTION_LABELS = {
    "reply": "Ответить",
    "like": "Только лайк",
    "skip": "Не отвечать",
    "hide": "Скрыть / модерировать",
    "need_context": "Нужен контекст поста",
}


def _render(payload: dict) -> str:
    lines = ["💬 Комментарии", "", f"Контекст поста: {payload.get('post_context') or 'неизвестно'}"]
    for index, item in enumerate(payload["items"], 1):
        lines.extend([
            "",
            f"{index}. «{item['comment']}»",
            f"Действие: {_ACTION_LABELS[item['recommend_action']]}",
            f"Почему: {item['reason']}",
        ])
        for letter, reply in zip("ABC", item["replies"]):
            lines.append(f"{letter}. {reply}")
    return "\n".join(lines)


def _result_kb(draft_id: str, payload: dict) -> InlineKeyboardMarkup:
    rows = []
    for item_index, item in enumerate(payload["items"]):
        if item["recommend_action"] == "reply":
            rows.append([
                InlineKeyboardButton(text=f"Берём {item_index + 1}A", callback_data=f"crpick:{draft_id}:{item_index}:0"),
                InlineKeyboardButton(text=f"{item_index + 1}B", callback_data=f"crpick:{draft_id}:{item_index}:1"),
                InlineKeyboardButton(text=f"{item_index + 1}C", callback_data=f"crpick:{draft_id}:{item_index}:2"),
            ])
        elif item["recommend_action"] in {"like", "skip", "hide"}:
            rows.append([InlineKeyboardButton(
                text=f"Подтвердить: {_ACTION_LABELS[item['recommend_action']].lower()}",
                callback_data=f"craction:{draft_id}:{item_index}:{item['recommend_action']}",
            )])
    rows.append([InlineKeyboardButton(text="Ещё варианты", callback_data=f"cragain:{draft_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _download_image(message: Message) -> tuple[str, str] | None:
    file_id = None
    media_type = "image/jpeg"
    if message.photo:
        file_id = message.photo[-1].file_id
    elif message.document and (message.document.mime_type or "").startswith("image/"):
        file_id = message.document.file_id
        media_type = message.document.mime_type
    if not file_id:
        return None
    try:
        buf = await message.bot.download(file_id)
        return base64.b64encode(buf.read()).decode(), media_type
    except Exception as exc:  # noqa: BLE001
        log.warning("Cannot download comment screenshot: %s", exc)
        return None


async def _process(message: Message) -> None:
    text = (message.caption or message.text or "").strip()
    image = await _download_image(message)
    if not text and not image:
        await message.answer("Пришлите текст комментария или скриншот.", parse_mode=None)
        return
    await message.answer("Смотрю контекст и готовлю варианты…", parse_mode=None)
    payload = await _analyse(
        text=text,
        image_b64=image[0] if image else "",
        media_type=image[1] if image else "image/jpeg",
    )
    if not payload:
        await message.answer(
            "Не получилось уверенно разобрать комментарии. Пришлите более чёткий скриншот и добавьте в подписи, о чём был пост.",
            parse_mode=None,
        )
        return
    draft_id = await _save_draft(payload)
    await message.answer(_render(payload), parse_mode=None, reply_markup=_result_kb(draft_id, payload))


async def _start_private_mode(message: Message, state: FSMContext) -> None:
    await state.set_state(CommentCopilot.active)
    await message.answer(
        "💬 Ответы на комментарии\n\n"
        "Пришлите скриншот или вставьте текст комментария. Если из скриншота непонятно, о чём пост, добавьте контекст в подписи. Я предложу действие и варианты ответа. Ничего в Instagram автоматически не публикуется.",
        parse_mode=None,
        reply_markup=_close_kb(),
    )


@router.message(Command("comments", "commentreply"), F.chat.type == ChatType.PRIVATE)
async def comments_start(message: Message, state: FSMContext) -> None:
    if message.from_user.id not in config.ADMIN_IDS:
        return
    await _start_private_mode(message, state)


@router.callback_query(F.data == "ac:comments", F.from_user.id.in_(config.ADMIN_IDS))
async def comments_from_admin(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await _start_private_mode(callback.message, state)


@router.callback_query(F.data == "comments:close", F.from_user.id.in_(config.ADMIN_IDS))
async def comments_close(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer("Режим закрыт")
    await callback.message.edit_reply_markup(reply_markup=None)


@router.message(CommentCopilot.active, F.from_user.id.in_(config.ADMIN_IDS), F.photo | F.document | F.text)
async def comments_private_input(message: Message) -> None:
    if (message.text or "").startswith("/"):
        return
    await _process(message)


async def _configured_topic() -> tuple[int | None, int | None]:
    try:
        chat = int(await _meta_get("comment_copilot_chat_id") or "")
        topic = int(await _meta_get("comment_copilot_topic_id") or "")
        return chat, topic
    except ValueError:
        return None, None


@router.message(Command("commentsetup"))
async def comment_setup(message: Message) -> None:
    if message.from_user.id not in config.ADMIN_IDS:
        return
    if message.chat.type != ChatType.SUPERGROUP or not getattr(message.chat, "is_forum", False):
        await message.answer(
            "Запустите /commentsetup в закрытой супергруппе с включёнными темами. Боту нужны права администратора на управление темами.",
            parse_mode=None,
        )
        return
    current_chat, current_topic = await _configured_topic()
    if current_chat == message.chat.id and current_topic:
        await message.answer("Чат для комментариев уже подключён.", parse_mode=None)
        return
    try:
        topic = await message.bot.create_forum_topic(message.chat.id, name="💬 Ответы на комментарии")
        await _meta_set("comment_copilot_chat_id", message.chat.id)
        await _meta_set("comment_copilot_topic_id", topic.message_thread_id)
    except Exception as exc:  # noqa: BLE001
        log.exception("Comment topic setup failed")
        await message.answer(
            f"Не удалось создать тему: {type(exc).__name__}. Проверьте права бота.",
            parse_mode=None,
        )
        return
    await message.answer("Готово. Создана отдельная тема «💬 Ответы на комментарии».", parse_mode=None)


@router.message(ConfiguredCommentTopic(), F.from_user.id.in_(config.ADMIN_IDS), F.photo | F.document | F.text)
async def comments_topic_input(message: Message) -> None:
    if (message.text or "").startswith("/"):
        return
    await _process(message)


async def _draft(draft_id: str) -> tuple[CommentReplyDraft, dict] | None:
    async with get_session() as session:
        row = await session.get(CommentReplyDraft, draft_id)
        if not row or row.status != "pending":
            return None
        try:
            return row, json.loads(row.payload_json)
        except ValueError:
            return None


@router.callback_query(F.data.startswith("crpick:"), F.from_user.id.in_(config.ADMIN_IDS))
async def choose_reply(callback: CallbackQuery) -> None:
    _, draft_id, raw_item, raw_reply = callback.data.split(":")
    loaded = await _draft(draft_id)
    if not loaded:
        await callback.answer("Этот вариант уже обработан", show_alert=True)
        return
    row, payload = loaded
    try:
        item = payload["items"][int(raw_item)]
        reply = item["replies"][int(raw_reply)]
    except (IndexError, KeyError, TypeError, ValueError):
        await callback.answer("Вариант не найден", show_alert=True)
        return
    async with get_session() as session:
        stored = await session.get(CommentReplyDraft, draft_id)
        if not stored or stored.status != "pending":
            await callback.answer("Этот вариант уже обработан", show_alert=True)
            return
        stored.status = "accepted"
        stored.chosen_reply = reply
        session.add(CommentReplyExample(
            source_comment=item["comment"],
            post_context=row.post_context,
            action="reply",
            reply=reply,
        ))
        await session.commit()
    await callback.answer("Запомнил этот стиль")
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(f"Готовый ответ:\n\n{reply}", parse_mode=None)


@router.callback_query(F.data.startswith("craction:"), F.from_user.id.in_(config.ADMIN_IDS))
async def choose_action(callback: CallbackQuery) -> None:
    _, draft_id, raw_item, action = callback.data.split(":")
    if action not in {"like", "skip", "hide"}:
        await callback.answer("Неизвестное действие", show_alert=True)
        return
    loaded = await _draft(draft_id)
    if not loaded:
        await callback.answer("Этот вариант уже обработан", show_alert=True)
        return
    row, payload = loaded
    try:
        item = payload["items"][int(raw_item)]
    except (IndexError, KeyError, TypeError, ValueError):
        await callback.answer("Комментарий не найден", show_alert=True)
        return
    async with get_session() as session:
        stored = await session.get(CommentReplyDraft, draft_id)
        if not stored or stored.status != "pending":
            await callback.answer("Этот вариант уже обработан", show_alert=True)
            return
        stored.status = "accepted"
        session.add(CommentReplyExample(
            source_comment=item["comment"],
            post_context=row.post_context,
            action=action,
            reply=None,
        ))
        await session.commit()
    await callback.answer("Решение запомнено")
    await callback.message.edit_reply_markup(reply_markup=None)


@router.callback_query(F.data.startswith("cragain:"), F.from_user.id.in_(config.ADMIN_IDS))
async def regenerate(callback: CallbackQuery) -> None:
    draft_id = callback.data.split(":", 1)[1]
    loaded = await _draft(draft_id)
    if not loaded:
        await callback.answer("Черновик уже обработан", show_alert=True)
        return
    row, payload = loaded
    source = "\n".join(item.get("comment", "") for item in payload.get("items", []))
    await callback.answer("Готовлю другой подход…")
    new_payload = await _analyse(text=f"Контекст поста: {row.post_context}\nКомментарии:\n{source}\nНужны полностью другие варианты.")
    if not new_payload:
        await callback.message.answer("Не получилось подготовить новые варианты.", parse_mode=None)
        return
    async with get_session() as session:
        stored = await session.get(CommentReplyDraft, draft_id)
        if not stored or stored.status != "pending":
            await callback.answer("Черновик уже обработан", show_alert=True)
            return
        stored.status = "regenerated"
        await session.commit()
    new_id = await _save_draft(new_payload)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(_render(new_payload), parse_mode=None, reply_markup=_result_kb(new_id, new_payload))
