"""Местоположение участников: GPS → населённый пункт через Google Geocoding API (ключ GOOGLE_MAPS_API_KEY).

Определяется ЛЮБОЙ населённый пункт Нидерландов, Германии и Бельгии — город, пригород или деревня, — а не только
крупные города из списка. Название — официальное, латиницей, как пишут в самой стране (Amsterdam, Den Haag, München,
Gent, Liège): так же, как в постах, барахолке и чатах. Страна — по-русски, как в профиле.

POST /api/app/me/location {lat, lng}  — определить место по координатам и записать в профиль (город, страна, координаты)
GET  /api/app/geo/search?q=&country=  — поиск населённого пункта по названию (если GPS недоступен или выключен)

Лента «Рядом» берёт посты в радиусе NEAR_KM от сохранённых координат (near_clause).
"""
from __future__ import annotations

import logging
import math
import time
from datetime import datetime, timezone

import aiohttp
from aiohttp import web

import config
from database.db import get_session
from database.models import Country
from utils.app_api import _user, user_json
from utils.community import _rate
from utils.site_api import _body, _err, _json

log = logging.getLogger(__name__)

GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
NEAR_KM = 50
COUNTRIES = {"NL": Country.NL, "DE": Country.DE, "BE": Country.BE}
CODES = {v: k for k, v in COUNTRIES.items()}
# Типы адресных компонентов от самого точного к общему: деревня/город → пригород → община
_PLACE_TYPES = ("locality", "postal_town", "sublocality", "administrative_area_level_3", "administrative_area_level_2")
_cache: dict[tuple, tuple[float, object]] = {}
_CACHE_TTL = 7 * 86400


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def enabled() -> bool:
    return bool(config.GOOGLE_MAPS_API_KEY)


def _language(code: str, lat: float) -> str:
    """Язык названия — язык самой местности: nl для Нидерландов и Фландрии, fr для Валлонии, de для Германии."""
    if code == "DE":
        return "de"
    if code == "BE" and lat < 50.75 and not 50.78 < lat < 50.92:   # Брюссель (около 50.85) — нидерландское «Brussel»
        return "fr"
    return "nl"


async def _geocode(params: dict) -> list[dict]:
    """Запрос к Geocoding API. Пустой список — ничего не нашлось или API недоступен (причина — в логе)."""
    if not enabled():
        return []
    key = tuple(sorted(params.items()))
    hit = _cache.get(key)
    if hit and hit[0] > time.monotonic():
        return hit[1]  # type: ignore[return-value]
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(GEOCODE_URL, params=params | {"key": config.GOOGLE_MAPS_API_KEY},
                             timeout=aiohttp.ClientTimeout(total=10)) as r:
                data = await r.json(content_type=None)
    except Exception as e:  # noqa: BLE001
        log.warning("Geocoding: сеть: %s", e)
        return []
    status = data.get("status")
    if status not in ("OK", "ZERO_RESULTS"):
        # REQUEST_DENIED — для ключа не включён Geocoding API в Google Cloud
        log.error("Geocoding: %s %s", status, data.get("error_message", ""))
        return []
    results = data.get("results") or []
    _cache[key] = (time.monotonic() + _CACHE_TTL, results)
    if len(_cache) > 5000:
        _cache.clear()
    return results


def _place(result: dict) -> dict | None:
    """{name, country, code, lat, lng} из ответа Google, только для NL/DE/BE."""
    comps = result.get("address_components") or []
    code = next((c.get("short_name") for c in comps if "country" in c.get("types", [])), "")
    if code not in COUNTRIES:
        return None
    name = ""
    for t in _PLACE_TYPES:
        name = next((c.get("long_name") for c in comps if t in c.get("types", [])), "")
        if name:
            break
    if not name:
        return None
    loc = (result.get("geometry") or {}).get("location") or {}
    return {"name": name[:80], "country": COUNTRIES[code].value, "code": code,
            "lat": loc.get("lat"), "lng": loc.get("lng")}


async def reverse(lat: float, lng: float) -> dict | None:
    """Населённый пункт по координатам: сначала на «языке местности», чтобы название было официальным."""
    # Координаты округляем до ~100 м: и кэш работает, и точное место человека не уходит в логи и кэш
    lat, lng = round(lat, 3), round(lng, 3)
    first = await _geocode({"latlng": f"{lat},{lng}", "result_type": "|".join(_PLACE_TYPES[:4])})
    if not first:
        first = await _geocode({"latlng": f"{lat},{lng}"})
    if not first:
        return None
    base = next((p for p in map(_place, first) if p), None)
    if not base:
        return None
    lang = _language(base["code"], lat)
    local = await _geocode({"latlng": f"{lat},{lng}", "result_type": "|".join(_PLACE_TYPES[:4]), "language": lang})
    named = next((p for p in map(_place, local) if p), None)
    return (named or base) | {"lat": lat, "lng": lng}


async def search(q: str, country: Country | None = None) -> list[dict]:
    """Населённые пункты по названию (до 8), только в трёх странах."""
    comps = f"country:{CODES[country]}" if country else "country:NL|country:DE|country:BE"
    results = await _geocode({"address": q, "components": comps, "language": "nl" if country != Country.DE else "de"})
    out, seen = [], set()
    for r in results:
        if not set(r.get("types", [])) & set(_PLACE_TYPES + ("political",)):
            continue
        p = _place(r)
        if p and (p["name"], p["code"]) not in seen:
            seen.add((p["name"], p["code"]))
            out.append(p)
    return out[:8]


def near_clause(lat_col, lng_col, lat: float, lng: float, km: float = NEAR_KM):
    """Условие SQL «в радиусе km»: равнопромежуточная проекция — только арифметика, работает и в PostgreSQL, и в SQLite.
    Погрешность на 50 км в наших широтах — доли процента."""
    k = math.cos(math.radians(lat))
    r = km / 111.32
    return ((lat_col - lat) * (lat_col - lat) + (lng_col - lng) * k * (lng_col - lng) * k) <= r * r


def _coord(v, lo: float, hi: float) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if lo <= x <= hi and math.isfinite(x) else None


async def set_location(request: web.Request) -> web.Response:
    """POST /api/app/me/location {lat, lng} → {user, place}."""
    data = await _body(request)
    lat, lng = _coord(data.get("lat"), -90, 90), _coord(data.get("lng"), -180, 180)
    if lat is None or lng is None:
        return _err(request, "Нет координат.")
    async with get_session() as session:
        me = await _user(request, session)
        await session.commit()
    if not me:
        return _err(request, "Войдите заново.", 401)
    if _rate(f"geo:{me.id}", 30, 3600):
        return _err(request, "Слишком часто. Попробуйте через несколько минут.", 429)
    if not enabled():
        return _err(request, "Определение места временно недоступно. Выберите город вручную.", 503)
    place = await reverse(lat, lng)
    if not place:
        return _err(request, "Похоже, вы не в Нидерландах, Германии или Бельгии. Выберите город вручную.", 422)
    async with get_session() as session:
        me = await _user(request, session)
        me.city, me.country = place["name"], Country.parse(place["country"])
        me.lat, me.lng, me.geo_at = place["lat"], place["lng"], _now()
        user = user_json(me)
        await session.commit()
    return _json(request, {"ok": True, "user": user, "place": {k: place[k] for k in ("name", "country")}})


async def geo_search(request: web.Request) -> web.Response:
    q = " ".join(request.query.get("q", "").split())[:80]
    if len(q) < 2:
        return _json(request, {"ok": True, "places": []})
    country = None
    if request.query.get("country"):
        try:
            country = Country.parse(request.query["country"])
        except ValueError:
            return _err(request, "Страна: Нидерланды, Германия или Бельгия.")
    if _rate(f"geoq:{request.remote}", 120, 3600):
        return _err(request, "Слишком много запросов. Попробуйте позже.", 429)
    places = await search(q, country)
    return _json(request, {"ok": True, "places": [{k: p[k] for k in ("name", "country", "lat", "lng")} for p in places],
                           "available": enabled()})


def install_routes(app: web.Application) -> None:
    app.router.add_post("/api/app/me/location", set_location)
    app.router.add_get("/api/app/geo/search", geo_search)
