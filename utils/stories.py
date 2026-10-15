"""Истории (сторис) на 24 часа: фото или видео во весь экран 9:16, быстрые реакции-эмодзи.

GET  /api/app/stories                 — лента историй: мои, друзей и открытых аккаунтов моей страны
                                        [{user, items: [{id, url, kind, at, my_reaction}]}]
POST /api/app/stories                 — multipart: file (фото или видео)
POST /api/app/stories/{id}/react      — {emoji} из REACTIONS (автор получает уведомление в реальном времени)
GET  /api/app/stories/{id}/reactions  — кто как отреагировал (только автору)
POST /api/app/stories/{id}/delete     — удалить свою
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from aiohttp import web
from sqlalchemy import or_, select

from database.db import get_session
from database.models import AppUser, Story, StoryReaction
from utils import media, realtime, social
from utils.app_api import _user
from utils.community import _rate, can_write
from utils.feed import _at, _friend_ids, _hidden_authors
from utils.site_api import _body, _err, _json

TTL = timedelta(hours=24)
REACTIONS = ("❤️", "🔥", "😂", "😮", "😢", "👏")
AUTHORS = 30


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _live():
    return (Story.deleted.is_(False)) & (Story.expires_at > _now())


def _item(s: Story, mine: dict[int, str]) -> dict:
    return {"id": s.id, "url": media.url("stories", s.file), "kind": s.kind, "at": _at(s.created_at),
            "my_reaction": mine.get(s.id, "")}


async def stories(request: web.Request) -> web.Response:
    if request.method == "POST":
        return await upload(request)
    await media.cleanup()   # файлы истёкших историй и удалённых видео — с диска (не чаще раза в час)
    async with get_session() as session:
        me = await _user(request, session)
        if not me:
            return _json(request, {"ok": True, "groups": [], "reactions": list(REACTIONS)})
        friends = await _friend_ids(session, me.id)
        hidden = await _hidden_authors(session, me)
        # Чьи истории видно: свои, друзей и открытых аккаунтов той же страны
        authors = select(AppUser.id).where(AppUser.country == me.country, AppUser.is_private.is_(False))
        q = select(Story).where(_live(), or_(Story.user_id.in_(friends | {me.id}), Story.user_id.in_(authors)))
        if hidden:
            q = q.where(Story.user_id.notin_(hidden))
        rows = list((await session.execute(q.order_by(Story.id))).scalars())
        mine = dict((await session.execute(select(StoryReaction.story_id, StoryReaction.emoji).where(
            StoryReaction.user_id == me.id, StoryReaction.story_id.in_({s.id for s in rows})))).all()) if rows else {}
        users = {u.id: u for u in (await session.execute(select(AppUser).where(AppUser.id.in_({s.user_id for s in rows})))).scalars()}
        await session.commit()
    by: dict[int, list[Story]] = {}
    for s in rows:
        by.setdefault(s.user_id, []).append(s)
    # Сначала мои, потом друзья, потом остальные; внутри — у кого история свежее
    order = sorted(by, key=lambda uid: (uid != me.id, uid not in friends, -by[uid][-1].id))[:AUTHORS]
    groups = [{"user": social.card(users[uid]) if uid in users else {"id": uid, "name": "Участник"},
               "items": [_item(s, mine) for s in by[uid]], "mine": uid == me.id} for uid in order]
    return _json(request, {"ok": True, "groups": groups, "reactions": list(REACTIONS)})


async def upload(request: web.Request) -> web.Response:
    async with get_session() as session:
        me = await _user(request, session)
        denied = can_write(me)
        await session.commit()
    if denied:
        return _err(request, *denied)
    if _rate(f"story:{me.id}", 20, 86400):
        return _err(request, "Можно добавить до 20 историй в день.", 429)
    try:
        _, kind, name = await media.read_upload(request, "stories", ("photo", "video"))
    except media.UploadError as e:
        return _err(request, str(e))
    async with get_session() as session:
        s = Story(user_id=me.id, kind=kind, file=name, expires_at=_now() + TTL)
        session.add(s)
        await session.flush()
        item = _item(s, {})
        await session.commit()
    return _json(request, {"ok": True, "story": item})


async def _story(session, request: web.Request, me: AppUser) -> Story | None:
    s = await session.get(Story, int(request.match_info["id"]))
    if not s or s.deleted or s.expires_at <= _now() or s.user_id in await _hidden_authors(session, me):
        return None
    return s


async def react(request: web.Request) -> web.Response:
    data = await _body(request)
    emoji = str(data.get("emoji") or "")
    if emoji not in REACTIONS:
        return _err(request, "Такой реакции нет.")
    async with get_session() as session:
        me = await _user(request, session)
        if not me:
            return _err(request, "Войдите, чтобы реагировать.", 401)
        s = await _story(session, request, me)
        if not s:
            return _err(request, "История больше недоступна.", 404)
        if s.user_id == me.id:
            return _err(request, "Это ваша история.", 400)
        r = (await session.execute(select(StoryReaction).where(StoryReaction.story_id == s.id,
                                                              StoryReaction.user_id == me.id))).scalar_one_or_none()
        if r:
            r.emoji = emoji
        else:
            session.add(StoryReaction(story_id=s.id, user_id=me.id, emoji=emoji))
        author, sid, card = s.user_id, s.id, social.card(me)
        await session.commit()
    if not _rate(f"sreact:{me.id}:{sid}", 1, 30):   # повторные тапы не засыпают автора уведомлениями
        await realtime.push_user(author, {"type": "story", "event": "reaction", "story": sid, "emoji": emoji, "user": card})
    return _json(request, {"ok": True, "emoji": emoji})


async def reactions(request: web.Request) -> web.Response:
    async with get_session() as session:
        me = await _user(request, session)
        if not me:
            return _err(request, "Войдите заново.", 401)
        s = await session.get(Story, int(request.match_info["id"]))
        if not s or s.user_id != me.id:
            return _err(request, "История не найдена.", 404)
        rows = list((await session.execute(select(StoryReaction, AppUser).join(AppUser, AppUser.id == StoryReaction.user_id)
                                           .where(StoryReaction.story_id == s.id).order_by(StoryReaction.id.desc()))).all())
        await session.commit()
    return _json(request, {"ok": True, "reactions": [{"emoji": r.emoji, "user": social.card(u)} for r, u in rows]})


async def remove(request: web.Request) -> web.Response:
    async with get_session() as session:
        me = await _user(request, session)
        s = await session.get(Story, int(request.match_info["id"]))
        if not me or not s or s.user_id != me.id:
            return _err(request, "История не найдена.", 404)
        s.deleted = True
        name = s.file
        await session.commit()
    media.remove("stories", name)
    return _json(request, {"ok": True})


def install_routes(app: web.Application) -> None:
    app.router.add_get("/api/app/stories", stories)
    app.router.add_post("/api/app/stories", stories)
    app.router.add_post(r"/api/app/stories/{id:\d+}/react", react)
    app.router.add_get(r"/api/app/stories/{id:\d+}/reactions", reactions)
    app.router.add_post(r"/api/app/stories/{id:\d+}/delete", remove)
