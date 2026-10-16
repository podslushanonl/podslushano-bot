"""Платные функции приложения. Сейчас одна: «Премиум верификация» — синяя галочка за 3,99 € в месяц.

GET  /api/app/billing/verify          — статус: есть ли галочка, до какого числа, цена, готова ли оплата, есть ли подписка
POST /api/app/billing/verify          — начать оплату: {url} страницы оплаты Mollie (первый платёж подписки)
POST /api/app/billing/verify/cancel   — отменить подписку (галочка остаётся до конца оплаченного месяца)

Оплата — Mollie (тот же MOLLIE_API_KEY и вебхук /mollie-webhook, что у донатов): iDEAL, Bancontact, карта,
Apple Pay. Первый платёж (sequenceType=first) создаёт мандат; после его оплаты заводится подписка «1 месяц»,
и Mollie сам списывает 3,99 € каждый месяц. Каждый платёж приходит в вебхук (kind app_verify / app_verify_sub,
см. handlers/selfadd.on_payment_paid) → on_mollie_payment.

После оплаты: is_verified = True, verified_until = через месяц (+ 3 дня запаса на автосписание); каждое
списание по подписке сдвигает срок (один раз на платёж — повторные уведомления Mollie не продлевают дважды).
Срок истёк, а списания нет — галочка снимается (app_api.expire_paid). Галочку создателя
(verified_until = NULL) оплата и истечение не трогают.

Без Mollie работает проверочный режим BILLING_MOCK=1 (только для разработки и тестов!): «оплата» проходит сразу.
"""
from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta, timezone

from aiohttp import web
from sqlalchemy import select

import config
from database.db import get_session
from database.models import AppPayment, AppUser
from utils.app_api import _user, expire_paid, user_json
from utils.community import _rate
from utils.site_api import _err, _json, _mollie

log = logging.getLogger(__name__)

PRICE_CENTS = 399
PRICE = "3.99"
CURRENCY = "EUR"
PERIOD = timedelta(days=31)
GRACE = timedelta(days=3)          # запас на задержку автосписания
DESCRIPTION = "podslushano.nl — Premium verificatie"


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def mollie_ready() -> bool:
    return config.payments_enabled()


def mock_mode() -> bool:
    return os.getenv("BILLING_MOCK", "").strip() == "1" and not mollie_ready()


async def _subscription(session, user_id: int) -> AppPayment | None:
    """Действующая подписка Mollie: строка kind=verify_sub, external_id = «customer/subscription»."""
    return (await session.execute(select(AppPayment).where(
        AppPayment.user_id == user_id, AppPayment.kind == "verify_sub", AppPayment.status == "active")
        .order_by(AppPayment.id.desc()))).scalars().first()


async def _status(session, u: AppUser) -> dict:
    return {"verified": bool(u.is_verified), "until": u.verified_until.strftime("%Y-%m-%d") if u.verified_until else "",
            "lifetime": bool(u.is_verified and not u.verified_until),
            "subscribed": bool(await _subscription(session, u.id)),
            "price": PRICE_CENTS / 100, "currency": CURRENCY,
            "available": mollie_ready() or mock_mode(), "mock": mock_mode()}


async def grant(session, user_id: int, payment: AppPayment | None = None) -> AppUser | None:
    """Оплата прошла: галочка и срок на месяц вперёд (от текущего срока, если он ещё не истёк)."""
    u = await session.get(AppUser, user_id)
    if not u:
        return None
    if payment and payment.status != "paid":
        payment.status, payment.paid_at = "paid", _now()
    if u.is_verified and not u.verified_until:
        return u   # бессрочная галочка (создатель) — не превращаем в платную
    start = max(u.verified_until or _now(), _now())
    u.is_verified, u.verified_until = True, start + PERIOD + (GRACE if not u.verified_until else timedelta(0))
    return u


async def verify(request: web.Request) -> web.Response:
    async with get_session() as session:
        me = await _user(request, session)
        if not me:
            await session.commit()
            return _err(request, "Войдите заново.", 401)
        if await expire_paid(session, force=True):
            await session.refresh(me)
        if request.method == "GET":
            out = await _status(session, me)
            await session.commit()
            return _json(request, {"ok": True, **out})
        if me.is_verified and not me.verified_until:
            await session.commit()
            return _err(request, "У вас уже есть бессрочная галочка.", 409)
        if await _subscription(session, me.id):
            await session.commit()
            return _err(request, "Подписка уже оформлена — галочка продлевается автоматически.", 409)
        if _rate(f"billing:{me.id}", 10, 3600):
            await session.commit()
            return _err(request, "Слишком много попыток. Попробуйте через час.", 429)
        if not (mollie_ready() or mock_mode()):
            await session.commit()
            return _err(request, "Оплата временно недоступна. Попробуйте позже.", 503)
        pay = AppPayment(user_id=me.id, kind="verify", provider="mollie" if mollie_ready() else "mock",
                         amount_cents=PRICE_CENTS, currency=CURRENCY)
        session.add(pay)
        await session.flush()
        if pay.provider == "mock":
            # Проверочный режим: «оплата» проходит сразу — так же, как после вебхука Mollie
            u = await grant(session, me.id, pay)
            out = {"ok": True, "paid": True, "user": user_json(u), **await _status(session, u)}
            await session.commit()
            log.info("Верификация (проверочный режим): пользователь %s", me.id)
            return _json(request, out)
        pid, uid = pay.id, me.id
        name = f"@{me.username}" if me.username else (me.name or f"user{me.id}")
        email = me.email or None
        await session.commit()
    base = config.WEBHOOK_BASE_URL.rstrip("/")
    customer = await _mollie("POST", "/customers", {"name": name, **({"email": email} if email else {})})
    if not customer or not customer.get("id"):
        return _err(request, "Не получилось открыть оплату. Попробуйте позже.", 502)
    payment = await _mollie("POST", "/payments", {
        "amount": {"currency": CURRENCY, "value": PRICE},
        "description": DESCRIPTION,
        "redirectUrl": f"{base}/app/premium?paid=1",
        "webhookUrl": f"{base}/mollie-webhook",
        "customerId": customer["id"],
        "sequenceType": "first",
        "metadata": {"kind": "app_verify", "payment_id": pid, "user_id": uid, "customer_id": customer["id"]},
    })
    checkout = ((payment or {}).get("_links") or {}).get("checkout", {}).get("href")
    if not checkout:
        return _err(request, "Не получилось открыть оплату. Попробуйте позже.", 502)
    async with get_session() as session:
        row = await session.get(AppPayment, pid)
        row.external_id = payment.get("id")
        await session.commit()
    return _json(request, {"ok": True, "url": checkout})


async def on_mollie_payment(payment_id: str, payment: dict) -> None:
    """Вебхук Mollie (вызывается из handlers/selfadd.on_payment_paid) для kind app_verify и app_verify_sub."""
    if payment.get("status") != "paid":
        return
    meta = payment.get("metadata") or {}
    try:
        uid = int(meta.get("user_id") or 0)
    except (TypeError, ValueError):
        uid = 0
    if not uid:
        return
    async with get_session() as session:
        # Каждый платёж Mollie засчитывается один раз: повторные уведомления о нём ничего не продлевают
        if (await session.execute(select(AppPayment.id).where(
                AppPayment.external_id == payment_id, AppPayment.status == "paid"))).first():
            return
        if meta.get("kind") == "app_verify":
            row = await session.get(AppPayment, int(meta.get("payment_id") or 0))
            if not row or row.user_id != uid:
                return
            row.external_id = payment_id
            await grant(session, uid, row)
            customer_id = meta.get("customer_id") or payment.get("customerId")
            await session.commit()
            log.info("Премиум верификация оплачена: пользователь %s", uid)
            # Подписка: следующее списание через месяц, дальше — каждый месяц
            sub = await _mollie("POST", f"/customers/{customer_id}/subscriptions", {
                "amount": {"currency": CURRENCY, "value": PRICE},
                "interval": "1 month",
                "startDate": (date.today() + timedelta(days=30)).isoformat(),
                "description": DESCRIPTION,
                "webhookUrl": f"{config.WEBHOOK_BASE_URL.rstrip('/')}/mollie-webhook",
                "metadata": {"kind": "app_verify_sub", "user_id": uid},
            }) if customer_id else None
            if not sub or not sub.get("id"):
                log.error("Mollie: не создалась подписка на верификацию (пользователь %s)", uid)
                return
            session.add(AppPayment(user_id=uid, kind="verify_sub", provider="mollie", amount_cents=PRICE_CENTS,
                                   currency=CURRENCY, status="active", external_id=f"{customer_id}/{sub['id']}"))
            await session.commit()
            return
        if meta.get("kind") == "app_verify_sub":
            session.add(AppPayment(user_id=uid, kind="verify", provider="mollie", amount_cents=PRICE_CENTS,
                                   currency=CURRENCY, status="paid", external_id=payment_id, paid_at=_now()))
            await grant(session, uid)
            await session.commit()
            log.info("Премиум верификация продлена: пользователь %s", uid)


async def cancel(request: web.Request) -> web.Response:
    """Отмена подписки: дальше не списываем, галочка остаётся до конца оплаченного срока и снимается сама."""
    async with get_session() as session:
        me = await _user(request, session)
        if not me:
            await session.commit()
            return _err(request, "Войдите заново.", 401)
        sub = await _subscription(session, me.id)
        await session.commit()
    if not sub:
        return _err(request, "Активной подписки нет.", 404)
    customer_id, sub_id = (sub.external_id or "/").split("/", 1)
    if await _mollie("DELETE", f"/customers/{customer_id}/subscriptions/{sub_id}") is None:
        return _err(request, "Не получилось отменить. Попробуйте позже или напишите нам.", 502)
    async with get_session() as session:
        row = await session.get(AppPayment, sub.id)
        row.status = "canceled"
        me = await session.get(AppUser, me.id)
        out = await _status(session, me)
        await session.commit()
    return _json(request, {"ok": True, **out})


def install_routes(app: web.Application) -> None:
    app.router.add_get("/api/app/billing/verify", verify)
    app.router.add_post("/api/app/billing/verify", verify)
    app.router.add_post("/api/app/billing/verify/cancel", cancel)
