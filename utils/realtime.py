"""Живое соединение приложения podslushano (WebSocket): сообщения приходят сразу, без опроса.

GET /api/app/ws?token=<токен входа> — одно соединение на устройство.
Клиент шлёт: {"type":"join"|"leave","room":slug} — подписка на чат (открыт всем, дружба не нужна),
             {"type":"say","room":slug,"text":...,"ref":...} — сообщение в чат, ответ {"type":"said","ref":...},
             {"type":"typing","conv":id} — «печатает…» собеседнику в личном диалоге.
Сервер шлёт: {"type":"dm",...}, {"type":"read",...}, {"type":"typing",...}, {"type":"room",...},
             {"type":"friend","event":"request"|"accepted",...}.

Работает в одном процессе бота (как и сейчас на Railway). Кто сейчас в сети — видно по online().
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict

from aiohttp import WSMsgType, web

from database.db import get_session
from database.models import AppUser
from utils.site_api import read_token

log = logging.getLogger(__name__)

_users: dict[int, set[web.WebSocketResponse]] = defaultdict(set)
_rooms: dict[str, set[web.WebSocketResponse]] = defaultdict(set)
_who: dict[web.WebSocketResponse, int] = {}
# Обработчик «печатает…»: (кто, диалог) -> кому переслать; задаётся модулем личных сообщений
typing_handler = None
# Отправка в комнату по WebSocket: (кто, комната, текст) -> ответ; задаётся модулем сообщества
say_handler = None


def online(uid: int) -> bool:
    return bool(_users.get(uid))


async def _send(ws: web.WebSocketResponse, payload: str) -> None:
    try:
        await ws.send_str(payload)
    except (ConnectionResetError, RuntimeError):
        pass


async def push_user(uid: int, data: dict) -> None:
    payload = json.dumps(data, ensure_ascii=False)
    await asyncio.gather(*(_send(ws, payload) for ws in list(_users.get(uid, ()))))


async def push_room(slug: str, data: dict, skip_users: set[int] | None = None) -> None:
    payload = json.dumps(data, ensure_ascii=False)
    targets = [ws for ws in list(_rooms.get(slug, ())) if _who.get(ws) not in (skip_users or set())]
    await asyncio.gather(*(_send(ws, payload) for ws in targets))


async def ws_handler(request: web.Request) -> web.StreamResponse:
    data = read_token(request.query.get("token", ""), "app")
    uid = int((data or {}).get("u") or 0)
    if uid:
        async with get_session() as session:
            if not await session.get(AppUser, uid):
                uid = 0
    if not uid:
        raise web.HTTPUnauthorized()
    ws = web.WebSocketResponse(heartbeat=25, max_msg_size=8192)
    await ws.prepare(request)
    _users[uid].add(ws)
    _who[ws] = uid
    joined: set[str] = set()
    try:
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                continue
            try:
                ev = json.loads(msg.data)
            except ValueError:
                continue
            kind = ev.get("type")
            if kind in ("join", "leave"):
                slug = str(ev.get("room") or "")[:40]
                if not slug:
                    continue
                if kind == "join" and len(joined) < 20:
                    _rooms[slug].add(ws)
                    joined.add(slug)
                else:
                    _rooms[slug].discard(ws)
                    joined.discard(slug)
            elif kind == "say" and say_handler:
                ref = str(ev.get("ref") or "")[:40]
                try:
                    res = await say_handler(uid, str(ev.get("room") or "")[:40], str(ev.get("text") or "")[:2000])
                except Exception as e:  # noqa: BLE001
                    log.warning("say: %s", e)
                    res = {"ok": False, "error": "Не отправилось. Попробуйте ещё раз.", "status": 500}
                await _send(ws, json.dumps({"type": "said", "ref": ref} | res, ensure_ascii=False))
            elif kind == "typing" and typing_handler:
                try:
                    await typing_handler(uid, int(ev.get("conv") or 0))
                except Exception as e:  # noqa: BLE001
                    log.debug("typing: %s", e)
    finally:
        _users[uid].discard(ws)
        if not _users[uid]:
            _users.pop(uid, None)
        for slug in joined:
            _rooms[slug].discard(ws)
            if not _rooms[slug]:
                _rooms.pop(slug, None)
        _who.pop(ws, None)
    return ws


def install_routes(app: web.Application) -> None:
    app.router.add_get("/api/app/ws", ws_handler)
