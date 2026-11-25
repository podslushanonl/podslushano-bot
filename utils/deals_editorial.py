"""Private editorial batch delivery for the configured Vygodno NL channel.
No payment changes, separate bot, new server or public storage of editorial copy.
"""
from __future__ import annotations
import asyncio
import io
import json
import logging
import os
import re
import secrets
from datetime import datetime, timezone
from urllib.parse import urlsplit

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, Message, LinkPreviewOptions
import config
from utils.deals_bridge import wp_call
from utils.site_api import _meta_set

log = logging.getLogger(__name__)
router = Router(name="deals_editorial")
_lock = asyncio.Lock()
MAX_BYTES = 65000
MAX_POSTS = 15

def valid_https(url):
    if not isinstance(url, str) or not 1 <= len(url) <= 1500 or any(c.isspace() or ord(c) < 32 for c in url):
        return False
    try:
        u = urlsplit(url)
        return u.scheme == "https" and bool(u.hostname) and not u.username and not u.password
    except ValueError:
        return False

def markup(buttons):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=x["label"], url=x["url"])] for x in buttons
    ]) if buttons else None

async def confirmed_channel(bot, expected=None):
    settings = await wp_call("bridge-secret")
    cid = str((settings or {}).get("chat", ""))
    if not re.fullmatch(r"-100\d{7,15}", cid) or (expected is not None and cid != str(expected)):
        raise ValueError("channel configuration mismatch")
    chat = await bot.get_chat(int(cid))
    me = await bot.get_chat_member(int(cid), bot.id)
    if chat.type != "channel" or getattr(me, "can_post_messages", False) is not True:
        raise ValueError("channel posting permission missing")
    return int(cid)

def parse_batch(raw):
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_BYTES:
        raise ValueError("invalid batch length")
    obj = json.loads(raw)
    if not isinstance(obj, dict) or not re.fullmatch(r"-100\d{7,15}", str(obj.get("channel_id", ""))):
        raise ValueError("invalid channel")
    posts = obj.get("posts")
    if not isinstance(posts, list) or not 1 <= len(posts) <= MAX_POSTS:
        raise ValueError("invalid post count")
    ids = set()
    for p in posts:
        if not isinstance(p, dict) or not re.fullmatch(r"[a-z0-9_-]{3,64}", str(p.get("id", ""))) or p["id"] in ids:
            raise ValueError("invalid post id")
        ids.add(p["id"])
        if not isinstance(p.get("html"), str) or not 1 <= len(p["html"]) <= 3800:
            raise ValueError("invalid text")
        if not isinstance(p.get("buttons"), list) or not 1 <= len(p["buttons"]) <= 4:
            raise ValueError("invalid buttons")
        for button in p["buttons"]:
            if not isinstance(button, dict) or not isinstance(button.get("label"), str) or not 1 <= len(button["label"]) <= 60:
                raise ValueError("invalid label")
            if not valid_https(button.get("url")):
                raise ValueError("invalid URL")
        if "photo_url" in p and (not valid_https(p["photo_url"]) or len(p["html"]) > 1000):
            raise ValueError("invalid photo or caption")
        until = datetime.fromisoformat(p["publish_before"])
        if until.tzinfo is None:
            raise ValueError("timezone required")
    return obj

async def publish_batch(bot, batch):
    # Resolve the confirmed channel via existing authenticated WordPress bridge.
    # A batch cannot redirect the bot to any other channel.
    async with _lock:
        cid = await confirmed_channel(bot, batch["channel_id"])
        stats = {"sent": 0, "skipped": 0, "failed": 0}
        for post in batch["posts"]:
            pid = post["id"]
            if datetime.fromisoformat(post["publish_before"]) <= datetime.now(timezone.utc):
                stats["skipped"] += 1
                log.info("deals editorial skipped expired %s", pid)
                continue
            # Claim first, to avoid duplicate public posts on restart or network timeout.
            if not await _meta_set("deals_editorial:" + pid, "claimed"):
                stats["skipped"] += 1
                continue
            try:
                common = dict(parse_mode="HTML", reply_markup=markup(post["buttons"]),
                              disable_notification=bool(batch.get("silent", True)))
                if post.get("photo_url"):
                    # Telegram fetches the verified public image; no local remote download.
                    msg = await bot.send_photo(cid, photo=post["photo_url"], caption=post["html"], **common)
                else:
                    msg = await bot.send_message(cid, post["html"],
                        link_preview_options=LinkPreviewOptions(is_disabled=True), **common)
                stats["sent"] += 1
                log.info("deals editorial published %s message_id=%s", pid, msg.message_id)
            except Exception as e:
                stats["failed"] += 1
                # Do not retry an ambiguous delivery. An administrator may review logs.
                log.warning("deals editorial delivery failed %s (%s)", pid, type(e).__name__)
            await asyncio.sleep(0.5)
        return stats

async def publish_startup_batch(bot):
    raw = os.getenv("DEALS_EDITORIAL_BATCH", "")
    if not raw:
        return
    try:
        batch = parse_batch(raw)
        # No effect on startup or payment processing. Only retry target preflight.
        for attempt in range(3):
            try:
                stats = await publish_batch(bot, batch)
                log.info("deals editorial batch result sent=%d skipped=%d failed=%d",
                         stats["sent"], stats["skipped"], stats["failed"])
                return
            except Exception as exc:
                log.warning("deals editorial preflight failed (%s)", type(exc).__name__)
                if attempt < 2:
                    await asyncio.sleep(15)
    except Exception as exc:
        log.warning("deals editorial batch rejected (%s)", type(exc).__name__)

@router.message(F.chat.type == "private", F.document, F.caption == "/deals_publish")
async def admin_upload(message: Message):
    # Existing configured admin IDs only; caption is an explicit publication action.
    if not message.from_user or message.from_user.id not in config.ADMIN_IDS:
        return
    if not message.document or (message.document.file_size or 0) > MAX_BYTES:
        await message.answer("Файл слишком большой.", parse_mode=None)
        return
    try:
        dest = io.BytesIO()
        await message.bot.download(message.document, destination=dest)
        batch = parse_batch(dest.getvalue().decode("utf-8"))
        stats = await publish_batch(message.bot, batch)
        await message.answer(
            f"Выгодно в NL: опубликовано {stats['sent']}; пропущено {stats['skipped']}; ошибок {stats['failed']}.",
            parse_mode=None)
    except Exception:
        await message.answer("Пакет не опубликован: проверьте формат и права канала.", parse_mode=None)


# Manual administrator workflow. Only the existing configured administrators may
# enter it. Drafts are ephemeral; restarting the bot never publishes a draft.
class DealsDraft(StatesGroup):
    content = State()
    buttons = State()
    preview = State()

def manual_buttons(text):
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    if not 1 <= len(lines) <= 4:
        raise ValueError("one to four buttons")
    result = []
    for line in lines:
        label, sep, url = line.partition("|")
        label, url = label.strip(), url.strip()
        if not sep or not 1 <= len(label) <= 60 or not valid_https(url):
            raise ValueError("invalid button")
        result.append({"label":label, "url":url})
    return result

def action_keyboard(nonce, preview=False):
    if preview:
        rows = [[InlineKeyboardButton(text="Опубликовать", callback_data="dp:publish:"+nonce)],
                [InlineKeyboardButton(text="Отменить", callback_data="dp:cancel:"+nonce)]]
    else:
        rows = [[InlineKeyboardButton(text="Без кнопок", callback_data="dp:skip:"+nonce)],
                [InlineKeyboardButton(text="Отменить", callback_data="dp:cancel:"+nonce)]]
    return InlineKeyboardMarkup(inline_keyboard=rows)

def admin(user):
    return bool(user and user.id in config.ADMIN_IDS)

@router.message(F.chat.type == "private", F.from_user.id.in_(config.ADMIN_IDS), Command("deals_post"))
async def manual_start(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(DealsDraft.content)
    await state.update_data(nonce=secrets.token_hex(8))
    await message.answer("Новый пост в «Выгодно в NL». Отправьте текст или одну фотографию с подписью. Можно использовать форматирование Telegram. /deals_cancel — отмена.", parse_mode=None)

@router.message(F.chat.type == "private", F.from_user.id.in_(config.ADMIN_IDS),
                StateFilter(DealsDraft.content, DealsDraft.buttons, DealsDraft.preview), Command("deals_cancel"))
async def manual_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Черновик отменён.", parse_mode=None)

@router.message(F.chat.type == "private", F.from_user.id.in_(config.ADMIN_IDS), DealsDraft.content)
async def manual_content(message: Message, state: FSMContext):
    if message.media_group_id or not (message.text or message.photo):
        await message.answer("Отправьте обычный текст или одну фотографию (не альбом).", parse_mode=None)
        return
    if message.text and message.text.startswith("/"):
        await message.answer("Отправьте содержание поста или /deals_cancel.", parse_mode=None)
        return
    data = await state.get_data()
    await state.update_data(source_chat=message.chat.id, source_message=message.message_id, buttons=[])
    await state.set_state(DealsDraft.buttons)
    await message.answer("Добавьте до четырёх кнопок: по одной на строку, в формате\nНазвание | https://ссылка\nИли нажмите «Без кнопок».",
                         reply_markup=action_keyboard(data["nonce"]), parse_mode=None)

async def manual_preview(bot, chat_id, state, buttons):
    data = await state.get_data()
    await bot.copy_message(chat_id=chat_id, from_chat_id=data["source_chat"],
                           message_id=data["source_message"], reply_markup=markup(buttons))
    await state.update_data(buttons=buttons)
    await state.set_state(DealsDraft.preview)
    await bot.send_message(chat_id, "Предпросмотр выше. Опубликовать в «Выгодно в NL»?",
                           reply_markup=action_keyboard(data["nonce"], preview=True), parse_mode=None)

@router.message(F.chat.type == "private", F.from_user.id.in_(config.ADMIN_IDS), DealsDraft.buttons)
async def manual_add_buttons(message: Message, state: FSMContext):
    try:
        buttons = manual_buttons(message.text)
    except ValueError:
        await message.answer("Используйте формат «Название | https://ссылка», до четырёх строк, или /deals_cancel.", parse_mode=None)
        return
    try:
        await manual_preview(message.bot, message.chat.id, state, buttons)
    except Exception:
        await message.answer("Не удалось создать предпросмотр. Повторите ввод кнопок или /deals_cancel.", parse_mode=None)

@router.callback_query(F.data.startswith("dp:"))
async def manual_action(query: CallbackQuery, state: FSMContext):
    if not admin(query.from_user) or not query.message or query.message.chat.type != "private":
        await query.answer("Недоступно.", show_alert=True)
        return
    _, _, rest = query.data.partition(":")
    action, _, nonce = rest.partition(":")
    async with _lock:
        data = await state.get_data()
        current = await state.get_state()
        if not nonce or nonce != data.get("nonce") or current not in (
            DealsDraft.content.state, DealsDraft.buttons.state, DealsDraft.preview.state):
            await query.answer("Этот черновик больше не активен.", show_alert=True)
            return
        if action == "cancel":
            await state.clear()
            await query.answer("Отменено.")
            await query.message.answer("Черновик отменён.", parse_mode=None)
            return
        if action == "skip" and current == DealsDraft.buttons.state:
            await query.answer()
            try:
                await manual_preview(query.bot, query.message.chat.id, state, [])
            except Exception:
                await query.message.answer("Предпросмотр не создан. Попробуйте ещё раз.", parse_mode=None)
            return
        if action != "publish" or current != DealsDraft.preview.state:
            await query.answer("Сначала создайте предпросмотр.", show_alert=True)
            return
        await query.answer("Проверяем канал…")
        try:
            cid = await confirmed_channel(query.bot)
        except Exception:
            await query.message.answer("Канал недоступен или не хватает прав. Черновик сохранён; попробуйте снова.", parse_mode=None)
            return
        key = "deals_manual:" + str(query.from_user.id) + ":" + str(data["source_message"])
        if not await _meta_set(key, "claimed"):
            await state.clear()
            await query.message.answer("Этот черновик уже был отправлен или обработан. Проверьте канал.", parse_mode=None)
            return
        await state.clear()
        try:
            sent = await query.bot.copy_message(chat_id=cid, from_chat_id=data["source_chat"],
                        message_id=data["source_message"], reply_markup=markup(data["buttons"]),
                        disable_notification=True)
        except Exception as exc:
            log.warning("deals manual delivery uncertain (%s)", type(exc).__name__)
            await query.message.answer("Отправка не подтверждена. Проверьте канал перед повторной публикацией.", parse_mode=None)
            return
        await query.message.answer(f"Опубликовано в «Выгодно в NL» (сообщение {sent.message_id}).", parse_mode=None)
