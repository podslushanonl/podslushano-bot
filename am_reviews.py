"""AM Projects reviews: durable moderation in the existing bot database."""
import asyncio
from functools import wraps
import hmac
import html
import os
import re
from datetime import datetime

from aiohttp import web
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import Boolean, DateTime, Integer, String, Text, func, select
from sqlalchemy.orm import Mapped, mapped_column

import config
from database.db import get_session
from database.models import Base

router = Router(name="am_reviews")
_write_lock = asyncio.Lock()


def serialized(fn):
    @wraps(fn)
    async def wrapper(*args, **kwargs):
        async with _write_lock:
            return await fn(*args, **kwargs)
    return wrapper



class AMReview(Base):
    __tablename__ = "am_project_reviews"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(80))
    text: Mapped[str] = mapped_column(Text)
    rating: Mapped[int] = mapped_column(Integer)
    project: Mapped[str] = mapped_column(String(120), default="")
    contact: Mapped[str] = mapped_column(String(200), default="")
    notified: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


def keyboard(row, confirm=False):
    def button(label, action):
        return InlineKeyboardButton(text=label, callback_data=f"amr:{action}:{row.id}")
    if confirm:
        buttons = [button("Да, удалить", "delete"), button("Отмена", "cancel")]
    elif row.status == "deleted":
        buttons = []
    elif row.status == "published":
        buttons = [button("Удалить", "askdelete")]
    else:
        buttons = [button("Опубликовать", "publish"), button("Удалить", "askdelete")]
    return InlineKeyboardMarkup(inline_keyboard=[buttons] if buttons else [])


def card(row):
    if row.status == "deleted":
        return f"<b>Отзыв AM Projects №{row.id} удалён.</b>\nОн не отображается на сайте и не учитывается в рейтинге."
    status = "Опубликован на сайте" if row.status == "published" else "Ожидает проверки"
    return "\n".join([
        f"<b>Отзыв — AM Projects №{row.id}</b>", f"Статус: {status}", "",
        f"<b>Имя:</b> {html.escape(row.name)}", f"<b>Оценка:</b> {row.rating} / 5",
        f"<b>Проект:</b> {html.escape(row.project or 'Не указан')}",
        f"<b>Контакт (не публиковать):</b> {html.escape(row.contact or 'Не указан')}",
        "", "<b>Текст:</b>", html.escape(row.text), "",
        "Автор согласился на публикацию имени, оценки и текста.",
    ])


def validate(data):
    if not isinstance(data, dict):
        return False
    def field(key, low, high):
        v = data.get(key, "")
        return isinstance(v, str) and low <= len(v.strip()) <= high and len(v) <= high
    return (field("name", 2, 80) and field("text", 10, 2000)
            and field("project", 0, 120) and field("contact", 0, 200)
            and type(data.get("rating")) is int and 1 <= data["rating"] <= 5
            and data.get("consent") is True)


async def public_reviews(request):
    async with get_session() as session:
        rows = (await session.scalars(select(AMReview).where(
            AMReview.status == "published").order_by(AMReview.id.desc()))).all()
        return web.json_response({"reviews": [dict(id=r.id, name=r.name, text=r.text,
            rating=r.rating, project=r.project, published=True) for r in rows]},
            headers={"Cache-Control": "no-store"})


@serialized
async def receive_review(request):
    # A dedicated secret is shared only with the AM Projects backend.
    secret = os.environ.get("AM_REVIEWS_SECRET", "")
    supplied = request.headers.get("Authorization", "")
    if not secret or not hmac.compare_digest(supplied, "Bearer " + secret):
        raise web.HTTPUnauthorized()
    if request.content_length and request.content_length > 24000:
        raise web.HTTPRequestEntityTooLarge(max_size=24000, actual_size=request.content_length)
    try:
        data = await request.json()
    except (ValueError, TypeError):
        raise web.HTTPBadRequest()
    if not validate(data):
        raise web.HTTPBadRequest()
    source = data.get("submissionId", "")
    if not isinstance(source, str) or not re.fullmatch(r"[a-f0-9]{64}", source):
        raise web.HTTPBadRequest()
    chat = os.environ.get("AM_REVIEWS_CHAT_ID", "")
    if not chat:
        raise web.HTTPServiceUnavailable()
    async with get_session() as session:
        row = await session.scalar(select(AMReview).where(AMReview.source == source))
        if row is None:
            row = AMReview(source=source, **{k: data.get(k, "").strip()
                for k in ("name", "text", "project", "contact")}, rating=data["rating"], status="pending")
            session.add(row)
            await session.commit()
        # Pending data is safe even when notification fails; /amreviews retrieves it.
        if row.status == "pending" and not row.notified:
            try:
                await request.app["bot"].send_message(chat, card(row), reply_markup=keyboard(row))
                row.notified = True
                await session.commit()
            except Exception:
                return web.json_response({"ok": False}, status=502)
    return web.json_response({"ok": True})


@router.callback_query(F.data.startswith("amr:"))
@serialized
async def moderate(query):
    if query.from_user.id not in config.ADMIN_IDS:
        return await query.answer("Доступ только администратору.", show_alert=True)
    parts = query.data.split(":")
    if len(parts) != 3 or not parts[2].isdigit():
        return await query.answer("Неизвестная кнопка.")
    action, review_id = parts[1], int(parts[2])
    async with get_session() as session:
        row = await session.get(AMReview, review_id)
        if row is None:
            return await query.answer("Отзыв не найден.", show_alert=True)
        if row.status == "deleted":
            return await query.answer("Отзыв уже удалён.", show_alert=True)
        if action == "askdelete":
            await query.message.edit_reply_markup(reply_markup=keyboard(row, confirm=True))
            return await query.answer("Подтвердите удаление отзыва с сайта.")
        if action == "publish":
            row.status = "published"
        elif action == "delete":
            row.status = "deleted"
            # Keep only an idempotency tombstone; erase review and private contact.
            row.name = row.text = row.project = row.contact = ""
        elif action != "cancel":
            return await query.answer("Неизвестная кнопка.")
        await session.commit()
        await query.answer("Опубликовано" if action == "publish" else "Удалено" if action == "delete" else "Удаление отменено")
        try:
            await query.message.edit_text(card(row), reply_markup=keyboard(row))
        except Exception:
            # The DB is authoritative; repeated clicks cannot undo deletion.
            pass


def parse_legacy(text):
    pattern = (r"^Новый отзыв — AM Projects\n.*?\nИмя: (.*?)\nОценка: ([1-5]) / 5\n"
               r"Проект: (.*?)\nКонтакт \(не публиковать\): (.*?)\n\nТекст:\n(.*?)\n\n"
               r"Автор согласился на публикацию имени, оценки и текста\.$")
    match = re.fullmatch(pattern, text or "", re.S)
    if not match:
        return None
    name, rating, project, contact, text = match.groups()
    data = dict(name=name, rating=int(rating), project="" if project == "Не указан" else project,
                contact="" if contact == "Не указан" else contact, text=text, consent=True)
    return data if validate(data) else None


@router.message(Command("amreview", "amreviews"))
@serialized
async def admin_reviews(message):
    if message.from_user.id not in config.ADMIN_IDS:
        return
    old = message.reply_to_message
    async with get_session() as session:
        if old:
            # Import only an actual historical notification sent by this bot.
            me = await message.bot.get_me()
            data = parse_legacy(old.text) if old.from_user and old.from_user.id == me.id else None
            if data is None:
                return await message.answer("Ответьте командой /amreview на старое сообщение бота «Новый отзыв — AM Projects».")
            source = f"telegram:{old.chat.id}:{old.message_id}"
            row = await session.scalar(select(AMReview).where(AMReview.source == source))
            if row is None:
                row = AMReview(source=source, **{k: data[k] for k in ("name", "rating", "text", "project", "contact")}, status="pending")
                session.add(row)
                await session.commit()
            await message.answer(card(row), reply_markup=keyboard(row))
            return
        rows = (await session.scalars(select(AMReview).where(
            AMReview.status != "deleted").order_by(AMReview.id.desc()).limit(20))).all()
        if not rows:
            return await message.answer("Отзывов пока нет. Для старого отзыва ответьте на его сообщение командой /amreview.")
        for row in rows:
            await message.answer(card(row), reply_markup=keyboard(row))


def install_routes(app):
    app.router.add_get("/api/am-reviews", public_reviews)
    app.router.add_post("/api/am-reviews", receive_review)
