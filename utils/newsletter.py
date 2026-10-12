"""Пятничная рассылка «Неделя в Нидерландах»: подписка с сайта с подтверждением почты.

POST /api/newsletter/subscribe    {email}  → письмо «Подтвердите подписку»
GET  /api/newsletter/confirm?t=   подтверждение → подписка активна + welcome-письмо с подарком
GET|POST /api/newsletter/unsubscribe?t=   отписка в один клик (ссылка в каждом письме)
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

from aiohttp import web
from sqlalchemy import func, select

import config
from database.db import get_session
from database.models import WeekSubscriber
from utils.allo_v2 import _cors
from utils.email_templates import confirm_week, welcome_week
from utils.invoices import send_email_message
from utils.site_api import EMAIL_RE, _api_base, _body, _err, _html_page, _json, make_token, read_token

GIFT_URL = "https://t.me/podslushano_nl_bot?start=tax_guide_2026"
_hits: dict[str, list[float]] = {}


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def unsubscribe_url(email: str) -> str:
    return f"{_api_base()}/api/newsletter/unsubscribe?t={make_token({'k': 'wunsub', 'e': email}, 10 * 365 * 86400)}"


def _limited(key: str, limit: int, window: int = 3600) -> bool:
    now = time.time()
    hits = [t for t in _hits.get(key, []) if now - t < window]
    _hits[key] = hits
    if len(hits) >= limit:
        return True
    hits.append(now)
    return False


async def subscribe(request: web.Request) -> web.Response:
    data = await _body(request)
    email = str(data.get("email") or "").strip().lower()[:200]
    if not EMAIL_RE.match(email):
        return _err(request, "Проверьте почту.")
    ip = request.headers.get("X-Forwarded-For", request.remote or "").split(",")[0].strip()
    if _limited(f"ip:{ip}", 10) or _limited(f"e:{email}", 3, 86400):
        return _err(request, "Слишком много попыток. Попробуйте позже.", 429)
    async with get_session() as session:
        row = (await session.execute(select(WeekSubscriber).where(WeekSubscriber.email == email))).scalar_one_or_none()
        if row and row.status == "active":
            return _json(request, {"ok": True, "already": True})
        if row is None:
            row = WeekSubscriber(email=email, status="pending", source=str(data.get("source") or "site")[:40])
            session.add(row)
        else:
            row.status = "pending"
        await session.commit()
    link = f"{_api_base()}/api/newsletter/confirm?t={make_token({'k': 'wconf', 'e': email}, 7 * 86400)}"
    ok, _ = await send_email_message(email, *confirm_week(confirm_url=link))
    if not ok:
        return _err(request, "Не удалось отправить письмо. Попробуйте ещё раз позже.", 502)
    return _json(request, {"ok": True})


async def confirm(request: web.Request) -> web.Response:
    data = read_token(request.query.get("t", ""), "wconf")
    if not data:
        return _html_page("Ссылка устарела", "Подпишитесь ещё раз на сайте, и мы пришлём новую ссылку.")
    email = data["e"]
    first = False
    async with get_session() as session:
        row = (await session.execute(select(WeekSubscriber).where(WeekSubscriber.email == email))).scalar_one_or_none()
        if row is None:
            row = WeekSubscriber(email=email, status="pending")
            session.add(row)
        if row.status != "active":
            first = row.confirmed_at is None
            row.status, row.confirmed_at, row.unsubscribed_at = "active", row.confirmed_at or _now(), None
        await session.commit()
    if first:
        unsub = unsubscribe_url(email)
        await send_email_message(email, *welcome_week(unsubscribe_url=unsub, gift_url=GIFT_URL), unsubscribe_url=unsub)
    return _html_page("Подписка подтверждена",
                      "Готово! «Неделя в Нидерландах» будет приходить по пятницам. "
                      "Подарок, гайд «Налоги и субсидии 2026», уже в письме.")


async def unsubscribe(request: web.Request) -> web.Response:
    token = request.query.get("t", "")
    data = read_token(token, "wunsub")
    if not data:
        return _html_page("Ссылка не работает", f"Напишите нам на {config.COMPANY_EMAIL}, и мы отпишем вас вручную.")
    if request.method == "GET":
        form = (f"<form method='post' action='?t={token}'>"
                "<button type='submit'>Отписаться от рассылки</button></form>")
        return _html_page("Отписаться от «Недели в Нидерландах»?", "Письма перестанут приходить сразу.", form)
    async with get_session() as session:
        row = (await session.execute(select(WeekSubscriber).where(WeekSubscriber.email == data["e"]))).scalar_one_or_none()
        if row and row.status != "unsubscribed":
            row.status, row.unsubscribed_at = "unsubscribed", _now()
            await session.commit()
    return _html_page("Вы отписались", "Больше писем не будет. Если передумаете, подписаться можно на сайте в любой момент.")


async def active_count() -> int:
    async with get_session() as session:
        return int(await session.scalar(select(func.count()).select_from(WeekSubscriber)
                                        .where(WeekSubscriber.status == "active")) or 0)


async def _options(request: web.Request) -> web.Response:
    return _cors(request, web.Response(status=204))


def install_routes(app: web.Application) -> None:
    app.router.add_post("/api/newsletter/subscribe", subscribe)
    app.router.add_route("OPTIONS", "/api/newsletter/subscribe", _options)
    app.router.add_get("/api/newsletter/confirm", confirm)
    app.router.add_get("/api/newsletter/unsubscribe", unsubscribe)
    app.router.add_post("/api/newsletter/unsubscribe", unsubscribe)
