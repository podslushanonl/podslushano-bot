"""Календарь «Nederland 2027»: продажа личной версии на сайте + календарь в телефоне.

Поток:
  /calendar            — страница заказа: подпись на обложку, регион, до 15 личных дат, адрес
  POST /calendar/order — сохраняем заказ (status=new) и отправляем в Mollie
  Mollie webhook       — kind="calendar" → paid → админам приходит заказ + готовый PDF для печати
  /calendar/thanks     — спасибо + ссылка в бота
  t.me/<bot>?start=cal_<code> — QR на задней обложке: привязываем календарь к Telegram
  /cal/<token>         — кнопки «Добавить в Apple / Google Calendar»
  /cal/<token>.ics     — подписка (webcal): общие даты + регион + личные даты
  calendar_loop        — ежедневные напоминания владельцам + сверка неоплаченных заказов
"""
from __future__ import annotations

import asyncio
import datetime as dt
import html
import json
import logging
import re
import secrets
import tempfile
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo

from aiogram.types import BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup
from aiohttp import web
from sqlalchemy import BigInteger, DateTime, Integer, String, Text, UniqueConstraint, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column

import ad_season_campaign_runtime as season
import config
from calendar_print import core
from database.db import get_session
from database.models import Base

log = logging.getLogger(__name__)

TZ = ZoneInfo("Europe/Amsterdam")
REMINDER_HOUR = 9
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def calendar_price() -> str:
    raw = __import__("os").getenv("CALENDAR_PRICE", "30.00")
    try:
        return f"{Decimal(raw):.2f}"
    except InvalidOperation:
        return "30.00"


def calendar_sales_open() -> bool:
    """Приём заказов закрыт по умолчанию: форма заказа не утверждена и не должна быть публичной.
    Открыть: CALENDAR_SALES_OPEN=1 в Railway."""
    return __import__("os").getenv("CALENDAR_SALES_OPEN", "0").strip().lower() not in {"0", "false", "no", "off"}


# ---------------------------------------------------------------- models

class CalendarOrder(Base):
    __tablename__ = "calendar_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(12), unique=True, index=True)
    token: Mapped[str] = mapped_column(String(48), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(16), default="new")  # new | paid | failed | printed | shipped
    title: Mapped[str | None] = mapped_column(String(64), nullable=True)
    region: Mapped[str | None] = mapped_column(String(1), nullable=True)
    dates_json: Mapped[str] = mapped_column(Text, default="[]")
    buyer_name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    street: Mapped[str] = mapped_column(String(200))
    postcode: Mapped[str] = mapped_column(String(10))
    city: Mapped[str] = mapped_column(String(80))
    amount: Mapped[str] = mapped_column(String(12))
    payment_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    tg_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    paid_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def as_order(self) -> dict:
        return {"code": self.code, "title": self.title or "", "region": self.region or "",
                "dates": json.loads(self.dates_json or "[]")}


class CalendarReminderLog(Base):
    __tablename__ = "calendar_reminder_log"
    __table_args__ = (UniqueConstraint("order_id", "key", name="uq_calendar_reminder"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(Integer, index=True)
    key: Mapped[str] = mapped_column(String(200))
    sent_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ---------------------------------------------------------------- helpers

def _base() -> str:
    return (config.WEBHOOK_BASE_URL or "").rstrip("/")


def _bot_link(code: str) -> str:
    return f"{config.BOT_URL.rstrip('/')}?start=cal_{code}"


def _new_code() -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(6))


_POSTCODE = re.compile(r"^\s*([1-9][0-9]{3})\s?([A-Za-z]{2})\s*$")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def parse_form(data) -> tuple[dict | None, str | None]:
    """Проверяет форму заказа. Возвращает (поля, None) или (None, текст ошибки)."""
    get = lambda k: " ".join(str(data.get(k) or "").split())  # noqa: E731
    name, email, street, city = get("buyer_name"), get("email").lower(), get("street"), get("city")
    pc = _POSTCODE.match(get("postcode"))
    if not name or not street or not city:
        return None, "Заполните имя и адрес доставки."
    if not pc:
        return None, "Проверьте postcode — например, 1012 AB."
    if not _EMAIL.match(email):
        return None, "Проверьте e-mail."
    if str(data.get("consent") or "") not in {"1", "on", "yes", "true"}:
        return None, "Нужно согласие на обработку данных для печати и доставки."
    dates = []
    for i in range(core.MAX_PERSONAL_DATES):
        label = get(f"label_{i}")
        if not label:
            continue
        dates.append({"m": data.get(f"m_{i}"), "d": data.get(f"d_{i}"), "label": label,
                      "kind": "bday" if data.get(f"kind_{i}") == "bday" else "date"})
    order = core.clean_order({"title": get("title"), "region": get("region"), "dates": dates})
    if len(order["dates"]) != len(dates):
        return None, "Одна из личных дат указана неверно — проверьте день и месяц."
    return {
        "buyer_name": name[:120], "email": email[:200], "phone": get("phone")[:40] or None,
        "street": street[:200], "postcode": f"{pc.group(1)} {pc.group(2).upper()}", "city": city[:80],
        "order": order,
    }, None


# ---------------------------------------------------------------- pages

_CSS = """
:root{--ink:#1C1B19;--mut:#8E8981;--line:#E7E3DC;--or:#FC9740;--ord:#E9781C}
*{box-sizing:border-box}body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;color:var(--ink);background:#FAF8F5}
.wrap{max-width:720px;margin:0 auto;padding:28px 16px 64px}
.brand{font-weight:700}.brand:before{content:"";display:inline-block;width:.6em;height:.6em;border-radius:50%;background:var(--or);margin-right:.4em}
h1{font-size:34px;letter-spacing:-.03em;margin:22px 0 6px;line-height:1.05}h1 span{color:var(--or)}
.lead{color:#4A4741;line-height:1.5;margin:0 0 22px}
.card{background:#fff;border:1px solid var(--line);border-radius:16px;padding:20px;margin:14px 0}
.card h2{font-size:17px;margin:0 0 4px}.card .hint{color:var(--mut);font-size:14px;margin:0 0 14px;line-height:1.45}
label{display:block;font-size:14px;font-weight:600;margin:12px 0 6px}
input,select{width:100%;font:inherit;font-size:16px;padding:11px 12px;border:1px solid var(--line);border-radius:10px;background:#fff;color:var(--ink)}
.row{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.regions{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}
.regions label{margin:0;border:1px solid var(--line);border-radius:10px;padding:10px;text-align:center;font-weight:500;cursor:pointer}
.regions input{display:none}.regions input:checked+span{color:var(--ord);font-weight:700}
.regions label:has(input:checked){border-color:var(--or);background:#FFF4EA}
.dt{display:grid;grid-template-columns:64px 1fr 1.6fr 92px;gap:8px;margin-top:8px}
.dt[hidden]{display:none}
.dt select,.dt input{padding:10px 8px}
.add{margin-top:10px;background:none;border:1px dashed var(--line);border-radius:10px;padding:10px;width:100%;font:inherit;color:var(--ord);cursor:pointer}
.check{display:flex;gap:10px;align-items:flex-start;font-weight:400;font-size:14px;line-height:1.45}.check input{width:auto;margin-top:3px}
.pay{width:100%;margin-top:18px;background:var(--ink);color:#fff;border:0;border-radius:12px;padding:15px;font:inherit;font-size:17px;font-weight:600;cursor:pointer}
.err{background:#FDECEA;color:#B42318;border-radius:10px;padding:12px;margin:12px 0}
ul.f{padding-left:18px;line-height:1.6;color:#4A4741;margin:0}
.btn{display:block;text-align:center;text-decoration:none;background:var(--ink);color:#fff;border-radius:12px;padding:14px;font-weight:600;margin-top:10px}
.btn.alt{background:#fff;color:var(--ink);border:1px solid var(--line)}
@media(max-width:520px){.dt{grid-template-columns:56px 1fr;}.dt .lbl,.dt .knd{grid-column:span 2}.regions{grid-template-columns:repeat(2,1fr)}h1{font-size:28px}}
"""


def _page(title: str, body: str) -> web.Response:
    doc = (f'<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
           f'<title>{html.escape(title)}</title><style>{_CSS}</style></head><body><div class="wrap">'
           f'<div class="brand">Podslushano.nl</div>{body}</div></body></html>')
    return web.Response(text=doc, content_type="text/html", headers={"Cache-Control": "no-store"})


def _date_row(i: int, v: dict) -> str:
    months = "".join(f'<option value="{m}"{" selected" if str(v.get("m")) == str(m) else ""}>{core.MGEN[m-1]}</option>' for m in range(1, 13))
    days = "".join(f'<option{" selected" if str(v.get("d")) == str(d) else ""}>{d}</option>' for d in range(1, 32))
    kind = v.get("kind", "bday")
    return (f'<div class="dt" data-i="{i}"{"" if i == 0 or v else " hidden"}>'
            f'<select name="d_{i}" aria-label="День">{days}</select>'
            f'<select name="m_{i}" aria-label="Месяц">{months}</select>'
            f'<input class="lbl" name="label_{i}" maxlength="28" placeholder="Например: ДР мамы" value="{html.escape(v.get("label", ""))}">'
            f'<select class="knd" name="kind_{i}"><option value="bday"{" selected" if kind == "bday" else ""}>🎂 ДР</option>'
            f'<option value="date"{" selected" if kind == "date" else ""}>⭐ Дата</option></select></div>')


def order_page(error: str = "", form=None) -> web.Response:
    f = form or {}
    v = lambda k: html.escape(str(f.get(k) or ""))  # noqa: E731
    region = str(f.get("region") or "")
    prev_dates = []
    for i in range(core.MAX_PERSONAL_DATES):
        if f.get(f"label_{i}"):
            prev_dates.append({"m": f.get(f"m_{i}"), "d": f.get(f"d_{i}"), "label": f.get(f"label_{i}"), "kind": f.get(f"kind_{i}")})
    rows = "".join(_date_row(i, prev_dates[i] if i < len(prev_dates) else {}) for i in range(core.MAX_PERSONAL_DATES))
    regs = "".join(f'<label><input type="radio" name="region" value="{k}"{" checked" if region == k else ""}><span>{n}</span></label>'
                   for k, n in [("N", "Noord"), ("M", "Midden"), ("Z", "Zuid"), ("", "Не нужно")])
    closed = "" if calendar_sales_open() else '<div class="err">Приём заказов временно закрыт.</div>'
    body = f'''
<h1>Календарь <span>Nederland 2027</span></h1>
<p class="lead">Настенный календарь A4 для тех, кто живёт в Нидерландах: праздники, schoolvakanties, налоги и дедлайны, сезоны и места.
Мы напечатаем его <b>лично для вас</b> — с вашей подписью на обложке и днями рождения близких в сетке. А по QR-коду все даты появятся в телефоне.</p>
{closed}{f'<div class="err">{html.escape(error)}</div>' if error else ''}
<form method="post" action="/calendar/order" id="f">
<div class="card"><h2>1. Обложка</h2><p class="hint">Подпись над «Nederland 2027». Можно оставить пустой.</p>
<input name="title" maxlength="48" placeholder="Календарь семьи Ивановых" value="{v('title')}"></div>
<div class="card"><h2>2. Ваш регион школьных каникул</h2><p class="hint">В календаре останутся только каникулы вашего региона.</p>
<div class="regions">{regs}</div></div>
<div class="card"><h2>3. Ваши даты</h2><p class="hint">До {core.MAX_PERSONAL_DATES} дат: дни рождения, годовщины, важные события. Они будут в сетке календаря, а бот напомнит о них.</p>
{rows}<button type="button" class="add" id="add">+ Добавить дату</button></div>
<div class="card"><h2>4. Доставка</h2><p class="hint">Доставка по Нидерландам включена в цену.</p>
<label>Имя и фамилия</label><input name="buyer_name" required maxlength="120" value="{v('buyer_name')}" autocomplete="name">
<label>Улица и номер дома</label><input name="street" required maxlength="200" value="{v('street')}" autocomplete="street-address">
<div class="row"><div><label>Postcode</label><input name="postcode" required maxlength="8" placeholder="1012 AB" value="{v('postcode')}" autocomplete="postal-code"></div>
<div><label>Город</label><input name="city" required maxlength="80" value="{v('city')}" autocomplete="address-level2"></div></div>
<label>E-mail</label><input name="email" type="email" required maxlength="200" value="{v('email')}" autocomplete="email">
<label>Телефон (по желанию)</label><input name="phone" maxlength="40" value="{v('phone')}" autocomplete="tel">
<label class="check"><input type="checkbox" name="consent" value="1" required>Согласен(на), что Podslushano.nl использует эти данные для печати, доставки и напоминаний в боте. <a href="/privacy">Privacy</a></label>
</div>
<button class="pay" type="submit"{" disabled" if not calendar_sales_open() else ""}>Оплатить €{calendar_price().replace(".", ",")}</button>
</form>
<script>
document.getElementById('add').onclick=function(){{var h=document.querySelector('.dt[hidden]');if(h){{h.hidden=false;h.querySelector('.lbl').focus();}}if(!document.querySelector('.dt[hidden]'))this.hidden=true;}};
</script>'''
    return _page("Календарь Nederland 2027 — Podslushano.nl", body)


async def calendar_page(request: web.Request) -> web.Response:
    if not calendar_sales_open():
        raise web.HTTPNotFound()
    return order_page()


async def create_order(request: web.Request) -> web.Response:
    if not calendar_sales_open():
        raise web.HTTPNotFound()
    data = await request.post()
    if not config.payments_enabled():
        return order_page("Оплата временно недоступна. Попробуйте чуть позже.", data)
    fields, err = parse_form(data)
    if err:
        return order_page(err, data)
    order = fields.pop("order")
    amount = calendar_price()
    async with get_session() as session:
        for _ in range(5):
            row = CalendarOrder(code=_new_code(), token=secrets.token_urlsafe(24), title=order["title"] or None,
                                region=order["region"] or None, dates_json=json.dumps(order["dates"], ensure_ascii=False),
                                amount=amount, **fields)
            session.add(row)
            try:
                await session.commit()
                break
            except IntegrityError:
                await session.rollback()
        else:
            return order_page("Не удалось создать заказ. Попробуйте ещё раз.", data)
        from utils.payments import create_payment
        pay = await create_payment(
            f"Календарь Nederland 2027 · {row.code}", {"kind": "calendar", "code": row.code}, amount,
            redirect_url=f"{_base()}/calendar/thanks?c={row.code}")
        if not pay or not pay.get("checkout_url"):
            return order_page("Не получилось открыть оплату. Попробуйте ещё раз через минуту.", data)
        row.payment_id = pay["id"]
        await session.commit()
    raise web.HTTPSeeOther(pay["checkout_url"])


async def thanks_page(request: web.Request) -> web.Response:
    code = (request.query.get("c") or "").upper()[:12]
    async with get_session() as session:
        row = await session.scalar(select(CalendarOrder).where(CalendarOrder.code == code))
    if row is None:
        raise web.HTTPNotFound()
    if row.status in ("new",) and row.payment_id:
        await _sync_payment(request.app["bot"], row.payment_id)
        async with get_session() as session:
            row = await session.scalar(select(CalendarOrder).where(CalendarOrder.code == code))
    if row.status == "failed":
        body = '<h1>Оплата не прошла</h1><p class="lead">Заказ не оплачен. Можно попробовать ещё раз.</p><a class="btn" href="/calendar">Вернуться к заказу</a>'
        return _page("Оплата не прошла", body)
    paid = row.status in ("paid", "printed", "shipped")
    body = f'''
<h1>{"Спасибо! Календарь <span>№ " + row.code + "</span> заказан" if paid else "Ждём подтверждение оплаты…"}</h1>
<p class="lead">{"Мы напечатаем ваш календарь и напишем на " + html.escape(row.email) + ", когда он будет в пути." if paid else "Обычно это занимает несколько секунд. Обновите страницу."}</p>
<div class="card"><h2>Не ждите посылку — подключите календарь к телефону уже сейчас</h2>
<p class="hint">Бот Podslushano.nl добавит все даты в iPhone или Google Calendar и будет напоминать о дедлайнах{" и днях рождения" if json.loads(row.dates_json or "[]") else ""}.</p>
<a class="btn" href="{_bot_link(row.code)}">Открыть бота</a></div>'''
    return _page("Календарь Nederland 2027", body)


async def connect_page(request: web.Request) -> web.Response:
    token = request.match_info["token"]
    async with get_session() as session:
        row = await session.scalar(select(CalendarOrder).where(CalendarOrder.token == token))
    if row is None or row.status not in ("paid", "printed", "shipped"):
        raise web.HTTPNotFound()
    host = _base().split("://", 1)[-1]
    webcal = f"webcal://{host}/cal/{token}.ics"
    google = "https://calendar.google.com/calendar/r?cid=" + webcal
    body = f'''
<h1>Календарь <span>№ {row.code}</span> в телефон</h1>
<p class="lead">Это подписка: если мы добавим новые даты — например, когда объявят Sinterklaas или Keukenhof, — они появятся у вас сами.</p>
<a class="btn" href="{webcal}">Добавить в iPhone / Apple Calendar</a>
<a class="btn alt" href="{html.escape(google)}">Добавить в Google Calendar</a>
<p class="hint" style="margin-top:16px;color:#8E8981;font-size:14px">Google Calendar: откройте ссылку в браузере на компьютере или телефоне и нажмите «Добавить».</p>'''
    return _page("Календарь в телефон", body)


async def ics_feed(request: web.Request) -> web.Response:
    token = request.match_info["token"]
    async with get_session() as session:
        row = await session.scalar(select(CalendarOrder).where(CalendarOrder.token == token))
    if row is None or row.status not in ("paid", "printed", "shipped"):
        raise web.HTTPNotFound()
    name = "Nederland 2027 · " + (row.title or "Podslushano.nl")
    return web.Response(body=core.build_ics(row.as_order(), name=name).encode(), content_type="text/calendar",
                        charset="utf-8", headers={"Cache-Control": "public, max-age=3600"})


async def public_info(request: web.Request) -> web.Response:
    """Цена и открыт ли приём заказов — сайт показывает те же значения, что и форма оплаты."""
    return web.json_response({"price": calendar_price(), "open": calendar_sales_open()},
                             headers={"Access-Control-Allow-Origin": "*", "Cache-Control": "public, max-age=300"})


def install_routes(app: web.Application) -> None:
    app.router.add_get("/calendar", calendar_page)
    app.router.add_get("/calendar/info.json", public_info)
    app.router.add_post("/calendar/order", create_order)
    app.router.add_get("/calendar/thanks", thanks_page)
    app.router.add_get(r"/cal/{token:[A-Za-z0-9_\-]{16,64}}.ics", ics_feed)
    app.router.add_get(r"/cal/{token:[A-Za-z0-9_\-]{16,64}}", connect_page)


_original_install = season._install_routes


def _install_with_calendar(app: web.Application) -> None:
    _original_install(app)
    install_routes(app)


season._install_routes = _install_with_calendar


# ---------------------------------------------------------------- payment

async def _sync_payment(bot, payment_id: str) -> None:
    from utils.payments import get_payment
    payment = await get_payment(payment_id)
    if payment:
        await on_payment(bot, payment_id, payment)


async def on_payment(bot, payment_id: str, payment: dict) -> None:
    status = payment.get("status")
    code = (payment.get("metadata") or {}).get("code")
    async with get_session() as session:
        row = await session.scalar(select(CalendarOrder).where(CalendarOrder.payment_id == payment_id))
        if row is None or (code and row.code != code):
            log.warning("Calendar payment %s: order not found", payment_id)
            return
        if status == "paid" and row.status == "new":
            row.status = "paid"
            row.paid_at = dt.datetime.now(dt.timezone.utc)
            await session.commit()
            asyncio.create_task(_notify_admins(bot, row.id))
        elif status in ("failed", "canceled", "expired") and row.status == "new":
            row.status = "failed"
            await session.commit()


def _admin_text(row: CalendarOrder) -> str:
    dates = json.loads(row.dates_json or "[]")
    lines = [f"🗓 <b>Новый заказ календаря № {row.code}</b> · €{row.amount}",
             f"Обложка: {html.escape(row.title or '— (стандартная)')}",
             f"Регион: {core.REGIONS.get(row.region or '', 'все')}",
             f"Личных дат: {len(dates)}"]
    lines += [f"  • {d['d']} {core.MGEN[d['m']-1]} — {html.escape(d['label'])}" for d in dates]
    lines += ["", "<b>Доставка</b>", html.escape(row.buyer_name), html.escape(row.street),
              f"{html.escape(row.postcode)} {html.escape(row.city)}", html.escape(row.email)]
    if row.phone:
        lines.append(html.escape(row.phone))
    return "\n".join(lines)


async def _notify_admins(bot, order_id: int) -> None:
    async with get_session() as session:
        row = await session.get(CalendarOrder, order_id)
    if row is None:
        return
    text = _admin_text(row)
    pdf_bytes = None
    try:
        with tempfile.TemporaryDirectory() as tmp:
            out = await core.render_pdf(row.as_order(), Path(tmp) / f"calendar-{row.code}.pdf")
            pdf_bytes = out.read_bytes()
    except Exception as e:  # noqa: BLE001 — заказ важнее PDF: админ всё равно получит данные
        log.exception("Calendar PDF render failed for %s: %s", row.code, e)
        text += "\n\n⚠️ PDF не сгенерировался — данные заказа выше."
    for admin_id in config.ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, parse_mode="HTML")
            if pdf_bytes:
                await bot.send_document(admin_id, BufferedInputFile(pdf_bytes, f"Nederland-2027-{row.code}.pdf"),
                                        caption=f"PDF для печати · № {row.code} · 303×216 мм, вылеты 3 мм")
        except Exception as e:  # noqa: BLE001
            log.warning("Calendar admin notify %s failed: %s", admin_id, e)


# ---------------------------------------------------------------- bot deep link

async def handle_start(message, code: str) -> None:
    code = (code or "").upper()[:12]
    async with get_session() as session:
        row = await session.scalar(select(CalendarOrder).where(CalendarOrder.code == code))
        if row is None or row.status not in ("paid", "printed", "shipped"):
            await message.answer("Не нашёл такой календарь 🤔 Проверьте QR-код или напишите нам сюда — разберёмся.")
            return
        uid = message.from_user.id
        if row.tg_user_id and row.tg_user_id != uid:
            # Календарь могут повесить дома несколько человек: подписка работает у всех,
            # а напоминания остаются у первого, кто его подключил.
            owner = False
        else:
            row.tg_user_id = uid
            owner = True
            await session.commit()
        token, title, n_dates = row.token, row.title, len(json.loads(row.dates_json or "[]"))
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Добавить в телефон", url=f"{_base()}/cal/{token}")],
    ])
    hello = f"«{html.escape(title)}»" if title else f"№ {code}"
    text = (f"🗓 Календарь {hello} подключён!\n\n"
            "Нажмите кнопку ниже — все даты 2027 года окажутся в календаре вашего телефона: "
            "праздники, schoolvakanties, налоги и дедлайны"
            + (f", а также {n_dates} ваших личных дат" if n_dates else "") + ".\n\n")
    text += ("🔔 А я буду напоминать о важном: за неделю до дедлайнов по налогам и страховке"
             + (", о днях рождения близких" if n_dates else "") + " и накануне праздников."
             if owner else "🔔 Напоминания приходят тому, кто подключил календарь первым.")
    await message.answer(text, reply_markup=kb, parse_mode="HTML")


# ---------------------------------------------------------------- loop

async def _send_reminders(bot, today: dt.date) -> int:
    sent = 0
    async with get_session() as session:
        rows = (await session.scalars(select(CalendarOrder).where(
            CalendarOrder.tg_user_id.is_not(None), CalendarOrder.status.in_(("paid", "printed", "shipped"))))).all()
    for row in rows:
        for key, text in core.reminders_for(row.as_order(), today):
            async with get_session() as session:
                session.add(CalendarReminderLog(order_id=row.id, key=key))
                try:
                    await session.commit()
                except IntegrityError:
                    continue
            try:
                await bot.send_message(row.tg_user_id, text)
                sent += 1
            except Exception as e:  # noqa: BLE001 — пользователь мог заблокировать бота
                log.info("Calendar reminder to %s failed: %s", row.tg_user_id, e)
    return sent


async def calendar_loop(bot) -> None:
    await asyncio.sleep(60)
    while True:
        try:
            now = dt.datetime.now(TZ)
            if now.hour >= REMINDER_HOUR:
                await _send_reminders(bot, now.date())
            utcnow = dt.datetime.now(dt.timezone.utc)
            async with get_session() as session:
                pending = (await session.execute(select(CalendarOrder.payment_id, CalendarOrder.created_at).where(
                    CalendarOrder.status == "new", CalendarOrder.payment_id.is_not(None)))).all()
            for pid, created in pending:
                if created is None:
                    continue
                if created.tzinfo is None:
                    created = created.replace(tzinfo=dt.timezone.utc)
                if dt.timedelta(minutes=3) < utcnow - created < dt.timedelta(days=2):
                    await _sync_payment(bot, pid)
        except Exception as e:  # noqa: BLE001
            log.warning("calendar_loop: %s", e)
        await asyncio.sleep(30 * 60)
