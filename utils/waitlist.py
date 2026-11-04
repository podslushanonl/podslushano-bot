"""Лист ожидания товара партнёра на сайте (первая кампания — свеча Soul of Sol × podslushano.nl).

POST /api/waitlist/<campaign>/join  {email, consent}  → письмо «Подтвердите место» (защита от чужих адресов)
GET  /api/waitlist/confirm?t=                         → место подтверждено, страница с номером в списке
GET  /api/waitlist/<campaign>                         → {"count": N, "stock": 24} для баннера на сайте
GET|POST /api/waitlist/unsubscribe?t=                 → выйти из списка

Через Telegram записываются по ссылке t.me/<бот>?start=wl_<campaign> (handlers/waitlist.py).
Данные нужны только для одного письма о старте продаж; партнёру мы передаём число, а не адреса.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

from aiohttp import web
from sqlalchemy import func, select

import config
from database.db import get_session
from database.models import WaitlistEntry
from utils.allo_v2 import _cors
from utils.email_templates import waitlist_confirm
from utils.invoices import send_email_message
from utils.site_api import EMAIL_RE, _api_base, _body, _err, _html_page, _json, make_token, read_token

# Кампании: название для писем, сколько товара в первой партии
CAMPAIGNS = {
    "candle": {"title": "рождественская свеча Soul of Sol × podslushano.nl «Пахнет как дома»", "stock": 24},
}
_hits: dict[str, list[float]] = {}


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


async def add_telegram(campaign: str, user_id: int) -> tuple[bool, int]:
    """Записывает пользователя бота. (новый ли, номер в списке)."""
    async with get_session() as session:
        row = (await session.execute(select(WaitlistEntry).where(
            WaitlistEntry.campaign == campaign, WaitlistEntry.tg_user_id == user_id))).scalars().first()
        new = row is None or row.status != "active"
        if row is None:
            row = WaitlistEntry(campaign=campaign, tg_user_id=user_id, source="telegram")
            session.add(row)
        if row.status != "active":
            row.status, row.confirmed_at = "active", _now()
        await session.commit()
        await session.refresh(row)
    return new, await position(campaign, row)


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
        if row and row.status == "active":
            return _json(request, {"ok": True, "already": True})
        if row is None:
            row = WaitlistEntry(campaign=campaign, email=email, source=str(data.get("source") or "site")[:40])
            session.add(row)
        row.status = "pending"
        await session.commit()
        await session.refresh(row)
    link = f"{_api_base()}/api/waitlist/confirm?t={make_token({'k': 'wlok', 'c': campaign, 'i': row.id}, 7 * 86400)}"
    ok, _ = await send_email_message(email, *waitlist_confirm(title=CAMPAIGNS[campaign]["title"], confirm_url=link))
    if not ok:
        return _err(request, "Не удалось отправить письмо. Попробуйте ещё раз позже.", 502)
    return _json(request, {"ok": True})


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
