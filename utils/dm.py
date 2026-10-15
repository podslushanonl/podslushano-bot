"""Личные сообщения в приложении podslushano.

Два вида диалогов:
- просто переписка — только между друзьями: перед созданием диалога и перед каждым сообщением
  сервер проверяет дружбу (Friendship со статусом accepted); нет дружбы — 403;
- по объявлению барахолки — продавцу может написать любой пользователь, дружба не нужна
  (автор подавал объявление через приложение, у него есть аккаунт).
Блокировка закрывает оба вида. Сообщения
доставляются сразу через живое соединение (utils.realtime); если продавца нет в приложении, а у него
есть Telegram — бот присылает короткое напоминание (не чаще раза в 10 минут на диалог).
Те же правила, что в чатах: вход, имя, принятые правила, без бана, фильтр мата и ссылок, лимиты.
Жалоба на диалог уходит модераторам (тема «Модерация») с последними сообщениями и кнопками бана.

GET  /api/app/dm                 — мои диалоги и общее число непрочитанных
POST /api/app/dm/start           — {user_id} или {item_id} (объявление барахолки) → {id} (создать или открыть диалог)
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
from database.models import AppUser, DmConversation, DmMessage, Listing, MarketItem
from utils import realtime, social
from utils.app_api import _user
from utils.community import FOREVER, _rate, can_write, check_text
from utils.site_api import _body, _err, _json

log = logging.getLogger(__name__)
router = Router()

DM_MAX = 1000
PAGE = 100
NUDGE_EVERY = timedelta(minutes=10)


def _int(v) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


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


async def _listing_json(session, cv: DmConversation) -> dict | None:
    if cv.item_id:   # объявление барахолки приложения
        it = await session.get(MarketItem, cv.item_id)
        if not it:
            return None
        from utils.app_market import price_label
        photo = f"/api/app/market/{it.id}/photo/0" if it.photo_count and it.status == "active" else ""
        return {"id": it.id, "title": it.title, "price": price_label(it.price), "photo": photo}
    # Старые диалоги по объявлениям из бота: только название (карточки в приложении у них нет)
    l = await session.get(Listing, cv.listing_id) if cv.listing_id else None
    return {"id": 0, "title": l.title, "price": l.price or "", "photo": ""} if l else None


async def _may_write(session, cv: DmConversation, me: int) -> bool:
    """По объявлению — всем (кроме блокировки), обычная переписка — только друзьям."""
    peer = _peer_id(cv, me)
    if await social.blocked_between(session, me, peer):
        return False
    return bool(cv.listing_id or cv.item_id) or await social.are_friends(session, me, peer)


async def _conv_json(session, cv: DmConversation, me: int, last: DmMessage | None = None, unread: int = 0,
                     with_access: bool = False) -> dict:
    peer = await session.get(AppUser, _peer_id(cv, me))
    extra = {"can_write": await _may_write(session, cv, me)} if with_access else {}
    return extra | {
        "id": cv.id, "peer": {"id": _peer_id(cv, me), "name": (peer.name if peer else "") or "Участник",
                 "avatar": f"/api/app/user/{peer.id}/avatar?v={peer.avatar_v}" if peer and peer.avatar_v else ""},
        "listing": await _listing_json(session, cv), "unread": unread,
        "last": {"text": last.text, "at": _at(last.created_at), "mine": last.sender_id == me} if last else None,
    }


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
        item_id, peer = None, 0
        if data.get("item_id"):
            it = await session.get(MarketItem, _int(data.get("item_id")))
            if not it or it.status != "active":
                return _err(request, "Объявление снято с публикации.", 404)
            if it.user_id == me.id:
                return _err(request, "Это ваше объявление.", 400)
            item_id, peer = it.id, it.user_id
        else:
            peer = _int(data.get("user_id"))
            if peer == me.id:
                return _err(request, "Это вы.", 400)
            if not peer or not await session.get(AppUser, peer):
                return _err(request, "Пользователь не найден.", 404)
        if await social.blocked_between(session, me.id, peer):
            return _err(request, "Переписка с этим пользователем недоступна.", 403)
        # Вопрос по объявлению — любому продавцу; обычная переписка — только друзьям
        if not item_id and not await social.are_friends(session, me.id, peer):
            return _err(request, social.NOT_FRIENDS, 403)
        if item_id:
            cv = (await session.execute(select(DmConversation).where(
                DmConversation.item_id == item_id, DmConversation.buyer_id == me.id,
                DmConversation.seller_id == peer))).scalar_one_or_none()
        else:  # личный диалог без объявления — один на пару, кто бы его ни начал
            cv = (await session.execute(select(DmConversation).where(
                DmConversation.listing_id.is_(None), DmConversation.item_id.is_(None), or_(
                    (DmConversation.buyer_id == me.id) & (DmConversation.seller_id == peer),
                    (DmConversation.buyer_id == peer) & (DmConversation.seller_id == me.id)))
                .order_by(DmConversation.id).limit(1))).scalar_one_or_none()
        if not cv:
            if _rate(f"dmstart:{me.id}", 15, 3600):
                return _err(request, "Слишком много новых диалогов. Попробуйте через час.", 429)
            cv = DmConversation(item_id=item_id, buyer_id=me.id, seller_id=peer)
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
        conv = await _conv_json(session, cv, me.id, rows[-1] if rows else None, unread, with_access=True)
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
    if await social.blocked_between(session, me.id, peer):
        return _err(request, "Переписка с этим пользователем недоступна.", 403)
    if not cv.listing_id and not cv.item_id and not await social.are_friends(session, me.id, peer):
        return _err(request, social.NOT_FRIENDS, 403)
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
    listing = (await session.get(MarketItem, cv.item_id) if cv.item_id
               else await session.get(Listing, cv.listing_id) if cv.listing_id else None)
    await session.commit()
    mine = msg_json(m, me.id, _their_read(cv, me.id))
    theirs = mine | {"mine": False, "read": False}
    await realtime.push_user(peer, {"type": "dm", "conv": cv.id, "message": theirs})
    await realtime.push_user(me.id, {"type": "dm", "conv": cv.id, "message": mine})  # другие устройства автора
    if nudge and peer_user and peer_user.tg_id:
        await _nudge(request.app.get("bot"), peer_user.tg_id, me.name or "Участник", listing, text, cv.id)
    return _json(request, {"ok": True, "message": mine})


async def _nudge(bot, tg_id: int, who: str, listing: Listing | MarketItem | None, text: str, cid: int) -> None:
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
