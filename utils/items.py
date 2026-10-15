"""Реакции на новости и события ленты: лайки, комментарии, «поделиться в профиле».

Новости и события живут не в нашей базе постов (новости — с сайта, события — из афиши), поэтому
реакции привязаны к паре kind + key: kind — news | event, key — id новости или ключ события.

GET  /api/app/items/stats?keys=news:123,event:abc  — {"news:123": {likes, liked, comments, shares, shared}}
POST /api/app/items/{kind}/{key}/like              — {on} → {likes, liked}
GET  /api/app/items/{kind}/{key}/comments          — комментарии
POST /api/app/items/{kind}/{key}/comments          — {text}
POST /api/app/items/{kind}/{key}/share             — {title, url, img, text} → пост-ссылка на моей стене

Комментарии: удалить свой — /api/app/delete kind=icomment, пожаловаться — /api/app/report kind=icomment.
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit

from aiohttp import web
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from database.db import get_session
from database.models import ItemComment, ItemLike, UserPost
from utils import feed
from utils.app_api import _user
from utils.community import OWN_HOSTS, POST_MAX, _rate, can_write, check_text
from utils.market import _read_json
from utils.site_api import _err, _json

KINDS = ("news", "event")
_KEY = re.compile(r"^[A-Za-z0-9_.:\-]{1,120}$")
MAX_KEYS = 60


def _target(request: web.Request) -> tuple[str, str] | None:
    kind, key = request.match_info.get("kind", ""), request.match_info.get("key", "")
    return (kind, key) if kind in KINDS and _KEY.match(key) else None


def _own_url(v) -> str:
    """Ссылка и картинка превью — только с нашего сайта: клиент не может подложить фишинг или трекер."""
    v = str(v or "").strip()[:700]
    try:
        u = urlsplit(v)
    except ValueError:
        return ""
    host = (u.hostname or "").lower()
    ok = u.scheme == "https" and any(host == h or host.endswith("." + h) for h in OWN_HOSTS)
    return v if ok else ""


async def stats(request: web.Request) -> web.Response:
    pairs = []
    for raw in (request.query.get("keys") or "").split(",")[:MAX_KEYS]:
        kind, _, key = raw.partition(":")
        if kind in KINDS and _KEY.match(key):
            pairs.append((kind, key))
    if not pairs:
        return _json(request, {"ok": True, "stats": {}})
    async with get_session() as session:
        me = await _user(request, session)
        out = {f"{k}:{v}": {"likes": 0, "liked": False, "comments": 0, "shares": 0, "shared": False} for k, v in pairs}
        for kind in KINDS:
            keys = [v for k, v in pairs if k == kind]
            if not keys:
                continue
            for key, n in (await session.execute(select(ItemLike.key, func.count()).where(
                    ItemLike.kind == kind, ItemLike.key.in_(keys)).group_by(ItemLike.key))).all():
                out[f"{kind}:{key}"]["likes"] = n
            for key, n in (await session.execute(select(ItemComment.key, func.count()).where(
                    ItemComment.kind == kind, ItemComment.key.in_(keys), ItemComment.deleted.is_(False),
                    ItemComment.hidden.is_(False)).group_by(ItemComment.key))).all():
                out[f"{kind}:{key}"]["comments"] = n
            for key, n in (await session.execute(select(UserPost.share_key, func.count()).where(
                    UserPost.share_kind == kind, UserPost.share_key.in_(keys), UserPost.deleted.is_(False),
                    UserPost.hidden.is_(False)).group_by(UserPost.share_key))).all():
                out[f"{kind}:{key}"]["shares"] = n
            if me:
                for key in (await session.execute(select(ItemLike.key).where(
                        ItemLike.kind == kind, ItemLike.key.in_(keys), ItemLike.user_id == me.id))).scalars():
                    out[f"{kind}:{key}"]["liked"] = True
                for key in (await session.execute(select(UserPost.share_key).where(
                        UserPost.share_kind == kind, UserPost.share_key.in_(keys), UserPost.user_id == me.id,
                        UserPost.deleted.is_(False)))).scalars():
                    out[f"{kind}:{key}"]["shared"] = True
        await session.commit()
    return _json(request, {"ok": True, "stats": out})


async def like(request: web.Request) -> web.Response:
    t = _target(request)
    if not t:
        return _err(request, "Не найдено.", 404)
    kind, key = t
    data = await _read_json(request)
    on = data.get("on", True) is not False
    async with get_session() as session:
        me = await _user(request, session)
        if not me:
            return _err(request, "Войдите, чтобы ставить лайки.", 401)
        row = (await session.execute(select(ItemLike).where(
            ItemLike.kind == kind, ItemLike.key == key, ItemLike.user_id == me.id))).scalar_one_or_none()
        if on and not row:
            if _rate(f"like:{me.id}", 120, 3600):
                return _err(request, "Слишком много лайков. Передохните немного.", 429)
            session.add(ItemLike(kind=kind, key=key, user_id=me.id))
        elif not on and row:
            await session.delete(row)
        try:
            await session.commit()
        except IntegrityError:   # двойное нажатие
            await session.rollback()
        likes = await session.scalar(select(func.count()).select_from(ItemLike).where(
            ItemLike.kind == kind, ItemLike.key == key)) or 0
        liked = bool(await session.scalar(select(ItemLike.id).where(
            ItemLike.kind == kind, ItemLike.key == key, ItemLike.user_id == me.id)))
        await session.commit()
    return _json(request, {"ok": True, "likes": likes, "liked": liked})


def _comment(c: ItemComment, users, me) -> dict:
    return {"id": c.id, "text": c.text, "at": feed._at(c.created_at), "author": feed._author(users.get(c.user_id), c.user_id),
            "mine": bool(me and me.id == c.user_id)}


async def comments(request: web.Request) -> web.Response:
    t = _target(request)
    if not t:
        return _err(request, "Не найдено.", 404)
    kind, key = t
    async with get_session() as session:
        me = await _user(request, session)
        if request.method == "GET":
            q = select(ItemComment).where(ItemComment.kind == kind, ItemComment.key == key,
                                          ItemComment.deleted.is_(False), ItemComment.hidden.is_(False))
            hidden = await feed._hidden_authors(session, me)
            if hidden:
                q = q.where(ItemComment.user_id.notin_(hidden))
            rows = list((await session.execute(q.order_by(ItemComment.id).limit(300))).scalars())
            users = await feed._users(session, {c.user_id for c in rows})
            await session.commit()
            return _json(request, {"ok": True, "comments": [_comment(c, users, me) for c in rows]})
        data = await _read_json(request)
        text = str(data.get("text") or "").strip()
        denied = can_write(me)
        if denied:
            await session.commit()
            return _err(request, *denied)
        reason = check_text(me, text, feed.COMMENT_MAX)
        if reason:
            return _err(request, reason)
        if _rate(f"c5:{me.id}", 1, 5) or _rate(f"c3600:{me.id}", 60, 3600):
            return _err(request, "Не так быстро: подождите немного.", 429)
        c = ItemComment(kind=kind, key=key, user_id=me.id, text=text)
        session.add(c)
        await session.commit()
        return _json(request, {"ok": True, "comment": _comment(c, {me.id: me}, me)})


async def share(request: web.Request) -> web.Response:
    """Поделиться новостью или событием у себя в профиле: пост с превью-ссылкой (и своим текстом)."""
    t = _target(request)
    if not t:
        return _err(request, "Не найдено.", 404)
    kind, key = t
    data = await _read_json(request)
    title = " ".join(str(data.get("title") or "").split())[:300]
    if not title:
        return _err(request, "Нет заголовка.")
    async with get_session() as session:
        me = await _user(request, session)
        denied = can_write(me)
        if denied:
            await session.commit()
            return _err(request, *denied)
        if await session.scalar(select(UserPost.id).where(
                UserPost.user_id == me.id, UserPost.share_kind == kind, UserPost.share_key == key, UserPost.deleted.is_(False))):
            return _err(request, "Вы уже поделились этим.", 409)
        reason = check_text(me, title, 300)
        if reason:
            return _err(request, reason)
        text = str(data.get("text") or "").strip()
        if text:
            reason = check_text(me, text, POST_MAX)
            if reason:
                return _err(request, reason)
        if _rate(f"repost:{me.id}", 20, 86400):
            return _err(request, "Слишком много репостов за день. Попробуйте завтра.", 429)
        p = UserPost(user_id=me.id, text=text, city=me.city or "", country=me.country, share_kind=kind, share_key=key,
                     share_title=title, share_url=_own_url(data.get("url")) if kind == "news" else "",
                     share_img=_own_url(data.get("img")))
        session.add(p)
        await session.commit()
        item = (await feed.posts_json(session, [p], me))[0]
    return _json(request, {"ok": True, "post": item})


def install_routes(app: web.Application) -> None:
    app.router.add_get("/api/app/items/stats", stats)
    app.router.add_post(r"/api/app/items/{kind:news|event}/{key}/like", like)
    app.router.add_get(r"/api/app/items/{kind:news|event}/{key}/comments", comments)
    app.router.add_post(r"/api/app/items/{kind:news|event}/{key}/comments", comments)
    app.router.add_post(r"/api/app/items/{kind:news|event}/{key}/share", share)
