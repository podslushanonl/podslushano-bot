"""Pulse — лента вертикальных видео во весь экран.

GET  /api/app/pulse?before=            — лента (по 10, новые сверху), без авторов, скрытых от меня
GET  /api/app/pulse/saved              — мои закладки
GET  /api/app/user/{id}/pulse          — видео человека (для вкладки Pulse в профиле)
POST /api/app/pulse                    — multipart: file (видео MP4/MOV/WebM до 80 МБ), text
POST /api/app/pulse/{id}/like          — {on}
POST /api/app/pulse/{id}/save          — {on} в закладки
GET/POST /api/app/pulse/{id}/comments  — комментарии / {text}
Удалить своё и пожаловаться — общими /api/app/delete и /api/app/report (kind=clip).
"""
from __future__ import annotations

from aiohttp import web
from sqlalchemy import delete, func, select

from database.db import get_session
from database.models import AppUser, PulseClip, PulseComment, PulseLike, PulseSave
from utils import media
from utils.app_api import _user
from utils.community import _rate, can_write, check_text
from utils.feed import _at, _author, _hidden_authors, _users
from utils.site_api import _body, _err, _json

PAGE = 10
TEXT_MAX = 500


async def _clips_json(session, rows: list[PulseClip], me: AppUser | None) -> list[dict]:
    ids = {c.id for c in rows}
    users = await _users(session, {c.user_id for c in rows})

    async def count(model, *where) -> dict[int, int]:
        if not ids:
            return {}
        return dict((await session.execute(select(model.clip_id, func.count()).where(model.clip_id.in_(ids), *where)
                                           .group_by(model.clip_id))).all())

    likes, comments = await count(PulseLike), await count(PulseComment, PulseComment.deleted.is_(False), PulseComment.hidden.is_(False))
    mine_l = set((await session.execute(select(PulseLike.clip_id).where(PulseLike.user_id == me.id, PulseLike.clip_id.in_(ids)))).scalars()) if me and ids else set()
    mine_s = set((await session.execute(select(PulseSave.clip_id).where(PulseSave.user_id == me.id, PulseSave.clip_id.in_(ids)))).scalars()) if me and ids else set()
    return [{"id": c.id, "url": media.url("pulse", c.file), "text": c.text, "at": _at(c.created_at),
             "author": _author(users.get(c.user_id), c.user_id), "mine": bool(me and me.id == c.user_id),
             "likes": likes.get(c.id, 0), "liked": c.id in mine_l, "saved": c.id in mine_s, "comments": comments.get(c.id, 0)}
            for c in rows]


def _visible(q):
    return q.where(PulseClip.deleted.is_(False), PulseClip.hidden.is_(False))


async def _clip(session, cid: int, me: AppUser | None) -> PulseClip | None:
    c = await session.get(PulseClip, cid)
    if not c or c.deleted or c.hidden or c.user_id in await _hidden_authors(session, me):
        return None
    return c


def _cid(request: web.Request) -> int:
    return int(request.match_info["id"])


async def feed(request: web.Request) -> web.Response:
    if request.method == "POST":
        return await upload(request)
    async with get_session() as session:
        me = await _user(request, session)
        q = _visible(select(PulseClip))
        hidden = await _hidden_authors(session, me)
        if hidden:
            q = q.where(PulseClip.user_id.notin_(hidden))
        before = request.query.get("before", "")
        if before.isdigit():
            q = q.where(PulseClip.id < int(before))
        rows = list((await session.execute(q.order_by(PulseClip.id.desc()).limit(PAGE))).scalars())
        items = await _clips_json(session, rows, me)
        await session.commit()
    return _json(request, {"ok": True, "clips": items, "more": len(rows) == PAGE})


async def saved(request: web.Request) -> web.Response:
    async with get_session() as session:
        me = await _user(request, session)
        if not me:
            return _err(request, "Войдите заново.", 401)
        hidden = await _hidden_authors(session, me)
        q = _visible(select(PulseClip).join(PulseSave, PulseSave.clip_id == PulseClip.id).where(PulseSave.user_id == me.id))
        if hidden:
            q = q.where(PulseClip.user_id.notin_(hidden))
        rows = list((await session.execute(q.order_by(PulseSave.id.desc()).limit(100))).scalars())
        items = await _clips_json(session, rows, me)
        await session.commit()
    return _json(request, {"ok": True, "clips": items})


async def upload(request: web.Request) -> web.Response:
    async with get_session() as session:
        me = await _user(request, session)
        denied = can_write(me)
        await session.commit()
    if denied:
        return _err(request, *denied)
    if _rate(f"pulse:{me.id}", 5, 86400):
        return _err(request, "Можно публиковать до 5 видео в день.", 429)
    try:
        fields, _, name = await media.read_upload(request, "pulse", ("video",))
    except media.UploadError as e:
        return _err(request, str(e))
    text = " ".join(str(fields.get("text") or "").split())[:TEXT_MAX]
    if text:
        reason = check_text(me, text, TEXT_MAX)
        if reason:
            media.remove("pulse", name)
            return _err(request, reason)
    async with get_session() as session:
        clip = PulseClip(user_id=me.id, text=text, file=name)
        session.add(clip)
        await session.flush()
        item = (await _clips_json(session, [clip], me))[0]
        await session.commit()
    return _json(request, {"ok": True, "clip": item})


async def _toggle(request: web.Request, model) -> web.Response:
    data = await _body(request)
    on = bool(data.get("on", True))
    async with get_session() as session:
        me = await _user(request, session)
        if not me:
            return _err(request, "Войдите, чтобы продолжить.", 401)
        c = await _clip(session, _cid(request), me)
        if not c:
            return _err(request, "Видео удалено или недоступно.", 404)
        exists = await session.scalar(select(model.id).where(model.clip_id == c.id, model.user_id == me.id))
        if on and not exists:
            session.add(model(clip_id=c.id, user_id=me.id))
        elif not on and exists:
            await session.execute(delete(model).where(model.clip_id == c.id, model.user_id == me.id))
        await session.flush()
        n = await session.scalar(select(func.count()).select_from(model).where(model.clip_id == c.id)) or 0
        await session.commit()
    return _json(request, {"ok": True, "on": on, "count": n})


async def like(request: web.Request) -> web.Response:
    return await _toggle(request, PulseLike)


async def save(request: web.Request) -> web.Response:
    return await _toggle(request, PulseSave)


def _comment(c: PulseComment, users, me) -> dict:
    return {"id": c.id, "text": c.text, "at": _at(c.created_at), "author": _author(users.get(c.user_id), c.user_id),
            "mine": bool(me and me.id == c.user_id)}


async def comments(request: web.Request) -> web.Response:
    async with get_session() as session:
        me = await _user(request, session)
        clip = await _clip(session, _cid(request), me)
        if not clip:
            return _err(request, "Видео удалено или недоступно.", 404)
        if request.method == "GET":
            q = select(PulseComment).where(PulseComment.clip_id == clip.id, PulseComment.deleted.is_(False),
                                           PulseComment.hidden.is_(False))
            hidden = await _hidden_authors(session, me, private=False)
            if hidden:
                q = q.where(PulseComment.user_id.notin_(hidden))
            rows = list((await session.execute(q.order_by(PulseComment.id).limit(300))).scalars())
            users = await _users(session, {c.user_id for c in rows})
            await session.commit()
            return _json(request, {"ok": True, "comments": [_comment(c, users, me) for c in rows]})
        data = await _body(request)
        text = str(data.get("text") or "").strip()
        denied = can_write(me)
        if denied:
            await session.commit()
            return _err(request, *denied)
        reason = check_text(me, text, 1000)
        if reason:
            return _err(request, reason)
        if _rate(f"pcm:{me.id}", 20, 600):
            return _err(request, "Слишком много комментариев подряд. Подождите немного.", 429)
        c = PulseComment(clip_id=clip.id, user_id=me.id, text=text)
        session.add(c)
        await session.flush()
        item = _comment(c, {me.id: me}, me)
        await session.commit()
    return _json(request, {"ok": True, "comment": item})


async def by_user(request: web.Request) -> web.Response:
    uid = int(request.match_info["id"])
    async with get_session() as session:
        me = await _user(request, session)
        if uid in await _hidden_authors(session, me):   # блокировка или закрытый аккаунт не друга
            await session.commit()
            return _json(request, {"ok": True, "clips": []})
        rows = list((await session.execute(_visible(select(PulseClip)).where(PulseClip.user_id == uid)
                                           .order_by(PulseClip.id.desc()).limit(60))).scalars())
        items = await _clips_json(session, rows, me)
        await session.commit()
    return _json(request, {"ok": True, "clips": items})


def install_routes(app: web.Application) -> None:
    app.router.add_get(r"/api/app/user/{id:\d+}/pulse", by_user)
    app.router.add_get("/api/app/pulse", feed)
    app.router.add_post("/api/app/pulse", feed)
    app.router.add_get("/api/app/pulse/saved", saved)
    app.router.add_post(r"/api/app/pulse/{id:\d+}/like", like)
    app.router.add_post(r"/api/app/pulse/{id:\d+}/save", save)
    app.router.add_get(r"/api/app/pulse/{id:\d+}/comments", comments)
    app.router.add_post(r"/api/app/pulse/{id:\d+}/comments", comments)
