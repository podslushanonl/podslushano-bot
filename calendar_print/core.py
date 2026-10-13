"""Календарь Podslushano.nl «Nederland 2027»: данные, личная версия, печатный HTML и ICS.

Один источник данных (calendar_2027.json) используется и для печатного PDF,
и для подписки на календарь в телефоне, и для напоминаний в боте.
"""
from __future__ import annotations

import calendar as _cal
import datetime as dt
import hashlib
import html
import json
from pathlib import Path

from .icons import icon

HERE = Path(__file__).resolve().parent
ASSETS = HERE / "assets"
DATA = json.loads((HERE / "calendar_2027.json").read_text(encoding="utf-8"))
Y = DATA["year"]
MONTHS, MGEN, WD = DATA["months"], DATA["months_gen"], DATA["weekdays"]
REGIONS = DATA["regions"]  # {"N": "Noord", "M": "Midden", "Z": "Zuid"}
MAX_PERSONAL_DATES = 15
BOT_USERNAME = "podslushano_nl_bot"


# ---------------------------------------------------------------- data

def events(order: dict | None = None) -> dict[tuple[int, int], list[tuple[str, str]]]:
    """{(month, day): [(label, kind)]} — общие даты + личные даты заказа (kind="me")."""
    ev: dict[tuple[int, int], list[tuple[str, str]]] = {}
    for e in DATA["events"]:
        ev.setdefault((e["m"], e["d"]), []).append((e["label"], e["kind"]))
    for p in (order or {}).get("dates", []):
        ev.setdefault((int(p["m"]), int(p["d"])), []).insert(0, (p["label"], "me"))
    return ev


def vacations(region: str | None = None) -> list[tuple[dt.date, dt.date, str, str]]:
    out = []
    for v in DATA["vacations"]:
        regs = v["regions"]
        if region:
            if region not in regs:
                continue
            regs = region
        out.append((dt.date.fromisoformat(v["start"]), dt.date.fromisoformat(v["end"]), regs, v["name"]))
    return out


def clean_order(raw: dict) -> dict:
    """Нормализует данные заказа: регион, подпись, до 15 корректных личных дат."""
    region = (raw.get("region") or "").strip().upper()[:1]
    if region not in REGIONS:
        region = ""
    title = " ".join(str(raw.get("title") or "").split())[:48]
    dates = []
    for p in raw.get("dates") or []:
        try:
            m, d = int(p.get("m")), int(p.get("d"))
            dt.date(Y, m, d)
        except (TypeError, ValueError):
            continue
        label = " ".join(str(p.get("label") or "").split())[:28]
        if not label:
            continue
        kind = "bday" if p.get("kind") == "bday" else "date"
        dates.append({"m": m, "d": d, "label": label, "kind": kind})
        if len(dates) >= MAX_PERSONAL_DATES:
            break
    dates.sort(key=lambda x: (x["m"], x["d"]))
    return {"title": title, "region": region, "dates": dates, "code": str(raw.get("code") or "")}


# ---------------------------------------------------------------- ICS

def _esc(t: str) -> str:
    return t.replace("\\", "\\\\").replace(",", r"\,").replace(";", r"\;").replace("\n", r"\n")


DEADLINE_DETAILS = {
    (2, 1): "последний день выбрать новую zorgverzekering, если старую отменили до 31 декабря",
    (3, 1): "открывается aangifte за 2026 год. Подадите до 1 апреля — Belastingdienst ответит до 1 июля",
    (5, 1): "последний день подать aangifte за 2026 год или попросить uitstel",
    (12, 31): "последний день отменить zorgverzekering, чтобы сменить её с 1 января",
}

_PFX = {"hol": "🇳🇱 ", "dead": "⚠️ ", "bday": "🎂 ", "dst": "🕑 "}


def build_ics(order: dict | None = None, *, name: str = "Nederland 2027 · Podslushano.nl") -> str:
    order = clean_order(order or {})
    code = order.get("code", "")
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Podslushano.nl//Nederland 2027//RU",
             "CALSCALE:GREGORIAN", "METHOD:PUBLISH", f"X-WR-CALNAME:{_esc(name)}",
             "X-WR-TIMEZONE:Europe/Amsterdam", "REFRESH-INTERVAL;VALUE=DURATION:P1D", "X-PUBLISHED-TTL:P1D"]

    def add(start, end, title, desc="", alarms=(), rrule=None):
        uid = hashlib.md5(f"{start}{title}{code}".encode()).hexdigest() + "@podslushano.nl"
        lines.extend(["BEGIN:VEVENT", f"UID:{uid}", f"DTSTAMP:{now}", f"DTSTART;VALUE=DATE:{start:%Y%m%d}",
                      f"DTEND;VALUE=DATE:{end:%Y%m%d}", f"SUMMARY:{_esc(title)}", "TRANSP:TRANSPARENT"])
        if desc:
            lines.append(f"DESCRIPTION:{_esc(desc)}")
        if rrule:
            lines.append(f"RRULE:{rrule}")
        for a in alarms:
            lines.extend(["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{_esc(title)}", f"TRIGGER:{a}", "END:VALARM"])
        lines.append("END:VEVENT")

    base = events()
    for (m, d), evs in sorted(base.items()):
        prev = {l for l, _ in base.get((m, d - 1), [])}
        for label, kind in evs:
            if label in prev:      # многодневные подписи — одно событие в первый день
                continue
            day = dt.date(Y, m, d)
            alarms = ("-P7D", "-P1D") if kind == "dead" else ()
            desc = f"Дедлайн. Помощь с письмами — в боте @{BOT_USERNAME}" if kind == "dead" else ""
            add(day, day + dt.timedelta(1), _PFX.get(kind, "") + label, desc, alarms)
    for p in order["dates"]:
        day = dt.date(Y, p["m"], p["d"])
        bday = p["kind"] == "bday"
        add(day, day + dt.timedelta(1), ("🎂 " if bday else "⭐ ") + p["label"],
            "Личная дата из вашего календаря Podslushano.nl",
            ("-P7D", "-PT0M") if bday else ("-P1D",), "FREQ=YEARLY" if bday else None)
    for a, b, regs, nm in vacations(order["region"] or None):
        who = "все регионы" if len(regs) == 3 else " + ".join(REGIONS[r] for r in "NMZ" if r in regs)
        add(a, b + dt.timedelta(1), f"🏫 {nm} · {who}",
            "Рекомендованные даты Rijksoverheid — сверяйтесь со своей школой")
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


# ---------------------------------------------------------------- reminders

def reminders_for(order: dict, today: dt.date) -> list[tuple[str, str]]:
    """[(key, text)] — напоминания, которые нужно отправить сегодня владельцу календаря."""
    order = clean_order(order)
    out: list[tuple[str, str]] = []
    base = events()

    def when(n):
        return "сегодня" if n == 0 else ("завтра" if n == 1 else f"через {n} дней")

    for (m, d), evs in base.items():
        day = dt.date(Y, m, d)
        n = (day - today).days
        for label, kind in evs:
            if kind == "dead" and n in (7, 1):
                detail = DEADLINE_DETAILS.get((m, d), label)
                out.append((f"dead:{m}-{d}:{label}:{n}", f"⚠️ {when(n).capitalize()}, {d} {MGEN[m-1]}: {detail}"))
            elif kind == "hol" and n == 1:
                out.append((f"hol:{m}-{d}:{label}", f"🇳🇱 Завтра {label} — официальный выходной"))
            elif kind == "dst" and n == 1:
                out.append((f"dst:{m}-{d}", f"🕑 Завтра {label.lower()}: переводим часы"))
    for p in order["dates"]:
        try:
            day = dt.date(today.year, p["m"], p["d"])
        except ValueError:
            continue
        n = (day - today).days
        offsets = (7, 0) if p["kind"] == "bday" else (1, 0)
        if n in offsets:
            icon_ = "🎂" if p["kind"] == "bday" else "⭐"
            out.append((f"me:{today.year}:{p['m']}-{p['d']}:{p['label']}:{n}",
                        f"{icon_} {when(n).capitalize()}: {p['label']}"))
    return out


# ---------------------------------------------------------------- print HTML

def _qr(url: str) -> str:
    import segno
    return '<img class="qrimg" src="' + segno.make(url, error="m").png_data_uri(scale=20, border=0, dark="#1C1B19") + '">'


def _cell_icon(evs, prev):
    pl = {l for l, _ in prev}
    for l, x in evs:
        if not l or l in pl:
            continue
        for kw, ic in DATA["icon_map"]:
            if kw.lower() in l.lower():
                return icon(ic, "ci" + (" red" if x == "dead" else " mut" if x == "dst" else ""))
    return ""


_ORDER_KIND = {"me": -1, "hol": 0, "dead": 1, "bday": 2, "trad": 3, "dst": 4, "oth": 5}


def _month(m: int, ev, vac) -> str:
    info = DATA["info"][str(m)]
    weeks = _cal.Calendar(0).monthdatescalendar(Y, m)
    rows = ""
    for w in weeks:
        cells = ""
        for d in w:
            if d.month != m:
                cells += '<div class="c out"></div>'
                continue
            evs = ev.get((m, d.day), [])
            kinds = [k for _, k in evs]
            cls = "c" + (" we" if d.weekday() >= 5 else "") + (" hol" if "hol" in kinds else "") + (" me" if "me" in kinds else "")
            lab = "".join(f'<i class="{k}">{html.escape(l)}</i>'
                          for l, k in sorted(evs, key=lambda e: _ORDER_KIND[e[1]]) if l)
            cells += f'<div class="{cls}"><b>{d.day}</b>{_cell_icon(evs, ev.get((m, d.day - 1), []))}<div class="ls">{lab}</div></div>'
        segs = []
        for i, d in enumerate(w):
            regs, name = set(), ""
            if d.month == m:
                for va, vb, rg, nm in vac:
                    if va <= d <= vb:
                        regs.update(rg)
                        name = nm
            v = (frozenset(regs), name) if regs else None
            if v and segs and segs[-1][2] == v and segs[-1][1] == i - 1:
                segs[-1][1] = i
            elif v:
                segs.append([i, i, v])
        bars = ""
        for a, b, (regs, name) in segs:
            rk = "".join(sorted(regs))
            who = "все регионы" if len(regs) == 3 else " + ".join(REGIONS[r] for r in "NMZ" if r in regs)
            lab = f"{name} · {who}" if b > a else ("все" if len(regs) == 3 else who)
            bars += f'<div class="vb r{rk}" style="left:calc({a}/7*100% + 1mm);width:calc({b-a+1}/7*100% - 2mm)">{html.escape(lab)}</div>'
        rows += f'<div class="row">{cells}{bars}</div>'
    first, last = dt.date(Y, m, 1), dt.date(Y, m, _cal.monthrange(Y, m)[1])
    has_vac = any(not (vb < first or va > last) for va, vb, _, _ in vac)
    notes = "".join(f"<li>{html.escape(n)}</li>" for n in info["notes"])
    t1, t2 = info["tip"]
    return f'''
<section class="page">
  <aside>
    <div class="mh"><span class="mn">{m:02d}</span><h1>{MONTHS[m-1]}</h1><span class="yr">{Y}</span></div>
    <figure style="background-image:url({ASSETS.as_uri()}/photo_{m}.jpg);background-position:{info["pos"]}"><figcaption>{html.escape(info["place"])}</figcaption></figure>
    <div class="kv"><div class="k">{icon(info["season_icons"][0], "si")}Сезон</div><p>{html.escape(info["season"])}</p></div>
    <div class="kv"><div class="k">{icon("bike", "si")}Куда поехать</div><p>{html.escape(info["go"])}</p></div>
    {f'<ul class="notes">{notes}</ul>' if notes else ''}
    <div class="tip">{icon(info["tip_icon"], "ti")}<div><div class="k">Совет месяца</div><b>{html.escape(t1)}</b><p>{html.escape(t2)}</p></div></div>
  </aside>
  <main>
    <div class="wd">{"".join(f'<span{" class=we" if i > 4 else ""}>{w}</span>' for i, w in enumerate(WD))}</div>
    <div class="grid n{len(weeks)}">{rows}</div>
    <div class="gfoot">{'<span>Полоса — schoolvakanties, рекомендованные даты Rijksoverheid. Сверяйтесь со своей школой.</span>' if has_vac else '<span></span>'}<span class="brand">Podslushano.nl</span></div>
  </main>
</section>'''


def _cover(order: dict) -> str:
    c = DATA["cover"]
    pers = ""
    if order.get("region") or order.get("dates"):
        bits = []
        if order.get("region"):
            bits.append(f"регион каникул: {REGIONS[order['region']]}")
        if order.get("dates"):
            bits.append(f"личных дат: {len(order['dates'])}")
        txt = " · ".join(bits)
        pers = f'<div class="pers">{txt[:1].upper() + txt[1:]}</div>'
    kick = html.escape(order["title"]) if order.get("title") else "Календарь эмигранта"
    return f'''
<section class="page cover">
  <div class="cl">
    <div class="brand">Podslushano.nl</div>
    <div class="ct">
      <div class="kick">{kick}</div>
      <h1>Nederland<br><span>{Y}</span></h1>
      <p>Праздники, schoolvakanties, налоги и дедлайны, сезоны и места — всё, что важно, когда живёшь в Нидерландах.</p>
    </div>
    <div class="tags"><span>праздники</span><span>schoolvakanties</span><span>налоги</span><span>сезоны</span><span>куда поехать</span></div>
    {pers}
  </div>
  <figure class="cph" style="background-image:url({ASSETS.as_uri()}/photo_cover.jpg);background-position:{c["pos"]}"><figcaption>{html.escape(c["place"])}</figcaption></figure>
</section>'''


def _mini(m: int, ev) -> str:
    s = "".join(f"<i class='h'>{w[0]}</i>" for w in WD)
    for w in _cal.Calendar(0).monthdatescalendar(Y, m):
        for d in w:
            if d.month != m:
                s += "<i></i>"
                continue
            kk = {x for _, x in ev.get((m, d.day), [])}
            s += f"<i class='{'o' if 'hol' in kk else ('w' if d.weekday() >= 5 else '')}'>{d.day}</i>"
    return f"<div class='mini'><h4>{MONTHS[m-1]}</h4><div class='mg'>{s}</div></div>"


def _back(order: dict, ev) -> str:
    code = order.get("code", "")
    url = f"https://t.me/{BOT_USERNAME}?start=cal_{code}" if code else f"https://t.me/{BOT_USERNAME}"
    credits = " · ".join(f"{MONTHS[int(k)-1] if k != 'cover' else 'Обложка'}: {html.escape(v['artist'])}, {v['lic']}"
                         for k, v in DATA["credits"].items())
    pay = [("euro", "Toeslagen", "около 20-го числа каждого месяца"),
           ("baby", "Kinderbijslag", "раз в квартал: январь, апрель, июль, октябрь"),
           ("bin", "Gemeente", "afvalstoffenheffing, rioolheffing, OZB — обычно в феврале–марте, можно частями"),
           ("drop", "Waterschap", "zuiveringsheffing и ingezetenenheffing — платят и арендаторы"),
           ("car", "Motorrijtuigenbelasting", "по incasso около 27-го или раз в 3 месяца"),
           ("home", "Aangifte", "1 марта – 1 мая, за 2026 год")]
    payh = "".join(f'<div>{icon(i, "pi")}<p><b>{t}</b>{html.escape(x)}</p></div>' for i, t, x in pay)
    me_leg = '<div><span class="sw me">Aa</span>ваши личные даты</div>' if order.get("dates") else ""
    return f'''
<section class="page back">
  <div class="bh"><h2>{Y}</h2><span class="brand">Podslushano.nl</span></div>
  <div class="minis">{"".join(_mini(m, ev) for m in range(1, 13))}</div>
  <div class="brow">
    <div class="leg">
      <div class="k">Обозначения</div>
      <div><span class="sw hol">5</span>официальный праздник</div>
      <div><span class="sw dead">Aa</span>дедлайн: налоги и страховка</div>
      <div><span class="sw trad">Aa</span>событие, традиция, памятная дата</div>
      <div><span class="sw oth">Aa</span>другие даты: королевская семья, религиозные, международные</div>
      <div><span class="sw vb"></span>schoolvakanties с регионом</div>
      {me_leg}
    </div>
    <div class="pay"><div class="k">Платежи и налоги года</div><div class="pg">{payh}</div></div>
  </div>
  <div class="link">
    <div class="lq">{_qr(url)}</div>
    <div><div class="k">Календарь в телефоне</div>
      <b>Наведи камеру — и все даты окажутся в твоём iPhone или Google Calendar</b>
      <p>Бот Podslushano.nl напомнит о дедлайнах по налогам и страховке{", днях рождения близких" if order.get("dates") else ""} и пришлёт даты, которые объявят позже: Sinterklaas, Keukenhof и другие.</p>
      <p class="sm">{("Календарь № " + html.escape(code) + " · ") if code else ""}Telegram @{BOT_USERNAME} · Instagram @podslushano.nl</p>
    </div>
  </div>
  <p class="foot">Даты: Rijksoverheid, Belastingdienst, SVB, wincalendar.com и сайты организаторов, по состоянию на октябрь 2026 — сверяйтесь с официальными источниками. Фото: Wikimedia Commons. {credits}.</p>
</section>'''


def build_html(order: dict | None = None) -> str:
    order = clean_order(order or {})
    ev = events(order)
    vac = vacations(order["region"] or None)
    css = (HERE / "style.css").read_text(encoding="utf-8").replace("{ASSETS}", ASSETS.as_uri())
    body = _cover(order) + "".join(_month(m, ev, vac) for m in range(1, 13)) + _back(order, ev)
    return f'<!doctype html><html lang="ru"><head><meta charset="utf-8"><style>{css}</style></head><body>{body}</body></html>'


async def render_pdf(order: dict, out_path: str | Path) -> Path:
    """Печатный PDF 303×216 мм (A4 альбом + 3 мм под обрез). Нужен playwright + chromium."""
    from playwright.async_api import async_playwright
    out = Path(out_path)
    html_path = out.with_suffix(".html")
    html_path.write_text(build_html(order), encoding="utf-8")
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--no-sandbox"])
        try:
            page = await browser.new_page()
            await page.goto(html_path.as_uri())
            await page.wait_for_timeout(500)
            await page.pdf(path=str(out), width="303mm", height="216mm", print_background=True)
        finally:
            await browser.close()
    html_path.unlink(missing_ok=True)
    return out
