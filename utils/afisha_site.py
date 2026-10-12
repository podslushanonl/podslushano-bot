"""Платное размещение события в афише с сайта и лента одобренных событий для сайта.

POST /api/afisha/submit   анкета с постером → заявка (awaiting_payment) → ссылка на оплату
GET  /api/afisha/events   одобренные и ещё не прошедшие события для афиши на сайте
GET  /ev-photo/{id}       постер события (файл с сайта или фото из Telegram)

После оплаты работает общий поток из handlers.afisha: проверка админом в Telegram,
затем событие появляется в ленте и на сайте.
"""
from __future__ import annotations

import logging
import os
import re
import time
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from aiohttp import web
from sqlalchemy import or_, select

import config
from database.db import get_session
from database.models import EventListing
from utils.allo_v2 import _cors
from utils.payments import create_payment
from utils.site_api import EMAIL_RE, _err, _json, _site

log = logging.getLogger(__name__)

AMS = ZoneInfo("Europe/Amsterdam")
POSTER_DIR = os.path.join(os.path.dirname(config.DB_PATH), "afisha_posters")
MAX_POSTER = 8 * 1024 * 1024
CATEGORIES = ("концерт", "стендап", "театр", "встреча", "вечеринка", "мастер-класс",
              "детям", "спорт", "выставка", "фестиваль", "другое")
LIMITS = {"title": 120, "description": 3000, "city": 80, "venue": 160, "link": 400, "email": 200}
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_recent: dict[str, list[float]] = {}


def poster_path(ev_id: int) -> str:
    return os.path.join(POSTER_DIR, f"{int(ev_id)}.jpg")


def _too_many(ip: str) -> bool:
    now = time.time()
    hits = [t for t in _recent.get(ip, []) if now - t < 3600]
    _recent[ip] = hits
    if len(hits) >= 6:
        return True
    hits.append(now)
    return False


def _day_bounds(start: date, end: date) -> tuple[datetime, datetime]:
    s = datetime.combine(start, datetime.min.time(), AMS).astimezone(timezone.utc).replace(tzinfo=None)
    e = datetime.combine(end, datetime.max.time(), AMS).astimezone(timezone.utc).replace(tzinfo=None)
    return s, e


def validate(fields: dict, today: date | None = None) -> tuple[dict | None, str]:
    """Проверяет анкету с сайта. (чистые данные, "") или (None, текст ошибки)."""
    today = today or datetime.now(AMS).date()
    f = {k: re.sub(r"[ \t]+", " ", str(fields.get(k) or "")).strip() for k in
         ("title", "description", "date", "end", "time", "city", "venue", "link", "email", "category", "online")}
    for k, n in LIMITS.items():
        if len(f[k]) > n:
            return None, "Слишком длинный текст в одном из полей."
    if len(f["title"]) < 3:
        return None, "Напишите название события."
    if len(f["description"]) < 20:
        return None, "Опишите событие хотя бы в паре предложений."
    if not _DATE_RE.match(f["date"]):
        return None, "Укажите дату события."
    try:
        start = date.fromisoformat(f["date"])
        end = date.fromisoformat(f["end"]) if f["end"] else start
    except ValueError:
        return None, "Проверьте дату."
    if start < today:
        return None, "Эта дата уже прошла."
    if end < start or (end - start).days > 31:
        return None, "Проверьте дату окончания."
    if start > today + timedelta(days=180):
        return None, "Событие можно добавить максимум на полгода вперёд."
    if f["time"] and not _TIME_RE.match(f["time"]):
        return None, "Проверьте время начала."
    online = f["online"] in ("1", "true", "on")
    if not online and len(f["city"]) < 2:
        return None, "Укажите город."
    if f["link"]:
        if not re.match(r"^https?://", f["link"], re.I):
            f["link"] = "https://" + f["link"]
        if " " in f["link"] or "." not in f["link"]:
            return None, "Проверьте ссылку на билеты."
    if not EMAIL_RE.match(f["email"]):
        return None, "Проверьте почту: на неё придёт счёт и ответ о публикации."
    cat = f["category"].lower()
    starts_at, ends_at = _day_bounds(start, end)
    label = start.strftime("%d.%m.%Y") if end == start else f"{start:%d}–{end:%d.%m.%Y}"
    return {
        "title": f["title"], "description": f["description"], "link": f["link"] or None,
        "city": "" if online else f["city"], "is_nationwide": online, "venue": f["venue"] or None,
        "event_time": f["time"] or None, "category": cat if cat in CATEGORIES else "другое",
        "event_date": label, "starts_at": starts_at, "ends_at": ends_at,
        "month_key": start.strftime("%Y-%m"), "invoice_email": f["email"].lower(),
    }, ""


async def submit(request: web.Request) -> web.Response:
    if not config.payments_enabled():
        return _err(request, "Размещение временно недоступно. Попробуйте позже.", 503)
    ip = request.headers.get("X-Forwarded-For", request.remote or "").split(",")[0].strip()
    if _too_many(ip):
        return _err(request, "Слишком много заявок подряд. Попробуйте через час.", 429)
    if request.content_length and request.content_length > MAX_POSTER + 200_000:
        return _err(request, "Постер должен быть меньше 8 МБ.")
    fields, blob, ctype = {}, b"", ""
    try:
        reader = await request.multipart()
        async for part in reader:
            if part.name == "poster":
                ctype = part.headers.get("Content-Type", "")
                blob = await part.read(decode=False)
                if len(blob) > MAX_POSTER:
                    return _err(request, "Постер должен быть меньше 8 МБ.")
            elif part.name:
                fields[part.name] = (await part.text())[:4000]
    except Exception:  # noqa: BLE001
        return _err(request, "Не удалось прочитать форму. Попробуйте ещё раз.")
    data, error = validate(fields)
    if not data:
        return _err(request, error)
    if ctype not in ("image/jpeg", "image/png", "image/webp") or len(blob) < 1000:
        return _err(request, "Добавьте постер: картинку JPG, PNG или WebP.")
    jpeg = _to_jpeg(blob)
    if not jpeg:
        return _err(request, "Не получилось открыть постер. Попробуйте другую картинку.")
    async with get_session() as session:
        ev = EventListing(**data, status="awaiting_payment", source="site")
        session.add(ev)
        await session.commit()
        await session.refresh(ev)
        ev_id = ev.id
    os.makedirs(POSTER_DIR, exist_ok=True)
    with open(poster_path(ev_id), "wb") as fh:
        fh.write(jpeg)
    payment = await create_payment(
        f"Plaatsing evenement in podslushano.nl-afisha: {data['title'][:60]}",
        {"event_id": ev_id, "kind": "afisha", "source": "site"},
        config.AFISHA_PRICE, redirect_url=f"{_site()}/events/?afisha=thanks")
    if not payment or not payment.get("checkout_url"):
        return _err(request, "Не удалось открыть оплату. Попробуйте ещё раз.", 502)
    async with get_session() as session:
        ev = await session.get(EventListing, ev_id)
        ev.payment_id = payment["id"]
        await session.commit()
    return _json(request, {"ok": True, "checkout_url": payment["checkout_url"]})


def _to_jpeg(blob: bytes) -> bytes | None:
    """Приводит постер к JPEG до 1600 px: так его примет Telegram и быстро отдаст сайт."""
    try:
        from io import BytesIO

        from PIL import Image
        im = Image.open(BytesIO(blob))
        im.load()
        if im.mode not in ("RGB", "L"):
            bg = Image.new("RGB", im.size, (255, 255, 255))
            bg.paste(im.convert("RGBA"), mask=im.convert("RGBA").split()[-1])
            im = bg
        im = im.convert("RGB")
        im.thumbnail((1600, 1600))
        out = BytesIO()
        im.save(out, "JPEG", quality=86, optimize=True)
        return out.getvalue()
    except Exception as e:  # noqa: BLE001
        log.info("Афиша: постер не открылся: %s", e)
        return None


def _paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n|\r?\n", text or "") if p.strip()][:12]


def event_item(ev: EventListing) -> dict:
    start = ev.starts_at.replace(tzinfo=timezone.utc).astimezone(AMS).date() if ev.starts_at else None
    end = ev.ends_at.replace(tzinfo=timezone.utc).astimezone(AMS).date() if ev.ends_at else None
    base = (config.WEBHOOK_BASE_URL or "").rstrip("/")
    has_img = bool(ev.photo_file_id) or os.path.exists(poster_path(ev.id))
    return {
        "key": f"u{ev.id}", "h": ev.title, "s": (ev.description or "").split("\n")[0][:140],
        "date": start.isoformat() if start else "", "end": end.isoformat() if end and end != start else "",
        "time": ev.event_time or "", "venue": ev.venue or "",
        "city": "Онлайн / по всей стране" if ev.is_nationwide else (ev.city or ""),
        "url": ev.link or "", "img": f"{base}/ev-photo/{ev.id}" if has_img else "",
        "p": _paragraphs(ev.description or ""), "cat": ev.category or "событие", "user": True,
    }


async def events(request: web.Request) -> web.Response:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    async with get_session() as session:
        rows = (await session.execute(select(EventListing).where(
            EventListing.status == "approved",
            EventListing.starts_at.is_not(None),
            or_(EventListing.ends_at.is_(None), EventListing.ends_at >= now),
        ).order_by(EventListing.starts_at).limit(200))).scalars().all()
    resp = _json(request, {"events": [event_item(e) for e in rows]})
    resp.headers["Cache-Control"] = "public, max-age=300"
    return resp


async def photo(request: web.Request) -> web.Response:
    ev_s = request.match_info.get("eid", "")
    if not ev_s.isdigit():
        return web.Response(status=404, text="not found")
    data = None
    async with get_session() as session:
        ev = await session.get(EventListing, int(ev_s))
    if not ev or ev.status != "approved":  # постер публичен только после оплаты и проверки
        return web.Response(status=404, text="not found")
    if os.path.exists(poster_path(ev.id)):
        with open(poster_path(ev.id), "rb") as fh:
            data = fh.read()
    else:
        if ev.photo_file_id and request.app.get("bot"):
            try:
                bot = request.app["bot"]
                f = await bot.get_file(ev.photo_file_id)
                data = (await bot.download_file(f.file_path)).read()
            except Exception as e:  # noqa: BLE001
                log.warning("Афиша: постер #%s не отдан: %s", ev_s, e)
    if not data:
        return web.Response(status=404, text="no photo")
    resp = web.Response(body=data, content_type="image/jpeg")
    resp.headers["Cache-Control"] = "public, max-age=86400"
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp


async def _options(request: web.Request) -> web.Response:
    return _cors(request, web.Response(status=204))


def install_routes(app: web.Application) -> None:
    app.router.add_post("/api/afisha/submit", submit)
    app.router.add_route("OPTIONS", "/api/afisha/submit", _options)
    app.router.add_get("/api/afisha/events", events)
    app.router.add_get("/ev-photo/{eid}", photo)
