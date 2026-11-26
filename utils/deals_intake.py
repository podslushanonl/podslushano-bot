"""Signed intake for the existing editorial publisher; no bot-token export.

Only the public verification key is installed on Railway. Signing authority is
limited to editorial delivery to the channel confirmed by the existing bridge.
It expires at the configured pilot boundary. Payment routes are not involved.
"""
import asyncio
import hashlib
import logging
import os
import re
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from aiohttp import web
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from utils.deals_editorial import (
    MAX_BYTES, parse_batch, publish_batch, read_receipts, verify_existing_posts,
)

log = logging.getLogger(__name__)
TZ = ZoneInfo("Europe/Amsterdam")
BASE = "/api/deals/editorial"
TASKS = web.AppKey("deals_editorial_tasks", set)


def signing_message(timestamp, method, path, body):
    return f"v1\n{timestamp}\n{method}\n{path}\n{hashlib.sha256(body).hexdigest()}".encode()


def authorize(request, body):
    key = os.getenv("DEALS_EDITORIAL_PUBLIC_KEY", "")
    until = os.getenv("DEALS_EDITORIAL_ACTIVE_UNTIL", "")
    try:
        expiry = datetime.fromisoformat(until)
        if expiry.tzinfo is None or expiry <= datetime.now(timezone.utc):
            raise ValueError()
        stamp = request.headers.get("X-Editorial-Timestamp", "")
        signature = request.headers.get("X-Editorial-Signature", "")
        if not re.fullmatch(r"\d{10}", stamp) or abs(time.time() - int(stamp)) > 300:
            raise ValueError()
        if not re.fullmatch(r"[a-f0-9]{128}", signature):
            raise ValueError()
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(key)).verify(
            bytes.fromhex(signature), signing_message(stamp, request.method, request.path, body))
    except (ValueError, TypeError, InvalidSignature):
        raise web.HTTPUnauthorized()


def validate_current(batch):
    now = datetime.now(TZ)
    checked = datetime.fromisoformat(batch.get("checked_at", ""))
    if checked.tzinfo is None or not -60 <= now.timestamp() - checked.timestamp() <= 3600:
        raise ValueError("research must be checked within the last hour")
    if len(batch["posts"]) > 6:
        raise ValueError("maximum six posts per release")
    day = now.date().isoformat()
    for post in batch["posts"]:
        if not post["id"].startswith(day + "-"):
            raise ValueError("only current Amsterdam date accepted")
        end = datetime.fromisoformat(post["publish_before"])
        if end <= now or end.astimezone(TZ).date() != now.date():
            raise ValueError("post expiry must be later on the current Amsterdam date")
    if not isinstance(batch.get("silent", True), bool):
        raise ValueError("silent must be boolean")


async def target_status(bot, batch=None):
    # Same confirmed target and permissions as the existing document publisher.
    from utils.deals_bridge import wp_call
    settings = await wp_call("bridge-secret")
    cid = str((settings or {}).get("chat", ""))
    if not re.fullmatch(r"-100\d{7,15}", cid):
        raise ValueError("configured channel unavailable")
    if batch is not None and str(batch["channel_id"]) != cid:
        raise ValueError("channel configuration mismatch")
    chat = await bot.get_chat(int(cid))
    member = await bot.get_chat_member(int(cid), bot.id)
    if chat.type != "channel" or getattr(member, "can_post_messages", False) is not True:
        raise ValueError("channel posting permission missing")
    return {"can_post": True, "photo_supported": True}


async def status(request):
    authorize(request, b"")
    try:
        target = await target_status(request.app["bot"])
    except Exception:
        return web.json_response({"ok": False, "error": "target preflight unavailable"}, status=503)
    day = datetime.now(TZ).date().isoformat()
    return web.json_response({"ok": True, **target, "date": day,
        "recent": await read_receipts(day + "-")})


async def ingest(request):
    if request.content_length and request.content_length > MAX_BYTES:
        raise web.HTTPRequestEntityTooLarge(max_size=MAX_BYTES, actual_size=request.content_length)
    body = bytearray()
    async for chunk in request.content.iter_chunked(4096):
        body.extend(chunk)
        if len(body) > MAX_BYTES:
            raise web.HTTPRequestEntityTooLarge(max_size=MAX_BYTES, actual_size=len(body))
    body = bytes(body)
    authorize(request, body)
    try:
        batch = parse_batch(body.decode("utf-8"))
        validate_current(batch)
        if not isinstance(batch.get("dry_run", False), bool):
            raise ValueError("dry_run must be boolean")
        await verify_existing_posts(batch["posts"])
    except (ValueError, TypeError, KeyError, UnicodeError):
        return web.json_response({"ok": False, "error": "invalid or conflicting batch"}, status=400)
    try:
        await target_status(request.app["bot"], batch)
    except Exception:
        return web.json_response({"ok": False, "error": "target preflight unavailable"}, status=503)
    if batch.get("dry_run") is True:
        return web.json_response({"ok": True, "state": "validated_not_sent", "count": len(batch["posts"])})
    # Keep delivery alive if the HTTP client disconnects. Receipts distinguish an
    # acknowledged Telegram send from an ambiguous network result on retries.
    task = asyncio.create_task(publish_batch(request.app["bot"], batch))
    request.app[TASKS].add(task)
    task.add_done_callback(request.app[TASKS].discard)
    try:
        result = await asyncio.shield(task)
    except Exception:
        log.warning("deals intake: batch incomplete; inspect receipts before retry")
        return web.json_response({"ok": False, "state": "review_receipts"}, status=503)
    ids = {post["id"] for post in batch["posts"]}
    receipts = [r for r in await read_receipts(datetime.now(TZ).date().isoformat() + "-") if r["id"] in ids]
    complete = len(receipts) == len(ids) and all(r["state"] == "sent" for r in receipts)
    return web.json_response({"ok": complete, **result, "receipts": receipts}, status=200 if complete else 207)


async def cleanup(app):
    pending = list(app[TASKS])
    if pending:
        await asyncio.wait(pending, timeout=5)


def install_routes(app):
    app[TASKS] = set()
    app.router.add_get(BASE + "/status", status)
    app.router.add_post(BASE, ingest)
    app.on_shutdown.append(cleanup)
