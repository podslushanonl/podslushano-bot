"""Уведомления приложения, которые приходят сами (сервер: Expo push через utils/push.py).

1. Утренняя сводка — каждый день в 7:30 по Амстердаму, по провинции человека:
   погода на день, сколько сегодня событий, главная новость. Нажатие открывает «Сегодня».
2. Сбои на своей станции — проверка каждые 5 минут: текущие сбои NS и ремонт, который начнётся
   в ближайшие сутки, на станции, которую приложение выбрало у дома (или человек сам). Один сбой —
   одно уведомление. Нажатие открывает «Поезда».

Что получать, человек выбирает в профиле приложения (поля morning и trains у устройства).
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import date, datetime
from zoneinfo import ZoneInfo

import aiohttp
from sqlalchemy import select

from database.db import get_session
from database.models import AppPushToken, Meta
from utils.push import PROVINCES, send_each

log = logging.getLogger(__name__)
TZ = ZoneInfo("Europe/Amsterdam")
MORNING_AT = (7, 30)
SITE_JSON = "https://www.podslushano.nl/wp-json/pn/v1/app"
# Центры провинций (как в приложении) — для прогноза погоды
CENTER = {"gr": (53.22, 6.57), "fr": (53.2, 5.8), "dr": (52.99, 6.56), "ov": (52.51, 6.09), "fl": (52.52, 5.47),
          "ge": (51.98, 5.91), "ut": (52.09, 5.12), "nh": (52.38, 4.64), "zh": (52.08, 4.31), "ze": (51.5, 3.61),
          "nb": (51.69, 5.3), "li": (50.85, 5.69)}
WMO = {0: "ясно", 1: "почти ясно", 2: "переменная облачность", 3: "пасмурно", 45: "туман", 48: "туман",
       51: "морось", 53: "морось", 55: "морось", 61: "дождь", 63: "дождь", 65: "сильный дождь", 66: "ледяной дождь",
       67: "ледяной дождь", 71: "снег", 73: "снег", 75: "сильный снег", 77: "снежная крупа", 80: "ливни", 81: "ливни",
       82: "сильные ливни", 85: "снегопад", 86: "снегопад", 95: "гроза", 96: "гроза с градом", 99: "гроза с градом"}


def plural(n: int, forms: tuple[str, str, str]) -> str:
    n10, n100 = n % 10, n % 100
    return forms[0] if n10 == 1 and n100 != 11 else forms[1] if 2 <= n10 <= 4 and not 12 <= n100 <= 14 else forms[2]


def morning_text(province: str, weather: dict | None, events_today: int, headline: str) -> tuple[str, str]:
    """Заголовок и текст утренней сводки."""
    name = PROVINCES.get(province, "")
    if weather:
        title = f"{name}: {weather['min']:+.0f}…{weather['max']:+.0f}°, {WMO.get(weather['code'], 'погода меняется')}"
        if weather.get("rain", 0) >= 60:
            title += ", возьмите зонт"
    else:
        title = f"Доброе утро, {name}"
    parts = []
    if events_today:
        parts.append(f"Сегодня {events_today} {plural(events_today, ('событие', 'события', 'событий'))} в провинции")
    if headline:
        parts.append(headline)
    return title[:80], (". ".join(parts) or "Новости, события и важные даты — в приложении.")[:178]


async def _json(session: aiohttp.ClientSession, url: str, **params):
    try:
        async with session.get(url, params=params or None, timeout=aiohttp.ClientTimeout(total=20)) as r:
            return await r.json(content_type=None) if r.status == 200 else None
    except Exception as e:  # noqa: BLE001
        log.info("app_alerts: %s unavailable: %s", url.split("?")[0], e)
        return None


async def _weather(session: aiohttp.ClientSession, province: str) -> dict | None:
    lat, lon = CENTER[province]
    d = await _json(session, "https://api.open-meteo.com/v1/forecast", latitude=str(lat), longitude=str(lon),
                    daily="weathercode,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                    timezone="Europe/Amsterdam", forecast_days="1")
    try:
        day = d["daily"]
        return {"code": int(day["weathercode"][0]), "max": float(day["temperature_2m_max"][0]),
                "min": float(day["temperature_2m_min"][0]), "rain": int(day["precipitation_probability_max"][0] or 0)}
    except Exception:  # noqa: BLE001
        return None


def events_on(events: list[dict], province: str, day: date) -> int:
    d = day.isoformat()
    return sum(1 for e in events if (e.get("province") == province)
               and (e.get("date") or "") <= d <= (e.get("end") or e.get("date") or ""))


async def send_morning(today: date | None = None, skip: set[str] | None = None) -> list[str]:
    """Разослать сводку тем, кто её ещё не получил сегодня (skip). Возвращает токены, которые Expo принял."""
    today = today or datetime.now(TZ).date()
    skip = skip or set()
    async with get_session() as session:
        rows = [(t, p) for t, p in await session.execute(select(AppPushToken.token, AppPushToken.province).where(
            AppPushToken.active.is_(True), AppPushToken.morning.is_(True))) if t not in skip]
    if not rows:
        return []
    from utils.auto_events import load as auto_events
    async with aiohttp.ClientSession(trust_env=True) as s:
        site = await _json(s, SITE_JSON) or {}
        events = (site.get("events") or []) + auto_events()
        news = site.get("news") or []
        headline = (news[0].get("h") or "") if news else ""
        msgs = []
        for province in sorted({p for _, p in rows if p in CENTER}):
            title, body = morning_text(province, await _weather(s, province), events_on(events, province, today), headline)
            msgs += [{"to": t, "title": title, "body": body, "data": {"url": "/"}} for t, p in rows if p == province]
    ok = await send_each(msgs)
    done = [m["to"] for m, good in zip(msgs, ok) if good]
    log.info("app_alerts: morning sent %d of %d", len(done), len(msgs))
    return done


def station_alerts(tokens: list[tuple[str, str, str, str]], items: list[dict]) -> tuple[list[dict], list[str]]:
    """Сообщения о сбоях для устройств (token, station, station_name, sent_alerts) и id сбоя каждого сообщения."""
    msgs, ids = [], []
    for token, station, name, sent in tokens:
        done = [x for x in (sent or "").split(",") if x]
        for x in items:
            if not x.get("id") or x["id"] in done or station not in (x.get("stations") or []):
                continue
            kind = x.get("type_ru") or "Изменения"
            when = "" if x.get("active", True) else (f" С {x['start_ru']}." if x.get("start_ru") else "")
            body = " ".join(filter(None, [x.get("title") or "", x.get("situation") or "", when.strip()]))
            msgs.append({"to": token, "title": f"Поезда · {name or station}: {kind.lower()}"[:80], "body": body[:178],
                         "data": {"url": "/trains"}})
            ids.append(x["id"])
            done.append(x["id"])
    return msgs, ids


def new_marks(tokens: list[tuple[str, str, str, str]], msgs: list[dict], ids: list[str], ok: list[bool]) -> dict[str, str]:
    """Отметки «уже отправлено»: только сбои, которые Expo принял — остальные повторятся при следующей проверке."""
    prev = {t: [x for x in (sent or "").split(",") if x] for t, _, _, sent in tokens}
    marks: dict[str, list[str]] = {}
    for m, aid, good in zip(msgs, ids, ok):
        if good:
            marks.setdefault(m["to"], list(prev.get(m["to"], []))).append(aid)
    return {t: ",".join(v[-40:]) for t, v in marks.items()}


async def check_trains() -> int:
    from utils import ns_alerts, ns_trains
    async with get_session() as session:
        tokens = [tuple(r) for r in await session.execute(select(
            AppPushToken.token, AppPushToken.station, AppPushToken.station_name, AppPushToken.sent_alerts).where(
            AppPushToken.active.is_(True), AppPushToken.trains.is_(True), AppPushToken.station != ""))]
    if not tokens:
        return 0
    items = ns_alerts.relevant(await ns_trains.get_disruptions())
    msgs, ids = station_alerts(tokens, items)
    if not msgs:
        return 0
    ok = await send_each(msgs)
    marks = new_marks(tokens, msgs, ids, ok)
    sent = sum(ok)
    async with get_session() as session:
        for row in await session.scalars(select(AppPushToken).where(AppPushToken.token.in_(list(marks)))):
            row.sent_alerts = marks[row.token]
        await session.commit()
    return sent


MORNING_KEY = "app_morning_push"


def morning_window(now: datetime) -> bool:
    """Сводку шлём с 7:30 до 11:00: позже она уже не утренняя."""
    return MORNING_AT <= (now.hour, now.minute) and now.hour < 11


async def morning_round(now: datetime) -> int:
    """Одна попытка утренней рассылки. Прогресс по получателям хранится в meta:
    значение «дата|токен,токен…» — кто уже получил; «дата|done» — все получили.
    Сбой Expo или ошибка не теряют сводку: в следующий раз дошлём тем, кому не дошло."""
    if not morning_window(now):
        return 0
    day = now.date().isoformat()
    async with get_session() as session:
        row = await session.get(Meta, MORNING_KEY)
        value = row.value if row else ""
    stamp, _, got = value.partition("|")
    if stamp == day and got == "done":
        return 0
    have = set(got.split(",")) - {""} if stamp == day else set()
    done = await send_morning(now.date(), have)
    async with get_session() as session:
        total = {t for (t,) in await session.execute(select(AppPushToken.token).where(
            AppPushToken.active.is_(True), AppPushToken.morning.is_(True)))}
        have |= set(done)
        mark = "done" if total <= have else ",".join(sorted(have & total))
        await session.merge(Meta(key=MORNING_KEY, value=f"{day}|{mark}"))
        await session.commit()
    return len(done)


async def app_alerts_loop() -> None:
    from utils import ns_trains
    await asyncio.sleep(120)
    while True:
        started = time.monotonic()
        try:
            await morning_round(datetime.now(TZ))
        except Exception:  # noqa: BLE001
            log.exception("app_alerts: morning failed")
        try:
            if ns_trains._key():
                n = await check_trains()
                if n:
                    log.info("app_alerts: train alerts sent %d", n)
        except Exception:  # noqa: BLE001
            log.exception("app_alerts: trains failed")
        await asyncio.sleep(max(60, 300 - (time.monotonic() - started)))


__all__ = ["app_alerts_loop", "morning_text", "station_alerts", "new_marks", "events_on", "morning_round"]
