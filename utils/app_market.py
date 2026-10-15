"""Барахолка приложения podslushano — независимая от Telegram-бота.

Объявления и фото лежат в PostgreSQL (market_items, market_photos), всё работает через этот API.
Публикация сразу, на 30 дней; три жалобы от разных людей скрывают объявление до решения модератора.
Связь с продавцом — личным сообщением в приложении (POST /api/app/dm/start {item_id}).

GET  /api/app/market?cat=&city=&q=&offset=   — лента (по 30), категории и города
GET  /api/app/market/my                       — мои объявления
GET  /api/app/market/{id}                     — карточка
GET  /api/app/market/{id}/photo/{n}           — фото n (JPEG)
POST /api/app/market                          — подать или изменить (id):
     {category, title, description, price, city, photos: ["keep:<n>" | "data:image/..."]}
POST /api/app/market/{id}/close               — снять с публикации
POST /api/app/market/{id}/report              — {reason} пожаловаться
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from aiohttp import web
from sqlalchemy import delete, func, or_, select

from database.db import get_session
from database.models import AppUser, ContentReport, MarketItem, MarketPhoto
from utils.app_api import _user
from utils.community import _rate, can_write, check_text
from utils.market import _read_json, prepare_photo
from utils.site_api import _err, _json

PAGE = 30
MAX_PHOTOS = 5
MAX_ACTIVE = 10
DAYS = 30
HIDE_AFTER = 3   # жалоб от разных людей
MAX_PRICE = 1_000_000

# ключ, название, что внутри
CATEGORIES = [
    ("wardrobe", "Гардероб", "Одежда, обувь, аксессуары"),
    ("home", "Дом и Уют", "Мебель, декор, растения, посуда"),
    ("tech", "Техно", "Гаджеты, Apple, приставки, электроника"),
    ("sport", "Спорт и Байки", "Велосипеды, самокаты, экипировка"),
    ("tickets", "Билеты", "Концерты, фестивали, события"),
    ("housing", "Жилье", "Аренда комнат, квартир, субаренда"),
    ("services", "Услуги", "Локальные мастера, хелперы, репетиторы"),
    ("free", "Даром", "Вещи за самовывоз, бесплатно"),
]
CATEGORY_LABELS = {k: t for k, t, _ in CATEGORIES}
FREE = "free"
CITIES = ["Amsterdam", "Rotterdam", "Den Haag", "Eindhoven"]
STATUS_LABELS = {"active": "Опубликовано", "closed": "Снято", "hidden": "Скрыто после жалоб", "expired": "Срок истёк"}


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _at(d: datetime | None) -> str:
    return d.strftime("%Y-%m-%dT%H:%M:%SZ") if d else ""


def price_label(price: int | None) -> str:
    if price is None:
        return "Договорная"
    if price == 0:
        return "Бесплатно"
    return "€" + f"{price:,}".replace(",", " ")


def _status(it: MarketItem) -> str:
    if it.status == "active" and it.expires_at and it.expires_at <= _now():
        return "expired"
    return it.status


def _live():
    return (MarketItem.status == "active") & or_(MarketItem.expires_at.is_(None), MarketItem.expires_at > _now())


def item_json(it: MarketItem, me: AppUser | None, seller: AppUser | None = None, full: bool = False) -> dict:
    photos = [f"/api/app/market/{it.id}/photo/{i}" for i in range(it.photo_count or 0)]
    st = _status(it)
    d = {"id": it.id, "cat": it.category, "cat_title": CATEGORY_LABELS.get(it.category, "Барахолка"),
         "title": it.title, "price": price_label(it.price), "price_value": it.price, "city": it.city,
         "photo": photos[0] if photos else "", "at": _at(it.created_at), "mine": bool(me and me.id == it.user_id),
         "status": st, "status_title": STATUS_LABELS.get(st, st)}
    if full:
        d |= {"description": it.description or "", "photos": photos, "until": _at(it.expires_at)[:10],
              "chat": not d["mine"], "seller_id": it.user_id}
        if seller:
            d["seller"] = {"id": seller.id, "name": seller.name or "Участник", "city": seller.city or "",
                           "avatar": f"/api/app/user/{seller.id}/avatar?v={seller.avatar_v}" if seller.avatar_v else "",
                           "since": _at(seller.created_at)[:10]}
    return d


def _meta() -> dict:
    return {"categories": [{"key": k, "title": t, "hint": h, "intents": []} for k, t, h in CATEGORIES], "cities": CITIES}


# ---------------------------------------------------------------- просмотр

async def listings(request: web.Request) -> web.Response:
    cat = request.query.get("cat", "")
    city = " ".join(request.query.get("city", "").split())[:80]
    text = request.query.get("q", "").strip()[:60]
    try:
        offset = max(0, int(request.query.get("offset", "0")))
    except ValueError:
        offset = 0
    q = select(MarketItem).where(_live())
    if cat in CATEGORY_LABELS:
        q = q.where(MarketItem.category == cat)
    if city:
        q = q.where(MarketItem.city == city)
    if text:
        like = f"%{text}%"
        q = q.where(or_(MarketItem.title.ilike(like), MarketItem.description.ilike(like)))
    q = q.order_by(MarketItem.created_at.desc(), MarketItem.id.desc())
    async with get_session() as session:
        me = await _user(request, session)
        rows = list((await session.execute(q.offset(offset).limit(PAGE + 1))).scalars())
        await session.commit()
    return _json(request, {"ok": True, "items": [item_json(it, me) for it in rows[:PAGE]], "more": len(rows) > PAGE} | _meta())


async def my_listings(request: web.Request) -> web.Response:
    async with get_session() as session:
        me = await _user(request, session)
        if not me:
            return _err(request, "Войдите заново.", 401)
        rows = list((await session.execute(select(MarketItem).where(MarketItem.user_id == me.id)
                                           .order_by(MarketItem.id.desc()).limit(50))).scalars())
        await session.commit()
    return _json(request, {"ok": True, "items": [item_json(it, me) for it in rows], "max": MAX_ACTIVE})


async def listing(request: web.Request) -> web.Response:
    iid = int(request.match_info["id"])
    async with get_session() as session:
        me = await _user(request, session)
        it = await session.get(MarketItem, iid)
        seller = await session.get(AppUser, it.user_id) if it else None
        await session.commit()
    mine = bool(it and me and it.user_id == me.id)
    if not it or (not mine and _status(it) != "active"):
        return _err(request, "Объявление снято с публикации.", 404)
    return _json(request, {"ok": True, "item": item_json(it, me, seller, full=True)})


async def photo(request: web.Request) -> web.Response:
    iid, idx = int(request.match_info["id"]), int(request.match_info["n"])
    async with get_session() as session:
        it = await session.get(MarketItem, iid)
        data = await session.scalar(select(MarketPhoto.data).where(MarketPhoto.item_id == iid, MarketPhoto.idx == idx)) if it else None
    if not data:
        raise web.HTTPNotFound()
    # Фото снятого объявления видно только по прямой ссылке автору (кэш браузера не держим)
    public = _status(it) == "active"
    return web.Response(body=data, content_type="image/jpeg",
                        headers={"Cache-Control": "public, max-age=604800, immutable" if public else "private, no-store"})


# ---------------------------------------------------------------- подача

def _clean(s: str, limit: int) -> str:
    return " ".join(str(s or "").split())[:limit]


def _parse_price(raw) -> tuple[bool, int | None]:
    """(ok, цена в евро | None — договорная)."""
    if raw is None or raw == "":
        return True, None
    digits = re.sub(r"[^\d]", "", str(raw))
    if not digits or len(digits) > 7:
        return False, None
    value = int(digits)
    return value <= MAX_PRICE, value


def _validate(data: dict, u: AppUser) -> tuple[dict | None, str | None]:
    cat = str(data.get("category") or "")
    if cat not in CATEGORY_LABELS:
        return None, "Выберите категорию."
    title = _clean(data.get("title"), 100)
    desc = re.sub(r"\n{3,}", "\n\n", str(data.get("description") or "").replace("\r", "")).strip()[:2000]
    city = _clean(data.get("city"), 80)
    if len(title) < 3:
        return None, "Название: от 3 до 100 символов."
    if len(desc) < 10:
        return None, "Опишите товар: хотя бы пару слов о состоянии."
    ok, price = _parse_price(data.get("price")) if cat != FREE else (True, 0)   # «Даром» — всегда бесплатно
    if not ok:
        return None, "Проверьте цену: целое число евро."
    if not city:
        return None, "Выберите город."
    for text in (title, desc):
        reason = check_text(u, text, 2000)
        if reason:
            return None, reason
    return {"category": cat, "title": title, "description": desc, "price": price, "city": city}, None


async def submit(request: web.Request) -> web.Response:
    data = await _read_json(request)
    raw = [str(x) for x in data.get("photos") or [] if x][:MAX_PHOTOS] if isinstance(data.get("photos"), list) else []
    async with get_session() as session:
        me = await _user(request, session)
        denied = can_write(me)
        if denied:
            await session.commit()
            return _err(request, *denied)
        fields, error = _validate(data, me)
        if error:
            return _err(request, error)
        it = None
        if data.get("id"):
            try:
                it = await session.get(MarketItem, int(data["id"]))
            except (TypeError, ValueError):
                it = None
            if not it or it.user_id != me.id:
                return _err(request, "Объявление не найдено.", 404)
            if it.status == "hidden":
                return _err(request, "Объявление скрыто после жалоб — дождитесь решения модератора.", 409)
        else:
            active = await session.scalar(select(func.count()).select_from(MarketItem).where(MarketItem.user_id == me.id, _live())) or 0
            if active >= MAX_ACTIVE:
                return _err(request, f"Можно держать до {MAX_ACTIVE} объявлений одновременно. Снимите старые.", 409)
            if _rate(f"mk60:{me.id}", 1, 60) or _rate(f"mkday:{me.id}", 10, 86400):
                return _err(request, "Можно подать до 10 объявлений в день и не чаще раза в минуту.", 429)
        # Фото по порядку: keep:<n> — уже загруженное фото этого объявления, иначе новая картинка
        old = {}
        if it:
            old = dict((await session.execute(select(MarketPhoto.idx, MarketPhoto.data).where(MarketPhoto.item_id == it.id))).all())
        jpegs: list[bytes] = []
        for r in raw:
            if r.startswith("keep:"):
                try:
                    j = old.get(int(r[5:]))
                except ValueError:
                    j = None
            else:
                j = prepare_photo(r)
            if not j:
                return _err(request, "Не получилось прочитать одно из фото. Попробуйте другое.")
            jpegs.append(j)
        if it:
            for k, v in fields.items():
                setattr(it, k, v)
            if it.status != "active":   # исправленное снятое объявление публикуется снова
                it.status = "active"
            it.expires_at = _now() + timedelta(days=DAYS)
            await session.execute(delete(MarketPhoto).where(MarketPhoto.item_id == it.id))
        else:
            it = MarketItem(user_id=me.id, expires_at=_now() + timedelta(days=DAYS), **fields)
            session.add(it)
        it.photo_count = len(jpegs)
        await session.flush()
        for i, j in enumerate(jpegs):
            session.add(MarketPhoto(item_id=it.id, idx=i, data=j))
        await session.commit()
        return _json(request, {"ok": True, "id": it.id, "status": it.status})


async def close(request: web.Request) -> web.Response:
    iid = int(request.match_info["id"])
    async with get_session() as session:
        me = await _user(request, session)
        it = await session.get(MarketItem, iid)
        if not me or not it or it.user_id != me.id:
            return _err(request, "Объявление не найдено.", 404)
        if it.status == "active":
            it.status = "closed"
        await session.commit()
    return _json(request, {"ok": True})


async def report(request: web.Request) -> web.Response:
    iid = int(request.match_info["id"])
    data = await _read_json(request)
    async with get_session() as session:
        me = await _user(request, session)
        if not me:
            return _err(request, "Войдите, чтобы пожаловаться.", 401)
        it = await session.get(MarketItem, iid)
        if not it or it.user_id == me.id:
            return _err(request, "Объявление не найдено.", 404)
        if not await session.scalar(select(ContentReport.id).where(
                ContentReport.kind == "item", ContentReport.target_id == iid, ContentReport.reporter_id == me.id)):
            session.add(ContentReport(kind="item", target_id=iid, reporter_id=me.id, reason=str(data.get("reason") or "")[:200]))
            await session.flush()
            n = await session.scalar(select(func.count(func.distinct(ContentReport.reporter_id))).where(
                ContentReport.kind == "item", ContentReport.target_id == iid, ContentReport.resolved == "")) or 0
            if n >= HIDE_AFTER and it.status == "active":
                it.status = "hidden"
        await session.commit()
    return _json(request, {"ok": True})


def install_routes(app: web.Application) -> None:
    app.router.add_get("/api/app/market", listings)
    app.router.add_post("/api/app/market", submit)
    app.router.add_get("/api/app/market/my", my_listings)
    app.router.add_get(r"/api/app/market/{id:\d+}", listing)
    app.router.add_get(r"/api/app/market/{id:\d+}/photo/{n:\d}", photo)
    app.router.add_post(r"/api/app/market/{id:\d+}/close", close)
    app.router.add_post(r"/api/app/market/{id:\d+}/report", report)
