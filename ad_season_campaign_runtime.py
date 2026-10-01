"""Q4 2026 advertising campaign runtime for /ads.

Adds the newsletter opt-in used by the animated gift on the advertising page
and a signed 26% discount option for the public advertising formats. The
checkout keeps using the existing /ads/book route and Mollie flow.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
import time
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo

from aiohttp import web
from sqlalchemy import select

import ad_products_runtime  # noqa: F401 — ensure the public Q4 products exist
import config
from database.db import get_session
from database.models import AdLead
from handlers import ads as ads_handler


_CAMPAIGN_END = datetime(2026, 12, 31, 23, 59, 59, tzinfo=ZoneInfo("Europe/Amsterdam"))
_DISCOUNT_RATE = Decimal("0.26")
_OPTION_KEY = "q4_26"
_NEWSLETTER_BUSINESS = "Podslushano Ads Q4 2026"
_ALLOWED_FORMATS = {
    "ad_single",
    "ad_telegram",
    "ad_expert_live",
    "ad_promotion",
    "ad_campaign",
}
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_TOKEN_MARKER = "SEASON26:"


def _campaign_active() -> bool:
    return datetime.now(ZoneInfo("Europe/Amsterdam")) <= _CAMPAIGN_END


def _discount_price(value: str) -> str:
    amount = Decimal(value)
    discounted = (amount * (Decimal("1") - _DISCOUNT_RATE)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    return f"{discounted:.2f}"


def _register_discount_options() -> None:
    for fmt in _ALLOWED_FORMATS:
        info = config.AD_FORMATS.get(fmt)
        if not info:
            continue
        options = info.setdefault("options", [])
        if any(option.get("key") == _OPTION_KEY for option in options):
            continue
        regular = next((option for option in options if option.get("key") == "std"), None)
        if regular is None:
            continue
        options.append(
            {
                "key": _OPTION_KEY,
                "label": f"{regular['label']} · Q4 −26%",
                "price": _discount_price(str(regular["price"])),
            }
        )


_register_discount_options()


def _secret() -> bytes:
    raw = (
        config.BOT_TOKEN
        or config.MOLLIE_API_KEY
        or config.CRM_WEBHOOK_SECRET
        or ""
    ).encode("utf-8")
    if not raw:
        return b""
    return hashlib.sha256(b"podslushano:ads:q4:2026:" + raw).digest()


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def _issue_token(email: str) -> str:
    secret = _secret()
    if not secret:
        raise RuntimeError("Advertising campaign secret is not configured")
    normalized = email.strip().lower()
    expiry = int(_CAMPAIGN_END.timestamp())
    payload = f"{normalized}|{expiry}".encode("utf-8")
    signature = hmac.new(secret, payload, hashlib.sha256).hexdigest()
    return f"{_b64encode(payload)}.{signature}"


def _token_email(token: str) -> str | None:
    secret = _secret()
    if not token or not secret or "." not in token:
        return None
    encoded, signature = token.split(".", 1)
    try:
        payload = _b64decode(encoded)
        expected = hmac.new(secret, payload, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return None
        decoded = payload.decode("utf-8")
        email, expiry_raw = decoded.rsplit("|", 1)
        expiry = int(expiry_raw)
    except (ValueError, UnicodeError, base64.binascii.Error):
        return None
    if expiry != int(_CAMPAIGN_END.timestamp()) or int(time.time()) > expiry:
        return None
    if not _EMAIL_RE.match(email):
        return None
    return email.lower()


def _extract_discount_token(phone: str) -> tuple[str, str | None]:
    parts = [part for part in (phone or "").split("|||") if part]
    token = None
    cleaned: list[str] = []
    for part in parts:
        if part.startswith(_TOKEN_MARKER):
            token = part[len(_TOKEN_MARKER):].strip()
        else:
            cleaned.append(part)
    return "|||".join(cleaned), token


if not getattr(ads_handler.book_and_pay, "_q4_discount_wrapper", False):
    _original_book_and_pay = ads_handler.book_and_pay

    async def _book_and_pay_q4(fmt: str, opt: str, dates: list, fields: dict):
        copied = dict(fields or {})
        clean_phone, token = _extract_discount_token(copied.get("phone") or "")
        copied["phone"] = clean_phone
        if opt == _OPTION_KEY:
            if fmt not in _ALLOWED_FORMATS:
                return None, "Сезонная скидка недоступна для этого формата."
            if not _campaign_active() or _token_email(token or "") is None:
                return None, "Скидка −26% не подтверждена. Откройте подарок на рекламной странице и подпишитесь на обновления."
        return await _original_book_and_pay(fmt, opt, dates, copied)

    _book_and_pay_q4._q4_discount_wrapper = True  # type: ignore[attr-defined]
    ads_handler.book_and_pay = _book_and_pay_q4


async def newsletter_subscribe(request: web.Request) -> web.Response:
    if not _campaign_active():
        return web.json_response(
            {"ok": False, "error": "Сезонное предложение завершено."}, status=410
        )
    data = await request.post()
    email = (data.get("email") or "").strip().lower()
    consent = (data.get("consent") or "").strip().lower()
    if len(email) > 200 or not _EMAIL_RE.match(email):
        return web.json_response(
            {"ok": False, "error": "Укажите корректный e-mail."}, status=400
        )
    if consent not in {"1", "true", "yes", "on"}:
        return web.json_response(
            {"ok": False, "error": "Нужно подтвердить подписку на ежемесячные обновления."},
            status=400,
        )

    async with get_session() as session:
        existing = await session.scalar(
            select(AdLead.id).where(
                AdLead.business == _NEWSLETTER_BUSINESS,
                AdLead.contact == email,
            )
        )
        if existing is None:
            session.add(
                AdLead(
                    name="Q4 newsletter",
                    business=_NEWSLETTER_BUSINESS,
                    contact=email,
                    message=(
                        "Согласие с /ads: ежемесячные обновления рекламных возможностей "
                        "Podslushano.nl, не чаще 1 письма в месяц. Разблокирована скидка −26%."
                    ),
                )
            )
            await session.commit()

    return web.json_response(
        {
            "ok": True,
            "token": _issue_token(email),
            "discount": 26,
            "expires": _CAMPAIGN_END.isoformat(),
        },
        headers={"Cache-Control": "no-store"},
    )


async def newsletter_status(request: web.Request) -> web.Response:
    token = (request.query.get("token") or "").strip()
    email = _token_email(token) if _campaign_active() else None
    return web.json_response(
        {
            "ok": bool(email),
            "discount": 26 if email else 0,
            "expires": _CAMPAIGN_END.isoformat(),
        },
        headers={"Cache-Control": "no-store"},
    )


def _install_routes(app: web.Application) -> None:
    app.router.add_post("/ads-season/subscribe", newsletter_subscribe)
    app.router.add_get("/ads-season/status", newsletter_status)


async def start_webserver_with_ads_campaign(bot):
    """Install Q4 routes and preserve the existing Gmail OAuth route wrapper."""
    import gmail_oauth_runtime
    from utils import webserver as ws

    original_application = ws.web.Application

    def application_factory(*args, **kwargs):
        app = original_application(*args, **kwargs)
        _install_routes(app)
        return app

    ws.web.Application = application_factory
    try:
        return await gmail_oauth_runtime.start_webserver_with_gmail(bot)
    finally:
        ws.web.Application = original_application
