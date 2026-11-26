"""Private editorial batch delivery for the configured Vygodno NL channel.
No payment changes, separate bot, new server or public storage of editorial copy.
"""
from __future__ import annotations
import asyncio
import hashlib
import io
import json
import logging
import os
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit

from aiogram import F, Router
from aiogram.exceptions import TelegramRetryAfter, TelegramBadRequest
from sqlalchemy import select
from database.db import get_session
from database.models import Meta
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, LinkPreviewOptions
import config
from utils.deals_bridge import wp_call
from utils.site_api import _meta_set

log = logging.getLogger(__name__)
router = Router(name="deals_editorial")
_lock = asyncio.Lock()
MAX_BYTES = 65000
MAX_POSTS = 15

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
            url = button.get("url")
            if not isinstance(url, str) or len(url)>1500:
                raise ValueError("invalid URL")
            u = urlsplit(url)
            if u.scheme != "https" or not u.hostname or u.username or u.password:
                raise ValueError("invalid URL")
        photo = p.get("photo_url")
        if photo is not None:
            if not isinstance(photo, str) or len(photo) > 2000 or len(p["html"]) > 1000:
                raise ValueError("invalid photo post")
            u = urlsplit(photo)
            if u.scheme != "https" or not u.hostname or u.username or u.password or u.port not in (None, 443):
                raise ValueError("invalid photo URL")
        until = datetime.fromisoformat(p["publish_before"])
        if until.tzinfo is None:
            raise ValueError("timezone required")
    return obj

async def release_claim(pid):
    async with get_session() as session:
        row = await session.get(Meta, "deals_editorial:" + pid)
        if row and (row.value == "claimed" or row.value.startswith("claimed:")):
            await session.delete(row)
            await session.commit()

def post_digest(post):
    return hashlib.sha256(json.dumps(post, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode()).hexdigest()

def receipt(pid, value):
    parts = (value or "").split(":")
    if parts[0] == "sent" and len(parts) == 3:
        return {"id": pid, "state": "sent", "message_id": int(parts[1])}
    return {"id": pid, "state": "delivery_unknown"}

async def read_receipts(prefix):
    async with get_session() as session:
        rows = (await session.scalars(select(Meta).where(
            Meta.key.startswith("deals_editorial:" + prefix)).limit(100))).all()
        return [receipt(row.key.removeprefix("deals_editorial:"), row.value) for row in rows]

async def verify_existing_posts(posts):
    # Reject changed content under an existing id before sending any part of a batch.
    async with get_session() as session:
        for post in posts:
            row = await session.get(Meta, "deals_editorial:" + post["id"])
            if row and ":" in row.value and row.value.rsplit(":", 1)[-1] != post_digest(post):
                raise ValueError("post id already belongs to different content")

async def record_sent(pid, digest, message_id):
    async with get_session() as session:
        row = await session.get(Meta, "deals_editorial:" + pid)
        if row is None:
            raise RuntimeError("publication claim missing")
        # Under 100 characters, compatible with the existing Meta value column.
        row.value = f"sent:{message_id}:{digest}"
        await session.commit()

async def deliver(bot, cid, post, silent):
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=x["label"], url=x["url"])] for x in post["buttons"]
    ])
    for attempt in range(3):
        try:
            if post.get("photo_url"):
                return await bot.send_photo(int(cid), photo=post["photo_url"],
                    caption=post["html"], parse_mode="HTML", reply_markup=markup,
                    disable_notification=silent)
            return await bot.send_message(int(cid), post["html"], parse_mode="HTML",
                reply_markup=markup, link_preview_options=LinkPreviewOptions(is_disabled=True),
                disable_notification=silent)
        except TelegramRetryAfter as exc:
            if attempt == 2 or exc.retry_after > 30:
                raise
            await asyncio.sleep(exc.retry_after + 1)
            if datetime.fromisoformat(post["publish_before"]) <= datetime.now(timezone.utc):
                raise

async def publish_batch(bot, batch):
    # Resolve the confirmed channel via existing authenticated WordPress bridge.
    # A batch cannot redirect the bot to any other channel.
    async with _lock:
        await verify_existing_posts(batch["posts"])
        settings = await wp_call("bridge-secret")
        cid = str(batch["channel_id"])
        if not settings or str(settings.get("chat", "")) != cid:
            raise ValueError("channel configuration mismatch")
        chat = await bot.get_chat(int(cid))
        me = await bot.get_chat_member(int(cid), bot.id)
        if chat.type != "channel" or getattr(me, "can_post_messages", False) is not True:
            raise ValueError("channel posting permission missing")
        stats = {"sent": 0, "skipped": 0, "failed": 0}
        for post in batch["posts"]:
            pid = post["id"]
            if datetime.fromisoformat(post["publish_before"]) <= datetime.now(timezone.utc):
                stats["skipped"] += 1
                log.info("deals editorial skipped expired %s", pid)
                continue
            # Claim first, to avoid duplicate public posts on restart or network timeout.
            digest = post_digest(post)
            if not await _meta_set("deals_editorial:" + pid, "claimed:" + digest):
                stats["skipped"] += 1
                continue
            try:
                msg = await deliver(bot, cid, post, bool(batch.get("silent", True)))
                await record_sent(pid, digest, msg.message_id)
                stats["sent"] += 1
                log.info("deals editorial published %s message_id=%s", pid, msg.message_id)
            except (TelegramRetryAfter, TelegramBadRequest) as e:
                await release_claim(pid)
                stats["failed"] += 1
                log.warning("deals editorial rejected %s (%s)", pid, type(e).__name__)
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
