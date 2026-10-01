"""Website checkout for Contact Guide purchases from /ads.

The Q4 advertising page should keep visitors on one surface: choose a Contact
Guide plan, submit the card details and pay through Mollie without jumping to
Telegram. Existing specialist payment/webhook processing remains canonical.
"""
from __future__ import annotations

import html
import re
from decimal import Decimal, ROUND_HALF_UP

from aiohttp import web
from sqlalchemy import func, select

import ad_season_campaign_runtime as season
import config
from database.db import get_session
from database.models import Specialist
from handlers import selfadd
from utils.geo import detect_category, detect_city


_DISCOUNT_RATE = Decimal("0.26")
_ALLOWED_PLANS = set(selfadd.SELFADD_PLANS)


def _discount_price(value: str) -> str:
    amount = Decimal(str(value))
    return f"{(amount * (Decimal('1') - _DISCOUNT_RATE)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):.2f}"


def _flag(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


async def _season_entitlement(email: str, token: str) -> bool:
    normalized = (email or "").strip().lower()
    token_email = season._token_email((token or "").strip()) if season._campaign_active() else None
    if not normalized or token_email != normalized:
        return False
    async with get_session() as session:
        subscriber_id = await session.scalar(
            select(season.AdsNewsletterSubscriber.id).where(
                func.lower(season.AdsNewsletterSubscriber.email) == normalized,
                season.AdsNewsletterSubscriber.is_active.is_(True),
            )
        )
    return bool(subscriber_id)


def _json_error(message: str, status: int = 400) -> web.Response:
    return web.json_response(
        {"ok": False, "error": message},
        status=status,
        headers={"Cache-Control": "no-store"},
    )


async def contact_guide_checkout(request: web.Request) -> web.Response:
    data = await request.post()
    plan = (data.get("plan") or "").strip()
    if plan not in _ALLOWED_PLANS:
        return _json_error("Выберите тариф Contact Guide.")
    if not config.payments_enabled():
        return _json_error("Оплата временно недоступна. Попробуйте чуть позже.", 503)

    name = selfadd._clean_text((data.get("name") or "").strip())
    category_raw = selfadd._clean_text((data.get("category") or "").strip())
    city_raw = selfadd._clean_text((data.get("city") or "").strip())
    description = (data.get("description") or "").strip()
    contact = selfadd._clean_text((data.get("contact") or "").strip())
    email = (data.get("email") or "").strip().lower()
    online = _flag(data.get("online"))
    terms = _flag(data.get("terms"))
    token = (data.get("token") or "").strip()

    if not selfadd._valid_name(name):
        return _json_error("Укажите имя специалиста или название компании.")
    if not 2 <= len(category_raw) <= 50 or len(re.findall(r"[A-Za-zА-Яа-яЁё]", category_raw)) < 2:
        return _json_error("Укажите понятную категорию услуги.")
    if not selfadd._valid_description(description):
        return _json_error("Описание должно быть понятным и содержать минимум 20 символов.")
    if not selfadd._valid_contact(contact):
        return _json_error("Укажите рабочий публичный контакт: сайт, e-mail, телефон или Telegram.")
    if not selfadd._valid_email(email):
        return _json_error("Укажите корректный e-mail для factuur.")
    if not terms:
        return _json_error("Подтвердите согласие с условиями и политикой конфиденциальности.")

    if online:
        city, province = "", ""
    else:
        if not 2 <= len(city_raw) <= 80 or len(re.findall(r"[A-Za-zА-Яа-яЁё]", city_raw)) < 2:
            return _json_error("Укажите город или выберите «Онлайн / по всей стране».")
        known_city = detect_city(city_raw)
        city, province = known_city if known_city else (city_raw, "")

    category = detect_category(category_raw) or category_raw.lower()
    info = config.plan_info(plan)
    seasonal = await _season_entitlement(email, token)
    if token and not seasonal:
        return _json_error(
            "Скидка −26% не подтверждена для этого e-mail. Используйте адрес, на который оформлена подписка, или обновите страницу.",
            403,
        )
    amount = _discount_price(info["price"]) if seasonal else info["price"]

    async with get_session() as session:
        specialist = Specialist(
            name=name,
            category=category,
            city=city,
            province=province,
            description=description,
            contact=contact,
            is_online=online,
            is_premium=info["premium"],
            status="awaiting_payment",
            source="self",
            submitter_user_id=None,
            invoice_email=email,
            plan=plan,
        )
        session.add(specialist)
        await session.commit()
        await session.refresh(specialist)
        sid = specialist.id

    metadata = {
        "specialist_id": sid,
        "kind": "new",
        "plan": plan,
        "source": "ads_page",
    }
    if seasonal:
        metadata["discount"] = "q4_26"

    payment = await selfadd.create_payment(
        f"{selfadd.DESC_NEW}: {name}",
        metadata,
        amount,
    )
    if not payment or not payment.get("checkout_url") or not payment.get("id"):
        return _json_error(
            "Не удалось создать оплату Mollie. Данные сохранены — попробуйте ещё раз через минуту.",
            502,
        )

    async with get_session() as session:
        specialist = await session.get(Specialist, sid)
        if specialist is not None:
            specialist.payment_id = payment["id"]
            await session.commit()

    return web.json_response(
        {
            "ok": True,
            "checkout_url": payment["checkout_url"],
            "specialist_id": sid,
            "plan": plan,
            "amount": amount,
            "discount": 26 if seasonal else 0,
        },
        headers={"Cache-Control": "no-store"},
    )


def _success_html(title: str, lead: str, detail: str) -> str:
    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)} — Podslushano.nl</title>
<style>
*{{box-sizing:border-box}}body{{margin:0;min-height:100vh;display:grid;place-items:center;padding:20px;background:#f3eee5;color:#19211e;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif}}
.card{{width:min(520px,100%);background:#fffdf8;border:1px solid #d8ccba;border-radius:24px;padding:28px;box-shadow:0 18px 56px rgba(45,37,25,.10)}}.brand{{font-weight:900;font-size:20px;margin-bottom:30px}}.mark{{width:48px;height:48px;border-radius:16px;background:#e1eee6;display:grid;place-items:center;font-size:25px;margin-bottom:16px}}h1{{font-size:34px;line-height:1;margin:0 0 12px;letter-spacing:-.04em}}p{{font-size:15px;line-height:1.55;color:#5d5851;margin:0 0 12px}}.note{{background:#f3eee5;border-radius:14px;padding:13px 15px;font-size:13px;color:#514d47;margin:18px 0}}a{{display:inline-flex;text-decoration:none;background:#183a31;color:#fff;border-radius:999px;padding:12px 18px;font-weight:800}}
</style></head><body><main class="card"><div class="brand">Podslushano.nl</div><div class="mark">✓</div><h1>{html.escape(title)}</h1><p>{html.escape(lead)}</p><div class="note">{html.escape(detail)}</div><a href="/ads#guide">Вернуться к рекламе</a></main></body></html>"""


async def contact_guide_success(request: web.Request) -> web.Response:
    raw_sid = (request.query.get("sid") or "").strip()
    if not raw_sid.isdigit():
        return web.Response(
            text=_success_html("Проверяем оплату", "Не удалось определить заказ.", "Если оплата прошла, factuur всё равно придёт на указанный e-mail."),
            content_type="text/html",
            status=400,
            headers={"Cache-Control": "no-store"},
        )

    async with get_session() as session:
        specialist = await session.get(Specialist, int(raw_sid))
        payment_id = specialist.payment_id if specialist else None

    status = ""
    if payment_id:
        payment = await selfadd.get_payment(payment_id)
        status = (payment or {}).get("status", "")

    if status == "paid":
        title = "Оплата получена"
        lead = "Спасибо! Заявка Contact Guide отправлена на проверку."
        detail = "Factuur придёт на указанный e-mail. Для Premium мы отдельно запросим фото или логотип перед публикацией карточки."
        code = 200
    elif status in {"failed", "canceled", "expired"}:
        title = "Оплата не завершена"
        lead = "Mollie не подтвердил платёж."
        detail = "Вернитесь на страницу рекламы и оформите Contact Guide ещё раз. Деньги по незавершённому платежу не списываются."
        code = 402
    else:
        title = "Платёж обрабатывается"
        lead = "Mollie ещё подтверждает оплату. Обычно это занимает совсем немного времени."
        detail = "После подтверждения заявка автоматически уйдёт на проверку, а factuur — на ваш e-mail."
        code = 200

    return web.Response(
        text=_success_html(title, lead, detail),
        content_type="text/html",
        status=code,
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


_ORIGINAL_INSTALL_ROUTES = season._install_routes


def _install_routes_with_guide_checkout(app: web.Application) -> None:
    _ORIGINAL_INSTALL_ROUTES(app)
    app.router.add_post("/ads/contact-guide/checkout", contact_guide_checkout)
    app.router.add_get("/ads/contact-guide/success", contact_guide_success)


_install_routes_with_guide_checkout._ads_guide_web_wrapper = True  # type: ignore[attr-defined]
if not getattr(season._install_routes, "_ads_guide_web_wrapper", False):
    season._install_routes = _install_routes_with_guide_checkout
