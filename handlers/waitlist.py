"""Лист ожидания свечи: только команды для админов (записываются люди на сайте и в /links/ по почте).

/candle              — сколько человек в листе ожидания, выгрузка CSV
/candle_open <ссылка> — письмо всем из списка: продажи открыты (с подтверждением)
"""
import asyncio
import csv
import html
import io
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.types import (BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup,
                           Message)
from sqlalchemy import select

import config
from database.db import get_session
from database.models import Meta, WaitlistEntry
from utils import waitlist as wl

log = logging.getLogger(__name__)
router = Router()
router.message.filter(F.chat.type == ChatType.PRIVATE)

CAMPAIGN = "candle"
_OPEN_URL_KEY = "waitlist_open_url:candle"
_LAUNCH_AT = datetime(2026, 11, 16, 9, tzinfo=ZoneInfo("Europe/Amsterdam"))
_LAUNCH_URL = ("https://soulofsol.com/podslushano/?utm_source=podslushano"
               "&utm_medium=referral&utm_campaign=paxnet_kak_doma")
_UNSUBSCRIBE_EXPIRES = int((_LAUNCH_AT + timedelta(days=365)).timestamp())


async def _rows() -> list[WaitlistEntry]:
    async with get_session() as session:
        return list((await session.scalars(select(WaitlistEntry).where(
            WaitlistEntry.campaign == CAMPAIGN).order_by(WaitlistEntry.id))).all())


@router.message(Command("candle"), F.from_user.id.in_(config.ADMIN_IDS))
async def candle_stats(message: Message) -> None:
    rows = await _rows()
    act = [r for r in rows if r.status == "active"]
    out = sum(1 for r in rows if r.status == "unsubscribed")
    await message.answer(
        f"🕯 <b>Лист ожидания свечи</b>\n\nВ списке: <b>{len(act)}</b>. Отписались: {out}.\n"
        f"Свечей в первой партии: {wl.CAMPAIGNS[CAMPAIGN]['stock']}.\n\n"
        "Эту цифру сайт показывает в баннере сам.\n"
        "Открыть продажи для списка: <code>/candle_open https://ссылка-на-покупку</code>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="📄 Скачать список (CSV)", callback_data="wl:csv")]]))


@router.callback_query(F.data == "wl:csv", F.from_user.id.in_(config.ADMIN_IDS))
async def candle_csv(callback: CallbackQuery) -> None:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["№", "почта", "статус", "источник", "записался"])
    for i, r in enumerate(await _rows(), 1):
        w.writerow([i, r.email or "", r.status, r.source,
                    f"{r.created_at:%d.%m.%Y %H:%M}" if r.created_at else ""])
    await callback.answer()
    await callback.message.answer_document(
        BufferedInputFile(buf.getvalue().encode("utf-8-sig"), filename="waitlist-candle.csv"),
        caption="Список для нас. Партнёру передаём только число: на передачу адресов согласия не было.")


@router.message(Command("candle_open"), F.from_user.id.in_(config.ADMIN_IDS))
async def candle_open(message: Message) -> None:
    parts = (message.text or "").split(maxsplit=1)
    url = parts[1].strip() if len(parts) > 1 else ""
    if not url.startswith("https://"):
        await message.answer("Пришлите ссылку на покупку: <code>/candle_open https://…</code>")
        return
    async with get_session() as session:
        await session.merge(Meta(key=_OPEN_URL_KEY, value=url))
        await session.commit()
    act = [r for r in await _rows() if r.status == "active" and not r.notified_at]
    await message.answer(
        f"Разослать «продажи открыты» <b>{len(act)}</b> людям из листа ожидания (письмо на почту)?\n"
        f"Ссылка: {html.escape(url)}",
        disable_web_page_preview=True,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Разослать", callback_data="wl:send"),
            InlineKeyboardButton(text="Отмена", callback_data="wl:no")]]))


@router.callback_query(F.data == "wl:no", F.from_user.id.in_(config.ADMIN_IDS))
async def candle_no(callback: CallbackQuery) -> None:
    await callback.answer("Отменено")
    await callback.message.edit_reply_markup(reply_markup=None)


@router.callback_query(F.data == "wl:send", F.from_user.id.in_(config.ADMIN_IDS))
async def candle_send(callback: CallbackQuery) -> None:
    async with get_session() as session:
        m = await session.get(Meta, _OPEN_URL_KEY)
    if not m:
        await callback.answer("Сначала /candle_open со ссылкой", show_alert=True)
        return
    await callback.answer("Рассылка запущена")
    await callback.message.edit_reply_markup(reply_markup=None)
    asyncio.create_task(_send_all(callback.bot, m.value, callback.from_user.id))


async def _deliver_launch(url: str) -> tuple[int, int]:
    from utils.email_templates import candle_launch
    from utils.invoices import send_email_message

    stock = wl.CAMPAIGNS[CAMPAIGN]["stock"]
    sent = failed = 0
    async with get_session() as session:
        entry_ids = (await session.scalars(select(WaitlistEntry.id).where(
            WaitlistEntry.campaign == CAMPAIGN,
            WaitlistEntry.status == "active",
            WaitlistEntry.notified_at.is_(None),
            WaitlistEntry.email.is_not(None),
        ).order_by(WaitlistEntry.id))).all()
    for entry_id in entry_ids:
        try:
            async with get_session() as session:
                row = await session.get(WaitlistEntry, entry_id, with_for_update=True)
                if not row or row.status != "active" or row.notified_at or not row.email:
                    continue
                unsubscribe = wl.unsubscribe_url(CAMPAIGN, row.id, expires_at=_UNSUBSCRIBE_EXPIRES)
                ok, _ = await send_email_message(
                    row.email, *candle_launch(url=url, unsubscribe_url=unsubscribe, stock=stock),
                    unsubscribe_url=unsubscribe,
                    idempotency_key=f"waitlist-candle-launch-2026-11-16-{row.id}",
                )
                if ok:
                    row.notified_at = datetime.now(timezone.utc).replace(tzinfo=None)
                    await session.commit()
                    sent += 1
                else:
                    failed += 1
        except Exception as exc:
            failed += 1
            log.warning("Не удалось обработать запись рассылки свечи #%s: %s", entry_id, type(exc).__name__)
        await asyncio.sleep(0.15)
    return sent, failed


async def scheduled_launch() -> None:
    end_at = _LAUNCH_AT + timedelta(hours=1)
    now = datetime.now(timezone.utc)
    if now >= end_at:
        return
    log.info("Письма листа ожидания свечи запланированы на %s", _LAUNCH_AT.isoformat())
    while (delay := (_LAUNCH_AT - datetime.now(timezone.utc)).total_seconds()) > 0:
        await asyncio.sleep(min(delay, 60))
    if datetime.now(timezone.utc) >= end_at:
        return
    while datetime.now(timezone.utc) < end_at:
        try:
            sent, failed = await _deliver_launch(_LAUNCH_URL)
        except Exception:
            log.exception("Не удалось начать рассылку свечи")
        else:
            log.info("Рассылка свечи: принято к отправке %s, ошибок %s", sent, failed)
            if not failed:
                return
        if datetime.now(timezone.utc) + timedelta(seconds=60) >= end_at:
            return
        await asyncio.sleep(60)


async def _send_all(bot, url: str, admin_id: int) -> None:
    sent, failed = await _deliver_launch(url)
    try:
        await bot.send_message(admin_id, f"🕯 Рассылка листа ожидания: принято к отправке {sent}, ошибок {failed}.")
    except Exception:  # noqa: BLE001
        pass
