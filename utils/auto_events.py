"""Автоматическая афиша по провинциям для приложения: GET /api/app/events.json

Работает сама, без ручного участия:
- Eventbrite (без ключа): страницы поиска по каждой провинции, события берём из разметки schema.org
  (название, дата, площадка, адрес, координаты, фото). Обходим вежливо: по одному запросу с паузой,
  только разрешённые robots.txt пути /d/…, дважды в сутки.
- Ticketmaster Discovery API (если на сервере задан TICKETMASTER_KEY — бесплатный ключ): крупные концерты,
  театр, спорт и детские события по всей стране.

Провинцию определяем по адресу события (код или название провинции), а не по странице поиска:
так событие из соседней провинции или из Бельгии не попадёт не туда. Бизнес-события (конференции,
вебинары, тренинги, ярмарки вакансий) отсеиваются: афиша — про то, куда сходить.

Результат хранится в data/auto_events.json (том Railway) и переживает перезапуски.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import aiohttp
from aiohttp import web

import config

log = logging.getLogger(__name__)
TZ = ZoneInfo("Europe/Amsterdam")
PATH = os.path.join(os.path.dirname(config.DB_PATH), "auto_events.json")
EVERY_SEC = 12 * 3600
PAUSE_SEC = 3.0          # пауза между запросами к одному сайту
HORIZON_DAYS = 120       # дальше не заглядываем: афиша про ближайшие месяцы
UA = "Mozilla/5.0 (compatible; podslushano.nl afisha; +https://www.podslushano.nl)"

# id провинций как в приложении
PROVINCES = {
    "gr": ("Groningen", "groningen"), "fr": ("Friesland", "friesland"), "dr": ("Drenthe", "drenthe"),
    "ov": ("Overijssel", "overijssel"), "fl": ("Flevoland", "flevoland"), "ge": ("Gelderland", "gelderland"),
    "ut": ("Utrecht", "utrecht"), "nh": ("Noord-Holland", "noord-holland"), "zh": ("Zuid-Holland", "zuid-holland"),
    "ze": ("Zeeland", "provincie-zeeland"), "nb": ("Noord-Brabant", "noord-brabant"), "li": ("Limburg", "limburg"),
}
_REGION = {
    "gr": "gr", "groningen": "gr", "fr": "fr", "friesland": "fr", "fryslan": "fr", "dr": "dr", "drenthe": "dr",
    "ov": "ov", "overijssel": "ov", "fl": "fl", "flevoland": "fl", "ge": "ge", "gelderland": "ge",
    "ut": "ut", "utrecht": "ut", "nh": "nh", "noordholland": "nh", "zh": "zh", "zuidholland": "zh",
    "ze": "ze", "zeeland": "ze", "nb": "nb", "noordbrabant": "nb", "brabant": "nb", "li": "li", "limburg": "li",
}
# Категории Eventbrite → подпись в приложении
EB_CATEGORIES = (
    ("music--events", "Концерт"),
    ("performing-visual-arts--events", "Сцена и искусство"),
    ("food-and-drink--events", "Еда и напитки"),
    ("holiday--events", "Праздник"),
    ("all-events", "Событие"),
)
TM_SEGMENTS = {"Music": "Концерт", "Arts & Theatre": "Театр и шоу", "Sports": "Спорт", "Family": "Детям",
               "Film": "Кино", "Miscellaneous": "Событие"}

_SKIP = re.compile(
    r"\b(conferen|congres|symposi|webinar|seminar|training|cursus|course|bootcamp|masterclass business|"
    r"scrum|agile|job ?fair|banenmarkt|vacature|recruit|netwerk|networking|summit|investor|startup|"
    r"accreditat|nascholing|bijscholing|workshop excel|linkedin|sales|marketing|leadership|webinar|"
    r"alumni|hackathon|meetup for developers|sample sale|factory sale)",
    re.I,
)


def _norm(s: str) -> str:
    return re.sub(r"[^a-z]", "", (s or "").lower().replace("â", "a"))


def province_of(region: str = "", city: str = "") -> str:
    """Id провинции по коду/названию региона из адреса, иначе по городу."""
    pid = _REGION.get(_norm(region))
    if pid:
        return pid
    try:
        from utils.geo import province_of_city
        name = province_of_city(city or "")
    except Exception:  # noqa: BLE001
        name = None
    return _REGION.get(_norm(name or ""), "")


def _day(value: str) -> str:
    m = re.match(r"(\d{4}-\d{2}-\d{2})", value or "")
    return m.group(1) if m else ""


def _hm(value: str) -> str:
    m = re.match(r"\d{4}-\d{2}-\d{2}T(\d{2}:\d{2})", value or "")
    return m.group(1) if m and m.group(1) != "00:00" else ""


# ---------------------------------------------------------------- Eventbrite

def parse_eventbrite(raw: str, cat: str) -> list[dict]:
    """События из JSON-LD страницы поиска Eventbrite (ItemList → Event)."""
    out = []
    for block in re.findall(r'<script type="application/ld\+json">(.*?)</script>', raw or "", re.S):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        items = data.get("itemListElement") if isinstance(data, dict) else None
        for it in items or []:
            e = (it or {}).get("item") or {}
            if e.get("@type") != "Event" or not e.get("name") or not e.get("url"):
                continue
            loc = e.get("location") or {}
            if (loc.get("@type") or "") == "VirtualLocation":
                continue
            addr = loc.get("address") or {}
            if (addr.get("addressCountry") or "NL") not in ("NL", "Nederland", "Netherlands"):
                continue
            city = (addr.get("addressLocality") or "").strip()
            if city.islower():
                city = city.title()
            m = re.search(r"-(\d{6,})(?:\?|$)", e["url"])
            out.append({
                "key": f"eb-{m.group(1) if m else hashlib.sha1(e['url'].encode()).hexdigest()[:12]}",
                "h": e["name"].strip()[:160],
                "s": (e.get("description") or "").strip()[:300],
                "date": _day(e.get("startDate", "")),
                "time": _hm(e.get("startDate", "")),
                "end": _day(e.get("endDate", "")),
                "venue": (loc.get("name") or "").strip()[:120],
                "addr": ", ".join(x for x in (addr.get("streetAddress"), city) if x)[:160],
                "city": city,
                "img": e.get("image") or "",
                "url": e["url"].split("?")[0],
                "tickets": [["Eventbrite", e["url"].split("?")[0]]],
                "cat": cat,
                "province": province_of(addr.get("addressRegion", ""), city),
                "src": "eventbrite",
            })
    return out


async def _get(session: aiohttp.ClientSession, url: str, **kw) -> str:
    try:
        async with session.get(url, **kw) as r:
            if r.status != 200:
                log.info("auto_events GET %s -> %s", url.split("?")[0], r.status)
                return ""
            return await r.text()
    except Exception as e:  # noqa: BLE001
        log.info("auto_events GET %s failed: %s", url.split("?")[0], e)
        return ""


async def collect_eventbrite() -> list[dict]:
    rows: list[dict] = []
    headers = {"User-Agent": UA, "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.7"}
    async with aiohttp.ClientSession(headers=headers, timeout=aiohttp.ClientTimeout(total=30), trust_env=True) as s:
        for pid, (_, slug) in PROVINCES.items():
            for path, cat in EB_CATEGORIES:
                for page in ((1, 2) if path == "all-events" else (1,)):
                    q = f"?page={page}" if page > 1 else ""
                    raw = await _get(s, f"https://www.eventbrite.nl/d/netherlands--{slug}/{path}/{q}")
                    found = [r for r in parse_eventbrite(raw, cat) if r["province"] == pid]
                    rows += found
                    await asyncio.sleep(PAUSE_SEC)
                    if not found:
                        break
    return rows


# ---------------------------------------------------------------- Ticketmaster (по ключу)

def parse_ticketmaster(data: dict) -> list[dict]:
    out = []
    for e in ((data or {}).get("_embedded") or {}).get("events") or []:
        venue = (((e.get("_embedded") or {}).get("venues")) or [{}])[0]
        city = ((venue.get("city") or {}).get("name") or "").strip()
        seg = (((e.get("classifications") or [{}])[0]).get("segment") or {}).get("name", "")
        start = (e.get("dates") or {}).get("start") or {}
        imgs = sorted(e.get("images") or [], key=lambda i: -(i.get("width") or 0))
        img = next((i["url"] for i in imgs if (i.get("ratio") == "16_9" and (i.get("width") or 0) <= 1200)), imgs[0]["url"] if imgs else "")
        prices = e.get("priceRanges") or []
        price = f"от €{prices[0]['min']:.0f}".replace(".", ",") if prices and prices[0].get("min") else ""
        out.append({
            "key": f"tm-{e.get('id')}",
            "h": (e.get("name") or "").strip()[:160],
            "s": "",
            "date": start.get("localDate", ""),
            "time": (start.get("localTime") or "")[:5],
            "end": "",
            "venue": (venue.get("name") or "")[:120],
            "addr": ", ".join(x for x in (((venue.get("address") or {}).get("line1")), city) if x)[:160],
            "city": city,
            "img": img,
            "url": e.get("url") or "",
            "tickets": [["Ticketmaster", e.get("url") or ""]] if e.get("url") else [],
            "price": price,
            "cat": TM_SEGMENTS.get(seg, "Событие"),
            "province": province_of((venue.get("state") or {}).get("name", ""), city),
            "src": "ticketmaster",
        })
    return out


async def collect_ticketmaster() -> list[dict]:
    key = os.getenv("TICKETMASTER_KEY", "").strip()
    if not key:
        return []
    rows: list[dict] = []
    until = (date.today() + timedelta(days=HORIZON_DAYS)).strftime("%Y-%m-%dT00:00:00Z")
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30), trust_env=True) as s:
        for page in range(5):   # API отдаёт не больше 1000 событий: 5 страниц по 200
            raw = await _get(s, "https://app.ticketmaster.com/discovery/v2/events.json", params={
                "apikey": key, "countryCode": "NL", "size": "200", "page": str(page), "sort": "date,asc",
                "endDateTime": until, "locale": "*"})
            try:
                data = json.loads(raw) if raw else {}
            except ValueError:
                data = {}
            found = parse_ticketmaster(data)
            rows += found
            total_pages = ((data.get("page") or {}).get("totalPages")) or 0
            if not found or page + 1 >= total_pages:
                break
            await asyncio.sleep(0.5)
    return rows


# ---------------------------------------------------------------- сборка и хранение

def clean(rows: list[dict], today: date | None = None) -> list[dict]:
    """Без прошедших, дальних, бизнес-событий, без провинции и без дублей (одно название в один день)."""
    today = today or datetime.now(TZ).date()
    last = today + timedelta(days=HORIZON_DAYS)
    seen: set[str] = set()
    out = []
    for r in sorted(rows, key=lambda x: (x.get("date", ""), x.get("time", ""))):
        d = r.get("date", "")
        if not d or not r.get("province") or _SKIP.search(r.get("h", "")):
            continue
        try:
            start = date.fromisoformat(d)
            end = date.fromisoformat(r["end"]) if r.get("end") else start
        except ValueError:
            continue
        if end < today or start > last or (end - start).days > 60:   # «каждый день весь год» — не событие
            continue
        sig = re.sub(r"\W+", "", r["h"].casefold()) + d
        if sig in seen or r["key"] in seen:
            continue
        seen.update((sig, r["key"]))
        out.append(r)
    return out


_state: dict = {"at": 0.0, "events": []}


def load() -> list[dict]:
    if not _state["events"] and os.path.exists(PATH):
        try:
            with open(PATH, encoding="utf-8") as f:
                d = json.load(f)
            _state.update(at=d.get("at", 0.0), events=d.get("events") or [])
        except Exception as e:  # noqa: BLE001
            log.warning("auto_events: cannot read %s: %s", PATH, e)
    return clean(_state["events"])   # прошедшие отпадают сразу, не дожидаясь следующего сбора


async def refresh() -> int:
    eb, tm = await asyncio.gather(collect_eventbrite(), collect_ticketmaster())
    events = clean(tm + eb)   # Ticketmaster первым: при дублях остаётся карточка с ценой
    if not events and _state["events"]:
        log.warning("auto_events: sources returned nothing, keeping previous %d", len(_state["events"]))
        return len(_state["events"])
    _state.update(at=time.time(), events=events)
    try:
        os.makedirs(os.path.dirname(PATH), exist_ok=True)
        tmp = PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_state, f, ensure_ascii=False)
        os.replace(tmp, PATH)
    except Exception as e:  # noqa: BLE001
        log.warning("auto_events: cannot write %s: %s", PATH, e)
    log.info("auto_events: %d events (eventbrite %d, ticketmaster %d)", len(events), len(eb), len(tm))
    return len(events)


async def auto_events_loop() -> None:
    load()
    await asyncio.sleep(90)   # не нагружаем старт сервера
    while True:
        try:
            if time.time() - _state["at"] > EVERY_SEC - 600:
                await refresh()
        except Exception:  # noqa: BLE001
            log.exception("auto_events: refresh failed")
        await asyncio.sleep(1800)


async def events_json(request: web.Request) -> web.Response:
    body = {"events": load(), "updated": int(_state["at"])}
    return web.json_response(body, headers={"Access-Control-Allow-Origin": "*", "Cache-Control": "public, max-age=600"},
                             dumps=lambda o: json.dumps(o, ensure_ascii=False))


def install_routes(app: web.Application) -> None:
    app.router.add_get("/api/app/events.json", events_json)
