"""Личные сообщения в приложении podslushano: диалоги покупателя и продавца по объявлениям барахолки.

Написать можно автору объявления, поданного через приложение (у него есть аккаунт). Сообщения
доставляются сразу через живое соединение (utils.realtime); если продавца нет в приложении, а у него
есть Telegram — бот присылает короткое напоминание (не чаще раза в 10 минут на диалог).
Те же правила, что в чатах: вход, имя, принятые правила, без бана, фильтр мата и ссылок, лимиты.
Жалоба на диалог уходит модераторам (тема «Модерация») с последними сообщениями и кнопками бана.

GET  /api/app/dm                 — мои диалоги и общее число непрочитанных
POST /api/app/dm/start           — {listing_id} → {id} (создать или открыть диалог)
GET  /api/app/dm/{id}            — диалог и последние сообщения
POST /api/app/dm/{id}            — {text} → сообщение
POST /api/app/dm/{id}/read       — прочитано
POST /api/app/dm/{id}/report     — пожаловаться
"""
from __future__ import annotations

import html
import logging
from datetime import datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiohttp import web
from sqlalchemy import func, or_, select

import config
from database.db import get_session
from database.models import AppUser, DmConversation, DmMessage, Listing, UserBlock
from handlers import board
from utils import realtime
from utils.app_api import _user
from utils.community import FOREVER, _rate, can_write, check_text
from utils.site_api import _body, _err, _json

log = logging.getLogger(__name__)
router = Router()

DM_MAX = 1000
PAGE = 100
NUDGE_EVERY = timedelta(minutes=10)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _at(d: datetime) -> str:
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def _peer_id(cv: DmConversation, me: int) -> int:
    return cv.seller_id if cv.buyer_id == me else cv.buyer_id


def _my_read(cv: DmConversation, me: int) -> int:
    return cv.buyer_read if cv.buyer_id == me else cv.seller_read


def _their_read(cv: DmConversation, me: int) -> int:
    return cv.seller_read if cv.buyer_id == me else cv.buyer_read


def msg_json(m: DmMessage, me: int, their_read: int) -> dict:
    mine = m.sender_id == me
    return {"id": m.id, "text": m.text, "at": _at(m.created_at), "mine": mine, "read": mine and m.id <= their_read}


async def _listing_json(session, lid: int | None) -> dict | None:
    l = await session.get(Listing, lid) if lid else None
    if not l:
        return None
    photo = f"/api/app/market/{l.id}/photo" if l.photo_file_id and board._status(l) == "approved" else ""
    return {"id": l.id, "title": l.title, "price": l.price or "", "photo": photo}


async def _conv_json(session, cv: DmConversation, me: int, last: DmMessage | None = None, unread: int = 0) -> dict:
    peer = await session.get(AppUser, _peer_id(cv, me))
    return {
        "id": cv.id, "peer": {"id": _peer_id(cv, me), "name": (peer.name if peer else "") or "Участник"},
        "listing": await _listing_json(session, cv.listing_id), "unread": unread,
        "last": {"text": last.text, "at": _at(last.created_at), "mine": last.sender_id == me} if last else None,
    }


async def _blocked_between(session, a: int, b: int) -> bool:
    return bool(await session.scalar(select(UserBlock.id).where(or_(
        (UserBlock.user_id == a) & (UserBlock.blocked_id == b), (UserBlock.user_id == b) & (UserBlock.blocked_id == a)))))


async def _mine(session, request: web.Request, cid: int) -> tuple[AppUser | None, DmConversation | None]:
    me = await _user(request, session)
    cv = await session.get(DmConversation, cid) if me else None
    if cv and me.id not in (cv.buyer_id, cv.seller_id):
        cv = None
    return me, cv


# ---------------------------------------------------------------- список и диалог

async def conversations(request: web.Request) -> web.Response:
    async with get_session() as session:
        me = await _user(request, session)
        if not me:
            return _err(request, "Войдите заново.", 401)
        convs = list((await session.execute(select(DmConversation).where(
            or_(DmConversation.buyer_id == me.id, DmConversation.seller_id == me.id))
            .order_by(DmConversation.last_at.desc()).limit(100))).scalars())
        items, total = [], 0
        for cv in convs:
            last = (await session.execute(select(DmMessage).where(DmMessage.conv_id == cv.id)
                                          .order_by(DmMessage.id.desc()).limit(1))).scalar_one_or_none()
            if not last:
                continue  # пустые диалоги (открыли, но не написали) не показываем
            unread = await session.scalar(select(func.count()).select_from(DmMessage).where(
                DmMessage.conv_id == cv.id, DmMessage.sender_id != me.id, DmMessage.id > _my_read(cv, me.id))) or 0
            total += unread
            items.append(await _conv_json(session, cv, me.id, last, unread))
        await session.commit()
    return _json(request, {"ok": True, "items": items, "unread": total})


async def start(request: web.Request) -> web.Response:
    data = await _body(request)
    async with get_session() as session:
        me = await _user(request, session)
        denied = can_write(me)
        if denied:
            await session.commit()
            return _err(request, *denied)
        l = await session.get(Listing, int(data.get("listing_id") or 0))
        if not l or board._status(l) != "approved":
            return _err(request, "Объявление снято или ещё не опубликовано.", 404)
        if not l.app_user_id:
            return _err(request, "Автор этого объявления пока не в приложении — свяжитесь по контактам.", 409)
        if l.app_user_id == me.id:
            return _err(request, "Это ваше объявление.", 400)
        if await _blocked_between(session, me.id, l.app_user_id):
            return _err(request, "Переписка с этим пользователем недоступна.", 403)
        cv = (await session.execute(select(DmConversation).where(
            DmConversation.listing_id == l.id, DmConversation.buyer_id == me.id,
            DmConversation.seller_id == l.app_user_id))).scalar_one_or_none()
        if not cv:
            if _rate(f"dmstart:{me.id}", 15, 3600):
                return _err(request, "Слишком много новых диалогов. Попробуйте через час.", 429)
            cv = DmConversation(listing_id=l.id, buyer_id=me.id, seller_id=l.app_user_id)
            session.add(cv)
        await session.commit()
        return _json(request, {"ok": True, "id": cv.id})


async def dialog(request: web.Request) -> web.Response:
    cid = int(request.match_info["id"])
    async with get_session() as session:
        me, cv = await _mine(session, request, cid)
        if not me:
            return _err(request, "Войдите заново.", 401)
        if not cv:
            return _err(request, "Диалог не найден.", 404)
        if request.method == "POST":
            return await _send(request, session, me, cv)
        rows = list((await session.execute(select(DmMessage).where(DmMessage.conv_id == cv.id)
                                           .order_by(DmMessage.id.desc()).limit(PAGE))).scalars())
        rows.reverse()
        unread = sum(1 for m in rows if m.sender_id != me.id and m.id > _my_read(cv, me.id))
        conv = await _conv_json(session, cv, me.id, rows[-1] if rows else None, unread)
        their = _their_read(cv, me.id)
        await session.commit()
    return _json(request, {"ok": True, "conversation": conv, "messages": [msg_json(m, me.id, their) for m in rows]})


async def _send(request: web.Request, session, me: AppUser, cv: DmConversation) -> web.Response:
    data = await _body(request)
    text = str(data.get("text") or "").strip()
    denied = can_write(me)
    if denied:
        return _err(request, *denied)
    reason = check_text(me, text, DM_MAX)
    if reason:
        return _err(request, reason)
    peer = _peer_id(cv, me.id)
    if await _blocked_between(session, me.id, peer):
        return _err(request, "Переписка с этим пользователем недоступна.", 403)
    if _rate(f"dm3:{me.id}", 3, 3) or _rate(f"dm60:{me.id}", 30, 60):
        return _err(request, "Не так быстро: подождите немного.", 429)
    m = DmMessage(conv_id=cv.id, sender_id=me.id, text=text)
    session.add(m)
    await session.flush()
    cv.last_at = m.created_at or _now()
    if cv.buyer_id == me.id:
        cv.buyer_read = m.id
    else:
        cv.seller_read = m.id
    nudge = not realtime.online(peer) and (not cv.nudged_at or _now() - cv.nudged_at > NUDGE_EVERY)
    if nudge:
        cv.nudged_at = _now()
    peer_user = await session.get(AppUser, peer)
    listing = await session.get(Listing, cv.listing_id) if cv.listing_id else None
    await session.commit()
    mine = msg_json(m, me.id, _their_read(cv, me.id))
    theirs = mine | {"mine": False, "read": False}
    await realtime.push_user(peer, {"type": "dm", "conv": cv.id, "message": theirs})
    await realtime.push_user(me.id, {"type": "dm", "conv": cv.id, "message": mine})  # другие устройства автора
    if nudge and peer_user and peer_user.tg_id:
        await _nudge(request.app.get("bot"), peer_user.tg_id, me.name or "Участник", listing, text, cv.id)
    return _json(request, {"ok": True, "message": mine})


async def _nudge(bot, tg_id: int, who: str, listing: Listing | None, text: str, cid: int) -> None:
    """Напоминание в Telegram, если собеседника нет в приложении."""
    if not bot:
        return
    about = f" по объявлению «{html.escape(listing.title)}»" if listing else ""
    url = f"{(config.WEBHOOK_BASE_URL or '').rstrip('/')}/app/dm/{cid}"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Ответить в приложении", url=url)]]) if url.startswith("https://") else None
    try:
        await bot.send_message(tg_id, f"💬 <b>{html.escape(who)}</b> написал(а) вам{about}:\n\n«{html.escape(text[:300])}»", reply_markup=kb)
    except Exception as e:  # noqa: BLE001
        log.info("ЛС: напоминание не отправлено %s: %s", tg_id, e)


async def read(request: web.Request) -> web.Response:
    cid = int(request.match_info["id"])
    async with get_session() as session:
        me, cv = await _mine(session, request, cid)
        if not cv:
            return _err(request, "Диалог не найден.", 404)
        top = await session.scalar(select(func.max(DmMessage.id)).where(DmMessage.conv_id == cv.id)) or 0
        if cv.buyer_id == me.id:
            cv.buyer_read = max(cv.buyer_read, top)
        else:
            cv.seller_read = max(cv.seller_read, top)
        peer = _peer_id(cv, me.id)
        await session.commit()
    await realtime.push_user(peer, {"type": "read", "conv": cid, "upto": top})
    return _json(request, {"ok": True})


async def typing(uid: int, cid: int) -> None:
    async with get_session() as session:
        cv = await session.get(DmConversation, cid)
    if cv and uid in (cv.buyer_id, cv.seller_id):
        await realtime.push_user(_peer_id(cv, uid), {"type": "typing", "conv": cid})

realtime.typing_handler = typing


# ---------------------------------------------------------------- жалобы и модерация

def ban_kb(uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="⏸ Бан 24 ч", callback_data=f"dmban:1:{uid}"),
        InlineKeyboardButton(text="⛔ Бан навсегда", callback_data=f"dmban:x:{uid}"),
    ], [InlineKeyboardButton(text="✅ Нарушений нет", callback_data=f"dmban:0:{uid}")]])


async def report(request: web.Request) -> web.Response:
    cid = int(request.match_info["id"])
    async with get_session() as session:
        me, cv = await _mine(session, request, cid)
        if not cv:
            return _err(request, "Диалог не найден.", 404)
        if _rate(f"dmrep:{me.id}:{cid}", 1, 86400):
            return _json(request, {"ok": True})
        peer = await session.get(AppUser, _peer_id(cv, me.id))
        rows = list((await session.execute(select(DmMessage).where(DmMessage.conv_id == cv.id)
                                           .order_by(DmMessage.id.desc()).limit(10))).scalars())
        await session.commit()
    rows.reverse()
    names = {me.id: me.name or "—", peer.id if peer else 0: (peer.name if peer else "") or "—"}
    lines = "\n".join(f"<b>{html.escape(names.get(m.sender_id, '—'))}:</b> {html.escape(m.text[:200])}" for m in rows)
    body = (f"🛡 <b>Жалоба на личную переписку</b> · диалог #{cid}\n"
            f"Пожаловался: {html.escape(me.name or '—')} (id {me.id})\n"
            f"На кого: {html.escape(names.get(peer.id if peer else 0, '—'))} (id {peer.id if peer else '—'})\n\n{lines or '—'}")
    bot = request.app.get("bot")
    if bot and peer:
        for admin in config.ADMIN_IDS:  # уходит в группу-инбокс, тема «Модерация» (utils.inbox)
            try:
                await bot.send_message(admin, body[:4000], reply_markup=ban_kb(peer.id))
            except Exception as e:  # noqa: BLE001
                log.warning("ЛС: жалоба не отправлена %s: %s", admin, e)
    return _json(request, {"ok": True})


@router.callback_query(F.data.startswith("dmban:"), F.from_user.id.in_(config.ADMIN_IDS))
async def cb_ban(callback: CallbackQuery) -> None:
    _, kind, uid = callback.data.split(":")
    async with get_session() as session:
        u = await session.get(AppUser, int(uid))
        if u and kind in ("1", "x"):
            u.banned_until = _now() + timedelta(hours=24) if kind == "1" else FOREVER
        await session.commit()
    msg = {"1": "Заблокирован на 24 часа.", "x": "Заблокирован навсегда.", "0": "Отмечено: нарушений нет."}.get(kind, "Готово.")
    await callback.answer(msg, show_alert=True)
    try:
        await callback.message.edit_text(callback.message.html_text + f"\n\n<b>Решение:</b> {msg}")
    except Exception:  # noqa: BLE001
        pass


def install_routes(app: web.Application) -> None:
    app.router.add_get("/api/app/dm", conversations)
    app.router.add_post("/api/app/dm/start", start)
    app.router.add_get(r"/api/app/dm/{id:\d+}", dialog)
    app.router.add_post(r"/api/app/dm/{id:\d+}", dialog)
    app.router.add_post(r"/api/app/dm/{id:\d+}/read", read)
    app.router.add_post(r"/api/app/dm/{id:\d+}/report", report)
