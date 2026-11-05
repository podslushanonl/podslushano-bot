"""Файл события для календаря: GET /api/app/event/{key}.ics

Кнопка «В календарь» в приложении открывает эту ссылку в браузере: на iPhone Safari сам предлагает
«Добавить в Календарь», на Android файл открывается в приложении календаря. Разрешение на доступ
к календарю не нужно. Данные события берём с сайта (тот же JSON, что читает приложение), а не из
ссылки: так файл на нашем домене нельзя заполнить чужим текстом.
"""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timedelta

import aiohttp
from aiohttp import web


log = logging.getLogger(__name__)

SITE_JSON = "https://www.podslushano.nl/wp-json/pn/v1/app"
_cache: dict = {"at": 0.0, "events": []}
CACHE_SEC = 600
DEFAULT_HOURS = 2   # длительность, если время окончания неизвестно


async def _events() -> list[dict]:
    if time.time() - _cache["at"] < CACHE_SEC and _cache["events"]:
        return _cache["events"]
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(SITE_JSON, timeout=aiohttp.ClientTimeout(total=20)) as r:
                data = await r.json(content_type=None)
        _cache.update(at=time.time(), events=data.get("events") or [])
    except Exception as e:  # noqa: BLE001 — при сбое отдаём то, что было
        log.warning("ics: site events unavailable: %s", e)
    return _cache["events"]


def _esc(s: str) -> str:
    return (s or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r", "").replace("\n", "\\n")


def _fold(line: str) -> str:
    """Строки iCalendar не длиннее 75 байт: длинные переносятся с пробелом в начале."""
    out, cur = [], ""
    for ch in line:
        if len((cur + ch).encode()) > 73:
            out.append(cur)
            cur = " " + ch
        else:
            cur += ch
    out.append(cur)
    return "\r\n".join(out)


def build_ics(e: dict, now: datetime | None = None) -> str:
    date = str(e.get("date") or "")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        raise ValueError("no date")
    tm = str(e.get("time") or "")
    end = str(e.get("end") or "")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//podslushano.nl//app//RU", "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
             "BEGIN:VEVENT", f"UID:{e.get('key')}@podslushano.nl",
             f"DTSTAMP:{(now or datetime.utcnow()).strftime('%Y%m%dT%H%M%SZ')}"]
    if re.fullmatch(r"\d{1,2}:\d{2}", tm):
        start = datetime.strptime(f"{date} {tm.zfill(5)}", "%Y-%m-%d %H:%M")
        finish = start + timedelta(hours=DEFAULT_HOURS)
        lines += [f"DTSTART;TZID=Europe/Amsterdam:{start:%Y%m%dT%H%M%S}", f"DTEND;TZID=Europe/Amsterdam:{finish:%Y%m%dT%H%M%S}"]
    else:   # без времени — событие на весь день (или на несколько дней, если есть дата окончания)
        last = datetime.strptime(end if re.fullmatch(r"\d{4}-\d{2}-\d{2}", end) else date, "%Y-%m-%d")
        lines += [f"DTSTART;VALUE=DATE:{date.replace('-', '')}", f"DTEND;VALUE=DATE:{(last + timedelta(days=1)):%Y%m%d}"]
    place = ", ".join(x for x in (e.get("venue"), e.get("addr") or e.get("city")) if x)
    url = e.get("url") if e.get("src") else f"https://www.podslushano.nl/events/{e.get('key')}/"
    # описание собираем отдельно: в Python 3.11 (сервер) внутри f-строки нельзя писать «\n»
    desc = ((e.get("s") or "") + "\n" if e.get("s") else "") + "Афиша podslushano.nl: " + url
    lines += [_fold(f"SUMMARY:{_esc(e.get('h', ''))}"), _fold(f"LOCATION:{_esc(place)}"), _fold(f"URL:{url}"),
              _fold("DESCRIPTION:" + _esc(desc)),
              "END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(lines) + "\r\n"


async def event_ics(request: web.Request) -> web.Response:
    key = request.match_info["key"]
    from utils.auto_events import load as auto_events
    e = next((x for x in [*await _events(), *auto_events()] if x.get("key") == key), None)
    if not e:
        return web.Response(status=404, text="Событие не найдено")
    try:
        body = build_ics(e)
    except ValueError:
        return web.Response(status=404, text="У события нет даты")
    return web.Response(body=body.encode(), content_type="text/calendar", charset="utf-8",
                        headers={"Content-Disposition": f'inline; filename="{key}.ics"', "Cache-Control": "public, max-age=600"})


def install_routes(app: web.Application) -> None:
    app.router.add_get(r"/api/app/event/{key:[A-Za-z0-9_\-]{1,120}}.ics", event_ics)
