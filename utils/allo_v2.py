"""Allo Walks storefront API, using the existing Railway/Mollie connection.

The WordPress page contains only HTML/CSS/JS. Prices, codes, inventory and
payment status are decided here, never by the browser.
"""
from __future__ import annotations

import base64
import asyncio
import hashlib
import hmac
import html
import json
import logging
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlsplit

from aiohttp import web
from cryptography.fernet import Fernet
from sqlalchemy import and_, func, or_, select, text

import config
from database.db import get_session
from database.models import AlloBooking, AlloWebCode, AlloWebSale
from utils.invoices import send_email_message
from utils.payments import create_payment, get_payment

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parent.parent
HOLD = timedelta(minutes=60)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _origin(url: str) -> str:
    p = urlsplit(url)
    return f"{p.scheme}://{p.netloc}" if p.scheme in ("http", "https") and p.netloc else ""


def _cors(request: web.Request, response: web.StreamResponse) -> web.StreamResponse:
    origin = request.headers.get("Origin", "")
    allowed = {_origin(config.WP_URL), _origin(config.SITE_URL),
               _origin(config.WEBHOOK_BASE_URL)}
    if origin and origin in allowed:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Cache-Control"] = "no-store"
    return response


def _json(request: web.Request, data: dict, status: int = 200) -> web.Response:
    return _cors(request, web.json_response(data, status=status,
        dumps=lambda obj: json.dumps(obj, ensure_ascii=False)))


async def options(request: web.Request) -> web.Response:
    return _cors(request, web.Response(status=204))


def _events() -> list[dict]:
    """Only complete, future, approved events are exposed publicly."""
    try:
        rows = json.loads((ROOT / "content" / "allo_events.json").read_text("utf-8"))
    except (OSError, ValueError):
        log.exception("Cannot read Allo event catalog")
        return []
    if not isinstance(rows, list):
        return []
    result, seen = [], set()
    for event in rows:
        try:
            if not isinstance(event, dict) or event.get("status") != "published":
                continue
            key = str(event["key"])
            start = datetime.fromisoformat(str(event["starts_at"]))
            photos = event["photos"]
            required = ("category", "title", "place", "meeting", "duration",
                        "intro", "route", "included", "extra", "price_cents", "capacity")
            if (not key or key in seen or start.tzinfo is None
                    or start <= datetime.now(start.tzinfo)
                    or event["category"] not in ("city", "nature", "special")
                    or any(not event.get(field) for field in required)
                    or not isinstance(photos, list) or not 3 <= len(photos) <= 6
                    or any(not isinstance(photo, dict) or not str(photo.get("url", "")).startswith("https://") or not photo.get("alt")
                           for photo in photos)
                    or len({photo["url"] for photo in photos}) != len(photos)
                    or any(not isinstance(event[field], list) or not event[field]
                           or any(not isinstance(item, str) or not item.strip() for item in event[field])
                           for field in ("route", "included", "extra"))
                    or not 1 <= int(event["capacity"]) <= 8
                    or not 1 <= int(event["price_cents"]) <= 100000):
                continue
            seen.add(key)
            result.append(event)
        except (KeyError, TypeError, ValueError):
            log.warning("Incomplete Allo event skipped: %r", event.get("key") if isinstance(event, dict) else event)
    return sorted(result, key=lambda row: row["starts_at"])


def _event(key: str) -> dict | None:
    return next((row for row in _events() if row["key"] == key), None)


def _gift_amounts() -> list[int]:
    try:
        settings = json.loads((ROOT / "content" / "allo_settings.json").read_text("utf-8"))
        amounts = settings.get("gift_amounts_eur", [])
        if not isinstance(amounts, list):
            return []
        return sorted({int(Decimal(str(value)) * 100) for value in amounts
                       if 100 <= int(Decimal(str(value)) * 100) <= 100000})
    except (OSError, ValueError, TypeError, InvalidOperation):
        return []


def _normal_code(value: str) -> str:
    return re.sub(r"\s+", "", value or "").upper()


def _hash_code(value: str) -> str:
    return hashlib.sha256(_normal_code(value).encode("utf-8")).hexdigest()


def _cipher() -> Fernet:
    secret = (os.getenv("ALLO_CODE_ENCRYPTION_KEY", "").strip()
              or os.getenv("GMAIL_TOKEN_ENCRYPTION_KEY", "").strip())
    if not secret:
        raise RuntimeError("ALLO_CODE_ENCRYPTION_KEY is not configured")
    digest = hmac.new(secret.encode(), b"allo-web-code-v1", hashlib.sha256).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _new_code() -> str:
    return "ALLO-" + secrets.token_hex(12).upper()


def _money(cents: int) -> str:
    return f"{Decimal(cents) / 100:.2f}"


def _valid_person(name: str, email: str) -> bool:
    return (1 <= len(name) <= 120 and len(email) <= 200
            and bool(re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email)))


async def _body(request: web.Request) -> dict:
    if request.content_length is not None and request.content_length > 8192:
        raise web.HTTPRequestEntityTooLarge(max_size=8192, actual_size=request.content_length)
    try:
        body = await request.json()
    except (ValueError, UnicodeDecodeError):
        raise web.HTTPBadRequest(text="Некорректные данные")
    if not isinstance(body, dict):
        raise web.HTTPBadRequest(text="Некорректные данные")
    return body


async def _lock(session) -> None:
    # The project uses SQLite on one Railway volume. Serialize stock/code checks.
    await session.execute(text("BEGIN IMMEDIATE"))


async def _inventory(session, key: str, capacity: int) -> dict:
    cutoff = _now() - HOLD
    old_paid = await session.scalar(select(func.count()).select_from(AlloBooking).where(
        AlloBooking.walk_key == key, AlloBooking.plan.in_(("single", "use")),
        AlloBooking.status == "paid")) or 0
    old_hold = await session.scalar(select(func.count()).select_from(AlloBooking).where(
        AlloBooking.walk_key == key, AlloBooking.plan.in_(("single", "use")),
        AlloBooking.status == "pending", AlloBooking.created_at >= cutoff)) or 0
    new_paid = await session.scalar(select(func.count()).select_from(AlloWebSale).where(
        AlloWebSale.event_key == key, AlloWebSale.kind == "walk", AlloWebSale.status == "paid")) or 0
    new_hold = await session.scalar(select(func.count()).select_from(AlloWebSale).where(
        AlloWebSale.event_key == key, AlloWebSale.kind == "walk",
        AlloWebSale.status == "pending", AlloWebSale.created_at >= cutoff)) or 0
    paid = old_paid + new_paid
    held = old_hold + new_hold
    return {"capacity": capacity, "paid": paid, "held": held,
            "available": max(0, capacity - paid - held)}


async def _code_available(session, code: AlloWebCode) -> int:
    cutoff = _now() - HOLD
    active = or_(AlloWebSale.status == "paid",
                 and_(AlloWebSale.status == "pending", AlloWebSale.created_at >= cutoff))
    if code.kind == "pass":
        used = await session.scalar(select(func.count()).select_from(AlloWebSale).where(
            AlloWebSale.code_id == code.id, AlloWebSale.kind == "walk", active)) or 0
        return max(0, code.total_uses - used)
    spent = await session.scalar(select(func.coalesce(func.sum(AlloWebSale.discount_cents), 0)).where(
        AlloWebSale.code_id == code.id, AlloWebSale.kind == "walk", active)) or 0
    return max(0, code.value_cents - spent)


async def catalog(request: web.Request) -> web.Response:
    result = []
    async with get_session() as session:
        for event in _events():
            row = {key: value for key, value in event.items() if key != "status"}
            row["inventory"] = await _inventory(session, event["key"], int(event["capacity"]))
            result.append(row)
    return _json(request, {"events": result, "gift_amounts_cents": _gift_amounts()})


async def book(request: web.Request) -> web.Response:
    body = await _body(request)
    key = str(body.get("event_key") or "")[:64]
    name = str(body.get("name") or "").strip()
    email = str(body.get("email") or "").strip().lower()
    submitted_code = _normal_code(str(body.get("code") or ""))
    event = _event(key)
    if not event:
        return _json(request, {"error": "Эта прогулка сейчас недоступна."}, 404)
    if not _valid_person(name, email) or body.get("agreed") is not True:
        return _json(request, {"error": "Заполните имя, почту и согласие с условиями."}, 400)

    async with get_session() as session:
        await _lock(session)
        inventory = await _inventory(session, key, int(event["capacity"]))
        if inventory["available"] < 1:
            return _json(request, {"error": "На эту прогулку мест уже нет."}, 409)
        code, discount = None, 0
        if submitted_code:
            code = await session.scalar(select(AlloWebCode).where(
                AlloWebCode.code_hash == _hash_code(submitted_code), AlloWebCode.active.is_(True)))
            if not code:
                return _json(request, {"error": "Код не найден или уже не действует."}, 400)
            remaining = await _code_available(session, code)
            if code.kind == "pass":
                if event["category"] not in ("city", "nature"):
                    return _json(request, {"error": "Этот абонемент действует только на прогулки по городу и природе."}, 400)
                if (code.owner_email or "").lower() != email:
                    return _json(request, {"error": "Укажите почту владельца абонемента."}, 400)
                if remaining < 1:
                    return _json(request, {"error": "Все прогулки по этому абонементу использованы."}, 400)
                discount = int(event["price_cents"])
            elif code.kind == "gift":
                if remaining < 1:
                    return _json(request, {"error": "На сертификате не осталось средств."}, 400)
                discount = min(int(event["price_cents"]), remaining)
            else:
                return _json(request, {"error": "Код не подходит для этой покупки."}, 400)
        gross = int(event["price_cents"])
        due = gross - discount
        sale = AlloWebSale(
            token=secrets.token_urlsafe(24), kind="walk", event_key=key,
            event_title=str(event["title"]), event_starts_at=str(event["starts_at"]),
            event_meeting=str(event["meeting"]), event_capacity=int(event["capacity"]),
            buyer_name=name, buyer_email=email, gross_cents=gross,
            discount_cents=discount, amount_cents=due,
            code_id=code.id if code else None,
            status="paid" if due == 0 else "pending",
            paid_at=_now() if due == 0 else None,
        )
        session.add(sale)
        await session.commit()
        sale_id, token = sale.id, sale.token

    if due == 0:
        await _deliver_sale(sale_id)
        return _json(request, {"status": "paid", "token": token})
    payment = await create_payment(
        f"Allo Walks: {event['title']}",
        {"kind": "allo_v2", "sale_id": sale_id, "token": token},
        _money(due),
    )
    if not payment or not payment.get("checkout_url"):
        async with get_session() as session:
            current = await session.get(AlloWebSale, sale_id)
            if current and current.status == "pending":
                current.status = "canceled"
                await session.commit()
        return _json(request, {"error": "Не удалось открыть оплату. Попробуйте ещё раз."}, 502)
    async with get_session() as session:
        current = await session.get(AlloWebSale, sale_id)
        if current:
            current.payment_id = payment["id"]
            await session.commit()
    return _json(request, {"status": "pending", "token": token,
                           "checkout_url": payment["checkout_url"]})


async def buy_gift(request: web.Request) -> web.Response:
    body = await _body(request)
    name = str(body.get("name") or "").strip()
    email = str(body.get("email") or "").strip().lower()
    recipient_name = str(body.get("recipient_name") or "").strip()
    recipient_email = str(body.get("recipient_email") or "").strip().lower()
    message = str(body.get("message") or "").strip()[:800]
    try:
        amount = int(body.get("amount_cents"))
    except (TypeError, ValueError):
        amount = 0
    if amount not in _gift_amounts():
        return _json(request, {"error": "Выберите доступную сумму сертификата."}, 400)
    if (not _valid_person(name, email)
            or not _valid_person(recipient_name, recipient_email)
            or body.get("agreed") is not True):
        return _json(request, {"error": "Заполните данные покупателя, получателя и согласие."}, 400)
    # The encryption key must be present before we accept money for a code.
    try:
        _cipher()
    except RuntimeError:
        log.exception("Gift code encryption is not configured")
        return _json(request, {"error": "Покупка сертификатов временно недоступна."}, 503)
    async with get_session() as session:
        sale = AlloWebSale(
            token=secrets.token_urlsafe(24), kind="gift", buyer_name=name,
            buyer_email=email, recipient_name=recipient_name,
            recipient_email=recipient_email, gift_message=message,
            gross_cents=amount, discount_cents=0, amount_cents=amount,
            status="pending",
        )
        session.add(sale)
        await session.commit()
        sale_id, token = sale.id, sale.token
    payment = await create_payment(
        "Подарочный сертификат Allo Walks",
        {"kind": "allo_v2", "sale_id": sale_id, "token": token},
        _money(amount),
    )
    if not payment or not payment.get("checkout_url"):
        async with get_session() as session:
            current = await session.get(AlloWebSale, sale_id)
            if current and current.status == "pending":
                current.status = "canceled"
                await session.commit()
        return _json(request, {"error": "Не удалось открыть оплату. Попробуйте ещё раз."}, 502)
    async with get_session() as session:
        current = await session.get(AlloWebSale, sale_id)
        if current:
            current.payment_id = payment["id"]
            await session.commit()
    return _json(request, {"status": "pending", "token": token,
                           "checkout_url": payment["checkout_url"]})


async def on_payment(payment_id: str, payment: dict) -> None:
    """Called by the existing Mollie webhook and by the return/status page."""
    meta = payment.get("metadata") or {}
    if meta.get("kind") != "allo_v2":
        return
    try:
        sale_id = int(meta.get("sale_id"))
    except (TypeError, ValueError):
        return
    status = payment.get("status")
    should_deliver = False
    async with get_session() as session:
        await _lock(session)
        sale = await session.get(AlloWebSale, sale_id)
        if (not sale or sale.token != meta.get("token")
                or (sale.payment_id and sale.payment_id != payment_id)
                or payment.get("id") != payment_id):
            return
        if status in ("failed", "canceled", "expired"):
            if sale.status == "pending":
                sale.status = "canceled"
                await session.commit()
            return
        if status != "paid":
            return
        paid_amount = payment.get("amount") or {}
        if (paid_amount.get("currency") != "EUR"
                or paid_amount.get("value") != _money(sale.amount_cents)):
            log.error("Allo payment amount mismatch: sale=%s payment=%s", sale_id, payment_id)
            return
        if sale.status == "canceled":
            sale.status = "refund_requested"
            await session.commit()
            log.error("Payment received for canceled Allo sale, refund required: %s", sale_id)
            return
        if sale.status == "paid":
            should_deliver = sale.email_state in ("pending", "failed", "sending")
        elif sale.status == "pending":
            if sale.kind == "walk":
                if sale.created_at < _now() - HOLD:
                    inventory = await _inventory(session, sale.event_key, int(sale.event_capacity or 0))
                    if inventory["available"] < 1:
                        sale.status = "refund_requested"
                        await session.commit()
                        log.error("Late Allo payment without seat, refund required: sale=%s", sale_id)
                        return
                if sale.code_id and sale.created_at < _now() - HOLD:
                    code = await session.get(AlloWebCode, sale.code_id)
                    available = await _code_available(session, code) if code else 0
                    needed = 1 if code and code.kind == "pass" else sale.discount_cents
                    if available < needed:
                        sale.status = "refund_requested"
                        await session.commit()
                        log.error("Late Allo payment without code balance, refund required: sale=%s", sale_id)
                        return
            sale.status = "paid"
            sale.paid_at = _now()
            sale.payment_id = payment_id
            if sale.kind == "gift":
                existing = await session.scalar(select(AlloWebCode).where(
                    AlloWebCode.issued_sale_id == sale.id))
                if not existing:
                    raw = _new_code()
                    session.add(AlloWebCode(
                        code_hash=_hash_code(raw),
                        code_encrypted=_cipher().encrypt(raw.encode()).decode(),
                        kind="gift", value_cents=sale.gross_cents,
                        owner_email=sale.recipient_email,
                        issued_sale_id=sale.id,
                    ))
            await session.commit()
            should_deliver = True
    if should_deliver:
        await _deliver_sale(sale_id)


async def _deliver_sale(sale_id: int) -> None:
    """Reserve a single notification attempt before sending to avoid webhook duplicates."""
    async with get_session() as session:
        await _lock(session)
        sale = await session.get(AlloWebSale, sale_id)
        if not sale or sale.status != "paid" or sale.email_state not in ("pending", "failed", "sending"):
            return
        if (sale.email_state == "failed" and sale.email_attempted_at
                and sale.email_attempted_at > _now() - timedelta(minutes=5)):
            return
        # Recover a worker that stopped after reserving an email attempt.
        if (sale.email_state == "sending" and sale.email_attempted_at
                and sale.email_attempted_at > _now() - timedelta(minutes=10)):
            return
        code = None
        if sale.kind == "gift":
            code = await session.scalar(select(AlloWebCode).where(
                AlloWebCode.issued_sale_id == sale.id))
            if not code or not code.code_encrypted:
                return
        sale.email_state = "sending"
        sale.email_attempted_at = _now()
        await session.commit()
        kind = sale.kind
        buyer_email = sale.buyer_email
        buyer_name = sale.buyer_name
        recipient_email = sale.recipient_email
        recipient_name = sale.recipient_name
        gift_message = sale.gift_message
        event_title = sale.event_title
        event_starts_at = sale.event_starts_at
        event_meeting = sale.event_meeting
        amount = sale.gross_cents
        code_id = code.id if code else None
        encrypted = code.code_encrypted if code else None

    if kind == "gift":
        try:
            raw = _cipher().decrypt(encrypted.encode()).decode()
        except Exception:
            log.exception("Cannot decrypt Allo gift code for sale %s", sale_id)
            async with get_session() as session:
                sale = await session.get(AlloWebSale, sale_id)
                if sale:
                    sale.email_state = "failed"
                    await session.commit()
            return
        safe_name = html.escape(recipient_name or "")
        safe_sender = html.escape(buyer_name)
        safe_message = html.escape(gift_message or "")
        subject = "Вам подарили прогулку Allo Walks"
        body = (f"<h1>Для вас — прогулка Allo Walks</h1><p>Здравствуйте, {safe_name}.</p>"
                f"<p>{safe_sender} подарил(а) вам сертификат на €{_money(amount)}.</p>"
                + (f"<p>{safe_message}</p>" if safe_message else "")
                + f"<p>Код сертификата: <strong>{raw}</strong></p>"
                "<p>Выберите прогулку на странице Allo Walks и введите код при оформлении. "
                "Остаток сохранится для следующей покупки.</p>")
        plain = (f"Здравствуйте, {recipient_name}. {buyer_name} подарил(а) вам "
                 f"сертификат Allo Walks на €{_money(amount)}. Код: {raw}. "
                 "Введите его при покупке прогулки. Остаток сохранится.")
        target = recipient_email
    else:
        if not event_title or not event_starts_at or not event_meeting:
            async with get_session() as session:
                sale = await session.get(AlloWebSale, sale_id)
                if sale:
                    sale.email_state = "failed"
                    await session.commit()
            return
        subject = "Ваше место на прогулке Allo Walks подтверждено"
        body = (f"<h1>Место подтверждено</h1><p>Здравствуйте, {html.escape(buyer_name)}.</p>"
                f"<p><strong>{html.escape(event_title)}</strong><br>"
                f"{html.escape(event_starts_at)}<br>"
                f"Встреча: {html.escape(event_meeting)}</p>"
                "<p>Сохраните это письмо. Если появятся вопросы, ответьте на него.</p>")
        plain = (f"Место подтверждено: {event_title}, {event_starts_at}. "
                 f"Встреча: {event_meeting}.")
        target = buyer_email
    ok, detail = await send_email_message(target, subject, body, plain)
    async with get_session() as session:
        sale = await session.get(AlloWebSale, sale_id)
        if sale and sale.email_state == "sending":
            sale.email_state = "sent" if ok else "failed"
            if ok and code_id:
                code = await session.get(AlloWebCode, code_id)
                if code:
                    code.email_sent_at = _now()
            await session.commit()
    if not ok:
        log.error("Allo confirmation email failed for sale %s: %s", sale_id, detail)


async def sale_status(request: web.Request) -> web.Response:
    token = request.match_info["token"]
    async with get_session() as session:
        sale = await session.scalar(select(AlloWebSale).where(AlloWebSale.token == token))
        if not sale:
            return _json(request, {"error": "Заказ не найден."}, 404)
        payment_id, sale_id = sale.payment_id, sale.id
    if payment_id:
        payment = await get_payment(payment_id)
        if payment:
            await on_payment(payment_id, payment)
    await _deliver_sale(sale_id)
    async with get_session() as session:
        sale = await session.get(AlloWebSale, sale_id)
        return _json(request, {"status": sale.status, "kind": sale.kind,
                               "email_sent": sale.email_state == "sent"})


async def reconcile_once() -> None:
    """Recover missed Mollie webhooks and transactional email failures."""
    async with get_session() as session:
        pending = (await session.scalars(select(AlloWebSale).where(
            AlloWebSale.status == "pending", AlloWebSale.payment_id.is_not(None))
            .order_by(AlloWebSale.id.desc()).limit(50))).all()
        emails = (await session.scalars(select(AlloWebSale).where(
            AlloWebSale.status == "paid", AlloWebSale.email_state != "sent")
            .order_by(AlloWebSale.id).limit(50))).all()
        payments = [(sale.id, sale.payment_id) for sale in pending]
        email_ids = [sale.id for sale in emails]
    for _, payment_id in payments:
        payment = await get_payment(payment_id)
        if payment:
            await on_payment(payment_id, payment)
    for sale_id in email_ids:
        await _deliver_sale(sale_id)


async def reconciliation_loop() -> None:
    while True:
        try:
            await reconcile_once()
        except Exception:
            log.exception("Allo payment reconciliation failed")
        await asyncio.sleep(60)


async def payment_return(request: web.Request) -> web.Response:
    token = request.query.get("token", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{20,64}", token):
        raise web.HTTPBadRequest(text="Некорректный заказ")
    page_url = os.getenv("ALLO_PAGE_URL", "").strip()
    allowed = {_origin(config.WP_URL), _origin(config.SITE_URL)}
    if _origin(page_url) in allowed and _origin(page_url):
        separator = "&" if "?" in page_url else "?"
        raise web.HTTPFound(f"{page_url}{separator}allo_order={token}#booking")
    raise web.HTTPFound(f"/allo-walks/v2?allo_order={token}#booking")


async def page(_: web.Request) -> web.Response:
    markup = (ROOT / "static" / "allo-walks" / "wordpress-embed.html").read_text("utf-8")
    return web.Response(text=("<!doctype html><html lang='ru'><head><meta charset='utf-8'>"
                              "<meta name='viewport' content='width=device-width,initial-scale=1'>"
                              "<title>allo walks</title></head><body style='margin:0'>"
                              + markup + "</body></html>"), content_type="text/html")
