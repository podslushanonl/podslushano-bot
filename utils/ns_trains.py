"""Поезда NS для сайта и виджета: отправления со станции и сбои.

Ключ NS API (продукт «Ns-App», Reisinformatie API) берётся из NS_API_KEY
и никогда не уходит в браузер: сайт ходит сюда, а не в NS напрямую.
"""
import json
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


# --- сбои и работы: русские формулировки -------------------------------------------------
# Типовые фразы NS переводим словарём; редкие — один раз через Claude Haiku (кэш в памяти).
_SITUATION_RU = {
    "er rijden geen treinen": "Поезда не ходят",
    "er rijden minder treinen": "Поездов меньше обычного",
    "er rijden geen sprinters": "Спринтеры не ходят",
    "er rijden minder sprinters": "Спринтеров меньше обычного",
    "er rijden geen intercity's": "Интерсити не ходят",
    "er rijden minder intercity's": "Интерсити меньше обычного",
    "er rijden geen internationale treinen": "Международные поезда не ходят",
    "er rijden minder internationale treinen": "Международных поездов меньше",
    "treinen rijden met een aangepaste dienstregeling": "Поезда ходят по изменённому расписанию",
    "er rijden extra bussen": "Ходят дополнительные автобусы",
    "er rijden bussen": "Вместо поездов ходят автобусы",
}
_CAUSE_RU = {
    "werkzaamheden": "ремонтные работы",
    "werkzaamheden aan het spoor": "ремонтные работы на путях",
    "een defect aan het spoor": "неисправность пути",
    "een storing aan het spoor": "неисправность пути",
    "een defecte trein": "неисправный поезд",
    "een defect aan een trein": "неисправный поезд",
    "een storing aan een trein": "неисправный поезд",
    "een aanrijding met een persoon": "наезд на человека",
    "een aanrijding met een voertuig": "столкновение с автомобилем",
    "een aanrijding": "столкновение",
    "een seinstoring": "неисправность сигнализации",
    "een storing in de bediening van seinen": "неисправность сигнализации",
    "een wisselstoring": "неисправность стрелки",
    "een defecte overweg": "неисправный переезд",
    "een overwegstoring": "неисправный переезд",
    "een stroomstoring": "отключение электричества",
    "een defecte bovenleiding": "повреждение контактной сети",
    "schade aan de bovenleiding": "повреждение контактной сети",
    "een verstoring elders": "сбой на другом участке",
    "een eerdere verstoring": "последствия более раннего сбоя",
    "hulpverlening": "работа экстренных служб",
    "inzet van hulpdiensten": "работа экстренных служб",
    "politie-inzet": "работа полиции",
    "inzet van de politie": "работа полиции",
    "brand": "пожар",
    "een brand": "пожар",
    "een staking": "забастовка",
    "staking": "забастовка",
    "weersomstandigheden": "погодные условия",
    "slechte weersomstandigheden": "плохая погода",
    "harde wind": "сильный ветер",
    "een boom op het spoor": "дерево на путях",
    "een persoon langs het spoor": "человек возле путей",
    "personen langs het spoor": "люди возле путей",
    "vee op het spoor": "животные на путях",
    "een technisch probleem": "техническая неисправность",
    "een storing in een ict-systeem": "сбой IT-системы",
    "een beperkte inzet van personeel": "нехватка персонала",
    "een bermbrand": "пожар у путей",
    "een ongeval": "происшествие",
}
_tr_cache: dict[str, str] = {}
_RU_MONTHS = ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]
_RU_DAYS = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]


def _norm(text: str) -> str:
    t = re.sub(r"\s+", " ", (text or "").strip().rstrip(".")).lower()
    return re.sub(r"^(door|vanwege|wegens)\s+", "", t)


def _dict_ru(text: str, table: dict) -> str | None:
    return table.get(_norm(text)) if text else None


async def _translate(texts: list[str]) -> None:
    """Переводит фразы, которых нет в словарях, одним запросом к Haiku. Тихо пропускает ошибки."""
    todo = [t for t in dict.fromkeys(texts) if t and t not in _tr_cache]
    if not todo or not os.getenv("ANTHROPIC_API_KEY"):
        return
    try:
        import config
        from utils.ai import _get_client, _parse_json
        prompt = ("Переведи на русский короткие сообщения NS о поездах. Названия станций и городов оставь "
                  "как есть, латиницей. Коротко, без пояснений. Ответь строго JSON-массивом строк "
                  "в том же порядке.\n" + json.dumps(todo, ensure_ascii=False))
        resp = await _get_client().messages.create(
            model=getattr(config, "SITE_NEWS_TRIAGE_MODEL", "claude-haiku-5-5"), max_tokens=3000,
            messages=[{"role": "user", "content": prompt}],
            extra_body={"output_config": {"effort": "low"}})
        raw = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        out = _parse_json(raw) if raw.strip().startswith("{") else json.loads(raw[raw.index("["):raw.rindex("]") + 1])
        if isinstance(out, list) and len(out) == len(todo):
            for src, ru in zip(todo, out):
                if isinstance(ru, str) and ru.strip():
                    _tr_cache[src] = ru.strip()
        if len(_tr_cache) > 2000:
            _tr_cache.clear()
    except Exception as e:  # noqa: BLE001 — без перевода покажем оригинал
        log.info("NS: перевод не удался: %s", e)


def _ru(text: str, table: dict | None = None) -> str:
    if not text:
        return ""
    return (table and _dict_ru(text, table)) or _tr_cache.get(text) or text


def _parse_ts(value: str | None):
    from datetime import datetime
    if not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M%z"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def _fmt_ts(dt) -> str:
    return f"{_RU_DAYS[dt.weekday()]} {dt.day} {_RU_MONTHS[dt.month - 1]}, {dt:%H:%M}" if dt else ""


def _minutes(obj: dict | None) -> tuple[int | None, int | None]:
    obj = obj or {}
    lo, hi = obj.get("minimumDurationInMinutes"), obj.get("maximumDurationInMinutes")
    if lo is None and hi is None:
        m = re.findall(r"(\d+)", obj.get("shortLabel") or obj.get("label") or "")
        if m:
            lo, hi = int(m[0]), int(m[-1])
    return lo, hi


def _raw_texts(i: dict) -> list[str]:
    if i.get("type") == "CALAMITY":
        return [i.get("title") or "", i.get("description") or ""]
    span = (i.get("timespans") or [{}])[0]
    out = []
    sit = (span.get("situation") or {}).get("label") or ""
    cause = (span.get("cause") or {}).get("label") or ""
    if sit and not _dict_ru(sit, _SITUATION_RU):
        out.append(sit)
    if cause and not _dict_ru(cause, _CAUSE_RU):
        out.append(cause)
    out += [a for a in span.get("advices") or [] if isinstance(a, str)][:2]
    exp = (i.get("expectedDuration") or {}).get("description")
    if exp:
        out.append(exp)
    return out


def normalize_disruption(i: dict) -> dict:
    kind = i.get("type") or ""
    item = {"id": i.get("id") or "", "type": kind, "type_ru": _DISRUPTION_RU.get(kind, "Изменения"),
            "title": (i.get("title") or "").rstrip("."), "active": bool(i.get("isActive", True))}
    if kind == "CALAMITY":
        item["title"] = _ru(i.get("title") or "").rstrip(".")
        item["text"] = _ru(i.get("description") or "")
        return item
    spans = i.get("timespans") or [{}]
    span = spans[0]
    start, end = _parse_ts(i.get("start") or span.get("start")), _parse_ts(i.get("end") or span.get("end"))
    sit = (span.get("situation") or {}).get("label") or ""
    cause = (span.get("cause") or {}).get("label") or ""
    lo, hi = _minutes(i.get("summaryAdditionalTravelTime") or span.get("additionalTravelTime"))
    alt = span.get("alternativeTransport") or {}
    if not alt:
        for t in i.get("alternativeTransportTimespans") or []:
            alt = t.get("alternativeTransport") or {}
            if alt:
                break
    item.update({
        "situation": _ru(sit, _SITUATION_RU),
        "cause": _ru(cause, _CAUSE_RU),
        "start": i.get("start") or span.get("start") or "",
        "end": i.get("end") or span.get("end") or "",
        "start_ru": _fmt_ts(start), "end_ru": _fmt_ts(end),
        "expected": _ru((i.get("expectedDuration") or {}).get("description") or ""),
        "extra_min": lo, "extra_max": hi,
        "buses": bool(alt),
        "advice": [_ru(a) for a in (span.get("advices") or []) if isinstance(a, str)][:2],
        "impact": (i.get("impact") or {}).get("value"),
    })
    return item


async def _load_disruptions() -> dict:
    from datetime import datetime, timedelta, timezone
    raw = await _ns_get("/v3/disruptions", {})
    items = raw if isinstance(raw, list) else raw.get("payload") or []
    await _translate([t for i in items for t in _raw_texts(i)])
    now = datetime.now(timezone.utc)
    soon = now + timedelta(days=7)
    current, planned = [], []
    for i in items:
        n = normalize_disruption(i)
        if n["active"]:
            current.append(n)
        elif n["type"] == "MAINTENANCE":
            st = _parse_ts(n.get("start"))
            if st and now <= st <= soon:
                planned.append(n)
    rank = {"CALAMITY": 0, "DISRUPTION": 1, "MAINTENANCE": 2}
    current.sort(key=lambda x: (rank.get(x["type"], 3), -(x.get("impact") or 0)))
    planned.sort(key=lambda x: x.get("start") or "")
    return {"now": current, "planned": planned[:30]}


async def disruptions(request: web.Request) -> web.Response:
    if not _key():
        return _json({"error": "ns_key_missing"}, 503)
    try:
        data = await _cached("disruptions", DISRUPTIONS_TTL, _load_disruptions)
    except Exception as e:  # noqa: BLE001
        log.warning("NS disruptions: %s", e)
        return _json({"error": "ns_unavailable"}, 502)
    now = data["now"]
    return _json({"count": len(now), "items": now[:20], "now": now, "planned": data["planned"], "source": "NS"})


def install_routes(app: web.Application) -> None:
    app.router.add_get("/api/ns/departures", departures)
    app.router.add_get("/api/ns/disruptions", disruptions)
