"""Поезда NS для сайта и виджета: отправления со станции и сбои.

Ключ NS API (продукт «Ns-App», Reisinformatie API) берётся из NS_API_KEY
и никогда не уходит в браузер: сайт ходит сюда, а не в NS напрямую.
"""
import logging
import os
import re
import time

import aiohttp
from aiohttp import web

log = logging.getLogger(__name__)

NS_BASE = "https://gateway.apiportal.ns.nl/reisinformatie-api/api"
DEPARTURES_TTL = 60
DISRUPTIONS_TTL = 300
_STATION_RE = re.compile(r"^[A-Za-z0-9]{2,8}$")
_CATEGORY_RU = {"IC": "Интерсити", "ICD": "Интерсити Директ", "SPR": "Спринтер",
                "ICE": "ICE", "EST": "Eurostar", "NSI": "NS International"}

_DISRUPTION_RU = {"CALAMITY": "Сбой", "DISRUPTION": "Нарушение движения",
                  "MAINTENANCE": "Ремонтные работы"}

_cache: dict[str, tuple[float, dict]] = {}


def _key() -> str:
    return os.getenv("NS_API_KEY", "").strip()


async def _ns_get(path: str, params: dict) -> dict:
    timeout = aiohttp.ClientTimeout(total=10)
    headers = {"Ocp-Apim-Subscription-Key": _key(), "Cache-Control": "no-cache"}
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(f"{NS_BASE}{path}", params=params, headers=headers) as resp:
            if resp.status != 200:
                raise RuntimeError(f"NS API {path}: HTTP {resp.status}")
            return await resp.json()


async def _cached(name: str, ttl: int, loader) -> dict:
    hit = _cache.get(name)
    if hit and time.monotonic() - hit[0] < ttl:
        return hit[1]
    data = await loader()
    _cache[name] = (time.monotonic(), data)
    return data


def _delay_min(planned: str | None, actual: str | None) -> int:
    if not planned or not actual or planned == actual:
        return 0
    from datetime import datetime
    fmt = "%Y-%m-%dT%H:%M:%S%z"
    try:
        return max(0, round((datetime.strptime(actual, fmt) - datetime.strptime(planned, fmt)).total_seconds() / 60))
    except ValueError:
        return 0


def normalize_departures(payload: dict, limit: int) -> list[dict]:
    out = []
    for d in (payload.get("payload") or {}).get("departures") or []:
        product = d.get("product") or {}
        cat = product.get("categoryCode") or d.get("trainCategory") or product.get("shortCategoryName") or ""
        planned = d.get("plannedDateTime")
        actual = d.get("actualDateTime") or planned
        out.append({
            "direction": d.get("direction") or "",
            "time": (planned or "")[11:16],
            "delay": _delay_min(planned, actual),
            "track": d.get("actualTrack") or d.get("plannedTrack") or "",
            "track_changed": bool(d.get("actualTrack") and d.get("plannedTrack")
                                  and d["actualTrack"] != d["plannedTrack"]),
            "category": _CATEGORY_RU.get(cat, cat),
            "operator": product.get("operatorName") or "",
            "cancelled": bool(d.get("cancelled")),
            "via": [s.get("mediumName") for s in (d.get("routeStations") or [])[:3] if s.get("mediumName")],
        })
        if len(out) >= limit:
            break
    return out


def _json(data: dict, status: int = 200) -> web.Response:
    resp = web.json_response(data, status=status)
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Cache-Control"] = "public, max-age=60"
    return resp


async def departures(request: web.Request) -> web.Response:
    station = request.query.get("station", "UT")
    if not _STATION_RE.match(station):
        return _json({"error": "bad_station"}, 400)
    try:
        limit = min(max(int(request.query.get("limit", "6")), 1), 20)
    except ValueError:
        limit = 6
    if not _key():
        return _json({"error": "ns_key_missing"}, 503)
    station = station.upper()
    try:
        raw = await _cached(f"dep:{station}", DEPARTURES_TTL,
                            lambda: _ns_get("/v2/departures", {"station": station, "maxJourneys": 20}))
    except Exception as e:  # noqa: BLE001 — отдаём сайту понятную ошибку, детали в лог
        log.warning("NS departures %s: %s", station, e)
        return _json({"error": "ns_unavailable"}, 502)
    return _json({"station": station, "departures": normalize_departures(raw, limit),
                  "source": "NS"})


async def disruptions(request: web.Request) -> web.Response:
    if not _key():
        return _json({"error": "ns_key_missing"}, 503)
    try:
        raw = await _cached("disruptions", DISRUPTIONS_TTL,
                            lambda: _ns_get("/v3/disruptions", {"isActive": "true"}))
    except Exception as e:  # noqa: BLE001
        log.warning("NS disruptions: %s", e)
        return _json({"error": "ns_unavailable"}, 502)
    items = raw if isinstance(raw, list) else raw.get("payload") or []
    out = [{"type": i.get("type"), "type_ru": _DISRUPTION_RU.get(i.get("type"), "Изменения"),
            "title": i.get("title") or ""}
           for i in items if i.get("isActive", True)]
    return _json({"count": len(out), "items": out[:20], "source": "NS"})


def install_routes(app: web.Application) -> None:
    app.router.add_get("/api/ns/departures", departures)
    app.router.add_get("/api/ns/disruptions", disruptions)
