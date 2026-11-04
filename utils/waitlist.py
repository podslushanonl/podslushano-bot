"""Лист ожидания товара партнёра на сайте (первая кампания — свеча Soul of Sol × podslushano.nl).

POST /api/waitlist/<campaign>/join  {email, consent}  → сразу в списке + письмо «Вы в листе ожидания» с отпиской
GET  /api/waitlist/<campaign>                         → {"count": N, "stock": 24, "buy": ""} для баннера
GET|POST /api/waitlist/unsubscribe?t=                 → выйти из списка
GET  /api/waitlist/confirm?t=                         → только для старых писем с подтверждением

Запись в один шаг: человек сам ставит галочку согласия, отдельного подтверждения нет.
Данные нужны только для письма о старте продаж; партнёру мы передаём число, а не адреса.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from aiohttp import web
from sqlalchemy import func, select

import config
from database.db import get_session
from database.models import WaitlistEntry
from utils.allo_v2 import _cors
from utils.email_templates import waitlist_joined
from utils.invoices import send_email_message
from utils.site_api import EMAIL_RE, _api_base, _body, _err, _html_page, _json, make_token, read_token

# Кампании: название для писем, сколько товара в первой партии
CAMPAIGNS = {
    "candle": {"title": "рождественская свеча Soul of Sol × podslushano.nl «Пахнет как дома»", "stock": 24},
}
_hits: dict[str, list[float]] = {}
log = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _limited(key: str, limit: int, window: int = 3600) -> bool:
    now = time.time()
    hits = [t for t in _hits.get(key, []) if now - t < window]
    _hits[key] = hits
    if len(hits) >= limit:
        return True
    hits.append(now)
    return False


def unsubscribe_url(campaign: str, entry_id: int) -> str:
    return f"{_api_base()}/api/waitlist/unsubscribe?t={make_token({'k': 'wlout', 'c': campaign, 'i': entry_id}, 365 * 86400)}"


async def count(campaign: str) -> int:
    async with get_session() as session:
        return int(await session.scalar(select(func.count()).select_from(WaitlistEntry).where(
            WaitlistEntry.campaign == campaign, WaitlistEntry.status == "active")) or 0)


async def position(campaign: str, entry: WaitlistEntry) -> int:
    async with get_session() as session:
        return int(await session.scalar(select(func.count()).select_from(WaitlistEntry).where(
            WaitlistEntry.campaign == campaign, WaitlistEntry.status == "active",
            WaitlistEntry.confirmed_at <= entry.confirmed_at)) or 0)


async def join(request: web.Request) -> web.Response:
    campaign = request.match_info.get("campaign", "")
    if campaign not in CAMPAIGNS:
        return _err(request, "Лист ожидания не найден.", 404)
    data = await _body(request)
    email = str(data.get("email") or "").strip().lower()[:200]
    if not EMAIL_RE.match(email):
        return _err(request, "Проверьте почту.")
    if str(data.get("consent") or "") not in ("1", "true", "on", "True"):
        return _err(request, "Подтвердите согласие на письмо о старте продаж.")
    ip = request.headers.get("X-Forwarded-For", request.remote or "").split(",")[0].strip()
    if _limited(f"ip:{ip}", 10) or _limited(f"e:{campaign}:{email}", 3, 86400):
        return _err(request, "Слишком много попыток. Попробуйте позже.", 429)
    async with get_session() as session:
        row = (await session.execute(select(WaitlistEntry).where(
            WaitlistEntry.campaign == campaign, WaitlistEntry.email == email))).scalars().first()
        already = bool(row and row.status == "active")
        if row is None:
            row = WaitlistEntry(campaign=campaign, email=email, source=str(data.get("source") or "site")[:40])
            session.add(row)
        if not already:
            row.status, row.confirmed_at = "active", _now()
        await session.commit()
        await session.refresh(row)
    n = await position(campaign, row)
    if not already:
        info = CAMPAIGNS[campaign]
        try:
            ok, err = await send_email_message(email, *waitlist_joined(
                title=info["title"], position=n, stock=info["stock"],
                unsubscribe_url=unsubscribe_url(campaign, row.id)))
            if not ok:
                log.info("Лист ожидания: письмо #%s не ушло: %s", row.id, err)
        except Exception as e:  # noqa: BLE001 — место в списке уже сохранено, письмо не главное
            log.info("Лист ожидания: письмо #%s не ушло: %s", row.id, e)
    return _json(request, {"ok": True, "already": already, "position": n, "count": await count(campaign)})


async def confirm(request: web.Request) -> web.Response:
    data = read_token(request.query.get("t", ""), "wlok")
    if not data or data.get("c") not in CAMPAIGNS:
        return _html_page("Ссылка устарела", "Запишитесь ещё раз на podslushano.nl, и мы пришлём новую ссылку.")
    async with get_session() as session:
        row = await session.get(WaitlistEntry, int(data["i"]))
        if row is None:
            return _html_page("Ссылка устарела", "Запишитесь ещё раз на podslushano.nl.")
        if row.status != "active":
            row.status, row.confirmed_at = "active", _now()
            await session.commit()
            await session.refresh(row)
    n = await position(data["c"], row)
    stock = CAMPAIGNS[data["c"]]["stock"]
    return _html_page("Вы в листе ожидания",
                      f"Готово! Вы {n}-й в списке, а в первой партии {stock} штук. "
                      "Мы напишем вам первыми в день старта продаж.")


async def unsubscribe(request: web.Request) -> web.Response:
    token = request.query.get("t", "")
    data = read_token(token, "wlout")
    if not data:
        return _html_page("Ссылка не работает", f"Напишите нам на {config.COMPANY_EMAIL}, и мы уберём вас вручную.")
    if request.method == "GET":
        form = f"<form method='post' action='?t={token}'><button type='submit'>Выйти из листа ожидания</button></form>"
        return _html_page("Выйти из листа ожидания?", "Писем о старте продаж больше не будет.", form)
    async with get_session() as session:
        row = await session.get(WaitlistEntry, int(data["i"]))
        if row and row.status != "unsubscribed":
            row.status = "unsubscribed"
            await session.commit()
    return _html_page("Готово", "Вы вышли из листа ожидания.")


async def stats(request: web.Request) -> web.Response:
    campaign = request.match_info.get("campaign", "")
    if campaign not in CAMPAIGNS:
        return _err(request, "Лист ожидания не найден.", 404)
    from database.models import Meta
    async with get_session() as session:
        m = await session.get(Meta, f"waitlist_open_url:{campaign}")   # ставит /candle_open: продажи открыты
    resp = _json(request, {"count": await count(campaign), "stock": CAMPAIGNS[campaign]["stock"],
                           "buy": m.value if m else ""})
    resp.headers["Cache-Control"] = "public, max-age=60"
    return resp


async def _options(request: web.Request) -> web.Response:
    return _cors(request, web.Response(status=204))


def install_routes(app: web.Application) -> None:
    app.router.add_post("/api/waitlist/{campaign}/join", join)
    app.router.add_route("OPTIONS", "/api/waitlist/{campaign}/join", _options)
    app.router.add_get("/api/waitlist/confirm", confirm)
    app.router.add_get("/api/waitlist/unsubscribe", unsubscribe)
    app.router.add_post("/api/waitlist/unsubscribe", unsubscribe)
    app.router.add_get("/api/waitlist/{campaign}", stats)
