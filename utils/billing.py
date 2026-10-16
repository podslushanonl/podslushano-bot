"""Платные функции приложения. Сейчас одна: «Премиум верификация» — синяя галочка за 3,99 € в месяц.

GET  /api/app/billing/verify          — статус: есть ли галочка, до какого числа, цена, готова ли оплата
POST /api/app/billing/verify          — начать оплату: {url} страницы оплаты Stripe Checkout (подписка)
POST /api/app/billing/stripe/webhook  — уведомления Stripe (подпись Stripe-Signature проверяется)

Оплата через Stripe включается переменными STRIPE_SECRET_KEY и STRIPE_WEBHOOK_SECRET (в Stripe: вебхук на
{WEBHOOK_BASE_URL}/api/app/billing/stripe/webhook с событиями checkout.session.completed, invoice.paid,
customer.subscription.deleted). Цена задаётся прямо в запросе (price_data) — отдельный товар в Stripe не нужен;
можно указать готовую цену STRIPE_PRICE_VERIFY.

Без Stripe работает проверочный режим BILLING_MOCK=1 (только для разработки и тестов!): «оплата» проходит сразу.
В рабочем приложении без ключей Stripe кнопка показывает «скоро» — бесплатно галочку получить нельзя.

После оплаты: is_verified = True, verified_until = через месяц (+ 3 дня запаса на продление); каждое продление
подписки (invoice.paid) сдвигает срок. Срок истёк, а продления нет — галочка снимается (expire_paid). Галочку,
выданную администратором (verified_until = NULL), оплата и истечение не трогают.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone

import aiohttp
from aiohttp import web
from sqlalchemy import select, update

import config
from database.db import get_session
from database.models import AppPayment, AppUser
from utils.app_api import _user, expire_paid, user_json
from utils.community import _rate
from utils.site_api import _err, _json

log = logging.getLogger(__name__)

PRICE_CENTS = 399
CURRENCY = "EUR"
PERIOD = timedelta(days=31)
GRACE = timedelta(days=3)          # запас на задержку автоплатежа
STRIPE_API = "https://api.stripe.com/v1"
SIG_TOLERANCE = 300                # секунд: старше — отклоняем (защита от повтора)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _env(name: str) -> str:
    return os.getenv(name, "").strip()


def stripe_ready() -> bool:
    return bool(_env("STRIPE_SECRET_KEY") and _env("STRIPE_WEBHOOK_SECRET"))


def mock_mode() -> bool:
    return _env("BILLING_MOCK") == "1" and not stripe_ready()


def _status(u: AppUser) -> dict:
    return {"verified": bool(u.is_verified), "until": u.verified_until.strftime("%Y-%m-%d") if u.verified_until else "",
            "lifetime": bool(u.is_verified and not u.verified_until),
            "price": PRICE_CENTS / 100, "currency": CURRENCY,
            "available": stripe_ready() or mock_mode(), "mock": mock_mode()}


async def grant(session, user_id: int, payment: AppPayment | None = None) -> AppUser | None:
    """Оплата прошла: галочка и срок на месяц вперёд (от текущего срока, если он ещё не истёк)."""
    u = await session.get(AppUser, user_id)
    if not u:
        return None
    if payment and payment.status != "paid":
        payment.status, payment.paid_at = "paid", _now()
    if u.is_verified and not u.verified_until:
        return u   # бессрочная галочка (создатель, выдана вручную) — не превращаем в платную
    start = max(u.verified_until or _now(), _now())
    u.is_verified, u.verified_until = True, start + PERIOD + (GRACE if not u.verified_until else timedelta(0))
    return u


async def _stripe(path: str, form: dict) -> dict:
    async with aiohttp.ClientSession() as s:
        async with s.post(f"{STRIPE_API}/{path}", data=form, auth=aiohttp.BasicAuth(_env("STRIPE_SECRET_KEY"), ""),
                          timeout=aiohttp.ClientTimeout(total=20)) as r:
            data = await r.json(content_type=None)
            if r.status >= 300:
                raise RuntimeError((data.get("error") or {}).get("message") or f"Stripe HTTP {r.status}")
            return data


async def verify(request: web.Request) -> web.Response:
    async with get_session() as session:
        me = await _user(request, session)
        if not me:
            await session.commit()
            return _err(request, "Войдите заново.", 401)
        if await expire_paid(session, force=True):
            await session.refresh(me)
        if request.method == "GET":
            out = _status(me)
            await session.commit()
            return _json(request, {"ok": True, **out})
        if me.is_verified and not me.verified_until:
            await session.commit()
            return _err(request, "У вас уже есть бессрочная галочка.", 409)
        if _rate(f"billing:{me.id}", 10, 3600):
            await session.commit()
            return _err(request, "Слишком много попыток. Попробуйте через час.", 429)
        if not (stripe_ready() or mock_mode()):
            await session.commit()
            return _err(request, "Оплата скоро появится. Мы сообщим, когда можно будет подключить галочку.", 503)
        pay = AppPayment(user_id=me.id, kind="verify", provider="stripe" if stripe_ready() else "mock",
                         amount_cents=PRICE_CENTS, currency=CURRENCY)
        session.add(pay)
        await session.flush()
        if pay.provider == "mock":
            # Проверочный режим: «оплата» проходит сразу — так же, как после вебхука Stripe
            u = await grant(session, me.id, pay)
            out = {"ok": True, "paid": True, "user": user_json(u), **_status(u)}
            await session.commit()
            log.info("Верификация (проверочный режим): пользователь %s", me.id)
            return _json(request, out)
        base = config.WEBHOOK_BASE_URL or config.SITE_URL
        form = {
            "mode": "subscription",
            "client_reference_id": str(pay.id),
            "metadata[payment_id]": str(pay.id), "metadata[user_id]": str(me.id),
            "subscription_data[metadata][user_id]": str(me.id),
            "success_url": f"{base}/app/premium?paid=1", "cancel_url": f"{base}/app/premium?canceled=1",
            "line_items[0][quantity]": "1",
            "locale": "auto",
        }
        if _env("STRIPE_PRICE_VERIFY"):
            form["line_items[0][price]"] = _env("STRIPE_PRICE_VERIFY")
        else:
            form |= {"line_items[0][price_data][currency]": CURRENCY.lower(),
                     "line_items[0][price_data][unit_amount]": str(PRICE_CENTS),
                     "line_items[0][price_data][recurring][interval]": "month",
                     "line_items[0][price_data][product_data][name]": "podslushano.nl — Премиум верификация"}
        if me.email:
            form["customer_email"] = me.email
        await session.commit()
    try:
        cs = await _stripe("checkout/sessions", form)
    except Exception as e:  # noqa: BLE001
        log.error("Stripe Checkout: %s", e)
        return _err(request, "Не получилось открыть оплату. Попробуйте позже.", 502)
    async with get_session() as session:
        await session.execute(update(AppPayment).where(AppPayment.id == pay.id).values(external_id=cs.get("id")))
        await session.commit()
    return _json(request, {"ok": True, "url": cs.get("url")})


def check_signature(payload: bytes, header: str, secret: str, now: float | None = None) -> bool:
    """Подпись Stripe: t=<время>,v1=<HMAC-SHA256(secret, "t.payload")>."""
    parts = dict(p.split("=", 1) for p in header.split(",") if "=" in p)
    try:
        ts = int(parts.get("t", ""))
    except ValueError:
        return False
    if abs((now or time.time()) - ts) > SIG_TOLERANCE:
        return False
    expected = hmac.new(secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    sigs = [v for k, v in (p.split("=", 1) for p in header.split(",") if "=" in p) if k == "v1"]
    return any(hmac.compare_digest(expected, s) for s in sigs)


async def stripe_webhook(request: web.Request) -> web.Response:
    payload = await request.read()
    secret = _env("STRIPE_WEBHOOK_SECRET")
    if not secret or not check_signature(payload, request.headers.get("Stripe-Signature", ""), secret):
        return web.Response(status=400, text="bad signature")
    try:
        ev = json.loads(payload)
    except ValueError:
        return web.Response(status=400, text="bad json")
    kind, obj = ev.get("type", ""), (ev.get("data") or {}).get("object") or {}
    async with get_session() as session:
        if kind == "checkout.session.completed" and obj.get("payment_status") in ("paid", "no_payment_required"):
            pid = int((obj.get("metadata") or {}).get("payment_id") or obj.get("client_reference_id") or 0)
            pay = await session.get(AppPayment, pid) if pid else None
            if pay and pay.status != "paid":
                pay.external_id = obj.get("subscription") or pay.external_id
                await grant(session, pay.user_id, pay)
                log.info("Верификация оплачена: пользователь %s", pay.user_id)
        elif kind == "invoice.paid" and obj.get("billing_reason") == "subscription_cycle" and obj.get("id"):
            # Продление: срок ещё на месяц. Stripe может прислать одно событие несколько раз — каждый счёт
            # записываем отдельным платежом (external_id = id счёта) и продлеваем только по новому
            pay = (await session.execute(select(AppPayment).where(
                AppPayment.external_id == obj.get("subscription")))).scalars().first()
            seen = (await session.execute(select(AppPayment.id).where(AppPayment.external_id == obj["id"]))).first()
            if pay and not seen:
                session.add(AppPayment(user_id=pay.user_id, kind="verify", provider="stripe", amount_cents=PRICE_CENTS,
                                       currency=CURRENCY, status="paid", external_id=obj["id"], paid_at=_now()))
                await grant(session, pay.user_id)
        elif kind == "customer.subscription.deleted":
            # Отменили: галочка остаётся до конца оплаченного срока, потом снимется сама
            pay = (await session.execute(select(AppPayment).where(AppPayment.external_id == obj.get("id")))).scalars().first()
            if pay:
                pay.status = "canceled"
        await session.commit()
    return web.json_response({"received": True})


def install_routes(app: web.Application) -> None:
    app.router.add_get("/api/app/billing/verify", verify)
    app.router.add_post("/api/app/billing/verify", verify)
    app.router.add_post("/api/app/billing/stripe/webhook", stripe_webhook)
