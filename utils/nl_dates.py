"""Важные даты Нидерландов для приложения: GET /api/app/dates.json

Всё считается само, без ручного ведения:
- государственные праздники и памятные дни — по календарю (Пасха по алгоритму Гаусса/Мееуса);
- переход на зимнее и летнее время — последнее воскресенье октября и марта;
- школьные каникулы по регионам noord / midden / zuid — из открытых данных правительства
  (opendata.rijksoverheid.nl), на текущий и следующий учебный год, кеш на сутки;
- сроки, которые касаются каждого: налоговая декларация, смена медстраховки.

Каждая дата с коротким пояснением по-русски: что это значит для человека.
"""
from __future__ import annotations

import logging
import time
from datetime import date, timedelta

import aiohttp
from aiohttp import web

log = logging.getLogger(__name__)
HOLIDAYS_API = "https://opendata.rijksoverheid.nl/v1/infotypes/schoolholidays/schoolyear/{y}-{n}?output=json"
VACATION_RU = {
    "herfstvakantie": "Осенние каникулы", "kerstvakantie": "Рождественские каникулы",
    "voorjaarsvakantie": "Весенние каникулы", "meivakantie": "Майские каникулы", "zomervakantie": "Летние каникулы",
}
_cache: dict[str, tuple[float, list]] = {}


def easter(year: int) -> date:
    """Григорианская Пасха (алгоритм Мееуса/Джонса/Бучера)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _last_sunday(year: int, month: int) -> date:
    d = date(year, month + 1, 1) - timedelta(days=1) if month < 12 else date(year, 12, 31)
    return d - timedelta(days=(d.weekday() + 1) % 7)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    d = date(year, month, 1)
    d += timedelta(days=(weekday - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def _item(d: date, title: str, text: str, kind: str, end: date | None = None, nl: str = "") -> dict:
    return {"date": d.isoformat(), "end": (end or d).isoformat(), "title": title, "nl": nl, "text": text, "kind": kind}


def year_dates(year: int) -> list[dict]:
    """Праздники, памятные дни, перевод часов и сроки одного календарного года."""
    e = easter(year)
    kd = date(year, 4, 27)
    if kd.weekday() == 6:      # Koningsdag в воскресенье переносится на субботу
        kd -= timedelta(days=1)
    off = "Выходной: большинство магазинов работают по воскресному графику, госучреждения закрыты."
    out = [
        _item(date(year, 1, 1), "Новый год", off, "holiday", nl="Nieuwjaarsdag"),
        _item(e - timedelta(days=2), "Страстная пятница", "Официально не выходной: многие работают, магазины открыты.", "day", nl="Goede Vrijdag"),
        _item(e, "Пасха", off, "holiday", e + timedelta(days=1), nl="Pasen"),
        _item(kd, "День короля", "Выходной. По всей стране блошиные рынки (vrijmarkt), праздники на улицах, всё в оранжевом. "
              "Поезда и центры городов переполнены.", "holiday", nl="Koningsdag"),
        _item(date(year, 5, 4), "День памяти", "В 20:00 две минуты тишины по всей стране: останавливается транспорт, "
              "принято молчать даже на улице.", "day", nl="Dodenherdenking"),
        _item(date(year, 5, 5), "День освобождения", "Фестивали освобождения по всей стране. Выходной не для всех: "
              "зависит от договора с работодателем (cao).", "holiday", nl="Bevrijdingsdag"),
        _item(e + timedelta(days=39), "Вознесение", off, "holiday", nl="Hemelvaartsdag"),
        _item(e + timedelta(days=49), "Троица", off, "holiday", e + timedelta(days=50), nl="Pinksteren"),
        _item(_nth_weekday(year, 5, 6, 2), "День матери", "", "day", nl="Moederdag"),
        _item(_nth_weekday(year, 6, 6, 3), "День отца", "", "day", nl="Vaderdag"),
        _item(_nth_weekday(year, 9, 1, 3), "День бюджета", "Король читает тронную речь, правительство объявляет бюджет: "
              "в этот день становится известно, что изменится с 1 января — налоги, пособия, минимальная зарплата.",
              "day", nl="Prinsjesdag"),
        _item(date(year, 12, 5), "Синтерклаас", "Вечер подарков: дети получают подарки, взрослые дарят их со стихами (surprise).",
              "day", nl="Sinterklaasavond"),
        _item(date(year, 12, 25), "Рождество", off, "holiday", date(year, 12, 26), nl="Kerstmis"),
        _item(_last_sunday(year, 3), "Переход на летнее время", "В ночь на воскресенье в 2:00 часы переводят на час вперёд.", "clock"),
        _item(_last_sunday(year, 10), "Переход на зимнее время", "В ночь на воскресенье в 3:00 часы переводят на час назад.", "clock"),
        _item(date(year, 5, 1), "Срок налоговой декларации", "До 1 мая подайте декларацию за прошлый год (aangifte inkomstenbelasting) "
              "через Mijn Belastingdienst, если получили письмо или ждёте возврат. Отсрочку можно попросить онлайн.", "deadline"),
        _item(date(year, 11, 12), "Новые цены на медстраховку", "Страховые объявляют взносы на следующий год. "
              "До 31 декабря можно сменить страховку или пакет.", "deadline", nl="Zorgverzekering"),
        _item(date(year, 12, 31), "Последний день смены медстраховки", "Сегодня — последний день, чтобы сменить базовую страховку "
              "на следующий год (новую можно оформить до 1 февраля, если старую расторгли).", "deadline", nl="Zorgverzekering"),
    ]
    return out


def parse_holidays(data, school_year: str) -> list[dict]:
    """Ответ opendata.rijksoverheid.nl → каникулы по регионам."""
    out = []
    items = data if isinstance(data, list) else [data]
    for block in items:
        for content in (block or {}).get("content") or []:
            for v in content.get("vacations") or []:
                name = (v.get("type") or "").strip()
                for r in v.get("regions") or []:
                    region = (r.get("region") or "").strip().lower()
                    start, end = (r.get("startdate") or "")[:10], (r.get("enddate") or "")[:10]
                    if not (start and end):
                        continue
                    out.append({"date": start, "end": end, "title": VACATION_RU.get(name.lower(), name), "nl": name,
                                "text": f"Школьный год {school_year}.", "kind": "school",
                                "region": "all" if "heel" in region else region})
    return out


async def school_holidays(today: date) -> list[dict]:
    first = today.year if today.month >= 8 else today.year - 1
    # С августа начинается новый учебный год, но летние каникулы прошлого идут до конца августа — сентября:
    # берём и прошлый год, лишнее уберёт upcoming() по дате окончания.
    years = (first - 1, first, first + 1) if today.month in (8, 9) else (first, first + 1)
    out = []
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15), trust_env=True) as s:
        for y in years:
            key = f"{y}-{y + 1}"
            hit = _cache.get(key)
            if hit and time.time() - hit[0] < 86400:
                out += hit[1]
                continue
            try:
                async with s.get(HOLIDAYS_API.format(y=y, n=y + 1)) as r:
                    data = await r.json(content_type=None) if r.status == 200 else None
            except Exception as e:  # noqa: BLE001
                log.info("nl_dates: holidays %s unavailable: %s", key, e)
                data = None
            rows = parse_holidays(data, key) if data else (hit[1] if hit else [])
            if data:
                _cache[key] = (time.time(), rows)
            out += rows
    return out


def upcoming(rows: list[dict], today: date, days: int = 400) -> list[dict]:
    last = (today + timedelta(days=days)).isoformat()
    t = today.isoformat()
    return sorted((r for r in rows if r["end"] >= t and r["date"] <= last), key=lambda r: (r["date"], r["kind"]))


async def dates_json(request: web.Request) -> web.Response:
    today = date.today()
    rows = year_dates(today.year) + year_dates(today.year + 1) + await school_holidays(today)
    return web.json_response({"dates": upcoming(rows, today)},
                             headers={"Access-Control-Allow-Origin": "*", "Cache-Control": "public, max-age=3600"})


def install_routes(app: web.Application) -> None:
    app.router.add_get("/api/app/dates.json", dates_json)
