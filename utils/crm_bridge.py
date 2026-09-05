"""Безопасная синхронизация рекламных броней Railway с закрытой CRM."""
from __future__ import annotations

import logging
import asyncio
import hashlib
import json
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.parse import urlsplit

from sqlalchemy import select

import aiohttp

import config
from database.db import get_session
from database.models import AdBooking, Meta

log = logging.getLogger(__name__)
_lock = asyncio.Lock()


def crm_bridge_enabled() -> bool:
    return bool(
        config.CRM_AD_ORDER_URL
        and config.CRM_WEBHOOK_SECRET
        and config.CRM_SITES_AUTH_TOKEN
    )


def booking_payload(booking: AdBooking) -> dict:
    info = config.AD_FORMATS.get(booking.fmt, {})
    option = config.ad_option(booking.fmt, booking.opt) or {}
    format_name = info.get("name") or booking.fmt
    option_label = option.get("label")
    if option_label:
        format_name = f"{format_name} — {option_label}"

    invoice = [
        booking.company,
        booking.buyer_name,
        booking.address,
        booking.postcode,
        f"BTW: {booking.btw}" if booking.btw else None,
        f"KVK: {booking.kvk}" if booking.kvk else None,
    ]
    all_dates = booking.dates_csv or booking.date
    return {
        "order_id": f"ad_booking:{booking.id}",
        "client_name": booking.company or booking.buyer_name or booking.email,
        "company": booking.company or "",
        "email": booking.email or "",
        "phone": booking.phone or "",
        "contact": booking.phone or booking.email or "",
        "format": format_name,
        "amount": booking.amount or option.get("price") or "0",
        "selected_date": booking.date,
        "note": f"Даты размещения: {all_dates}",
        "mollie_payment_id": booking.payment_id or "",
        "payment_status": booking.status,
        "invoice_details": "\n".join(str(value) for value in invoice if value),
    }


async def _sync_booking(booking_id: int) -> bool:
    """Отправляет актуальное состояние брони; ошибка не ломает оплату."""
    if not crm_bridge_enabled():
        return False
    async with get_session() as session:
        booking = await session.get(AdBooking, booking_id)
        if booking is None or booking.fmt == "closed":
            return False
        payload = booking_payload(booking)

    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    key = f"crm:booking:{booking_id}"
    async with get_session() as db_session:
        marker = await db_session.get(Meta, key)
        if marker and marker.value == digest:
            return True

    if booking.status == "paid":
        from utils.payments import get_payment
        payment = await get_payment(booking.payment_id or "")
        if not payment or payment.get("status") != "paid" or not payment.get("paidAt"):
            log.warning("CRM sync awaits verified payment date for booking %s", booking_id)
            return False
        payload["paid_at"] = payment["paidAt"]

    headers = {
        "content-type": "application/json",
        "x-crm-webhook-secret": config.CRM_WEBHOOK_SECRET,
        "OAI-Sites-Authorization": f"Bearer {config.CRM_SITES_AUTH_TOKEN}",
    }
    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                config.CRM_AD_ORDER_URL, json=payload, headers=headers
            ) as response:
                if response.status >= 300:
                    log.warning("CRM sync error %s for booking %s", response.status, booking_id)
                    return False
                result = await response.json()
                if not result.get("ok"):
                    return False
                async with get_session() as db_session:
                    await db_session.merge(Meta(key=key, value=digest))
                    await db_session.commit()
                return True
    except Exception as exc:  # noqa: BLE001 — CRM не должна ломать оплату
        log.warning("CRM sync failed for ad booking %s: %s", booking_id, exc)
        return False


async def safe_sync_booking(booking_id: int) -> None:
    async with _lock:
        try:
            await _sync_booking(booking_id)
        except Exception:
            log.exception("CRM sync failed; reconciliation will retry")


def _headers() -> dict:
    return {
        "x-crm-webhook-secret": config.CRM_WEBHOOK_SECRET,
        "OAI-Sites-Authorization": f"Bearer {config.CRM_SITES_AUTH_TOKEN}",
    }


async def deliver_daily_reminders(bot) -> None:
    if not config.CRM_TELEGRAM_CHAT_ID:
        return
    now = datetime.now(ZoneInfo("Europe/Amsterdam"))
    if (now.hour, now.minute) < (8, 30):
        return
    key = f"crm:reminders:{now.date()}:{config.CRM_TELEGRAM_CHAT_ID}"
    async with get_session() as db_session:
        if await db_session.get(Meta, key):
            return
    url = urlsplit(config.CRM_AD_ORDER_URL)
    endpoint = f"{url.scheme}://{url.netloc}/api/reminders/due"
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
        async with session.post(endpoint, headers=_headers()) as response:
            if response.status != 200:
                log.warning("CRM reminder preparation failed: %s", response.status)
                return
            data = await response.json()
    if not data.get("ok") or data.get("date") != now.date().isoformat():
        return
    text = data.get("text") or ""
    if text:
        # Plain text protects against customer-provided HTML. Split at Telegram's limit.
        for start in range(0, len(text), 3500):
            await bot.send_message(config.CRM_TELEGRAM_CHAT_ID, text[start:start+3500], parse_mode=None)
    async with get_session() as db_session:
        await db_session.merge(Meta(key=key, value="sent" if text else "empty"))
        await db_session.commit()


async def crm_sync_loop(bot) -> None:
    """Reconcile persisted bookings, retry failed deliveries, then prepare daily reminders."""
    while True:
        try:
            if crm_bridge_enabled():
                async with get_session() as session:
                    ids = (await session.scalars(select(AdBooking.id).where(AdBooking.fmt != "closed"))).all()
                for booking_id in ids:
                    await safe_sync_booking(booking_id)
                await deliver_daily_reminders(bot)
        except Exception:
            log.exception("CRM background cycle failed; will retry")
        await asyncio.sleep(300)
