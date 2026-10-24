"""Афиша на сайте из бота: список будущих событий, убрать и вернуть.

События сайта бывают двух видов:
- из бота (ключ u<id>): платные после проверки и добавленные админом вручную. Убрать —
  статус removed, вернуть — снова approved;
- из темы сайта (остальные ключи). Тему бот менять не может, поэтому такие события он
  скрывает: ключ попадает в список hidden, который сайт получает вместе с лентой
  /api/afisha/events и сам не показывает эти события.
После каждого изменения бот просит сайт сбросить кэш (utils.wordpress.refresh_site).
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import aiohttp
from sqlalchemy import select

from database.db import get_session
from database.models import EventListing, Meta
from utils import wordpress as wp

log = logging.getLogger(__name__)

AMS = ZoneInfo("Europe/Amsterdam")
HIDDEN_KEY = "afisha_hidden"
_BOT_KEY = re.compile(r"^u(\d+)$")


async def hidden() -> dict[str, dict]:
    """Скрытые события темы: {ключ: {"h": название, "date": дата}}."""
    async with get_session() as session:
        row = await session.get(Meta, HIDDEN_KEY)
    try:
        data = json.loads(row.value) if row else {}
    except ValueError:
        data = {}
    return data if isinstance(data, dict) else {}


async def _save_hidden(data: dict) -> None:
    async with get_session() as session:
        row = await session.get(Meta, HIDDEN_KEY)
        value = json.dumps(data, ensure_ascii=False)
        if row:
            row.value = value
        else:
            session.add(Meta(key=HIDDEN_KEY, value=value))
        await session.commit()


async def site_events() -> list[dict]:
    """Будущие события, которые сейчас показывает сайт (его открытый JSON для приложения)."""
    base = wp._wp_url()
    if not base:
        return []
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{base}/wp-json/pn/v1/app", headers={"User-Agent": wp._UA},
                                   ssl=wp._ssl_param(), timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json(content_type=None)
    except Exception as e:  # noqa: BLE001
        log.info("Афиша: список событий сайта не получен: %s", e)
        return []
    out = []
    for e in (data or {}).get("events") or []:
        if isinstance(e, dict) and e.get("key") and e.get("date"):
            out.append({"key": str(e["key"]), "h": str(e.get("h") or ""), "date": str(e["date"]),
                        "city": str(e.get("city") or "")})
    return out


def _bot_item(ev: EventListing) -> dict:
    start = ev.starts_at.replace(tzinfo=timezone.utc).astimezone(AMS).date().isoformat() if ev.starts_at else ""
    return {"key": f"u{ev.id}", "h": ev.title, "date": start, "city": ev.city or ""}


async def upcoming() -> list[dict]:
    """Все будущие события сайта. Свои события бот берёт из базы, чтобы новое было видно сразу."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    hid = await hidden()
    async with get_session() as session:
        mine = (await session.scalars(select(EventListing).where(
            EventListing.status == "approved", EventListing.starts_at.is_not(None),
            (EventListing.ends_at.is_(None)) | (EventListing.ends_at >= now)))).all()
    items = {i["key"]: i for i in map(_bot_item, mine)}
    for e in await site_events():
        if _BOT_KEY.match(e["key"]) or e["key"] in hid:
            continue   # свои события уже из базы; скрытые сайт мог ещё не забыть
        items[e["key"]] = e
    return sorted(items.values(), key=lambda e: (e["date"], e["h"]))


async def removed() -> list[dict]:
    """Убранные из афиши события, которые ещё не прошли: их можно вернуть."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    async with get_session() as session:
        mine = (await session.scalars(select(EventListing).where(
            EventListing.status == "removed", (EventListing.ends_at.is_(None)) | (EventListing.ends_at >= now)))).all()
    today = datetime.now(AMS).date().isoformat()
    out = [_bot_item(e) for e in mine]
    out += [{"key": k, "h": v.get("h", k), "date": v.get("date", ""), "city": ""}
            for k, v in (await hidden()).items() if (v.get("date") or today) >= today]
    return sorted(out, key=lambda e: (e["date"], e["h"]))


async def remove(item: dict) -> bool:
    """Убирает событие с сайта. item — запись из upcoming()."""
    m = _BOT_KEY.match(item["key"])
    if m:
        async with get_session() as session:
            ev = await session.get(EventListing, int(m.group(1)))
            if not ev or ev.status != "approved":
                return False
            ev.status = "removed"
            await session.commit()
    else:
        data = await hidden()
        data[item["key"]] = {"h": item.get("h", ""), "date": item.get("date", "")}
        await _save_hidden(data)
    await wp.refresh_site()
    return True


async def restore(key: str) -> bool:
    m = _BOT_KEY.match(key)
    if m:
        async with get_session() as session:
            ev = await session.get(EventListing, int(m.group(1)))
            if not ev or ev.status != "removed":
                return False
            ev.status = "approved"
            await session.commit()
    else:
        data = await hidden()
        if key not in data:
            return False
        del data[key]
        await _save_hidden(data)
    await wp.refresh_site()
    return True
