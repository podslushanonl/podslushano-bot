"""Автоматическая синхронизация рекламных броней с Google Calendar.

Источник истины — ``ad_bookings``. В Calendar создаётся одно событие на каждый
фактический выход. Идентификаторы событий хранятся в ``meta``, поэтому webhook,
перезапуск и периодическая сверка обновляют запись, а не создают дубликат.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
from datetime import date, datetime, timedelta
from urllib.parse import quote
from zoneinfo import ZoneInfo

import aiohttp
from sqlalchemy import select

import config
from database.db import get_session
from database.models import AdBooking, Meta

log = logging.getLogger(__name__)

_SCOPES = ("https://www.googleapis.com/auth/calendar.events",)
_BLOCKING = ("pending", "paid", "closed")
_META_PREFIX = "adcal:"
_SYNC_INTERVAL_SECONDS = 15 * 60
_credentials = None
_credentials_lock = asyncio.Lock()


def enabled() -> bool:
    return not calendar_configuration_errors()


def calendar_configuration_errors() -> list[str]:
    errors = []
    if not config.GOOGLE_CALENDAR_ID:
        errors.append("не задана переменная GOOGLE_CALENDAR_ID")
    if not config.GOOGLE_CALENDAR_CREDENTIALS_B64:
        errors.append("не задана переменная GOOGLE_CALENDAR_CREDENTIALS_B64")
    return errors


def _today() -> date:
    return datetime.now(ZoneInfo(config.GOOGLE_CALENDAR_TIMEZONE)).date()


def _date_label(value: str) -> str:
    parsed = date.fromisoformat(value)
    months = (
        "", "января", "февраля", "марта", "апреля", "мая", "июня",
        "июля", "августа", "сентября", "октября", "ноября", "декабря",
    )
    return f"{parsed.day} {months[parsed.month]} {parsed.year} года"


def _booking_dates(booking: AdBooking) -> list[str]:
    values = [
        item.strip()
        for item in (booking.dates_csv or booking.date or "").split(",")
        if item.strip()
    ]
    values = list(dict.fromkeys(values))
    # Старые брони Telegram-поста могли сохранить только первый выход, хотя
    # оплачен addon «повтор через 14 дней». Новые брони пишут обе даты сразу.
    if booking.addon == "repeat" and len(values) == 1:
        values.append((date.fromisoformat(values[0]) + timedelta(days=14)).isoformat())
    return sorted(values)


def _meta_key(booking_id: int, date_iso: str) -> str:
    return f"{_META_PREFIX}{booking_id}:{date_iso}"


def _meta_parts(key: str) -> tuple[int, str] | None:
    if not key.startswith(_META_PREFIX):
        return None
    try:
        booking_id, date_iso = key[len(_META_PREFIX):].split(":", 1)
        date.fromisoformat(date_iso)
        return int(booking_id), date_iso
    except (TypeError, ValueError):
        return None


def _client_name(booking: AdBooking) -> str:
    return (booking.company or booking.buyer_name or "Клиент без имени").strip()


def _status_label(status: str) -> str:
    return {
        "paid": "оплачено",
        "pending": "ожидает оплаты",
        "closed": "закрыто вручную",
    }.get(status, status)


def _format_details(booking: AdBooking) -> list[str]:
    if booking.fmt == "numr_campaign":
        return [
            "4 Reels — по 2 в месяц",
            "3 Stories с прямой ссылкой к каждому Reel — 12 Stories всего",
            "закрепление одного из четырёх Reels в верхней части профиля на 3 дня",
            "временная ссылка на NUMR на странице Links на время кампании",
            "создание материалов и публикация на площадках Podslushano.nl",
            "предварительная проверка клиентом фактической информации",
        ]
    return list((config.AD_FORMATS.get(booking.fmt) or {}).get("details") or [])


def _amount(booking: AdBooking) -> str:
    if booking.amount:
        return booking.amount
    option = config.ad_option(booking.fmt, booking.opt)
    total = (option or {}).get("price", "")
    addon = config.ad_addon(booking.fmt) if booking.addon else None
    if total and addon:
        try:
            return f"{float(total) + float(addon['price']):.2f}"
        except (KeyError, TypeError, ValueError):
            pass
    return total


def _event_payload(booking: AdBooking, date_iso: str) -> dict:
    next_date = (date.fromisoformat(date_iso) + timedelta(days=1)).isoformat()
    if booking.status == "closed":
        title = "Реклама: дата закрыта вручную — резерв"
        description = (
            f"Дата: {_date_label(date_iso)}\n"
            "Статус: закрыто вручную\n\n"
            "Рекламодатель: не привязан\n"
            "Рекламный формат: не выбран\n"
            "Оплата: отсутствует\n\n"
            "День сохранён как внутренний резерв и недоступен клиентам на "
            "странице покупки рекламы."
        )
    else:
        dates = _booking_dates(booking)
        position = dates.index(date_iso) + 1
        info = config.AD_FORMATS.get(booking.fmt) or {"name": booking.fmt}
        option = config.ad_option(booking.fmt, booking.opt) or {"label": booking.opt}
        client = _client_name(booking)
        addon = config.ad_addon(booking.fmt) if booking.addon else None

        if booking.fmt == "numr_campaign":
            title = f"Реклама NUMR — {position}-й Reel + 3 Stories"
        elif len(dates) > 1:
            title = f"Реклама: {client} — {position}-й выход"
        else:
            title = f"Реклама: {client} — {info['name']}"

        details = "\n".join(f"• {item};" for item in _format_details(booking))
        all_dates = ", ".join(_date_label(item).removesuffix(" года") for item in dates)
        price = _amount(booking)
        price_line = (
            f"Стоимость всей кампании: €{price}, BTW 21% включён\n"
            if price else ""
        )
        addon_line = addon["label"] if addon else "нет"
        description = (
            f"Клиент: {client}\n"
            f"Статус: {_status_label(booking.status)}\n"
            f"Дата публикации: {_date_label(date_iso)} — "
            f"{position}-й из {len(dates)} выходов\n\n"
            f"Пакет: «{info['name']}» — {option.get('label', '')}\n"
            f"{price_line}\n"
            f"В пакет входит:\n{details}\n\n"
            f"Все даты кампании: {all_dates}.\n"
            f"Дополнительные опции: {addon_line}."
        )

    return {
        "summary": title,
        "description": description,
        "start": {"date": date_iso},
        "end": {"date": next_date},
        "transparency": "opaque",
        "reminders": {"useDefault": False},
        "extendedProperties": {
            "private": {
                "podslushano_ad_booking_id": str(booking.id),
                "podslushano_ad_date": date_iso,
            }
        },
    }


def _credentials_info() -> dict:
    raw = base64.b64decode(config.GOOGLE_CALENDAR_CREDENTIALS_B64).decode("utf-8")
    data = json.loads(raw)
    if data.get("type") != "service_account":
        raise ValueError("Google Calendar credentials are not a service account")
    return data


async def _access_token(force_refresh: bool = False) -> str:
    global _credentials
    from google.auth.transport.requests import Request
    from google.oauth2.service_account import Credentials

    async with _credentials_lock:
        if _credentials is None:
            _credentials = Credentials.from_service_account_info(
                _credentials_info(), scopes=_SCOPES
            )
        if force_refresh or not _credentials.valid:
            await asyncio.to_thread(_credentials.refresh, Request())
        return _credentials.token


async def _calendar_request(
    method: str,
    path: str,
    payload: dict | None = None,
    *,
    not_found_ok: bool = False,
) -> dict | None:
    url = "https://www.googleapis.com/calendar/v3" + path
    for attempt in range(2):
        token = await _access_token(force_refresh=attempt > 0)
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.request(
                method,
                url,
                json=payload,
                headers={"Authorization": f"Bearer {token}"},
            ) as response:
                if response.status == 401 and attempt == 0:
                    continue
                if response.status == 404 and not_found_ok:
                    return None
                if response.status == 204:
                    return {}
                body = await response.text()
                if response.status < 200 or response.status >= 300:
                    raise RuntimeError(
                        f"Google Calendar API {method} {response.status}: {body[:500]}"
                    )
                return json.loads(body) if body else {}
    raise RuntimeError("Google Calendar API did not accept refreshed credentials")


def _calendar_path(suffix: str = "") -> str:
    calendar_id = quote(config.GOOGLE_CALENDAR_ID, safe="")
    return f"/calendars/{calendar_id}/events{suffix}"


async def _delete_event(event_id: str) -> None:
    await _calendar_request(
        "DELETE", _calendar_path("/" + quote(event_id, safe="")), not_found_ok=True
    )


async def _upsert_event(booking: AdBooking, date_iso: str, event_id: str | None) -> str:
    payload = _event_payload(booking, date_iso)
    if event_id:
        result = await _calendar_request(
            "PATCH",
            _calendar_path("/" + quote(event_id, safe="")),
            payload,
            not_found_ok=True,
        )
        if result is not None:
            return result["id"]
    result = await _calendar_request("POST", _calendar_path(), payload)
    if not result or not result.get("id"):
        raise RuntimeError("Google Calendar did not return an event id")
    return result["id"]


def _priority(booking: AdBooking) -> tuple[int, int]:
    return ({"paid": 0, "pending": 1, "closed": 2}.get(booking.status, 9), booking.id)


async def sync_date(date_iso: str) -> None:
    """Приводит одну дату в Calendar к текущему состоянию базы."""
    if not enabled():
        return
    date.fromisoformat(date_iso)
    async with get_session() as session:
        bookings = list((await session.scalars(
            select(AdBooking).where(AdBooking.status.in_(_BLOCKING))
        )).all())
        candidates = [b for b in bookings if date_iso in _booking_dates(b)]
        winner = min(candidates, key=_priority) if candidates else None
        mappings = list((await session.scalars(
            select(Meta).where(Meta.key.like(f"{_META_PREFIX}%:{date_iso}"))
        )).all())

        keep_key = _meta_key(winner.id, date_iso) if winner else None
        keep = next((item for item in mappings if item.key == keep_key), None)
        for item in mappings:
            if item.key == keep_key:
                continue
            await _delete_event(item.value)
            await session.delete(item)

        if winner is None:
            await session.commit()
            return

        event_id = await _upsert_event(winner, date_iso, keep.value if keep else None)
        await session.merge(Meta(key=keep_key, value=event_id))
        await session.commit()


async def sync_booking(booking_id: int) -> None:
    """Синхронизирует все даты брони, включая ранее сохранённые mappings."""
    if not enabled():
        return
    async with get_session() as session:
        booking = await session.get(AdBooking, booking_id)
        mappings = list((await session.scalars(
            select(Meta).where(Meta.key.like(f"{_META_PREFIX}{booking_id}:%"))
        )).all())
    dates = set(_booking_dates(booking)) if booking else set()
    dates.update(
        parts[1]
        for item in mappings
        if (parts := _meta_parts(item.key)) is not None
    )
    for date_iso in sorted(dates):
        await sync_date(date_iso)


async def safe_sync_booking(booking_id: int) -> None:
    try:
        await sync_booking(booking_id)
    except Exception as exc:  # noqa: BLE001 — Calendar не должен ломать оплату
        log.warning("Не синхронизировал рекламную бронь #%s с Calendar: %s", booking_id, exc)


async def reconcile_calendar() -> None:
    """Полная сверка будущих дат; восстанавливает пропущенные webhook-вызовы."""
    if not enabled():
        return
    async with get_session() as session:
        bookings = list((await session.scalars(
            select(AdBooking).where(AdBooking.status.in_(_BLOCKING))
        )).all())
        mappings = list((await session.scalars(
            select(Meta).where(Meta.key.like(f"{_META_PREFIX}%"))
        )).all())
    today = _today().isoformat()
    dates = {
        date_iso
        for booking in bookings
        for date_iso in _booking_dates(booking)
        if date_iso >= today
    }
    dates.update(
        parts[1]
        for item in mappings
        if (parts := _meta_parts(item.key)) is not None and parts[1] >= today
    )
    failures = []
    for date_iso in sorted(dates):
        try:
            await sync_date(date_iso)
        except Exception as exc:  # noqa: BLE001 — одна дата не блокирует остальные
            log.warning("Не синхронизировал рекламную дату %s: %s", date_iso, exc)
            failures.append((date_iso, exc))
    if failures:
        date_iso, exc = failures[0]
        raise RuntimeError(
            f"не синхронизировано дат: {len(failures)}; первая — {date_iso}: {exc}"
        )


async def _notify_admins(bot, text: str) -> None:
    if bot is None:
        return
    for admin_id in config.ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text)
        except Exception as exc:  # noqa: BLE001
            log.warning("Не уведомил администратора о Google Calendar: %s", exc)


async def calendar_sync_loop(bot=None) -> None:
    errors = calendar_configuration_errors()
    if errors:
        log.warning("Google Calendar рекламы выключен: %s", "; ".join(errors))
        await _notify_admins(
            bot,
            "❌ <b>Google Calendar рекламы не работает</b>\n\n"
            + "\n".join(f"• {item}" for item in errors)
            + "\n\nПосле настройки запустите <code>/adcalendar</code>.",
        )
        return
    first_error_reported = False
    while True:
        try:
            await reconcile_calendar()
            first_error_reported = False
        except Exception as exc:  # noqa: BLE001
            log.warning("Ошибка полной сверки рекламного Calendar: %s", exc)
            if not first_error_reported:
                await _notify_admins(
                    bot,
                    "❌ <b>Ошибка Google Calendar рекламы</b>\n\n"
                    f"<code>{str(exc)[:900]}</code>\n\n"
                    "После исправления доступа запустите <code>/adcalendar</code>.",
                )
                first_error_reported = True
        await asyncio.sleep(_SYNC_INTERVAL_SECONDS)
