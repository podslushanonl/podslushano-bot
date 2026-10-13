"""Барахолка в приложении podslushano — та же доска объявлений, что и в боте (таблица listings).

Объявления из бота и из приложения видны в обоих местах. Новое объявление уходит на проверку
в группу-инбокс (тема «Объявления») с теми же кнопками «Опубликовать» / «Отклонить», что и у бота
(handlers/board.py). Жильё — платное размещение, как в боте: после оплаты — на проверку.

Фото хранится в Telegram (file_id, как у объявлений из бота): приложение присылает картинку,
сервер уменьшает её, убирает метаданные (в т. ч. геопозицию) и загружает в Telegram.
Показ — через GET /api/app/market/{id}/photo с кэшем в памяти.

GET  /api/app/market?cat=&city=&q=&offset=   — опубликованные объявления
GET  /api/app/market/my                       — мои объявления (любой статус)
GET  /api/app/market/{id}                     — карточка
GET  /api/app/market/{id}/photo               — фото
POST /api/app/market                          — подать (или исправить: id)
POST /api/app/market/{id}/close               — снять с публикации
POST /api/app/market/{id}/report              — пожаловаться
"""
from __future__ import annotations

import base64
import binascii
import html
import io
import json
import logging
import re
from collections import OrderedDict
from datetime import datetime, timedelta

from aiogram.types import BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup
from aiohttp import web
from sqlalchemy import func, or_, select

import config
from database.db import get_session
from database.models import AppUser, Listing, Meta
from handlers import board
from utils.app_api import _user
from utils.community import _rate, can_write, check_text
from utils.contact_links import parse_contact_links
from utils.payments import create_payment
from utils.site_api import _err, _json, make_token, read_token

log = logging.getLogger(__name__)

PAGE = 30
PHOTO_MAX_BYTES = 8 * 1024 * 1024
PHOTO_SIDE = 1600
_LABELS = {"instagram": "Instagram", "telegram": "Telegram", "whatsapp": "WhatsApp",
           "phone": "Телефон", "email": "Почта", "website": "Сайт"}
STATUS_LABELS = {
    "awaiting_payment": "Ждёт оплаты", "pending": "На проверке", "approved": "Опубликовано",
    "rejected": "Отклонено", "closed": "Снято", "expired": "Срок истёк", "archived": "В архиве",
}
_photo_cache: OrderedDict[tuple[int, int], tuple[str, bytes]] = OrderedDict()
MAX_PHOTOS = 8


def all_photos(l: Listing) -> list[str]:
    """file_id всех фото: обложка первой."""
    try:
        ids = [x for x in json.loads(l.photos or "[]") if isinstance(x, str) and x]
    except ValueError:
        ids = []
    if l.photo_file_id and (not ids or ids[0] != l.photo_file_id):
        ids = [l.photo_file_id] + [x for x in ids if x != l.photo_file_id]
    return ids[:MAX_PHOTOS]
_PHOTO_CACHE_SIZE = 150


def _now() -> datetime:
    return datetime.utcnow()


def _cat_label(key: str) -> str:
    """Название категории без эмодзи: в приложении у категорий свои иконки."""
    return board.CATEGORY_LABELS.get(key, "📦 Разное").split(" ", 1)[-1]


def categories() -> list[dict]:
    return [{"key": k, "title": _cat_label(k),
             "intents": [{"key": i, "title": t} for i, t in board.INTENTS.get(k, [])]}
            for k, _ in board.CATEGORIES]


def _active():
    return (Listing.status == "approved") & or_(Listing.expires_at.is_(None), Listing.expires_at > _now())


def item_json(l: Listing, me: AppUser | None = None, full: bool = False) -> dict:
    status = board._status(l, _now())
    mine = bool(me and l.app_user_id == me.id)
    # фото до публикации видит только автор — по подписанной ссылке
    grant = "" if status == "approved" else "k=" + make_token({"k": "lphoto", "l": l.id}, 6 * 3600)
    urls = [f"/api/app/market/{l.id}/photo" + (f"?i={i}" if i else "") for i in range(len(all_photos(l)))]
    if grant:
        urls = [u + ("&" if "?" in u else "?") + grant for u in urls]
    photo = urls[0] if urls else ""
    d = {
        "id": l.id, "cat": l.category, "cat_title": _cat_label(l.category),
        "intent": l.intent or "", "intent_title": board.INTENT_LABELS.get((l.category, l.intent), ""),
        "title": l.title, "price": l.price or "",
        "city": "Вся страна" if l.is_nationwide else (l.city or ""),
        "photo": photo,
        "at": (l.bumped_at or l.created_at or _now()).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "mine": mine,
        # Автору можно написать прямо в приложении, если он сам подавал объявление через приложение
        "chat": bool(l.app_user_id) and not mine,
    }
    if full:
        d |= {
            "description": l.description or "",
            "contacts": [{"type": x["type"], "title": _LABELS.get(x["type"], x["label"]), "url": x["url"]}
                         for x in parse_contact_links(l.contact)],
            "until": l.expires_at.strftime("%Y-%m-%d") if l.expires_at and status == "approved" else "",
            "photos": urls,
        }
    if d["mine"]:
        d |= {"status": status, "status_title": STATUS_LABELS.get(status, status)}
        if full:
            d["form"] = {"city": l.city or "", "nationwide": bool(l.is_nationwide),
                         "contacts": {k[len("l_contact_"):]: v for k, v in board._contact_data(l.contact).items()}}
    return d


# ---------------------------------------------------------------- просмотр

async def listings(request: web.Request) -> web.Response:
    cat = request.query.get("cat", "")
    city = request.query.get("city", "").strip()[:60]
    q_text = request.query.get("q", "").strip()[:60]
    try:
        offset = max(0, int(request.query.get("offset", "0")))
    except ValueError:
        offset = 0
    q = select(Listing).where(_active())
    if cat in board.CATEGORY_LABELS:
        q = q.where(Listing.category == cat)
    if city:
        q = q.where(or_(Listing.is_nationwide.is_(True), Listing.city.ilike(f"%{city}%")))
    if q_text:
        like = f"%{q_text}%"
        q = q.where(or_(Listing.title.ilike(like), Listing.description.ilike(like)))
    q = q.order_by(func.coalesce(Listing.bumped_at, Listing.created_at).desc(), Listing.id.desc())
    async with get_session() as session:
        me = await _user(request, session)
        rows = list((await session.execute(q.offset(offset).limit(PAGE + 1))).scalars())
        await session.commit()
    return _json(request, {"ok": True, "items": [item_json(l, me) for l in rows[:PAGE]],
                           "more": len(rows) > PAGE, "categories": categories(),
                           "cities": board.POPULAR_CITIES})


async def my_listings(request: web.Request) -> web.Response:
    async with get_session() as session:
        me = await _user(request, session)
        if not me:
            return _err(request, "Войдите заново.", 401)
        rows = list((await session.execute(select(Listing).where(Listing.app_user_id == me.id)
                                           .order_by(Listing.id.desc()).limit(50))).scalars())
        await session.commit()
    return _json(request, {"ok": True, "items": [item_json(l, me) for l in rows], "max": config.BOARD_MAX_ACTIVE})


async def listing(request: web.Request) -> web.Response:
    lid = int(request.match_info["id"])
    async with get_session() as session:
        me = await _user(request, session)
        l = await session.get(Listing, lid)
        await session.commit()
    mine = bool(l and me and l.app_user_id == me.id)
    if not l or (not mine and board._status(l, _now()) != "approved"):
        return _err(request, "Объявление снято или ещё не опубликовано.", 404)
    return _json(request, {"ok": True, "item": item_json(l, me, full=True)})


async def photo(request: web.Request) -> web.Response:
    lid = int(request.match_info["id"])
    async with get_session() as session:
        l = await session.get(Listing, lid)
    ids = all_photos(l) if l else []
    try:
        idx = int(request.query.get("i", "0"))
    except ValueError:
        idx = -1
    if not 0 <= idx < len(ids):
        raise web.HTTPNotFound()
    file_id = ids[idx]
    if board._status(l, _now()) != "approved":
        grant = read_token(request.query.get("k", ""), "lphoto")
        if not grant or grant.get("l") != lid:
            raise web.HTTPNotFound()
    cached = _photo_cache.get((lid, idx))
    if cached and cached[0] == file_id:
        _photo_cache.move_to_end((lid, idx))
        data = cached[1]
    else:
        bot = request.app.get("bot")
        if not bot:
            raise web.HTTPNotFound()
        try:
            f = await bot.get_file(file_id)
            buf = io.BytesIO()
            await bot.download_file(f.file_path, buf)
            data = buf.getvalue()
        except Exception as e:  # noqa: BLE001
            log.warning("Барахолка: фото %s не скачано: %s", lid, e)
            raise web.HTTPNotFound()
        _photo_cache[(lid, idx)] = (file_id, data)
        while len(_photo_cache) > _PHOTO_CACHE_SIZE:
            _photo_cache.popitem(last=False)
    public = board._status(l, _now()) == "approved"
    return web.Response(body=data, content_type="image/jpeg",
                        headers={"Cache-Control": "public, max-age=86400" if public else "private, no-store"})


# ---------------------------------------------------------------- подача

def prepare_photo(raw: str) -> bytes | None:
    """base64 → JPEG не больше PHOTO_SIDE по длинной стороне, без EXIF. None — не картинка."""
    from PIL import Image, ImageOps
    if "," in raw[:100]:
        raw = raw.split(",", 1)[1]  # data:image/jpeg;base64,...
    try:
        data = base64.b64decode(raw, validate=False)
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img).convert("RGB")
    except (binascii.Error, ValueError, OSError):
        return None
    img.thumbnail((PHOTO_SIDE, PHOTO_SIDE))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=85, optimize=True)
    return out.getvalue()


async def _upload_photo(bot, jpeg: bytes, lid: int) -> str | None:
    """Загружает фото в Telegram и сразу убирает служебное сообщение. Возвращает file_id."""
    if not config.ADMIN_IDS:
        return None
    try:
        msg = await bot.send_photo(config.ADMIN_IDS[0], BufferedInputFile(jpeg, f"listing-{lid}.jpg"),
                                   caption=f"Фото к объявлению #{lid}", disable_notification=True)
        file_id = msg.photo[-1].file_id
    except Exception as e:  # noqa: BLE001
        log.warning("Барахолка: фото не загружено: %s", e)
        return None
    try:
        await bot.delete_message(msg.chat.id, msg.message_id)
    except Exception:  # noqa: BLE001
        pass
    return file_id


async def notify_moderators(bot, l: Listing, author: AppUser) -> None:
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Опубликовать", callback_data=f"lstok:{l.id}"),
        InlineKeyboardButton(text="❌ Отклонить", callback_data=f"lstno:{l.id}"),
    ]])
    who = html.escape(author.name or "—") + (f" · {html.escape(author.email)}" if author.email else "")
    text = f"🆕 <b>Объявление на проверку</b> · из приложения\nАвтор: {who}\n\n" + board._card_text(
        l, show_contact_values=True)
    for admin in config.ADMIN_IDS:  # уходит в группу-инбокс, тема «Объявления» (utils.inbox)
        try:
            if l.photo_file_id:
                await bot.send_photo(admin, l.photo_file_id, caption=text[:1024], reply_markup=kb)
            else:
                await bot.send_message(admin, text, reply_markup=kb)
        except Exception as e:  # noqa: BLE001
            log.warning("Барахолка: модераторам не отправлено %s: %s", admin, e)


def _validate(data: dict, u: AppUser) -> tuple[dict | None, str | None]:
    cat = str(data.get("category") or "")
    if cat not in board.CATEGORY_LABELS:
        return None, "Выберите категорию."
    intents = [k for k, _ in board.INTENTS.get(cat, [])]
    intent = str(data.get("intent") or "") or None
    if intents and intent not in intents:
        return None, "Выберите, что вы предлагаете или ищете."
    if not intents:
        intent = None
    title = board._clean(str(data.get("title") or ""))
    desc = re.sub(r"\n{3,}", "\n\n", str(data.get("description") or "").replace("\r", "")).strip()
    price = board._clean(str(data.get("price") or ""))
    nationwide = bool(data.get("nationwide"))
    city = board._clean(str(data.get("city") or ""))
    if not board._valid_title(title):
        return None, "Заголовок: от 5 до 100 символов."
    if not board._valid_description(desc):
        return None, "Описание: от 20 до 600 символов, пару предложений о главном."
    if price and not board._valid_price(price):
        return None, "Проверьте цену."
    if not nationwide and not board._valid_city(city):
        return None, "Укажите город."
    for text in (title, desc, price):
        reason = check_text(u, text, 600) if text else None
        if reason:
            return None, reason
    form: dict = {"l_cat": cat, "l_intent": intent, "l_title": title, "l_desc": desc,
                  "l_price": price or None, "l_city": "" if nationwide else city, "l_nationwide": nationwide}
    contacts = data.get("contacts") if isinstance(data.get("contacts"), dict) else {}
    for kind, (field, title_, _icon) in board._CONTACT_FIELDS.items():
        value = str(contacts.get(kind) or "").strip()
        if not value:
            continue
        norm = board._normalize_contact(kind, value)
        if not norm:
            return None, f"Проверьте контакт: {title_}."
        form[field] = norm
    if not board._build_contacts(form):
        return None, "Добавьте хотя бы один контакт, чтобы с вами могли связаться."
    return form, None


async def _read_json(request: web.Request) -> dict:
    if request.content_length and request.content_length > PHOTO_MAX_BYTES * 2:
        return {}
    try:
        data = json.loads(await request.text())
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
        return {}


async def submit(request: web.Request) -> web.Response:
    data = await _read_json(request)
    bot = request.app.get("bot")
    async with get_session() as session:
        me = await _user(request, session)
        denied = can_write(me)
        if denied:
            await session.commit()
            return _err(request, *denied)
        form, error = _validate(data, me)
        if error:
            return _err(request, error)
        existing = None
        if data.get("id"):
            existing = await session.get(Listing, int(data["id"]))
            if not existing or existing.app_user_id != me.id:
                return _err(request, "Объявление не найдено.", 404)
        else:
            active = await session.scalar(select(func.count()).select_from(Listing).where(
                Listing.app_user_id == me.id, Listing.status.in_(["awaiting_payment", "pending", "approved"]),
                or_(Listing.expires_at.is_(None), Listing.expires_at > _now()))) or 0
            if active >= config.BOARD_MAX_ACTIVE:
                return _err(request, f"У вас уже {active} активных объявлений: максимум {config.BOARD_MAX_ACTIVE}. "
                                     "Снимите одно из них в «Моих объявлениях».", 429)
        if _rate(f"market:{me.id}", 10, 3600):
            return _err(request, "Слишком часто. Попробуйте через час.", 429)
        # Фото: новый список «photos» — элементы "keep:<номер>" (оставить существующее) или картинка data:...;
        # старый клиент присылает одно «photo» (картинка или "" — убрать)
        old_ids = all_photos(existing) if existing else []
        plan: list[str | bytes] = []
        if isinstance(data.get("photos"), list):
            for item in data["photos"][:MAX_PHOTOS]:
                item = str(item or "")
                if item.startswith("keep:"):
                    try:
                        plan.append(old_ids[int(item[5:])])
                    except (ValueError, IndexError):
                        continue
                elif item:
                    jpeg = prepare_photo(item)
                    if not jpeg:
                        return _err(request, "Не получилось прочитать одно из фото. Попробуйте другое.")
                    plan.append(jpeg)
        elif data.get("photo"):
            jpeg = prepare_photo(str(data["photo"]))
            if not jpeg:
                return _err(request, "Не получилось прочитать фото. Попробуйте другое.")
            plan = [jpeg]
        elif data.get("photo") != "":
            plan = list(old_ids)
        # Оплачено — только если вебхук оплаты отметил этот платёж успешным (Meta pay:<id> = done),
        # а не когда для объявления просто создавали ссылку на оплату или меняли статус
        paid_mark = (await session.get(Meta, f"pay:{existing.payment_id}")
                     if existing and existing.category == "housing" and existing.payment_id else None)
        was_paid = bool(paid_mark and paid_mark.value == "done")
        l = existing or Listing(app_user_id=me.id, submitter_user_id=me.tg_id)
        board._apply_form(l, form)
        l.expires_at = l.bumped_at = None
        needs_payment = form["l_cat"] == "housing" and board._housing_paid() and not was_paid
        l.status = "awaiting_payment" if needs_payment else "pending"
        if not existing:
            session.add(l)
        await session.flush()
        ids: list[str] = []
        for item in plan:
            if isinstance(item, str):
                ids.append(item)
                continue
            if not bot:
                await session.rollback()
                return _err(request, "Фото сейчас не загрузить. Попробуйте позже.", 503)
            file_id = await _upload_photo(bot, item, l.id)
            if not file_id:
                await session.rollback()
                return _err(request, "Фото не загрузилось. Попробуйте ещё раз.", 502)
            ids.append(file_id)
        l.photo_file_id = ids[0] if ids else None
        l.photos = json.dumps(ids) if ids else None
        await session.commit()
        await session.refresh(l)
        result = {"ok": True, "id": l.id, "status": l.status}
        if needs_payment:
            pay = await create_payment(f"{board.DESC_LISTING}: {l.title}", {"listing_id": l.id, "kind": "listing"},
                                       config.BOARD_HOUSING_PRICE,
                                       redirect_url=f"{config.WEBHOOK_BASE_URL.rstrip('/')}/app/market/my"
                                       if config.WEBHOOK_BASE_URL else None)
            if pay and pay.get("checkout_url"):
                l.payment_id = pay["id"]
                await session.commit()
                result |= {"pay_url": pay["checkout_url"],
                           "price": f"{config.BOARD_HOUSING_PRICE} {config.LISTING_CURRENCY}"}
            else:
                result["pay_error"] = "Не получилось создать оплату. Объявление сохранено, попробуйте позже."
        elif bot:
            await notify_moderators(bot, l, me)
    return _json(request, result)


async def pay(request: web.Request) -> web.Response:
    """Повторная ссылка на оплату объявления о жилье."""
    lid = int(request.match_info["id"])
    async with get_session() as session:
        me = await _user(request, session)
        l = await session.get(Listing, lid)
        if not me or not l or l.app_user_id != me.id or l.status != "awaiting_payment":
            return _err(request, "Это объявление уже оплачено или недоступно.", 404)
        pay_ = await create_payment(f"{board.DESC_LISTING}: {l.title}", {"listing_id": l.id, "kind": "listing"},
                                    config.BOARD_HOUSING_PRICE,
                                    redirect_url=f"{config.WEBHOOK_BASE_URL.rstrip('/')}/app/market/my"
                                    if config.WEBHOOK_BASE_URL else None)
        if not pay_ or not pay_.get("checkout_url"):
            return _err(request, "Не получилось создать оплату. Попробуйте позже.", 502)
        l.payment_id = pay_["id"]
        await session.commit()
    return _json(request, {"ok": True, "pay_url": pay_["checkout_url"]})


async def close(request: web.Request) -> web.Response:
    lid = int(request.match_info["id"])
    async with get_session() as session:
        me = await _user(request, session)
        l = await session.get(Listing, lid)
        if not me or not l or l.app_user_id != me.id:
            return _err(request, "Объявление не найдено.", 404)
        l.status = "closed"
        await session.commit()
    return _json(request, {"ok": True})


async def report(request: web.Request) -> web.Response:
    lid = int(request.match_info["id"])
    data = await _read_json(request)
    reason = str(data.get("reason") or "other")
    if reason not in board.REPORT_REASONS:
        reason = "other"
    async with get_session() as session:
        me = await _user(request, session)
        l = await session.get(Listing, lid)
        await session.commit()
    if not me:
        return _err(request, "Войдите, чтобы пожаловаться.", 401)
    if not l or board._status(l, _now()) != "approved":
        return _err(request, "Объявление уже снято.", 404)
    if _rate(f"mrep:{me.id}:{lid}", 1, 86400):
        return _json(request, {"ok": True})
    bot = request.app.get("bot")
    if bot:
        text = (f"🚩 Жалоба на объявление #{lid} · из приложения\nПричина: {board.REPORT_REASONS[reason]}\n"
                f"От: {html.escape(me.name or '—')} (id {me.id})\n«{html.escape(l.title)}»\n/listing {lid}")
        for admin in config.ADMIN_IDS:
            try:
                await bot.send_message(admin, text)
            except Exception as e:  # noqa: BLE001
                log.warning("Барахолка: жалоба не отправлена %s: %s", admin, e)
    return _json(request, {"ok": True})


def install_routes(app: web.Application) -> None:
    app.router.add_get("/api/app/market", listings)
    app.router.add_post("/api/app/market", submit)
    app.router.add_get("/api/app/market/my", my_listings)
    app.router.add_get(r"/api/app/market/{id:\d+}", listing)
    app.router.add_get(r"/api/app/market/{id:\d+}/photo", photo)
    app.router.add_post(r"/api/app/market/{id:\d+}/pay", pay)
    app.router.add_post(r"/api/app/market/{id:\d+}/close", close)
    app.router.add_post(r"/api/app/market/{id:\d+}/report", report)
