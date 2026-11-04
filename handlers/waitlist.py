"""Лист ожидания в боте: запись по ссылке ?start=wl_<кампания> и команды для админов.

/candle              — сколько человек в листе ожидания свечи (почта и Telegram), выгрузка CSV
/candle_open <ссылка> — письмо и сообщение в боте всем из списка: продажи открыты (с подтверждением)
"""
import asyncio
import csv
import html
import io
import logging
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command, CommandStart
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


@router.message(CommandStart(deep_link=True), F.text.endswith(" wl_candle"))
async def join_from_bot(message: Message) -> None:
    new, n = await wl.add_telegram(CAMPAIGN, message.from_user.id)
    stock = wl.CAMPAIGNS[CAMPAIGN]["stock"]
    await message.answer(
        ("Готово, вы в листе ожидания! 🕯" if new else "Вы уже в листе ожидания 🕯")
        + f"\n\nРождественская свеча Soul of Sol × podslushano.nl «Пахнет как дома». "
        f"Вы {n}-й в списке, а в первой партии {stock} свечей.\n\n"
        "В день старта продаж я напишу вам первым, ещё до открытой продажи.")


async def _rows() -> list[WaitlistEntry]:
    async with get_session() as session:
        return list((await session.scalars(select(WaitlistEntry).where(
            WaitlistEntry.campaign == CAMPAIGN).order_by(WaitlistEntry.id))).all())


@router.message(Command("candle"), F.from_user.id.in_(config.ADMIN_IDS))
async def candle_stats(message: Message) -> None:
    rows = await _rows()
    act = [r for r in rows if r.status == "active"]
    mails = sum(1 for r in act if r.email)
    tg = sum(1 for r in act if r.tg_user_id)
    pend = sum(1 for r in rows if r.status == "pending")
    await message.answer(
        f"🕯 <b>Лист ожидания свечи</b>\n\nВ списке: <b>{len(act)}</b> (почта {mails}, Telegram {tg}).\n"
        f"Не подтвердили почту: {pend}. Свечей в первой партии: {wl.CAMPAIGNS[CAMPAIGN]['stock']}.\n\n"
        "Эту цифру сайт показывает в баннере сам.\n"
        "Открыть продажи для списка: <code>/candle_open https://ссылка-на-покупку</code>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="📄 Скачать список (CSV)", callback_data="wl:csv")]]))


@router.callback_query(F.data == "wl:csv", F.from_user.id.in_(config.ADMIN_IDS))
async def candle_csv(callback: CallbackQuery) -> None:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["№", "почта", "telegram_id", "статус", "источник", "записался", "подтвердил"])
    for i, r in enumerate(await _rows(), 1):
        w.writerow([i, r.email or "", r.tg_user_id or "", r.status, r.source,
                    f"{r.created_at:%d.%m.%Y %H:%M}" if r.created_at else "",
                    f"{r.confirmed_at:%d.%m.%Y %H:%M}" if r.confirmed_at else ""])
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
        f"Разослать «продажи открыты» <b>{len(act)}</b> людям из листа ожидания (письмо или сообщение в боте)?\n"
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


async def _send_all(bot, url: str, admin_id: int) -> None:
    from utils.email_templates import waitlist_open
    from utils.invoices import send_email_message
    title = wl.CAMPAIGNS[CAMPAIGN]["title"]
    note = ("Вы записались в лист ожидания, поэтому пишем вам первыми, ещё до открытой продажи. "
            f"В первой партии всего {wl.CAMPAIGNS[CAMPAIGN]['stock']} свечей.")
    sent = failed = 0
    for r in [r for r in await _rows() if r.status == "active" and not r.notified_at]:
        ok = False
        try:
            if r.email:
                ok, _ = await send_email_message(
                    r.email, *waitlist_open(title=title, url=url, note=note,
                                            unsubscribe_url=wl.unsubscribe_url(CAMPAIGN, r.id)))
            elif r.tg_user_id:
                await bot.send_message(
                    r.tg_user_id, f"🕯 <b>Продажи открыты!</b>\n\n{title}.\n{note}",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Купить", url=url)]]))
                ok = True
        except Exception as e:  # noqa: BLE001
            log.info("Лист ожидания: не отправлено #%s: %s", r.id, e)
        if ok:
            sent += 1
            async with get_session() as session:
                row = await session.get(WaitlistEntry, r.id)
                row.notified_at = datetime.now(timezone.utc).replace(tzinfo=None)
                await session.commit()
        else:
            failed += 1
        await asyncio.sleep(0.1)
    try:
        await bot.send_message(admin_id, f"🕯 Рассылка листа ожидания: доставлено {sent}, не доставлено {failed}.")
    except Exception:  # noqa: BLE001
        pass
