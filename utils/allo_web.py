"""Публичная витрина Allo Walks: каталог, лист ожидания и подготовка оплаты."""
from __future__ import annotations

import html
import json
from datetime import datetime, timedelta
from pathlib import Path

from aiohttp import web
from sqlalchemy import and_, func, or_, select

import config
from database.db import get_session
from database.models import AlloBooking
from utils.payments import create_payment


def _safe(value: object) -> str:
    return html.escape(str(value or ""))


def _public_walk(walk: dict) -> dict:
    return {key: walk.get(key) for key in (
        "key", "starts_at", "status", "date", "title", "place", "meet",
        "finish", "dur", "price", "tag", "tone", "desc")}


async def api_walks(_: web.Request) -> web.Response:
    return web.json_response({"walks": [_public_walk(w) for w in config.ALLO_WALKS
                                        if w.get("status") != "archived"]},
                             dumps=lambda value: json.dumps(value, ensure_ascii=False))


async def waitlist(request: web.Request) -> web.Response:
    data = await request.post()
    key = str(data.get("walk") or "").strip()
    name = str(data.get("name") or "").strip()[:120]
    email = str(data.get("email") or "").strip()[:200]
    telegram = str(data.get("telegram") or "").strip().lstrip("@").replace("https://t.me/", "")[:64]
    walk = config.allo_walk(key)
    if not walk or not name or "@" not in email:
        return web.json_response({"ok": False, "error": "Заполните имя и корректный e-mail."}, status=400)
    async with get_session() as session:
        session.add(AlloBooking(walk_key=key, plan="single", user_id=0,
                                username=telegram or None, first_name=name,
                                email=email, status="waitlist", agreed=True))
        await session.commit()
    bot = request.app["bot"]
    message = (f"✨ <b>Новый лист ожидания Allo Walks</b>\n\n"
               f"{_safe(walk['title'])}\n{_safe(name)} · {_safe(email)}"
               f"\nTelegram: @{_safe(telegram) if telegram else '—'}")
    for admin_id in config.ADMIN_IDS:
        try:
            await bot.send_message(admin_id, message)
        except Exception:
            pass
    return web.json_response({"ok": True})


async def book(request: web.Request) -> web.Response:
    data = await request.post()
    key = str(data.get("walk") or "").strip()
    walk = config.allo_walk(key)
    name = str(data.get("name") or "").strip()[:120]
    email = str(data.get("email") or "").strip()[:200]
    telegram = str(data.get("telegram") or "").strip().lstrip("@").replace("https://t.me/", "")[:64]
    if (not walk or walk.get("status") != "open" or not walk.get("price")
            or not walk.get("starts_at") or datetime.fromisoformat(walk["starts_at"]) <= datetime.now().astimezone()):
        return web.json_response({"ok": False, "error": "Запись на эту прогулку пока не открыта."}, status=400)
    if not name or "@" not in email:
        return web.json_response({"ok": False, "error": "Заполните имя и корректный e-mail."}, status=400)
    amount = f"{float(walk['price']):.2f}"
    async with get_session() as session:
        cutoff = datetime.utcnow() - timedelta(minutes=60)
        occupied = await session.scalar(
            select(func.count()).select_from(AlloBooking).where(
                AlloBooking.walk_key == key,
                or_(AlloBooking.status == "paid",
                    and_(AlloBooking.status == "pending",
                         AlloBooking.created_at >= cutoff)))) or 0
        if occupied >= config.ALLO_WALK_CAPACITY:
            return web.json_response(
                {"ok": False, "error": "Все места уже заняты. Оставьте заявку в листе ожидания."},
                status=409)
        booking = AlloBooking(walk_key=key, plan="single", user_id=0,
                              username=telegram or None, first_name=name, email=email,
                              amount=amount, status="pending", agreed=True)
        session.add(booking)
        await session.commit()
        await session.refresh(booking)
        bid = booking.id
    payment = await create_payment(
        f"Allo Walks: {walk['title']}",
        {"kind": "allo", "source": "website", "walk": key, "plan": "single",
         "booking_id": bid, "user_id": 0, "email": email}, amount, method="ideal")
    if not payment or not payment.get("checkout_url"):
        async with get_session() as session:
            booking = await session.get(AlloBooking, bid)
            if booking:
                booking.status = "canceled"
                await session.commit()
        return web.json_response({"ok": False, "error": "Не удалось открыть оплату. Попробуйте позже."}, status=502)
    async with get_session() as session:
        booking = await session.get(AlloBooking, bid)
        if booking:
            booking.payment_id = payment["id"]
            await session.commit()
    return web.json_response({"ok": True, "checkout_url": payment["checkout_url"]})


async def page(_: web.Request) -> web.Response:
    return web.FileResponse(Path(__file__).resolve().parent.parent / "static" / "allo-walks" / "index.html")


async def success(_: web.Request) -> web.Response:
    return web.FileResponse(Path(__file__).resolve().parent.parent / "static" / "allo-walks" / "success.html")
