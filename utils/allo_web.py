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
    public_keys = (
        "key", "starts_at", "status", "date", "title", "short_title", "place",
        "meet", "finish", "dur", "distance", "price", "capacity",
        "min_participants", "tag", "tone", "format", "desc", "program",
        "included", "not_included", "bring", "rules", "weather",
        "cancel_before_hours", "route_url", "directions_url", "map",
    )
    return {key: walk.get(key) for key in public_keys}


async def api_walks(_: web.Request) -> web.Response:
    walks = [_public_walk(w) for w in config.ALLO_WALKS if w.get("status") != "archived"]
    cutoff = datetime.utcnow() - timedelta(minutes=60)
    async with get_session() as session:
        rows = (await session.execute(
            select(AlloBooking.walk_key, func.count()).where(
                or_(AlloBooking.status == "paid",
                    and_(AlloBooking.status == "pending",
                         AlloBooking.created_at >= cutoff))
            ).group_by(AlloBooking.walk_key)
        )).all()
    occupied = dict(rows)
    for walk in walks:
        capacity = int(walk.get("capacity") or config.ALLO_WALK_CAPACITY)
        booked = int(occupied.get(walk["key"], 0))
        walk["booked"] = booked
        walk["spots_left"] = max(0, capacity - booked)
    return web.json_response({"walks": walks},
                             dumps=lambda value: json.dumps(value, ensure_ascii=False))


async def waitlist(request: web.Request) -> web.Response:
    data = await request.post()
    key = str(data.get("walk") or "").strip()
    name = str(data.get("name") or "").strip()[:120]
    email = str(data.get("email") or "").strip()[:200]
    telegram = str(data.get("telegram") or "").strip().lstrip("@").replace("https://t.me/", "")[:64]
    phone = str(data.get("phone") or "").strip()[:40]
    dietary = str(data.get("dietary") or "").strip()[:500]
    notes = str(data.get("notes") or "").strip()[:1000]
    walk = config.allo_walk(key)
    if not walk or not name or "@" not in email:
        return web.json_response({"ok": False, "error": "Заполните имя и корректный e-mail."}, status=400)
    async with get_session() as session:
        session.add(AlloBooking(walk_key=key, plan="single", user_id=0,
                                username=telegram or None, first_name=name,
                                email=email, phone=phone or None,
                                dietary=dietary or None, notes=notes or None,
                                status="waitlist", agreed=True))
        await session.commit()
    bot = request.app["bot"]
    message = (f"✨ <b>Новый лист ожидания Allo Walks</b>\n\n"
               f"{_safe(walk['title'])}\n{_safe(name)} · {_safe(email)}"
               f"\nTelegram: @{_safe(telegram) if telegram else '—'}"
               f"\nТелефон: {_safe(phone) if phone else '—'}"
               f"\nПитание / аллергии: {_safe(dietary) if dietary else '—'}"
               f"\nКомментарий: {_safe(notes) if notes else '—'}")
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
    phone = str(data.get("phone") or "").strip()[:40]
    dietary = str(data.get("dietary") or "").strip()[:500]
    notes = str(data.get("notes") or "").strip()[:1000]
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
        capacity = int(walk.get("capacity") or config.ALLO_WALK_CAPACITY)
        if occupied >= capacity:
            return web.json_response(
                {"ok": False, "error": "Все места уже заняты. Оставьте заявку в листе ожидания."},
                status=409)
        booking = AlloBooking(walk_key=key, plan="single", user_id=0,
                              username=telegram or None, first_name=name, email=email,
                              phone=phone or None, dietary=dietary or None,
                              notes=notes or None, amount=amount,
                              status="pending", agreed=True)
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
