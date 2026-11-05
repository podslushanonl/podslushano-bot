"""Push-уведомления приложения по провинциям (Expo Push API).

Приложение после разрешения на уведомления присылает свой Expo push token и выбранную провинцию:
    POST /api/app/push/register   {"token": "ExponentPushToken[...]", "province": "nb", "platform": "ios",
                                   "station": "O", "station_name": "Oss", "morning": true, "trains": true}
    POST /api/app/push/unregister {"token": "..."}            — человек выключил уведомления
При смене провинции приложение просто регистрируется заново с новой провинцией.

Рассылка — командой администратора в боте:
    /push nb Заголовок | Текст уведомления | /afisha
    /push all Заголовок | Текст | /guide
Провинция: gr fr dr ov fl ge ut nh zh ze nb li или all. Ссылка (необязательно) — экран приложения.
Токены, которые Expo называет недействительными (DeviceNotRegistered), выключаются.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

import aiohttp
from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from aiohttp import web
from sqlalchemy import select, update

import config
from database.db import get_session
from database.models import AppPushToken
from utils.site_api import _body, _err, _json

log = logging.getLogger(__name__)

EXPO_URL = "https://exp.host/--/api/v2/push/send"
PROVINCES = {"gr": "Groningen", "fr": "Friesland", "dr": "Drenthe", "ov": "Overijssel", "fl": "Flevoland", "ge": "Gelderland",
             "ut": "Utrecht", "nh": "Noord-Holland", "zh": "Zuid-Holland", "ze": "Zeeland", "nb": "Noord-Brabant", "li": "Limburg"}
TOKEN_RE = re.compile(r"^Expo(nent)?PushToken\[[A-Za-z0-9_\-]{10,120}\]$")


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------- HTTP

async def register(request: web.Request) -> web.Response:
    data = await _body(request)
    token = str(data.get("token") or "").strip()
    province = str(data.get("province") or "").strip().lower()
    platform = str(data.get("platform") or "")[:10]
    station = str(data.get("station") or "").strip().upper()[:8]
    station = station if re.fullmatch(r"[A-Z0-9]{1,8}", station) else ""
    station_name = str(data.get("station_name") or "").strip()[:100]
    flag = lambda k: str(data.get(k, "1")).lower() not in ("0", "false", "no", "")  # noqa: E731
    if not TOKEN_RE.match(token):
        return _err(request, "Неверный токен уведомлений.")
    if province not in PROVINCES:
        return _err(request, "Неизвестная провинция.")
    uid = None
    try:
        from utils.app_api import _user
        async with get_session() as session:
            u = await _user(request, session)
            uid = u.id if u else None
            await session.commit()
    except Exception:  # noqa: BLE001 — уведомления работают и без входа
        uid = None
    async with get_session() as session:
        row = await session.scalar(select(AppPushToken).where(AppPushToken.token == token))
        if row is None:
            row = AppPushToken(token=token)
            session.add(row)
        row.province, row.platform, row.active, row.updated_at = province, platform, True, _now()
        if station != (row.station or ""):
            row.sent_alerts = ""          # новая станция — старые отметки не нужны
        row.station, row.station_name = station, station_name
        row.morning, row.trains = flag("morning"), flag("trains")
        if uid:
            row.app_user_id = uid
        await session.commit()
    return _json(request, {"ok": True})


async def unregister(request: web.Request) -> web.Response:
    data = await _body(request)
    token = str(data.get("token") or "").strip()
    async with get_session() as session:
        await session.execute(update(AppPushToken).where(AppPushToken.token == token).values(active=False, updated_at=_now()))
        await session.commit()
    return _json(request, {"ok": True})


def install_routes(app: web.Application) -> None:
    app.router.add_post("/api/app/push/register", register)
    app.router.add_post("/api/app/push/unregister", unregister)


# ---------------------------------------------------------------- рассылка

async def _post(messages: list[dict]) -> list[dict]:
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if getattr(config, "EXPO_ACCESS_TOKEN", ""):
        headers["Authorization"] = f"Bearer {config.EXPO_ACCESS_TOKEN}"
    async with aiohttp.ClientSession() as s:
        async with s.post(EXPO_URL, json=messages, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as r:
            data = await r.json(content_type=None)
    return data.get("data") or []


async def send_messages(msgs: list[dict]) -> tuple[int, int]:
    """Отправить готовые сообщения Expo (у каждого «to» — токен). Возвращает (отправлено, ошибок)."""
    ok = await send_each(msgs)
    return sum(ok), len(ok) - sum(ok)


async def send_each(msgs: list[dict]) -> list[bool]:
    """Отправить сообщения Expo; для каждого — принял ли его Expo (False — можно повторить позже).
    Токены, которые Expo называет недействительными (DeviceNotRegistered), выключаются."""
    result: list[bool] = []
    dead: list[str] = []
    for i in range(0, len(msgs), 100):   # Expo принимает до 100 сообщений за запрос
        chunk = [{"sound": "default", "channelId": "default", **m} for m in msgs[i:i + 100]]
        try:
            tickets = await _post(chunk)
        except Exception as e:  # noqa: BLE001
            log.warning("Expo push failed: %s", e)
            tickets = []
        tickets = list(tickets) + [{}] * (len(chunk) - len(tickets))
        for m, ticket in zip(chunk, tickets):
            result.append(ticket.get("status") == "ok")
            if (ticket.get("details") or {}).get("error") == "DeviceNotRegistered":
                dead.append(m["to"])
    if dead:
        async with get_session() as session:
            await session.execute(update(AppPushToken).where(AppPushToken.token.in_(dead)).values(active=False, updated_at=_now()))
            await session.commit()
    return result


async def send_to_province(province: str, title: str, body: str, url: str = "") -> tuple[int, int]:
    """Отправить уведомление всем устройствам провинции (или всем: province="all")."""
    async with get_session() as session:
        q = select(AppPushToken.token).where(AppPushToken.active.is_(True))
        if province != "all":
            q = q.where(AppPushToken.province == province)
        tokens = list(await session.scalars(q))
    return await send_messages([{"to": t, "title": title, "body": body, "data": {"url": url} if url else {}} for t in tokens])


def parse_command(args: str) -> tuple[str, str, str, str] | str:
    """«nb Заголовок | Текст | /afisha» → (провинция, заголовок, текст, ссылка) или текст ошибки."""
    parts = (args or "").strip().split(maxsplit=1)
    if len(parts) < 2:
        return "Формат: /push nb Заголовок | Текст | /afisha\nПровинция: " + " ".join(PROVINCES) + " или all."
    province = parts[0].lower()
    if province != "all" and province not in PROVINCES:
        return "Неизвестная провинция. Варианты: " + " ".join(PROVINCES) + " или all."
    fields = [x.strip() for x in parts[1].split("|")]
    if len(fields) < 2 or not fields[0] or not fields[1]:
        return "Нужны заголовок и текст через «|»."
    url = fields[2] if len(fields) > 2 else ""
    if url and not url.startswith("/"):
        return "Ссылка — экран приложения, начинается с «/», например /afisha."
    return province, fields[0][:80], fields[1][:180], url


router = Router()
router.message.filter(F.chat.type == ChatType.PRIVATE, F.from_user.id.in_(config.ADMIN_IDS))


@router.message(Command("push"))
async def push_command(message: Message, command: CommandObject) -> None:
    parsed = parse_command(command.args or "")
    if isinstance(parsed, str):
        await message.answer(parsed)
        return
    province, title, body, url = parsed
    sent, failed = await send_to_province(province, title, body, url)
    where = "все провинции" if province == "all" else PROVINCES[province]
    await message.answer(f"Уведомление отправлено: {where}. Доставлено: {sent}, ошибок: {failed}.")
