"""Opt-in bridge to the authors' planner. No credentials in Telegram links."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from urllib.parse import urlsplit

import aiohttp
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from database.db import get_session
from database.models import Meta

log = logging.getLogger(__name__)
DEFAULT_PLANNER_URL = "https://podslushano-editorial.alex-podslushano.chatgpt.site"


class PlannerError(Exception):
    """A safe error suitable for showing to a Telegram user."""


def planner_url() -> str:
    raw = os.getenv("EDITORIAL_PLANNER_URL", DEFAULT_PLANNER_URL).strip().rstrip("/")
    parsed = urlsplit(raw)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        return DEFAULT_PLANNER_URL
    # The bridge uses an origin, never a URL containing an access token or query.
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        return DEFAULT_PLANNER_URL
    return raw


def bridge_enabled() -> bool:
    configured = os.getenv("EDITORIAL_PLANNER_URL", "").strip().rstrip("/")
    return bool(
        configured and configured == planner_url()
        and os.getenv("EDITORIAL_PLANNER_TOKEN", "").strip()
    )


def safe_record_url(value: str | None = None) -> str:
    base = planner_url()
    parsed = urlsplit(value or base)
    expected = urlsplit(base)
    if (parsed.scheme, parsed.netloc) != (expected.scheme, expected.netloc):
        return base
    if parsed.username or parsed.password:
        return base
    return value or base


def open_keyboard(url: str | None = None) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Открыть планировщик", url=safe_record_url(url)),
    ]])


async def planner_request(action: str, **payload) -> dict:
    token = os.getenv("EDITORIAL_PLANNER_TOKEN", "").strip()
    if not bridge_enabled():
        raise PlannerError("Связь с планировщиком ещё не подключена. Откройте кабинет по кнопке.")
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                planner_url() + "/api/telegram",
                json={"action": action, **payload},
                headers={"Authorization": f"Bearer {token}"},
                allow_redirects=False,
            ) as response:
                if response.status == 401:
                    raise PlannerError(
                        "Бот не прошёл проверку подключения к планировщику. "
                        "Владельцу: в кабинете откройте «Быстрый доступ» → "
                        "«Подключение бота владельцем», создайте секрет и сохраните "
                        "его в Railway как EDITORIAL_PLANNER_TOKEN, затем примените изменения. "
                        "Личный код /planner_link для этой настройки не подходит."
                    )
                if response.status == 403:
                    if action == "bind":
                        raise PlannerError(
                            "Доступ к профилю в планировщике отключён. "
                            "Попросите Алекса проверить доступ участника."
                        )
                    raise PlannerError(
                        "Telegram ещё не связан с активным профилем. "
                        "Откройте кабинет → «Быстрый доступ» → Telegram → "
                        "«Получить код подключения» и отправьте команду /planner_link "
                        "боту в личные сообщения."
                    )
                if response.status == 400:
                    raise PlannerError("Проверьте данные. Код подключения действует 10 минут.")
                if response.status != 200 and response.status != 201:
                    raise PlannerError("Планировщик временно недоступен. Попробуйте позже.")
                data = await response.json()
                if not isinstance(data, dict):
                    raise PlannerError("Планировщик вернул некорректный ответ. Попробуйте позже.")
                return data
    except PlannerError:
        raise
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
        # Never echo exception text: it may contain a URL or a credential.
        raise PlannerError("Не удалось связаться с планировщиком. Попробуйте позже.") from None


def _delivery_key(item_id: str) -> str:
    return "planner:delivered:" + hashlib.sha256(item_id.encode()).hexdigest()


async def _already_delivered(item_id: str) -> bool:
    async with get_session() as session:
        return await session.get(Meta, _delivery_key(item_id)) is not None


async def _mark_delivered(item_id: str) -> None:
    async with get_session() as session:
        await session.merge(Meta(key=_delivery_key(item_id), value="1"))
        await session.commit()


async def process_planner_reminders(bot) -> int:
    """Deliver only the Site's opt-in queue, ack only a successful delivery.

    Successful deliveries are remembered in the bot DB before ack. If the ack
    request fails, the next pass retries ack without resending the message.
    """
    if not bridge_enabled():
        return 0
    data = await planner_request("reminders")
    items = data.get("items", [])
    if not isinstance(items, list):
        return 0
    sent = 0
    for item in items[:20]:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id", ""))
        telegram_id = str(item.get("telegramId", ""))
        text = item.get("text")
        if not item_id or not telegram_id.isdecimal() or int(telegram_id) <= 0:
            continue
        if not isinstance(text, str) or not text.strip():
            continue
        try:
            if not await _already_delivered(item_id):
                await bot.send_message(
                    int(telegram_id), text[:4000], parse_mode=None,
                    reply_markup=open_keyboard(item.get("url")),
                )
                await _mark_delivered(item_id)
                sent += 1
            await planner_request("ack", id=item_id)
        except Exception:  # noqa: BLE001 — one blocked user must not stop the queue
            log.warning("Не удалось доставить или подтвердить напоминание планировщика")
    return sent


async def planner_reminder_loop(bot) -> None:
    if not bridge_enabled():
        return
    while True:
        try:
            await process_planner_reminders(bot)
        except Exception:  # noqa: BLE001 — do not log credentials or user payloads
            log.warning("Планировщик: очередь напоминаний временно недоступна")
        await asyncio.sleep(300)
