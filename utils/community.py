"""Сообщество в приложении podslushano: чаты по городам и темам, посты в ленте, модерация.

Писать могут только вошедшие пользователи с именем, принявшие правила и без бана.
Защита: лимиты частоты, фильтр мата, ссылки только у аккаунтов старше 3 дней.
Жалоба уходит модераторам в Telegram (группа-инбокс, тема «Модерация») с кнопками
«Удалить», «Бан 24 ч», «Бан навсегда», «Оставить». После 3 жалоб от разных людей
сообщение скрывается автоматически до решения модератора.

Сообщения забираются опросом (GET …/messages?after=<id>) раз в несколько секунд.
"""
from __future__ import annotations

import html
import logging
import re
import time
from datetime import datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiohttp import web
from sqlalchemy import func, select

import config
from database.db import get_session
from database.models import AppUser, ChatMessage, ChatRoom, ContentReport, UserBlock, UserPost
from utils import realtime
from utils.app_api import _user
from utils.site_api import _body, _err, _json

log = logging.getLogger(__name__)
router = Router()

MSG_MAX, POST_MAX = 1000, 2000
AUTO_HIDE_REPORTS = 3
LINK_AFTER_DAYS = 3
FOREVER = datetime(2100, 1, 1)

ROOMS = [
    # (slug, название, вид)
    ("nl", "Вся страна", "city"), ("amsterdam", "Amsterdam", "city"), ("rotterdam", "Rotterdam", "city"),
    ("den-haag", "Den Haag", "city"), ("utrecht", "Utrecht", "city"), ("eindhoven", "Eindhoven", "city"),
    ("groningen", "Groningen", "city"), ("noord-brabant", "Noord-Brabant", "city"), ("limburg", "Limburg", "city"),
    ("work", "Работа", "topic"), ("housing", "Жильё", "topic"), ("docs", "Документы и налоги", "topic"),
    ("health", "Врачи и медицина", "topic"), ("kids", "Мамы и дети", "topic"), ("cars", "Авто", "topic"),
    ("travel", "Путешествия", "topic"), ("talk", "Просто поговорить", "topic"),
]

# Мат ищем только с начала слова: «хлеба», «требования», «застрахуйтесь» — обычные слова
_W = r"(?<![а-яёa-z])"
_BAD = re.compile(_W + r"(?:"
                  r"(?:на|о|а|по|за|до|ни|от|пере)?ху[йяеёию]|пизд|"
                  r"(?:за|у|вы|на|по|отъ|об|подъ|разъ|съ|до)?[её]б(?:а|ан|ат|л|ну|ук|уч|ош)|"
                  r"бл[яь]д|бля\b|сук[аи]\b|муд[аи]к|пид[оа]р|долбо[её]б|шлюх)", re.I)
_HOST = re.compile(r"(?:https?://)?(?:www\.)?((?:[a-z0-9-]+\.)+[a-z]{2,})(?![a-z0-9-])", re.I)
OWN_HOSTS = ("podslushano.nl",)


def foreign_links(text: str) -> bool:
    """Есть ли в тексте ссылка не на наш сайт (каждая ссылка проверяется отдельно)."""
    for m in _HOST.finditer(text):
        host = m.group(1).lower()
        if not any(host == h or host.endswith("." + h) for h in OWN_HOSTS):
            return True
    return False
_hits: dict[str, list[float]] = {}


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _rate(key: str, limit: int, window: float) -> bool:
    """True — лимит превышен."""
    now = time.time()
    h = [t for t in _hits.get(key, []) if now - t < window]
    _hits[key] = h
    if len(h) >= limit:
        return True
    h.append(now)
    return False


def check_text(u: AppUser, text: str, limit: int) -> str | None:
    """Причина отказа или None. Общие правила для сообщений и постов."""
    if not text:
        return "Пустое сообщение."
    if len(text) > limit:
        return f"Слишком длинно: не больше {limit} символов."
    if _BAD.search(text):
        return "Без мата, пожалуйста: перепишите сообщение."
    if foreign_links(text) and (_now() - (u.created_at or _now())) < timedelta(days=LINK_AFTER_DAYS):
        return f"Ссылки можно отправлять через {LINK_AFTER_DAYS} дня после регистрации."
    return None


def can_write(u: AppUser | None) -> tuple[str, int] | None:
    if not u:
        return "Войдите, чтобы писать.", 401
    if u.banned_until and u.banned_until > _now():
        return ("Вы заблокированы в сообществе." if u.banned_until >= FOREVER else
                f"Вы не можете писать до {u.banned_until:%d.%m %H:%M}."), 403
    if not u.name:
        return "Укажите имя в профиле.", 409
    if not u.rules_at:
        return "Примите правила сообщества.", 428
    return None


async def ensure_rooms(session) -> None:
    if await session.scalar(select(func.count()).select_from(ChatRoom)):
        return
    for i, (slug, title, kind) in enumerate(ROOMS):
        session.add(ChatRoom(slug=slug, title=title, kind=kind, sort=i))
    await session.commit()


async def _blocked(session, u: AppUser | None) -> set[int]:
    if not u:
        return set()
    return set((await session.execute(select(UserBlock.blocked_id).where(UserBlock.user_id == u.id))).scalars())


async def _names(session, ids: set[int]) -> dict[int, AppUser]:
    if not ids:
        return {}
    return {x.id: x for x in (await session.execute(select(AppUser).where(AppUser.id.in_(ids)))).scalars()}


def _item(m, users: dict[int, AppUser], me: AppUser | None, extra: dict | None = None) -> dict:
    a = users.get(m.user_id)
    d = {"id": m.id, "text": m.text, "at": m.created_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
         "author": {"id": m.user_id, "name": (a.name if a else "") or "Участник", "city": a.city if a else ""},
         "mine": bool(me and me.id == m.user_id)}
    return d | (extra or {})


# ---------------------------------------------------------------- правила

async def rules(request: web.Request) -> web.Response:
    async with get_session() as session:
        u = await _user(request, session)
        if not u:
            return _err(request, "Войдите заново.", 401)
        u.rules_at = u.rules_at or _now()
        await session.commit()
    return _json(request, {"ok": True})


# ---------------------------------------------------------------- чаты

async def rooms(request: web.Request) -> web.Response:
    async with get_session() as session:
        await ensure_rooms(session)
        since = _now() - timedelta(days=1)
        counts = dict((await session.execute(select(ChatMessage.room_id, func.count()).where(
            ChatMessage.created_at >= since, ChatMessage.deleted.is_(False), ChatMessage.hidden.is_(False))
            .group_by(ChatMessage.room_id))).all())
        out = [{"slug": r.slug, "title": r.title, "kind": r.kind, "today": counts.get(r.id, 0)}
               for r in (await session.execute(select(ChatRoom).where(ChatRoom.active.is_(True))
                                               .order_by(ChatRoom.sort))).scalars()]
    return _json(request, {"ok": True, "rooms": out})


async def _room(session, slug: str) -> ChatRoom | None:
    await ensure_rooms(session)
    return (await session.execute(select(ChatRoom).where(ChatRoom.slug == slug, ChatRoom.active.is_(True)))).scalar_one_or_none()


async def messages(request: web.Request) -> web.Response:
    async with get_session() as session:
        room = await _room(session, request.match_info["slug"])
        if not room:
            return _err(request, "Нет такого чата.", 404)
        me = await _user(request, session)
        if request.method == "POST":
            data = await _body(request)
            text = str(data.get("text") or "").strip()
            denied = can_write(me)
            if denied:
                return _err(request, *denied)
            reason = check_text(me, text, MSG_MAX)
            if reason:
                return _err(request, reason)
            if _rate(f"m3:{me.id}", 1, 3) or _rate(f"m300:{me.id}", 20, 300):
                return _err(request, "Не так быстро: подождите немного.", 429)
            m = ChatMessage(room_id=room.id, user_id=me.id, text=text)
            session.add(m)
            await session.commit()
            # Сразу всем, у кого этот чат открыт (кроме скрывших автора)
            hidden_for = set((await session.execute(select(UserBlock.user_id).where(UserBlock.blocked_id == me.id))).scalars())
            await realtime.push_room(room.slug, {"type": "room", "slug": room.slug, "message": _item(m, {me.id: me}, None)},
                                     skip_users=hidden_for | {me.id})
            return _json(request, {"ok": True, "message": _item(m, {me.id: me}, me)})

        q = select(ChatMessage).where(ChatMessage.room_id == room.id, ChatMessage.deleted.is_(False),
                                      ChatMessage.hidden.is_(False))
        after, before = request.query.get("after"), request.query.get("before")
        if after and after.isdigit():
            q = q.where(ChatMessage.id > int(after)).order_by(ChatMessage.id).limit(100)
        else:
            if before and before.isdigit():
                q = q.where(ChatMessage.id < int(before))
            q = q.order_by(ChatMessage.id.desc()).limit(50)
        rows = list((await session.execute(q)).scalars())
        rows.sort(key=lambda m: m.id)
        hidden = await _blocked(session, me)
        rows = [m for m in rows if m.user_id not in hidden]
        users = await _names(session, {m.user_id for m in rows})
        await session.commit()
        return _json(request, {"ok": True, "room": {"slug": room.slug, "title": room.title},
                               "messages": [_item(m, users, me) for m in rows]})


# ---------------------------------------------------------------- посты

async def posts(request: web.Request) -> web.Response:
    async with get_session() as session:
        me = await _user(request, session)
        if request.method == "POST":
            data = await _body(request)
            text = str(data.get("text") or "").strip()
            denied = can_write(me)
            if denied:
                return _err(request, *denied)
            reason = check_text(me, text, POST_MAX)
            if reason:
                return _err(request, reason)
            if _rate(f"p60:{me.id}", 1, 60) or _rate(f"pday:{me.id}", 5, 86400):
                return _err(request, "Можно публиковать до 5 постов в день и не чаще раза в минуту.", 429)
            p = UserPost(user_id=me.id, text=text, city=me.city or "")
            session.add(p)
            await session.commit()
            return _json(request, {"ok": True, "post": _item(p, {me.id: me}, me, {"city": p.city})})

        q = select(UserPost).where(UserPost.deleted.is_(False), UserPost.hidden.is_(False)).order_by(UserPost.id.desc()).limit(30)
        before = request.query.get("before")
        if before and before.isdigit():
            q = q.where(UserPost.id < int(before))
        rows = list((await session.execute(q)).scalars())
        hidden = await _blocked(session, me)
        rows = [p for p in rows if p.user_id not in hidden]
        users = await _names(session, {p.user_id for p in rows})
        return _json(request, {"ok": True, "posts": [_item(p, users, me, {"city": p.city}) for p in rows]})


# ---------------------------------------------------------------- удалить своё, пожаловаться, скрыть автора

def _model(kind: str):
    return {"msg": ChatMessage, "post": UserPost}.get(kind)


async def delete_own(request: web.Request) -> web.Response:
    data = await _body(request)
    Model = _model(str(data.get("kind")))
    async with get_session() as session:
        me = await _user(request, session)
        if not me:
            return _err(request, "Войдите заново.", 401)
        obj = await session.get(Model, int(data.get("id") or 0)) if Model else None
        if not obj or obj.user_id != me.id:
            return _err(request, "Нельзя удалить чужое.", 403)
        obj.deleted = True
        await session.commit()
    return _json(request, {"ok": True})


async def report(request: web.Request) -> web.Response:
    data = await _body(request)
    kind = str(data.get("kind"))
    Model = _model(kind)
    async with get_session() as session:
        me = await _user(request, session)
        if not me:
            return _err(request, "Войдите, чтобы пожаловаться.", 401)
        obj = await session.get(Model, int(data.get("id") or 0)) if Model else None
        if not obj or obj.deleted:
            return _err(request, "Не найдено.", 404)
        dup = await session.scalar(select(ContentReport.id).where(
            ContentReport.kind == kind, ContentReport.target_id == obj.id, ContentReport.reporter_id == me.id))
        if dup:
            return _json(request, {"ok": True})
        r = ContentReport(kind=kind, target_id=obj.id, reporter_id=me.id, reason=str(data.get("reason") or "")[:200])
        session.add(r)
        await session.flush()
        n = await session.scalar(select(func.count(func.distinct(ContentReport.reporter_id))).where(
            ContentReport.kind == kind, ContentReport.target_id == obj.id)) or 0
        if n >= AUTO_HIDE_REPORTS:
            obj.hidden = True
        author = await session.get(AppUser, obj.user_id)
        text, rid, hidden = obj.text, r.id, obj.hidden
        await session.commit()
    bot = request.app.get("bot") if hasattr(request.app, "get") else None
    if bot:
        await notify_moderators(bot, rid, kind, text, author, me, hidden)
    return _json(request, {"ok": True})


async def block(request: web.Request) -> web.Response:
    data = await _body(request)
    async with get_session() as session:
        me = await _user(request, session)
        if not me:
            return _err(request, "Войдите заново.", 401)
        target = int(data.get("user_id") or 0)
        if target and target != me.id and not await session.scalar(select(UserBlock.id).where(
                UserBlock.user_id == me.id, UserBlock.blocked_id == target)):
            session.add(UserBlock(user_id=me.id, blocked_id=target))
            await session.commit()
    return _json(request, {"ok": True})


# ---------------------------------------------------------------- модерация в Telegram

def mod_kb(rid: int) -> InlineKeyboardMarkup:
    b = lambda t, a: InlineKeyboardButton(text=t, callback_data=f"cmod:{a}:{rid}")  # noqa: E731
    return InlineKeyboardMarkup(inline_keyboard=[[b("🗑 Удалить", "del"), b("✅ Оставить", "keep")],
                                                 [b("⏸ Бан 24 ч", "ban1"), b("⛔ Бан навсегда", "banx")]])


async def notify_moderators(bot, rid: int, kind: str, text: str, author: AppUser | None, reporter: AppUser,
                            hidden: bool) -> None:
    where = "сообщение в чате" if kind == "msg" else "пост в ленте"
    body = (f"🛡 <b>Жалоба на {where}</b>{' · скрыто автоматически (3 жалобы)' if hidden else ''}\n\n"
            f"Автор: {html.escape((author.name if author else '') or '—')} (id {author.id if author else '—'})\n"
            f"Пожаловался: {html.escape(reporter.name or '—')}\n\n«{html.escape(text[:800])}»")
    for admin in config.ADMIN_IDS:  # уходит в группу-инбокс, тема «Модерация» (utils.inbox)
        try:
            await bot.send_message(admin, body, reply_markup=mod_kb(rid))
        except Exception as e:  # noqa: BLE001
            log.warning("Модерация: не отправлено %s: %s", admin, e)


async def moderate(rid: int, action: str) -> str:
    async with get_session() as session:
        r = await session.get(ContentReport, rid)
        if not r:
            return "Жалоба не найдена."
        Model = _model(r.kind)
        obj = await session.get(Model, r.target_id) if Model else None
        reports = list((await session.execute(select(ContentReport).where(
            ContentReport.kind == r.kind, ContentReport.target_id == r.target_id))).scalars())
        if action == "keep":
            if obj:
                obj.hidden = False  # удалённое самим автором так и остаётся удалённым
            res, msg = "kept", "Оставлено." + (" Автор сам удалил его раньше." if obj and obj.deleted else " Сообщение снова видно.")
        else:
            if obj:
                obj.hidden = True
            res, msg = "deleted", "Удалено."
            if action in ("ban1", "banx") and obj:
                u = await session.get(AppUser, obj.user_id)
                if u:
                    u.banned_until = _now() + timedelta(hours=24) if action == "ban1" else FOREVER
                res, msg = "banned", "Удалено, автор заблокирован " + ("на 24 часа." if action == "ban1" else "навсегда.")
        for x in reports:
            x.resolved = res
        await session.commit()
        return msg


@router.callback_query(F.data.startswith("cmod:"), F.from_user.id.in_(config.ADMIN_IDS))
async def cb_moderate(callback: CallbackQuery) -> None:
    _, action, rid = callback.data.split(":")
    msg = await moderate(int(rid), action)
    await callback.answer(msg, show_alert=True)
    try:
        await callback.message.edit_text(callback.message.html_text + f"\n\n<b>Решение:</b> {msg}")
    except Exception:  # noqa: BLE001
        pass


def install_routes(app: web.Application) -> None:
    app.router.add_post("/api/app/rules", rules)
    app.router.add_get("/api/app/rooms", rooms)
    app.router.add_get("/api/app/rooms/{slug}/messages", messages)
    app.router.add_post("/api/app/rooms/{slug}/messages", messages)
    app.router.add_get("/api/app/posts", posts)
    app.router.add_post("/api/app/posts", posts)
    app.router.add_post("/api/app/delete", delete_own)
    app.router.add_post("/api/app/report", report)
    app.router.add_post("/api/app/block", block)
