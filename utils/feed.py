"""Лента приложения podslushano: посты, фото, лайки, комментарии, репосты.

Лента бывает трёх видов (scope):
- all     — все посты из трёх стран по дате; на первой странице сверху — свежие посты подтверждённых аккаунтов
            (приоритет «Премиум верификации»);
- friends — посты друзей и мои (нужен вход);
- near    — «Рядом»: посты в радиусе 50 км от моих координат (GPS), а посты без координат — из моего города;
            без координат у меня — только мой город; без входа — страна ?country= и город ?city=.
Посты тех, кого я заблокировал и кто заблокировал меня, не показываются.

GET  /api/app/posts?scope=&city=&country=&before=  — лента (по 20)
POST /api/app/posts                                — {text, photos: [data:...], repost_of}
GET  /api/app/posts/{id}                           — пост и комментарии
POST /api/app/posts/{id}/like                      — {on} → {likes, liked}
GET  /api/app/posts/{id}/comments                  — комментарии
POST /api/app/posts/{id}/comments                  — {text}
GET  /api/app/posts/{id}/photo/{i}                 — JPEG
POST /api/app/posts/{id}/repost                    — {on, text} репост на свою стену (on=false — убрать свой репост)
GET  /api/app/user/{id}/posts?before=              — стена пользователя: его посты и репосты

Фото хранятся прямо в базе (post_photos). Автор поста получает событие по живому соединению:
{"type":"post","event":"like"|"comment"|"repost","post":id,"user":{...}}.
Удалить свой комментарий и пожаловаться — общими /api/app/delete и /api/app/report (kind=comment).
"""
from __future__ import annotations

import io

from aiohttp import web
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError

from database.db import get_session
from database.models import AppUser, Country, Friendship, FriendStatus, PostComment, PostLike, PostPhoto, UserPost
from utils import realtime, social
from utils.app_api import _user
from utils.app_geo import near_clause
from utils.community import POST_MAX, _rate, can_write, check_text
from utils.market import _read_json, prepare_photo
from utils.site_api import _err, _json, grant, read_token

PAGE = 20
BOOST = 3                      # сколько свежих постов с галочкой поднимать наверх ленты «Все»
BOOST_AGE = timedelta(hours=48)
MAX_PHOTOS = 4
COMMENT_MAX = 1000


def _at(d) -> str:
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def _visible(q):
    return q.where(UserPost.deleted.is_(False), UserPost.hidden.is_(False))


async def _hidden_authors(session, me: AppUser | None, private: bool = True) -> set[int]:
    """Чьи публикации не показывать: я заблокировал или он меня, а также закрытые аккаунты, где мы не друзья
    (private=False — только блокировка: так фильтруются комментарии)."""
    out = await social.blocked_by(session, me.id) | await social.blockers_of(session, me.id) if me else set()
    if private:
        closed = set((await session.execute(select(AppUser.id).where(AppUser.is_private.is_(True)))).scalars())
        if me:
            closed.discard(me.id)
            if closed:
                closed -= await _friend_ids(session, me.id)
        out |= closed
    return out


async def _friend_ids(session, uid: int) -> set[int]:
    rows = (await session.execute(select(Friendship.user_id, Friendship.friend_id).where(
        or_(Friendship.user_id == uid, Friendship.friend_id == uid),
        Friendship.status == FriendStatus.ACCEPTED))).all()
    return {b if a == uid else a for a, b in rows}


def _author(u: AppUser | None, uid: int) -> dict:
    return {"id": uid, "name": (u.name if u else "") or "Участник", "city": (u.city if u else "") or "",
            "avatar": social.avatar_url(u) if u else "", "verified": bool(u and u.is_verified),
            "username": (u.username if u else "") or ""}


def _share(p: UserPost) -> dict | None:
    if not p.share_kind:
        return None
    return {"kind": p.share_kind, "key": p.share_key or "", "title": p.share_title or "", "url": p.share_url or "",
            "img": p.share_img or ""}


RATIOS = (1.0, 0.8, 16 / 9)   # квадрат 1:1, вертикаль 4:5, горизонталь 16:9


def photo_ratio(jpeg: bytes) -> float:
    """Ближайший стандартный формат картинки (ширина/высота): в ленте фото показывается в нём без искажений."""
    from PIL import Image
    w, h = Image.open(io.BytesIO(jpeg)).size
    r = w / max(1, h)
    return round(min(RATIOS, key=lambda x: abs(x - r)), 4)


def _photos(p: UserPost, author: AppUser | None = None) -> list[str]:
    # Фото закрытого аккаунта — по подписанной ссылке: её получает только тот, кому пост показали
    k = f"?k={grant({'k': 'pph', 'p': p.id})}" if author and author.is_private else ""
    return [f"/api/app/posts/{p.id}/photo/{i}{k}" for i in range(p.photo_count or 0)]


async def _count(session, col, ids: set[int], *where) -> dict[int, int]:
    if not ids:
        return {}
    return dict((await session.execute(select(col, func.count()).where(col.in_(ids), *where).group_by(col))).all())


async def posts_json(session, posts: list[UserPost], me: AppUser | None) -> list[dict]:
    """Посты для приложения со счётчиками, моим лайком и вложенным оригиналом репоста."""
    ids = {p.id for p in posts}
    orig_ids = {p.repost_of for p in posts if p.repost_of}
    originals = {o.id: o for o in (await session.execute(select(UserPost).where(UserPost.id.in_(orig_ids)))).scalars()} if orig_ids else {}
    users = await _users(session, {p.user_id for p in posts} | {o.user_id for o in originals.values()})
    likes = await _count(session, PostLike.post_id, ids)
    comments = await _count(session, PostComment.post_id, ids, PostComment.deleted.is_(False), PostComment.hidden.is_(False))
    reposts = await _count(session, UserPost.repost_of, ids, UserPost.deleted.is_(False), UserPost.hidden.is_(False))
    liked = set((await session.execute(select(PostLike.post_id).where(
        PostLike.user_id == me.id, PostLike.post_id.in_(ids)))).scalars()) if me and ids else set()
    hidden = await _hidden_authors(session, me) if orig_ids else set()   # блокировка действует и на репосты
    reposted = set((await session.execute(select(UserPost.repost_of).where(
        UserPost.user_id == me.id, UserPost.repost_of.in_(ids | orig_ids), UserPost.deleted.is_(False)))).scalars()) \
        if me and ids else set()
    out = []
    for p in posts:
        d = {"id": p.id, "text": p.text, "at": _at(p.created_at), "city": p.city or "", "country": p.country.value,
             "author": _author(users.get(p.user_id), p.user_id), "mine": bool(me and me.id == p.user_id),
             "photos": _photos(p, users.get(p.user_id)), "ratio": p.photo_ratio or 1.0, "likes": likes.get(p.id, 0), "liked": p.id in liked,
             "comments": comments.get(p.id, 0), "reposts": reposts.get(p.id, 0), "repost": None,
             # я уже сделал репост этого поста (для репоста — его оригинала)
             "reposted": (p.repost_of or p.id) in reposted, "share": _share(p)}
        if p.repost_of:
            o = originals.get(p.repost_of)
            d["repost"] = ({"id": o.id, "text": o.text, "at": _at(o.created_at), "city": o.city or "",
                            "author": _author(users.get(o.user_id), o.user_id), "photos": _photos(o, users.get(o.user_id)),
                            "ratio": o.photo_ratio or 1.0}
                           if o and not o.deleted and not o.hidden and o.user_id not in hidden
                           else {"id": p.repost_of, "deleted": True})
        out.append(d)
    return out


async def _users(session, ids: set[int]) -> dict[int, AppUser]:
    if not ids:
        return {}
    return {u.id: u for u in (await session.execute(select(AppUser).where(AppUser.id.in_(ids)))).scalars()}


async def _post(session, pid: int, me: AppUser | None) -> UserPost | None:
    p = await session.get(UserPost, pid)
    if not p or p.deleted or p.hidden or p.user_id in await _hidden_authors(session, me):
        return None
    return p


def _pid(request: web.Request) -> int:
    try:
        return int(request.match_info["id"])
    except (KeyError, ValueError):
        return 0


# ---------------------------------------------------------------- лента и публикация

async def posts(request: web.Request) -> web.Response:
    if request.method == "POST":
        return await create(request)
    scope = request.query.get("scope", "all")
    async with get_session() as session:
        me = await _user(request, session)
        q = _visible(select(UserPost))
        if scope == "friends":
            if not me:
                return _err(request, "Войдите, чтобы видеть ленту друзей.", 401)
            q = q.where(UserPost.user_id.in_(await _friend_ids(session, me.id) | {me.id}))
        elif scope == "near":
            city = request.query.get("city", "")[:80]
            if me and me.lat is not None and me.lng is not None and not city:
                # Радиус 50 км по координатам; посты без координат (старые, с другим городом) — по моему городу
                q = q.where(or_(and_(UserPost.lat.is_not(None), UserPost.lng.is_not(None),
                                     near_clause(UserPost.lat, UserPost.lng, me.lat, me.lng)),
                                and_(UserPost.lat.is_(None), UserPost.city == me.city, UserPost.country == me.country)))
            else:
                raw = request.query.get("country") or (me.country.value if me else Country.NL.value)
                try:
                    q = q.where(UserPost.country == Country.parse(raw))
                except ValueError:
                    return _err(request, "Страна: Нидерланды, Германия или Бельгия.")
                city = city or (me.city if me else "") or ""
                if city:
                    q = q.where(UserPost.city == city)
        hidden = await _hidden_authors(session, me)
        if hidden:
            q = q.where(UserPost.user_id.notin_(hidden))
        before = request.query.get("before", "")
        if before.isdigit():
            q = q.where(UserPost.id < int(before))
        rows = list((await session.execute(q.order_by(UserPost.id.desc()).limit(PAGE))).scalars())
        more = len(rows) == PAGE
        if scope == "all" and not before.isdigit():
            # Приоритет подтверждённых аккаунтов: их свежие посты — первыми на первой странице
            since = datetime.now(timezone.utc).replace(tzinfo=None) - BOOST_AGE
            boosted = list((await session.execute(
                q.where(UserPost.created_at >= since, UserPost.repost_of.is_(None),
                        UserPost.user_id.in_(select(AppUser.id).where(AppUser.is_verified.is_(True))))
                .order_by(UserPost.id.desc()).limit(BOOST))).scalars())
            ids = {p.id for p in boosted}
            rows = boosted + [p for p in rows if p.id not in ids]
        items = await posts_json(session, rows, me)
        await session.commit()
    return _json(request, {"ok": True, "posts": items, "more": more})


async def create(request: web.Request) -> web.Response:
    data = await _read_json(request)
    text = str(data.get("text") or "").strip()
    raw_photos = [str(x) for x in (data.get("photos") or []) if x][:MAX_PHOTOS] if isinstance(data.get("photos"), list) else []
    async with get_session() as session:
        me = await _user(request, session)
        denied = can_write(me)
        if denied:
            await session.commit()
            return _err(request, *denied)
        orig = None
        if data.get("repost_of"):
            try:
                orig = await _post(session, int(data["repost_of"]), me)
            except (TypeError, ValueError):
                orig = None
            if orig and orig.repost_of:   # репост репоста — делимся оригиналом
                orig = await _post(session, orig.repost_of, me)
            if not orig:
                return _err(request, "Пост удалён или недоступен.", 404)
            if orig.user_id == me.id:
                return _err(request, "Это ваш пост.", 400)
            if await session.scalar(select(UserPost.id).where(
                    UserPost.user_id == me.id, UserPost.repost_of == orig.id, UserPost.deleted.is_(False))):
                return _err(request, "Вы уже поделились этим постом.", 409)
        if text:
            reason = check_text(me, text, POST_MAX)
            if reason:
                return _err(request, reason)
        elif not raw_photos and not orig:
            return _err(request, "Напишите текст или добавьте фото.")
        jpegs = []   # сначала фото: битая картинка не должна съедать лимит публикаций
        for raw in raw_photos:
            jpeg = prepare_photo(raw)
            if not jpeg:
                return _err(request, "Не получилось прочитать одно из фото. Попробуйте другое.")
            jpegs.append(jpeg)
        if orig:
            if _rate(f"repost:{me.id}", 20, 86400):
                return _err(request, "Слишком много репостов за день. Попробуйте завтра.", 429)
        elif _rate(f"p60:{me.id}", 1, 60) or _rate(f"pday:{me.id}", 10, 86400):
            return _err(request, "Можно публиковать до 10 постов в день и не чаще раза в минуту.", 429)
        # Место поста: город, выбранный в редакторе (значок геопозиции), иначе — город профиля
        city = " ".join(str(data.get("city") or "").split())[:80] or me.city or ""
        # Координаты — только если пост из «моего» места (в редакторе можно выбрать другой город)
        here = city == (me.city or "")
        p = UserPost(user_id=me.id, text=text, city=city, country=me.country,
                     lat=me.lat if here else None, lng=me.lng if here else None,
                     repost_of=orig.id if orig else None, photo_count=len(jpegs),
                     photo_ratio=photo_ratio(jpegs[0]) if jpegs else None)
        session.add(p)
        await session.flush()
        for i, jpeg in enumerate(jpegs):
            session.add(PostPhoto(post_id=p.id, idx=i, data=jpeg))
        await session.commit()
        item = (await posts_json(session, [p], me))[0]
        orig_author = orig.user_id if orig else None
        me_card = {"id": me.id, "name": me.name or "Участник"}
    if orig_author:
        await realtime.push_user(orig_author, {"type": "post", "event": "repost", "post": orig.id, "user": me_card})
    return _json(request, {"ok": True, "post": item})


# ---------------------------------------------------------------- пост, лайк, комментарии, фото

def _comment(c: PostComment, users: dict[int, AppUser], me: AppUser | None) -> dict:
    return {"id": c.id, "text": c.text, "at": _at(c.created_at), "author": _author(users.get(c.user_id), c.user_id),
            "mine": bool(me and me.id == c.user_id)}


async def _comments(session, pid: int, me: AppUser | None) -> list[dict]:
    q = select(PostComment).where(PostComment.post_id == pid, PostComment.deleted.is_(False), PostComment.hidden.is_(False))
    hidden = await _hidden_authors(session, me, private=False)
    if hidden:
        q = q.where(PostComment.user_id.notin_(hidden))
    rows = list((await session.execute(q.order_by(PostComment.id).limit(300))).scalars())
    users = await _users(session, {c.user_id for c in rows})
    return [_comment(c, users, me) for c in rows]


async def post_detail(request: web.Request) -> web.Response:
    async with get_session() as session:
        me = await _user(request, session)
        p = await _post(session, _pid(request), me)
        if not p:
            return _err(request, "Пост удалён или недоступен.", 404)
        item = (await posts_json(session, [p], me))[0]
        comments = await _comments(session, p.id, me)
        await session.commit()
    return _json(request, {"ok": True, "post": item, "comments": comments})


async def like(request: web.Request) -> web.Response:
    data = await _read_json(request)
    on = bool(data.get("on", True))
    async with get_session() as session:
        me = await _user(request, session)
        if not me:
            return _err(request, "Войдите, чтобы ставить лайки.", 401)
        p = await _post(session, _pid(request), me)
        if not p:
            return _err(request, "Пост удалён или недоступен.", 404)
        row = (await session.execute(select(PostLike).where(PostLike.post_id == p.id, PostLike.user_id == me.id))).scalar_one_or_none()
        added = False
        if on and not row:
            if _rate(f"like:{me.id}", 120, 3600):
                return _err(request, "Слишком много лайков. Передохните немного.", 429)
            session.add(PostLike(post_id=p.id, user_id=me.id))
            added = True
        elif not on and row:
            await session.delete(row)
        try:
            await session.commit()
        except IntegrityError:   # двойное нажатие: лайк уже стоит
            await session.rollback()
            added = False
        likes = await session.scalar(select(func.count()).select_from(PostLike).where(PostLike.post_id == p.id)) or 0
        liked = bool(await session.scalar(select(PostLike.id).where(PostLike.post_id == p.id, PostLike.user_id == me.id)))
        author, pid, me_card = p.user_id, p.id, {"id": me.id, "name": me.name or "Участник"}
        await session.commit()
    if added and author != me_card["id"]:
        await realtime.push_user(author, {"type": "post", "event": "like", "post": pid, "user": me_card})
    return _json(request, {"ok": True, "likes": likes, "liked": liked})


async def comments(request: web.Request) -> web.Response:
    async with get_session() as session:
        me = await _user(request, session)
        p = await _post(session, _pid(request), me)
        if not p:
            return _err(request, "Пост удалён или недоступен.", 404)
        if request.method == "GET":
            items = await _comments(session, p.id, me)
            await session.commit()
            return _json(request, {"ok": True, "comments": items})
        data = await _read_json(request)
        text = str(data.get("text") or "").strip()
        denied = can_write(me)
        if denied:
            await session.commit()
            return _err(request, *denied)
        reason = check_text(me, text, COMMENT_MAX)
        if reason:
            return _err(request, reason)
        if _rate(f"c5:{me.id}", 1, 5) or _rate(f"c3600:{me.id}", 60, 3600):
            return _err(request, "Не так быстро: подождите немного.", 429)
        c = PostComment(post_id=p.id, user_id=me.id, text=text)
        session.add(c)
        await session.commit()
        item = _comment(c, {me.id: me}, me)
        author, pid, me_card = p.user_id, p.id, {"id": me.id, "name": me.name or "Участник"}
    if author != me_card["id"]:
        await realtime.push_user(author, {"type": "post", "event": "comment", "post": pid, "user": me_card,
                                          "text": text[:200]})
    return _json(request, {"ok": True, "comment": item})


async def photo(request: web.Request) -> web.Response:
    try:
        idx = int(request.match_info["i"])
    except (KeyError, ValueError):
        raise web.HTTPNotFound()
    async with get_session() as session:
        p = await session.get(UserPost, _pid(request))
        if not p or p.deleted or p.hidden:
            raise web.HTTPNotFound()
        author = await session.get(AppUser, p.user_id)
        private = bool(author and author.is_private)
        if private:
            ok = read_token(request.query.get("k", ""), "pph")
            if not ok or ok.get("p") != p.id:
                raise web.HTTPNotFound()
        data = await session.scalar(select(PostPhoto.data).where(PostPhoto.post_id == p.id, PostPhoto.idx == idx))
    if not data:
        raise web.HTTPNotFound()
    return web.Response(body=data, content_type="image/jpeg",
                        headers={"Cache-Control": "private, max-age=86400" if private else "public, max-age=86400"})


# ---------------------------------------------------------------- репост и стена

async def repost(request: web.Request) -> web.Response:
    """Репост в один тап: копия-ссылка на оригинал на моей стене. on=false убирает мой репост."""
    data = await _read_json(request)
    async with get_session() as session:
        me = await _user(request, session)
        denied = can_write(me)
        if denied:
            await session.commit()
            return _err(request, *denied)
        orig = await _post(session, _pid(request), me)
        if orig and orig.repost_of:   # репост репоста — это репост оригинала
            orig = await _post(session, orig.repost_of, me)
        if not orig:
            return _err(request, "Пост удалён или недоступен.", 404)
        if orig.user_id == me.id:
            return _err(request, "Это ваш пост.", 400)
        mine = (await session.execute(select(UserPost).where(
            UserPost.user_id == me.id, UserPost.repost_of == orig.id, UserPost.deleted.is_(False)))).scalars().first()
        if data.get("on", True) is False:
            if mine:
                mine.deleted = True
            await session.commit()
            item = None
        else:
            if mine:
                return _err(request, "Вы уже поделились этим постом.", 409)
            text = str(data.get("text") or "").strip()
            if text:
                reason = check_text(me, text, POST_MAX)
                if reason:
                    return _err(request, reason)
            if _rate(f"repost:{me.id}", 20, 86400):
                return _err(request, "Слишком много репостов за день. Попробуйте завтра.", 429)
            mine = UserPost(user_id=me.id, text=text, city=me.city or "", country=me.country, repost_of=orig.id,
                            lat=me.lat, lng=me.lng)
            session.add(mine)
            await session.commit()
            item = (await posts_json(session, [mine], me))[0]
        count = await session.scalar(select(func.count()).select_from(UserPost).where(
            UserPost.repost_of == orig.id, UserPost.deleted.is_(False), UserPost.hidden.is_(False))) or 0
        author, oid, me_card = orig.user_id, orig.id, {"id": me.id, "name": me.name or "Участник"}
        await session.commit()
    if item:
        await realtime.push_user(author, {"type": "post", "event": "repost", "post": oid, "user": me_card})
    return _json(request, {"ok": True, "post": item, "original": oid, "reposts": count, "reposted": item is not None})


async def wall(request: web.Request) -> web.Response:
    try:
        uid = int(request.match_info["id"])
    except (KeyError, ValueError):
        return _err(request, "Пользователь не найден.", 404)
    async with get_session() as session:
        me = await _user(request, session)
        if not me:
            return _err(request, "Войдите, чтобы смотреть профили.", 401)
        if uid in await _hidden_authors(session, me):
            # заблокирован или закрытый аккаунт не друга: публикаций не видно
            author = await session.get(AppUser, uid)
            locked = bool(author and author.is_private and not await social.blocked_between(session, me.id, uid))
            await session.commit()
            return _json(request, {"ok": True, "posts": [], "more": False, "locked": locked})
        q = _visible(select(UserPost)).where(UserPost.user_id == uid)
        before = request.query.get("before", "")
        if before.isdigit():
            q = q.where(UserPost.id < int(before))
        rows = list((await session.execute(q.order_by(UserPost.id.desc()).limit(PAGE))).scalars())
        items = await posts_json(session, rows, me)
        await session.commit()
    return _json(request, {"ok": True, "posts": items, "more": len(rows) == PAGE})


def install_routes(app: web.Application) -> None:
    app.router.add_post(r"/api/app/posts/{id:\d+}/repost", repost)
    app.router.add_get(r"/api/app/user/{id:\d+}/posts", wall)
    app.router.add_get("/api/app/posts", posts)
    app.router.add_post("/api/app/posts", posts)
    app.router.add_get(r"/api/app/posts/{id:\d+}", post_detail)
    app.router.add_post(r"/api/app/posts/{id:\d+}/like", like)
    app.router.add_get(r"/api/app/posts/{id:\d+}/comments", comments)
    app.router.add_post(r"/api/app/posts/{id:\d+}/comments", comments)
    app.router.add_get(r"/api/app/posts/{id:\d+}/photo/{i:\d+}", photo)
