"""Люди в приложении podslushano: профили, друзья, поиск, блокировка.

Правила:
- профиль любого пользователя открыт всем вошедшим (GET /api/app/user/{id}), флагов приватности нет;
- личные сообщения — только между друзьями (статус accepted), проверка в utils.dm;
- общие чаты по городам и темам открыты всем, дружба там не нужна.

Связь двух людей — одна запись Friendship: user_id отправил заявку, friend_id получил.
Блокировка — отдельная направленная запись со статусом blocked (кто заблокировал → кого).

GET  /api/app/user/{id}           — профиль, отношение ко мне, последние посты
GET  /api/app/users?q=&country=   — поиск людей по имени
GET  /api/app/friends             — друзья, входящие и исходящие заявки, заблокированные
POST /api/app/friends/request     — {user_id} заявка (встречная заявка сразу делает друзьями)
POST /api/app/friends/accept      — {user_id} принять заявку
POST /api/app/friends/remove      — {user_id} отклонить, отменить заявку или удалить из друзей
POST /api/app/friends/block       — {user_id} заблокировать (дружба и заявки удаляются)
POST /api/app/friends/unblock     — {user_id} разблокировать
"""
from __future__ import annotations

from aiohttp import web
from sqlalchemy import and_, delete, func, or_, select

from database.db import get_session
from database.models import AppUser, Country, Friendship, FriendStatus, UserPost
from utils import realtime
from utils.app_api import _user
from utils.site_api import _body, _err, _json

ACCEPTED, PENDING, BLOCKED = FriendStatus.ACCEPTED, FriendStatus.PENDING, FriendStatus.BLOCKED
NOT_FRIENDS = "Писать в личные сообщения можно только друзьям. Добавьте человека в друзья."


def _pair(a: int, b: int):
    return or_(and_(Friendship.user_id == a, Friendship.friend_id == b),
               and_(Friendship.user_id == b, Friendship.friend_id == a))


async def _rows(session, a: int, b: int) -> list[Friendship]:
    return list((await session.execute(select(Friendship).where(_pair(a, b)))).scalars())


async def are_friends(session, a: int, b: int) -> bool:
    return bool(await session.scalar(select(Friendship.id).where(_pair(a, b), Friendship.status == ACCEPTED)))


async def blocked_between(session, a: int, b: int) -> bool:
    return bool(await session.scalar(select(Friendship.id).where(_pair(a, b), Friendship.status == BLOCKED)))


async def blocked_by(session, uid: int) -> set[int]:
    """Кого заблокировал uid (их сообщения и посты ему не показываем)."""
    return set((await session.execute(select(Friendship.friend_id).where(
        Friendship.user_id == uid, Friendship.status == BLOCKED))).scalars())


async def blockers_of(session, uid: int) -> set[int]:
    """Кто заблокировал uid (им не доставляем его сообщения)."""
    return set((await session.execute(select(Friendship.user_id).where(
        Friendship.friend_id == uid, Friendship.status == BLOCKED))).scalars())


def _relation(me: int, other: int, rows: list[Friendship]) -> str:
    """self | none | outgoing | incoming | friends | blocked (я заблокировал) | unavailable (меня заблокировали)."""
    if me == other:
        return "self"
    for r in rows:
        if r.status == BLOCKED and r.user_id == me:
            return "blocked"
    for r in rows:
        if r.status == BLOCKED:
            return "unavailable"
    for r in rows:
        if r.status == ACCEPTED:
            return "friends"
        if r.status == PENDING:
            return "outgoing" if r.user_id == me else "incoming"
    return "none"


async def relation(session, me: int, other: int) -> str:
    return _relation(me, other, await _rows(session, me, other))


async def _relations(session, me: int, ids: set[int]) -> dict[int, str]:
    if not ids:
        return {}
    rows = list((await session.execute(select(Friendship).where(or_(
        and_(Friendship.user_id == me, Friendship.friend_id.in_(ids)),
        and_(Friendship.friend_id == me, Friendship.user_id.in_(ids)))))).scalars())
    by: dict[int, list[Friendship]] = {}
    for r in rows:
        by.setdefault(r.friend_id if r.user_id == me else r.user_id, []).append(r)
    return {i: _relation(me, i, by.get(i, [])) for i in ids}


def card(u: AppUser, rel: str | None = None) -> dict:
    d = {"id": u.id, "name": u.name or "Участник", "city": u.city or "", "country": u.country.value}
    return d | ({"relation": rel} if rel is not None else {})


def _target(data: dict) -> int:
    try:
        return int(data.get("user_id") or 0)
    except (TypeError, ValueError):
        return 0


async def _me_and_target(request: web.Request, session):
    """(я, цель, ошибка). Ошибка — готовый ответ."""
    data = await _body(request)
    me = await _user(request, session)
    if not me:
        return None, None, _err(request, "Войдите заново.", 401)
    tid = _target(data)
    if tid == me.id:
        return me, None, _err(request, "Это вы.", 400)
    other = await session.get(AppUser, tid) if tid else None
    if not other:
        return me, None, _err(request, "Пользователь не найден.", 404)
    return me, other, None


# ---------------------------------------------------------------- профиль и поиск

async def profile(request: web.Request) -> web.Response:
    try:
        uid = int(request.match_info["id"])
    except ValueError:
        return _err(request, "Пользователь не найден.", 404)
    async with get_session() as session:
        me = await _user(request, session)
        if not me:
            return _err(request, "Войдите, чтобы смотреть профили.", 401)
        u = await session.get(AppUser, uid)
        if not u:
            return _err(request, "Пользователь не найден.", 404)
        rel = await relation(session, me.id, u.id)
        friends = await session.scalar(select(func.count()).select_from(Friendship).where(
            or_(Friendship.user_id == u.id, Friendship.friend_id == u.id), Friendship.status == ACCEPTED)) or 0
        posts = [] if rel == "blocked" else list((await session.execute(select(UserPost).where(
            UserPost.user_id == u.id, UserPost.deleted.is_(False), UserPost.hidden.is_(False))
            .order_by(UserPost.id.desc()).limit(20))).scalars())
        await session.commit()
    return _json(request, {
        "ok": True, "user": card(u) | {"since": (u.created_at.strftime("%Y-%m-%d") if u.created_at else "")},
        "relation": rel, "friends": friends, "can_message": rel == "friends",
        "posts": [{"id": p.id, "text": p.text, "city": p.city, "at": p.created_at.strftime("%Y-%m-%dT%H:%M:%SZ")} for p in posts],
    })


async def search(request: web.Request) -> web.Response:
    q = (request.query.get("q") or "").strip()[:80]
    country = (request.query.get("country") or "").strip()
    async with get_session() as session:
        me = await _user(request, session)
        if not me:
            return _err(request, "Войдите заново.", 401)
        if len(q) < 2:
            return _json(request, {"ok": True, "users": []})
        stmt = select(AppUser).where(AppUser.id != me.id, AppUser.name != "", AppUser.name.ilike(f"%{q}%"))
        if country:
            try:
                stmt = stmt.where(AppUser.country == Country.parse(country))
            except ValueError:
                return _err(request, "Страна: Нидерланды, Германия или Бельгия.")
        users = list((await session.execute(stmt.order_by(AppUser.name).limit(30))).scalars())
        rels = await _relations(session, me.id, {u.id for u in users})
        await session.commit()
    return _json(request, {"ok": True, "users": [card(u, rels[u.id]) for u in users if rels[u.id] != "unavailable"]})


# ---------------------------------------------------------------- друзья

async def friends(request: web.Request) -> web.Response:
    async with get_session() as session:
        me = await _user(request, session)
        if not me:
            return _err(request, "Войдите заново.", 401)
        rows = list((await session.execute(select(Friendship).where(
            or_(Friendship.user_id == me.id, Friendship.friend_id == me.id)))).scalars())
        groups: dict[str, list[int]] = {"friends": [], "incoming": [], "outgoing": [], "blocked": []}
        for r in rows:
            other = r.friend_id if r.user_id == me.id else r.user_id
            rel = _relation(me.id, other, [r])
            if rel in groups:
                groups[rel].append(other)
        ids = {i for v in groups.values() for i in v}
        users = {u.id: u for u in (await session.execute(select(AppUser).where(AppUser.id.in_(ids)))).scalars()} if ids else {}
        await session.commit()
    out = {k: sorted((card(users[i], k) for i in v if i in users), key=lambda d: d["name"].lower()) for k, v in groups.items()}
    return _json(request, {"ok": True, **out})


async def request_friend(request: web.Request) -> web.Response:
    from utils.community import _rate
    async with get_session() as session:
        me, other, err = await _me_and_target(request, session)
        if err:
            return err
        rows = await _rows(session, me.id, other.id)
        rel = _relation(me.id, other.id, rows)
        if rel in ("blocked", "unavailable"):
            return _err(request, "Нельзя добавить этого пользователя.", 403)
        if rel in ("friends", "outgoing"):
            return _json(request, {"ok": True, "relation": rel})
        if rel == "incoming":   # он уже звал меня — встречная заявка = дружба
            for r in rows:
                if r.status == PENDING:
                    r.status = ACCEPTED
            await session.commit()
            await realtime.push_user(other.id, {"type": "friend", "event": "accepted", "user": card(me)})
            return _json(request, {"ok": True, "relation": "friends"})
        if _rate(f"friendreq:{me.id}", 30, 86400):
            return _err(request, "Слишком много заявок за день. Попробуйте завтра.", 429)
        session.add(Friendship(user_id=me.id, friend_id=other.id, status=PENDING))
        await session.commit()
    await realtime.push_user(other.id, {"type": "friend", "event": "request", "user": card(me)})
    return _json(request, {"ok": True, "relation": "outgoing"})


async def accept_friend(request: web.Request) -> web.Response:
    async with get_session() as session:
        me, other, err = await _me_and_target(request, session)
        if err:
            return err
        row = (await session.execute(select(Friendship).where(
            Friendship.user_id == other.id, Friendship.friend_id == me.id, Friendship.status == PENDING))).scalar_one_or_none()
        if not row:
            return _err(request, "Заявки нет или она уже отменена.", 404)
        row.status = ACCEPTED
        await session.commit()
    await realtime.push_user(other.id, {"type": "friend", "event": "accepted", "user": card(me)})
    return _json(request, {"ok": True, "relation": "friends"})


async def remove_friend(request: web.Request) -> web.Response:
    async with get_session() as session:
        me, other, err = await _me_and_target(request, session)
        if err:
            return err
        await session.execute(delete(Friendship).where(_pair(me.id, other.id), Friendship.status != BLOCKED))
        rel = await relation(session, me.id, other.id)
        await session.commit()
    return _json(request, {"ok": True, "relation": rel})


async def block_user(session, me_id: int, other_id: int) -> None:
    """Блокировка: дружба и заявки между двумя удаляются, остаётся запись «me заблокировал other»."""
    await session.execute(delete(Friendship).where(_pair(me_id, other_id), Friendship.status != BLOCKED))
    exists = await session.scalar(select(Friendship.id).where(
        Friendship.user_id == me_id, Friendship.friend_id == other_id))
    if not exists:
        session.add(Friendship(user_id=me_id, friend_id=other_id, status=BLOCKED))


async def block(request: web.Request) -> web.Response:
    async with get_session() as session:
        me, other, err = await _me_and_target(request, session)
        if err:
            return err
        await block_user(session, me.id, other.id)
        await session.commit()
    return _json(request, {"ok": True, "relation": "blocked"})


async def unblock(request: web.Request) -> web.Response:
    async with get_session() as session:
        me, other, err = await _me_and_target(request, session)
        if err:
            return err
        await session.execute(delete(Friendship).where(
            Friendship.user_id == me.id, Friendship.friend_id == other.id, Friendship.status == BLOCKED))
        rel = await relation(session, me.id, other.id)
        await session.commit()
    return _json(request, {"ok": True, "relation": rel})


def install_routes(app: web.Application) -> None:
    app.router.add_get(r"/api/app/user/{id:\d+}", profile)
    app.router.add_get("/api/app/users", search)
    app.router.add_get("/api/app/friends", friends)
    app.router.add_post("/api/app/friends/request", request_friend)
    app.router.add_post("/api/app/friends/accept", accept_friend)
    app.router.add_post("/api/app/friends/remove", remove_friend)
    app.router.add_post("/api/app/friends/block", block)
    app.router.add_post("/api/app/friends/unblock", unblock)
