"""Public API for the WordPress site: donations and the business cabinet.

Donations
  POST /api/donate                 one-off or monthly (Mollie first payment, then a subscription)
  GET|POST /api/donate/cancel      cancel a monthly donation from the link in the e-mail

Business cabinet (specialists manage their own cards on the site)
  POST /api/cabinet/login          e-mail with a sign-in link (invoice e-mail of the card)
  GET  /api/cabinet/session        exchange the link token for a 30-day session token
  GET  /api/cabinet/cards          the owner's cards
  POST /api/cabinet/edit           text edits go to moderation (same flow as the bot cabinet)
  POST /api/cabinet/photo          photo edit, goes to moderation
  POST /api/cabinet/color          card colour, applied at once
  POST /api/cabinet/visibility     hide or show a card
  POST /api/cabinet/delete         remove a card from the guide
  POST /api/cabinet/renew          Mollie payment to extend the card
Owners sign in either by the card's invoice e-mail or through the bot (/start cabinet_web).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import logging
import os
import re
import time
from datetime import date, timedelta

import aiohttp
from aiohttp import web
from sqlalchemy import func, select

import config
from database.db import get_session
from database.models import Meta, Specialist, SpecialistEdit
from utils.allo_v2 import _cors
from utils.invoices import send_email_message
from utils.payments import MOLLIE_API, _headers, create_payment

log = logging.getLogger(__name__)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
CARD_COLORS = ("red", "white", "blue", "green", "orange")
EDIT_FIELDS = {"name": 200, "category": 50, "city": 100, "description": 2000, "contact": 300}
SESSION_DAYS = 30


def _site() -> str:
    return (config.SITE_URL or "https://www.podslushano.nl").rstrip("/")


def _api_base() -> str:
    return (config.WEBHOOK_BASE_URL or "").rstrip("/")


# ---------------------------------------------------------------- tokens

def _secret() -> bytes:
    raw = os.getenv("SITE_API_SECRET") or config.MOLLIE_API_KEY or config.BOT_TOKEN or "dev"
    return hashlib.sha256(("site-api:" + raw).encode()).digest()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def make_token(payload: dict, ttl: int) -> str:
    body = dict(payload, x=int(time.time()) + ttl)
    raw = _b64(json.dumps(body, separators=(",", ":")).encode())
    sig = _b64(hmac.new(_secret(), raw.encode(), hashlib.sha256).digest())
    return f"{raw}.{sig}"


def grant(payload: dict, days: int = 7) -> str:
    """Подпись для ссылки на закрытую картинку. Срок округлён до суток, чтобы ссылка весь день была одной
    и картинка бралась из кэша."""
    now = int(time.time())
    return make_token(payload, (now // 86400 + days + 1) * 86400 - now)


def read_token(token: str, kind: str) -> dict | None:
    try:
        raw, sig = (token or "").split(".", 1)
        good = _b64(hmac.new(_secret(), raw.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, good):
            return None
        body = json.loads(_unb64(raw))
    except (ValueError, json.JSONDecodeError):
        return None
    if body.get("k") != kind or int(body.get("x", 0)) < time.time():
        return None
    return body


# ---------------------------------------------------------------- helpers

def _json(request: web.Request, data: dict, status: int = 200) -> web.Response:
    resp = web.json_response(data, status=status, dumps=lambda o: json.dumps(o, ensure_ascii=False))
    return _cors(request, resp)


def _err(request: web.Request, msg: str, status: int = 400) -> web.Response:
    return _json(request, {"ok": False, "error": msg}, status)


async def _body(request: web.Request) -> dict:
    if request.content_length and request.content_length > 64_000:
        return {}
    try:
        data = await request.json()
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
        return {}


def _money(cents: int) -> str:
    return f"{cents // 100}.{cents % 100:02d}"


async def _mollie(method: str, path: str, body: dict | None = None) -> dict | None:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.request(method, f"{MOLLIE_API}{path}", json=body, headers=_headers()) as resp:
                data = await resp.json(content_type=None) if resp.status != 204 else {}
                if resp.status >= 300:
                    log.warning("Mollie %s %s: %s %s", method, path, resp.status, data)
                    return None
                return data or {}
    except Exception as e:  # noqa: BLE001
        log.warning("Mollie %s %s failed: %s", method, path, e)
        return None


async def _meta_get(key: str) -> str | None:
    async with get_session() as session:
        row = await session.get(Meta, key)
        return row.value if row else None


async def _meta_set(key: str, value: str) -> bool:
    """Returns False if the key already existed (idempotency guard)."""
    async with get_session() as session:
        if await session.get(Meta, key):
            return False
        session.add(Meta(key=key, value=value[:100]))
        await session.commit()
        return True


def _html_page(title: str, text: str, form: str = "") -> web.Response:
    page = (
        "<!doctype html><html lang='ru'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{html.escape(title)} · podslushano.nl</title><style>"
        "body{margin:0;min-height:100vh;display:grid;place-items:center;background:#F4F5F7;"
        "font-family:-apple-system,'Segoe UI',Arial,sans-serif;color:#0D1117;padding:20px}"
        ".c{max-width:480px;background:#fff;border-radius:24px;padding:28px;box-shadow:0 24px 60px -30px rgba(0,0,0,.3)}"
        "h1{font-size:26px;margin:0 0 10px}p{color:#2E3540;line-height:1.55}"
        "button,a.b{display:inline-block;margin-top:12px;background:#FF5A1F;color:#fff;border:0;border-radius:14px;"
        "padding:12px 18px;font-size:15px;font-weight:700;text-decoration:none;cursor:pointer}</style></head>"
        f"<body><main class='c'><h1>{html.escape(title)}</h1><p>{html.escape(text)}</p>{form}"
        f"<p><a class='b' href='{_site()}/'>На сайт</a></p></main></body></html>"
    )
    return web.Response(text=page, content_type="text/html", headers={"Cache-Control": "no-store"})


# ---------------------------------------------------------------- donations

async def donate(request: web.Request) -> web.Response:
    body = await _body(request)
    try:
        cents = int(body.get("amount_cents"))
    except (TypeError, ValueError):
        cents = 0
    if not 100 <= cents <= 100_000:
        return _err(request, "Укажите сумму от €1 до €1000.")
    monthly = body.get("monthly") is True
    email = str(body.get("email") or "").strip().lower()[:200]
    name = str(body.get("name") or "").strip()[:120]
    if email and not EMAIL_RE.match(email):
        return _err(request, "Проверьте почту.")
    if monthly and not email:
        return _err(request, "Для ежемесячного вклада нужна почта: на неё придёт ссылка для отмены.")
    if not config.payments_enabled():
        return _err(request, "Оплата временно недоступна. Попробуйте позже.", 503)
    redirect = f"{_site()}/?donation=thanks"
    amount = _money(cents)
    if not monthly:
        payment = await create_payment("Bijdrage podslushano.nl",
                                       {"kind": "donation", "monthly": False, "email": email},
                                       amount, redirect_url=redirect)
        if not payment or not payment.get("checkout_url"):
            return _err(request, "Не удалось открыть оплату. Попробуйте ещё раз.", 502)
        return _json(request, {"ok": True, "checkout_url": payment["checkout_url"]})
    customer = await _mollie("POST", "/customers", {"name": name or email, "email": email})
    if not customer or not customer.get("id"):
        return _err(request, "Не удалось открыть оплату. Попробуйте ещё раз.", 502)
    payment = await _mollie("POST", "/payments", {
        "amount": {"currency": "EUR", "value": amount},
        "description": "Maandelijkse bijdrage podslushano.nl",
        "redirectUrl": redirect,
        "webhookUrl": f"{_api_base()}/mollie-webhook",
        "customerId": customer["id"],
        "sequenceType": "first",
        "metadata": {"kind": "donation", "monthly": True, "customer_id": customer["id"],
                     "amount": amount, "email": email},
    })
    checkout = ((payment or {}).get("_links") or {}).get("checkout", {}).get("href")
    if not checkout:
        return _err(request, "Не удалось открыть оплату. Попробуйте ещё раз.", 502)
    return _json(request, {"ok": True, "checkout_url": checkout})


async def on_donation_payment(payment_id: str, payment: dict) -> None:
    """Called from the Mollie webhook for kind=donation payments."""
    if payment.get("status") != "paid":
        return
    meta = payment.get("metadata") or {}
    email = meta.get("email") or ""
    if not meta.get("monthly"):
        if email and await _meta_set(f"don:{payment_id}", "thanks"):
            value = (payment.get("amount") or {}).get("value", "")
            from utils.email_templates import donation_thanks
            await send_email_message(email, *donation_thanks(amount=value.replace(".", ",")))
        return
    customer_id = meta.get("customer_id")
    if not customer_id or await _meta_get(f"don:{payment_id}"):
        return
    start = (date.today() + timedelta(days=31)).isoformat()
    sub = await _mollie("POST", f"/customers/{customer_id}/subscriptions", {
        "amount": {"currency": "EUR", "value": meta.get("amount")},
        "interval": "1 month",
        "startDate": start,
        "description": "Maandelijkse bijdrage podslushano.nl",
        "webhookUrl": f"{_api_base()}/mollie-webhook",
        "metadata": {"kind": "donation_sub", "email": email},
    })
    if not sub or not sub.get("id"):
        log.error("Could not create donation subscription for payment %s", payment_id)
        return
    if not await _meta_set(f"don:{payment_id}", sub["id"]):
        return
    link = f"{_api_base()}/api/donate/cancel?t={make_token({'k': 'don', 'c': customer_id, 's': sub['id']}, 10 * 365 * 86400)}"
    value = meta.get("amount", "")
    if email:
        from utils.email_templates import donation_thanks
        await send_email_message(email, *donation_thanks(amount=str(value).replace(".", ","), monthly=True,
                                                         cancel_url=link))


async def donate_cancel(request: web.Request) -> web.Response:
    token = request.query.get("t", "")
    data = read_token(token, "don")
    if not data:
        return _html_page("Ссылка не работает", "Ссылка устарела или повреждена. Напишите нам на podslushano.nl@gmail.com, и мы отменим вклад.")
    if request.method == "GET":
        form = (f"<form method='post' action='?t={html.escape(token)}'>"
                "<button type='submit'>Отменить ежемесячный вклад</button></form>")
        return _html_page("Отменить ежемесячный вклад?", "Списания прекратятся сразу. Уже сделанные вклады не возвращаются.", form)
    res = await _mollie("DELETE", f"/customers/{data['c']}/subscriptions/{data['s']}")
    if res is None:
        return _html_page("Не получилось", "Не удалось отменить. Напишите нам на podslushano.nl@gmail.com, и мы сделаем это вручную.")
    return _html_page("Вклад отменён", "Ежемесячные списания остановлены. Спасибо, что были с нами!")


# ---------------------------------------------------------------- cabinet

def _owner_filter(sess: dict):
    if sess.get("u"):
        return Specialist.submitter_user_id == int(sess["u"])
    return func.lower(Specialist.invoice_email) == str(sess.get("e", "")).lower()


def _session(request: web.Request) -> dict | None:
    return read_token(request.headers.get("X-Cabinet", ""), "cab")


def _card_json(s: Specialist, pending: int) -> dict:
    return {
        "id": s.id, "name": s.name, "category": s.category, "city": s.city or "", "province": s.province or "",
        "description": s.description or "", "contact": s.contact or "", "online": bool(s.is_online),
        "premium": bool(s.is_premium), "status": s.status, "plan": s.plan,
        "paid_until": s.paid_until.date().isoformat() if s.paid_until else None,
        "photo": f"{_api_base()}/sp-photo/{s.id}" if s.photo_file_id else None,
        "card_color": s.card_color or "white", "pending_edits": pending,
    }


async def _own_card(request: web.Request, sid) -> tuple[dict | None, Specialist | None]:
    sess = _session(request)
    if not sess:
        return None, None
    try:
        sid = int(sid)
    except (TypeError, ValueError):
        return sess, None
    async with get_session() as session:
        sp = await session.scalar(select(Specialist).where(Specialist.id == sid, _owner_filter(sess)))
    return sess, sp


async def cabinet_login(request: web.Request) -> web.Response:
    body = await _body(request)
    email = str(body.get("email") or "").strip().lower()[:200]
    if not EMAIL_RE.match(email):
        return _err(request, "Проверьте почту.")
    async with get_session() as session:
        count = await session.scalar(select(func.count(Specialist.id)).where(
            func.lower(Specialist.invoice_email) == email, Specialist.status != "deleted"))
    if count:
        link = f"{_site()}/cabinet/?t={make_token({'k': 'login', 'e': email}, 3600)}"
        from utils.email_templates import cabinet_login as cabinet_login_email
        await send_email_message(email, *cabinet_login_email(link=link))
    # Same answer either way, so the form does not reveal which e-mails are registered.
    return _json(request, {"ok": True})


def telegram_login_link(user_id: int) -> str:
    return f"{_site()}/cabinet/?t={make_token({'k': 'login', 'u': int(user_id)}, 3600)}"


async def cabinet_session(request: web.Request) -> web.Response:
    data = read_token(request.query.get("t", ""), "login")
    if not data:
        return _err(request, "Ссылка для входа устарела. Запросите новую.", 401)
    sess = {"k": "cab"}
    if data.get("u"):
        sess["u"] = int(data["u"])
    else:
        sess["e"] = data.get("e")
    return _json(request, {"ok": True, "session": make_token(sess, SESSION_DAYS * 86400)})


async def cabinet_cards(request: web.Request) -> web.Response:
    sess = _session(request)
    if not sess:
        return _err(request, "Войдите в кабинет заново.", 401)
    async with get_session() as session:
        rows = (await session.scalars(select(Specialist).where(
            _owner_filter(sess), Specialist.status != "deleted").order_by(Specialist.id))).all()
        out = []
        for s in rows:
            pending = await session.scalar(select(func.count(SpecialistEdit.id)).where(
                SpecialistEdit.specialist_id == s.id, SpecialistEdit.status == "pending"))
            out.append(_card_json(s, pending or 0))
    return _json(request, {"ok": True, "cards": out})


async def cabinet_edit(request: web.Request) -> web.Response:
    body = await _body(request)
    sess, sp = await _own_card(request, body.get("id"))
    if not sess:
        return _err(request, "Войдите в кабинет заново.", 401)
    if not sp:
        return _err(request, "Карточка не найдена.", 404)
    field = str(body.get("field") or "")
    value = str(body.get("value") or "").strip()
    if field not in EDIT_FIELDS:
        return _err(request, "Это поле нельзя изменить.")
    if not value or len(value) > EDIT_FIELDS[field]:
        return _err(request, "Проверьте значение.")
    if re.search(r"[іїєґІЇЄҐ]", value):
        return _err(request, "Карточка заполняется на русском языке.")
    async with get_session() as session:
        edit = SpecialistEdit(specialist_id=sp.id, user_id=int(sess.get("u") or 0), field=field, new_value=value)
        session.add(edit)
        await session.commit()
        await session.refresh(edit)
        eid = edit.id
    from handlers.cabinet import _notify_admins_edit
    bot = request.app.get("bot")
    if bot:
        await _notify_admins_edit(bot, eid, sp.name, field, getattr(sp, field, None), value)
    return _json(request, {"ok": True, "moderation": True})


async def cabinet_photo(request: web.Request) -> web.Response:
    sess = _session(request)
    if not sess:
        return _err(request, "Войдите в кабинет заново.", 401)
    reader = await request.multipart()
    sid, blob, ctype = None, b"", ""
    async for part in reader:
        if part.name == "id":
            sid = (await part.text()).strip()
        elif part.name == "file":
            ctype = part.headers.get("Content-Type", "")
            blob = await part.read(decode=False)
            if len(blob) > 6 * 1024 * 1024:
                return _err(request, "Фото должно быть меньше 6 МБ.")
    if ctype not in ("image/jpeg", "image/png", "image/webp") or not blob:
        return _err(request, "Загрузите фото в формате JPG, PNG или WebP.")
    _, sp = await _own_card(request, sid)
    if not sp:
        return _err(request, "Карточка не найдена.", 404)
    bot = request.app.get("bot")
    if not bot or not config.ADMIN_IDS:
        return _err(request, "Загрузка фото временно недоступна.", 503)
    from aiogram.types import BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup
    async with get_session() as session:
        edit = SpecialistEdit(specialist_id=sp.id, user_id=int(sess.get("u") or 0), field="photo", new_value="")
        session.add(edit)
        await session.commit()
        await session.refresh(edit)
        eid = edit.id
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Одобрить", callback_data=f"cabedit_ok:{eid}"),
        InlineKeyboardButton(text="❌ Отклонить", callback_data=f"cabedit_no:{eid}"),
    ]])
    caption = f"✏️ Новое фото карточки «{html.escape(sp.name)}» (с сайта)"
    file_id = None
    for i, admin_id in enumerate(config.ADMIN_IDS):
        try:
            photo = BufferedInputFile(blob, filename="photo.jpg") if file_id is None else file_id
            msg = await bot.send_photo(admin_id, photo, caption=caption, reply_markup=kb)
            if file_id is None and msg.photo:
                file_id = msg.photo[-1].file_id
        except Exception as e:  # noqa: BLE001
            log.warning("Photo edit to admin %s failed: %s", admin_id, e)
    async with get_session() as session:
        edit = await session.get(SpecialistEdit, eid)
        if file_id:
            edit.new_value = file_id
        else:
            edit.status = "rejected"
        await session.commit()
    if not file_id:
        return _err(request, "Не удалось загрузить фото. Попробуйте ещё раз.", 502)
    return _json(request, {"ok": True, "moderation": True})


async def cabinet_color(request: web.Request) -> web.Response:
    body = await _body(request)
    sess, sp = await _own_card(request, body.get("id"))
    if not sess:
        return _err(request, "Войдите в кабинет заново.", 401)
    color = str(body.get("color") or "")
    if not sp or color not in CARD_COLORS:
        return _err(request, "Проверьте карточку и цвет.")
    async with get_session() as session:
        s = await session.get(Specialist, sp.id)
        s.card_color = color
        await session.commit()
    return _json(request, {"ok": True})


async def cabinet_visibility(request: web.Request) -> web.Response:
    body = await _body(request)
    sess, sp = await _own_card(request, body.get("id"))
    if not sess:
        return _err(request, "Войдите в кабинет заново.", 401)
    if not sp or sp.status not in ("active", "hidden"):
        return _err(request, "Эту карточку сейчас нельзя скрыть или показать.")
    async with get_session() as session:
        s = await session.get(Specialist, sp.id)
        s.status = "hidden" if body.get("hidden") is True else "active"
        await session.commit()
        status = s.status
    return _json(request, {"ok": True, "status": status})


async def cabinet_delete(request: web.Request) -> web.Response:
    body = await _body(request)
    sess, sp = await _own_card(request, body.get("id"))
    if not sess:
        return _err(request, "Войдите в кабинет заново.", 401)
    if not sp:
        return _err(request, "Карточка не найдена.", 404)
    async with get_session() as session:
        s = await session.get(Specialist, sp.id)
        s.status = "deleted"
        await session.commit()
    return _json(request, {"ok": True})


async def cabinet_renew(request: web.Request) -> web.Response:
    body = await _body(request)
    sess, sp = await _own_card(request, body.get("id"))
    if not sess:
        return _err(request, "Войдите в кабинет заново.", 401)
    if not sp:
        return _err(request, "Карточка не найдена.", 404)
    from handlers.selfadd import DESC_RENEW, SELFADD_PLANS
    plan = str(body.get("plan") or sp.plan or "year")
    if plan not in SELFADD_PLANS:
        return _err(request, "Выберите тариф.")
    info = config.plan_info(plan)
    payment = await create_payment(f"{DESC_RENEW}: {sp.name}",
                                   {"specialist_id": sp.id, "kind": "renew", "plan": plan},
                                   info["price"], redirect_url=f"{_site()}/cabinet/?paid={sp.id}")
    if not payment or not payment.get("checkout_url"):
        return _err(request, "Не удалось открыть оплату. Попробуйте ещё раз.", 502)
    return _json(request, {"ok": True, "checkout_url": payment["checkout_url"]})


async def options(request: web.Request) -> web.Response:
    return _cors(request, web.Response(status=204))


ROUTES = [
    ("POST", "/api/donate", donate), ("GET", "/api/donate/cancel", donate_cancel), ("POST", "/api/donate/cancel", donate_cancel),
    ("POST", "/api/cabinet/login", cabinet_login), ("GET", "/api/cabinet/session", cabinet_session),
    ("GET", "/api/cabinet/cards", cabinet_cards), ("POST", "/api/cabinet/edit", cabinet_edit),
    ("POST", "/api/cabinet/photo", cabinet_photo), ("POST", "/api/cabinet/color", cabinet_color),
    ("POST", "/api/cabinet/visibility", cabinet_visibility), ("POST", "/api/cabinet/delete", cabinet_delete),
    ("POST", "/api/cabinet/renew", cabinet_renew),
]


def install_routes(app: web.Application) -> None:
    for method, path, handler in ROUTES:
        app.router.add_route(method, path, handler)
    for path in sorted({p for m, p, _ in ROUTES if p.startswith("/api/cabinet") or p == "/api/donate"}):
        app.router.add_route("OPTIONS", path, options)
