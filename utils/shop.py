"""Магазин мерча podslushano.nl в приложении: шопперы, которые печатаются под заказ.

Каталог — файл data/shop/catalog.json (правится в репозитории, без кода):
    {
      "currency": "EUR",
      "shipping": {"NL": "4.95", "DE": "7.95", "BE": "7.95"},    # доставка за заказ
      "products": [
        {"id": "shopper-molen", "title": "Шоппер «Мельница»", "price": "24.95",
         "text": "Плотный хлопок 340 г/м², ручки 65 см, размер 38×42 см.",
         "colors": ["Натуральный", "Чёрный"], "images": ["https://.../front.jpg", "https://.../back.jpg"],
         "available": true}
      ]
    }
Пока в каталоге нет доступных товаров или цен доставки, магазин в приложении показывает «Скоро».
Приём заказов включается переменной SHOP_OPEN=1 на сервере (по умолчанию выключен, как у календаря).

API:
    GET  /api/shop/catalog            — каталог, доставка, открыт ли магазин
    POST /api/shop/order              — заказ → платёж Mollie → {token, code, checkout_url}
    GET  /api/shop/order/{token}      — статус заказа (для экрана «Мой заказ»)
    GET  /shop/return?token=…         — сюда Mollie возвращает после оплаты: страница со статусом и ссылкой в приложение
Оплата: webhook Mollie с metadata.kind = "shop" → on_payment (вызывается из handlers/selfadd.on_payment_paid).
"""
from __future__ import annotations

import asyncio
import html
import json
import logging
import os
import re
import secrets
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from aiohttp import web
from sqlalchemy import select

import config
from database.db import get_session
from database.models import ShopOrder
from utils import payments
from utils.site_api import EMAIL_RE, _body, _err, _json

log = logging.getLogger(__name__)

CATALOG = Path(__file__).resolve().parent.parent / "data" / "shop" / "catalog.json"
COUNTRIES = {"NL": "Нидерланды", "DE": "Германия", "BE": "Бельгия"}
POSTCODE = {"NL": r"\d{4}\s?[A-Za-z]{2}", "DE": r"\d{5}", "BE": r"\d{4}"}
MAX_QTY = 10
_CODE = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
STATUS_RU = {"new": "Ждёт оплаты", "paid": "Оплачен", "printing": "В печати", "shipped": "Отправлен",
             "failed": "Оплата не прошла", "canceled": "Отменён"}


def _money(v) -> Decimal | None:
    try:
        d = Decimal(str(v))
        return d if d >= 0 else None
    except (InvalidOperation, TypeError):
        return None


def load_catalog() -> dict:
    try:
        raw = json.loads(CATALOG.read_text())
    except (OSError, ValueError):
        raw = {}
    shipping = {c: str(raw.get("shipping", {}).get(c) or "") for c in COUNTRIES}
    products = []
    for p in raw.get("products", []):
        if not (p.get("id") and p.get("title") and _money(p.get("price"))):
            continue
        # фото из папки data/shop/img (путь «img/…») сервер раздаёт сам; без файла фото не показываем
        imgs = []
        for src in p.get("images") or []:
            if src.startswith("https://"):
                imgs.append(src)
            elif src.startswith("img/") and (CATALOG.parent / src).is_file():
                imgs.append(f"{config.WEBHOOK_BASE_URL or ''}/shop-img/{src[4:]}")
        products.append({**p, "images": imgs})
    return {"currency": raw.get("currency", "EUR"), "shipping": shipping, "products": products}


def shop_open(cat: dict | None = None) -> bool:
    cat = cat or load_catalog()
    flag = os.getenv("SHOP_OPEN", "0").strip().lower() not in {"0", "false", "no", "off", ""}
    has_goods = any(p.get("available") for p in cat["products"])
    has_shipping = all(_money(v) is not None and v != "" for v in cat["shipping"].values())
    return flag and has_goods and has_shipping


def _new_code() -> str:
    return "PN-" + "".join(secrets.choice(_CODE) for _ in range(5))


def validate(data: dict, cat: dict) -> tuple[dict | None, str | None]:
    """Проверяет заказ. Возвращает (данные заказа, None) или (None, понятная ошибка)."""
    by_id = {p["id"]: p for p in cat["products"] if p.get("available")}
    items, subtotal = [], Decimal("0")
    for it in (data.get("items") or [])[:20]:
        p = by_id.get(str(it.get("id") or ""))
        if not p:
            return None, "Одного из товаров уже нет в продаже. Обновите корзину."
        try:
            qty = int(it.get("qty") or 0)
        except (TypeError, ValueError):
            qty = 0
        if not 1 <= qty <= MAX_QTY:
            return None, f"Количество одного товара — от 1 до {MAX_QTY}."
        color = str(it.get("color") or "")
        if p.get("colors") and color not in p["colors"]:
            return None, "Выберите цвет товара."
        price = _money(p["price"])
        subtotal += price * qty
        items.append({"id": p["id"], "title": p["title"], "color": color, "qty": qty, "price": f"{price:.2f}"})
    if not items:
        return None, "Корзина пуста."
    country = str(data.get("country") or "").upper()
    if country not in COUNTRIES:
        return None, "Доставляем только в Нидерланды, Германию и Бельгию."
    name = " ".join(str(data.get("name") or "").split())[:120]
    email = str(data.get("email") or "").strip().lower()[:200]
    street = " ".join(str(data.get("street") or "").split())[:160]
    house = str(data.get("house") or "").strip()[:20]
    postcode = str(data.get("postcode") or "").strip().upper()[:10]
    city = " ".join(str(data.get("city") or "").split())[:80]
    if len(name) < 2:
        return None, "Укажите имя и фамилию получателя."
    if not EMAIL_RE.match(email):
        return None, "Проверьте почту: на неё придёт подтверждение заказа."
    if not street or not house or not city:
        return None, "Заполните адрес: улица, дом и город."
    if not re.fullmatch(POSTCODE[country], postcode):
        return None, {"NL": "Индекс в Нидерландах — 4 цифры и 2 буквы, например 1011 AB.",
                      "DE": "Индекс в Германии — 5 цифр.", "BE": "Индекс в Бельгии — 4 цифры."}[country]
    phone = ""
    if data.get("phone"):
        from utils import phone as phones
        phone = phones.normalize(str(data["phone"])) or ""
        if not phone or not phone.startswith(("+31", "+49", "+32")):
            return None, "Телефон — только номер Нидерландов, Германии или Бельгии."
    shipping = _money(cat["shipping"][country]) or Decimal("0")
    return {
        "items": items, "subtotal": f"{subtotal:.2f}", "shipping": f"{shipping:.2f}", "total": f"{subtotal + shipping:.2f}",
        "name": name, "email": email, "phone": phone, "country": country, "street": street, "house": house,
        "postcode": re.sub(r"^(\d{4})\s?([A-Z]{2})$", r"\1 \2", postcode), "city": city,
    }, None


def order_json(o: ShopOrder) -> dict:
    return {
        "code": o.code, "token": o.token, "status": o.status, "status_ru": STATUS_RU.get(o.status, o.status),
        "items": json.loads(o.items or "[]"), "subtotal": o.subtotal, "shipping": o.shipping, "total": o.total,
        "name": o.name, "address": f"{o.street} {o.house}, {o.postcode} {o.city}, {COUNTRIES.get(o.country, o.country)}",
        "tracking": o.tracking, "created_at": o.created_at.isoformat() if o.created_at else "",
    }


# ---------------------------------------------------------------- HTTP

async def catalog(request: web.Request) -> web.Response:
    cat = load_catalog()
    return _json(request, {"ok": True, "open": shop_open(cat), "currency": cat["currency"], "shipping": cat["shipping"],
                           "countries": COUNTRIES, "products": cat["products"]})


async def create_order(request: web.Request) -> web.Response:
    cat = load_catalog()
    if not shop_open(cat):
        return _err(request, "Магазин пока не принимает заказы.", 403)
    data = await _body(request)
    order, error = validate(data, cat)
    if error:
        return _err(request, error)
    uid = None
    try:
        from utils.app_api import _user
        async with get_session() as session:
            u = await _user(request, session)
            uid = u.id if u else None
    except Exception:  # noqa: BLE001 — заказ можно сделать и без входа
        uid = None
    async with get_session() as session:
        row = ShopOrder(token=secrets.token_urlsafe(24), code=_new_code(), app_user_id=uid,
                        items=json.dumps(order.pop("items"), ensure_ascii=False), **order)
        session.add(row)
        await session.commit()
        await session.refresh(row)
    base = config.WEBHOOK_BASE_URL or ""
    pay = await payments.create_payment(
        f"podslushano.nl {row.code}", {"kind": "shop", "token": row.token, "code": row.code}, row.total,
        redirect_url=f"{base}/shop/return?token={row.token}")
    if not pay or not pay.get("checkout_url"):
        return _err(request, "Не получилось открыть оплату. Попробуйте ещё раз через минуту.", 502)
    async with get_session() as session:
        o = await session.get(ShopOrder, row.id)
        o.payment_id = pay["id"]
        await session.commit()
    return _json(request, {"ok": True, "token": row.token, "code": row.code, "checkout_url": pay["checkout_url"]})


async def get_order(request: web.Request) -> web.Response:
    token = request.match_info["token"]
    async with get_session() as session:
        o = await session.scalar(select(ShopOrder).where(ShopOrder.token == token))
    if not o:
        return _err(request, "Заказ не найден.", 404)
    return _json(request, {"ok": True, "order": order_json(o)})


async def return_page(request: web.Request) -> web.Response:
    """Mollie возвращает сюда после оплаты: короткая страница и переход в приложение."""
    token = re.sub(r"[^A-Za-z0-9_\-]", "", request.query.get("token", ""))[:64]
    async with get_session() as session:
        o = await session.scalar(select(ShopOrder).where(ShopOrder.token == token)) if token else None
    if o and o.status == "new" and o.payment_id:   # webhook мог ещё не дойти: сверяемся с Mollie сами
        p = await payments.get_payment(o.payment_id)
        if p:
            await apply_status(o.payment_id, p)
            async with get_session() as session:
                o = await session.scalar(select(ShopOrder).where(ShopOrder.token == token))
    status = STATUS_RU.get(o.status, "") if o else ""
    title = "Спасибо, заказ оплачен" if o and o.status == "paid" else ("Заказ не найден" if not o else status)
    app_link = f"podslushano://shop/order/{token}"
    body = (f"<h1>{html.escape(title)}</h1>"
            + (f"<p>Заказ {html.escape(o.code)} на €{html.escape(o.total)}. Подтверждение придёт на {html.escape(o.email)}.</p>" if o else "")
            + f'<p><a class="b" href="{html.escape(app_link)}">Вернуться в приложение</a></p>')
    page = ("<!doctype html><html lang=ru><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
            "<title>podslushano.nl</title><style>body{font:16px/1.5 -apple-system,Segoe UI,Roboto,Arial,sans-serif;"
            "background:#F4F5F7;color:#0D1117;margin:0;padding:48px 20px;text-align:center}h1{font-size:24px}"
            "a.b{display:inline-block;background:#FF5A1F;color:#0D1117;font-weight:700;padding:14px 24px;border-radius:999px;"
            "text-decoration:none}</style><body>" + body + "</body></html>")
    return web.Response(text=page, content_type="text/html")


# ---------------------------------------------------------------- оплата

async def apply_status(payment_id: str, payment: dict) -> ShopOrder | None:
    """Обновляет заказ по статусу платежа. Возвращает заказ, если он только что стал оплаченным."""
    status = payment.get("status")
    token = (payment.get("metadata") or {}).get("token")
    async with get_session() as session:
        o = await session.scalar(select(ShopOrder).where(ShopOrder.payment_id == payment_id))
        if o is None or (token and o.token != token):
            log.warning("Shop payment %s: order not found", payment_id)
            return None
        if status == "paid" and o.status == "new":
            o.status = "paid"
            o.paid_at = datetime.now(timezone.utc).replace(tzinfo=None)
            await session.commit()
            return o
        if status in ("failed", "canceled", "expired") and o.status == "new":
            o.status = "failed"
            await session.commit()
    return None


async def on_payment(bot, payment_id: str, payment: dict) -> None:
    o = await apply_status(payment_id, payment)
    if o:
        asyncio.create_task(_after_paid(bot, o))


def _email(o: ShopOrder) -> tuple[str, str, str]:
    from utils.email_brand import esc, facts, p, render_email, small, steps, text_version
    items = json.loads(o.items or "[]")
    rows = [(f"{esc(i['title'])}{' · ' + esc(i['color']) if i.get('color') else ''} × {i['qty']}", f"€{esc(i['price'])}") for i in items]
    rows += [("Доставка", f"€{esc(o.shipping)}"), ("Итого", f"€{esc(o.total)}"),
             ("Адрес", esc(f"{o.street} {o.house}, {o.postcode} {o.city}, {COUNTRIES.get(o.country, o.country)}"))]
    next_steps = [("Печать", "Мы передаём заказ в печать в течение 2 рабочих дней."),
                  ("Отправка", "Когда посылка уйдёт, пришлём письмо со ссылкой на отслеживание.")]
    body = p(f"Привет, {esc(o.name.split()[0])}! Заказ {esc(o.code)} оплачен.") + facts(rows) + steps(next_steps)
    body += small("Передумали? В течение 14 дней после получения можно вернуть товар: просто ответьте на это письмо.")
    subject = f"Заказ {o.code} оплачен"
    html_body = render_email(eyebrow="Магазин podslushano.nl", title="Спасибо за заказ", preheader=f"{o.code} · €{o.total}",
                             body=body, reason="Это подтверждение вашего заказа в магазине podslushano.nl.")
    text = text_version("Спасибо за заказ", [f"Заказ {o.code} оплачен.", *(f"{i['title']} × {i['qty']}: €{i['price']}" for i in items),
                                             f"Доставка: €{o.shipping}", f"Итого: €{o.total}"])
    return subject, html_body, text


async def _after_paid(bot, o: ShopOrder) -> None:
    from utils.invoices import send_email_message
    try:
        subject, html_body, text = _email(o)
        await send_email_message(o.email, subject, html_body, text)
    except Exception as e:  # noqa: BLE001 — письмо не должно ломать заказ
        log.warning("Shop email %s failed: %s", o.code, e)
    items = "\n".join(f"• {i['title']}{' · ' + i['color'] if i.get('color') else ''} × {i['qty']}" for i in json.loads(o.items or "[]"))
    text = (f"<b>Новый заказ {html.escape(o.code)}</b> · €{html.escape(o.total)}\n{html.escape(items)}\n\n"
            f"{html.escape(o.name)}\n{html.escape(o.street)} {html.escape(o.house)}\n{html.escape(o.postcode)} {html.escape(o.city)}, "
            f"{COUNTRIES.get(o.country, o.country)}\n{html.escape(o.email)} {html.escape(o.phone)}")
    for admin_id in config.ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, parse_mode="HTML")
        except Exception as e:  # noqa: BLE001
            log.warning("Shop admin notify %s failed: %s", admin_id, e)


def install_routes(app: web.Application) -> None:
    app.router.add_get("/api/shop/catalog", catalog)
    app.router.add_post("/api/shop/order", create_order)
    app.router.add_get(r"/api/shop/order/{token:[A-Za-z0-9_\-]{16,64}}", get_order)
    app.router.add_get("/shop/return", return_page)
    img_dir = CATALOG.parent / "img"
    img_dir.mkdir(parents=True, exist_ok=True)
    app.router.add_static("/shop-img/", img_dir, show_index=False)


# ---------------------------------------------------------------- управление заказами в боте

from aiogram import F, Router  # noqa: E402
from aiogram.enums import ChatType  # noqa: E402
from aiogram.filters import Command, CommandObject  # noqa: E402
from aiogram.types import Message  # noqa: E402

router = Router()
router.message.filter(F.chat.type == ChatType.PRIVATE, F.from_user.id.in_(config.ADMIN_IDS))

ORDER_HELP = ("Заказы магазина:\n"
              "/orders — открытые заказы (оплачены, в печати)\n"
              "/order PN-XXXXX — показать заказ\n"
              "/order PN-XXXXX printing — передан в печать\n"
              "/order PN-XXXXX shipped https://ссылка-на-отслеживание — отправлен, покупателю уйдёт письмо\n"
              "/order PN-XXXXX canceled — отменён (деньги возвращаются в Mollie вручную)")


def admin_order_text(o: ShopOrder) -> str:
    items = "\n".join(f"• {i['title']}{' · ' + i['color'] if i.get('color') else ''} × {i['qty']}" for i in json.loads(o.items or "[]"))
    return (f"<b>{html.escape(o.code)}</b> · {STATUS_RU.get(o.status, o.status)} · €{html.escape(o.total)}\n{html.escape(items)}\n\n"
            f"{html.escape(o.name)}\n{html.escape(o.street)} {html.escape(o.house)}, {html.escape(o.postcode)} {html.escape(o.city)}, "
            f"{COUNTRIES.get(o.country, o.country)}\n{html.escape(o.email)} {html.escape(o.phone)}"
            + (f"\nОтслеживание: {html.escape(o.tracking)}" if o.tracking else ""))


async def set_status(code: str, status: str, tracking: str = "") -> tuple[ShopOrder | None, str]:
    """Меняет статус оплаченного заказа. Возвращает (заказ, ошибка)."""
    allowed = {"paid": {"printing", "shipped", "canceled"}, "printing": {"shipped", "canceled"}, "shipped": {"shipped"}}
    async with get_session() as session:
        o = await session.scalar(select(ShopOrder).where(ShopOrder.code == code.upper()))
        if not o:
            return None, "Заказ не найден."
        if status not in allowed.get(o.status, set()):
            return None, f"Нельзя перевести заказ из статуса «{STATUS_RU.get(o.status, o.status)}» в «{STATUS_RU.get(status, status)}»."
        if status == "shipped":
            if not tracking.startswith("https://"):
                return None, "Для «отправлен» нужна ссылка на отслеживание, начинается с https://"
            o.tracking = tracking[:200]
        o.status = status
        await session.commit()
        return o, ""


def _shipped_email(o: ShopOrder) -> tuple[str, str, str]:
    from utils.email_brand import esc, p, render_email, small, text_version
    body = p(f"Привет, {esc(o.name.split()[0])}! Заказ {esc(o.code)} отправлен.") + small(
        "Посылка обычно идёт 1–3 рабочих дня по Нидерландам и 2–5 дней в Германию и Бельгию.")
    html_body = render_email(eyebrow="Магазин podslushano.nl", title="Заказ в пути", preheader=f"{o.code} отправлен",
                             body=body, cta=("Отследить посылку", o.tracking),
                             reason="Это письмо о вашем заказе в магазине podslushano.nl.")
    return f"Заказ {o.code} отправлен", html_body, text_version("Заказ в пути", [f"Заказ {o.code} отправлен."], ("Отследить посылку", o.tracking))


@router.message(Command("orders"))
async def orders_command(message: Message) -> None:
    async with get_session() as session:
        rows = list(await session.scalars(select(ShopOrder).where(ShopOrder.status.in_(("paid", "printing")))
                                          .order_by(ShopOrder.paid_at)))
    if not rows:
        await message.answer("Открытых заказов нет.\n\n" + ORDER_HELP)
        return
    await message.answer("\n\n".join(admin_order_text(o) for o in rows[:20]), parse_mode="HTML")


@router.message(Command("order"))
async def order_command(message: Message, command: CommandObject) -> None:
    parts = (command.args or "").split()
    if not parts:
        await message.answer(ORDER_HELP)
        return
    code = parts[0].upper()
    if len(parts) == 1:
        async with get_session() as session:
            o = await session.scalar(select(ShopOrder).where(ShopOrder.code == code))
        await message.answer(admin_order_text(o) if o else "Заказ не найден.", parse_mode="HTML")
        return
    o, error = await set_status(code, parts[1].lower(), parts[2] if len(parts) > 2 else "")
    if error:
        await message.answer(error)
        return
    if o.status == "shipped":
        from utils.invoices import send_email_message
        ok, _ = await send_email_message(o.email, *_shipped_email(o))
        await message.answer(f"{o.code}: отправлен." + (" Покупателю ушло письмо со ссылкой." if ok else " Письмо не отправилось, напишите покупателю сами."))
    else:
        await message.answer(f"{o.code}: {STATUS_RU.get(o.status, o.status)}.")
