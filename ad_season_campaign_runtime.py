"""Q4 2026 advertising campaign runtime for /ads.

Adds the newsletter opt-in used by the animated gift on the advertising page
and a signed 26% discount option for the public advertising formats. The
checkout keeps using the existing /ads/book route and Mollie flow.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import html
import re
import time
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo

from aiohttp import web
from sqlalchemy import Boolean, DateTime, Integer, String, func, select
from sqlalchemy.orm import Mapped, mapped_column

import ad_products_runtime  # noqa: F401 — ensure the public Q4 products exist
import config
from database.db import get_session
from database.models import Base
from handlers import ads as ads_handler


_CAMPAIGN_END = datetime(2026, 12, 31, 23, 59, 59, tzinfo=ZoneInfo("Europe/Amsterdam"))
_CAMPAIGN_LAST_DATE = "2026-12-31"
_DISCOUNT_RATE = Decimal("0.26")
_OPTION_KEY = "q4_26"
_ALLOWED_FORMATS = {
    "ad_single",
    "ad_telegram",
    "ad_expert_live",
    "ad_promotion",
    "ad_campaign",
}
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_TOKEN_MARKER = "SEASON26:"
_UNSUBSCRIBE_PREFIX = b"podslushano:ads:newsletter:unsubscribe:"


class AdsNewsletterSubscriber(Base):
    """Explicit advertising-newsletter consent collected on the /ads page."""

    __tablename__ = "ads_newsletter_subscribers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    source: Mapped[str] = mapped_column(String(40), default="ads_q4_2026")
    consent_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


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
    except (ValueError, UnicodeError, binascii.Error):
        return None
    if expiry != int(_CAMPAIGN_END.timestamp()) or int(time.time()) > expiry:
        return None
    if not _EMAIL_RE.match(email):
        return None
    return email.lower()


def _issue_unsubscribe_token(email: str) -> str:
    """Stable signed token for unsubscribe links used after the Q4 campaign ends."""
    secret = _secret()
    if not secret:
        raise RuntimeError("Advertising newsletter secret is not configured")
    normalized = email.strip().lower()
    payload = normalized.encode("utf-8")
    signature = hmac.new(secret, _UNSUBSCRIBE_PREFIX + payload, hashlib.sha256).hexdigest()
    return f"{_b64encode(payload)}.{signature}"


def _unsubscribe_token_email(token: str) -> str | None:
    secret = _secret()
    if not token or not secret or "." not in token:
        return None
    encoded, signature = token.split(".", 1)
    try:
        payload = _b64decode(encoded)
        expected = hmac.new(
            secret, _UNSUBSCRIBE_PREFIX + payload, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return None
        email = payload.decode("utf-8").strip().lower()
    except (UnicodeError, binascii.Error):
        return None
    return email if _EMAIL_RE.match(email) else None


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
            if any(str(value or "") > _CAMPAIGN_LAST_DATE for value in dates or []):
                return None, "Сезонная скидка действует только на размещения до 31 декабря 2026 года."
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
            {"ok": False, "error": "Нужно подтвердить подписку на рекламные обновления."},
            status=400,
        )

    async with get_session() as session:
        subscriber = await session.scalar(
            select(AdsNewsletterSubscriber).where(
                func.lower(AdsNewsletterSubscriber.email) == email
            )
        )
        if subscriber is None:
            session.add(AdsNewsletterSubscriber(email=email, is_active=True))
        else:
            subscriber.is_active = True
            subscriber.consent_at = datetime.utcnow()
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
    active = False
    if email:
        async with get_session() as session:
            active = bool(await session.scalar(
                select(AdsNewsletterSubscriber.id).where(
                    func.lower(AdsNewsletterSubscriber.email) == email,
                    AdsNewsletterSubscriber.is_active.is_(True),
                )
            ))
    return web.json_response(
        {
            "ok": active,
            "discount": 26 if active else 0,
            "expires": _CAMPAIGN_END.isoformat(),
        },
        headers={"Cache-Control": "no-store"},
    )


def _unsubscribe_page(token: str, *, error: str = "") -> str:
    safe_token = html.escape(token, quote=True)
    notice = (
        f'<p style="color:#8b3528">{html.escape(error)}</p>' if error else ""
    )
    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Отписаться — Podslushano.nl</title><style>
body{{margin:0;background:#f3eee5;color:#19211e;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;display:grid;place-items:center;min-height:100vh;padding:18px}}
.card{{width:min(480px,100%);background:#fffdf8;border:1px solid #d8ccba;border-radius:22px;padding:26px;box-shadow:0 18px 56px rgba(45,37,25,.10)}}
h1{{font-size:30px;line-height:1;margin:0 0 12px}}p{{color:#5d5851;line-height:1.5}}button{{border:0;border-radius:999px;padding:13px 18px;background:#183a31;color:#fff;font-weight:800;cursor:pointer}}
</style></head><body><main class="card"><h1>Отписаться от рассылки?</h1><p>После отписки мы больше не будем отправлять рекламные обновления Podslushano.nl на этот e-mail. Подписаться снова можно будет позже.</p>{notice}<form method="post" action="/ads-newsletter/unsubscribe"><input type="hidden" name="token" value="{safe_token}"><button type="submit">Да, отписаться</button></form></main></body></html>"""


async def newsletter_unsubscribe_page(request: web.Request) -> web.Response:
    token = (request.query.get("token") or "").strip()
    email = _unsubscribe_token_email(token)
    if not email:
        return web.Response(
            text=_unsubscribe_page(token, error="Ссылка для отписки недействительна."),
            content_type="text/html",
            status=400,
            headers={"Cache-Control": "no-store"},
        )
    return web.Response(
        text=_unsubscribe_page(token),
        content_type="text/html",
        headers={"Cache-Control": "no-store"},
    )


async def newsletter_unsubscribe(request: web.Request) -> web.Response:
    data = await request.post()
    token = (data.get("token") or "").strip()
    email = _unsubscribe_token_email(token)
    if not email:
        return web.Response(
            text=_unsubscribe_page(token, error="Ссылка для отписки недействительна."),
            content_type="text/html",
            status=400,
            headers={"Cache-Control": "no-store"},
        )

    async with get_session() as session:
        subscriber = await session.scalar(
            select(AdsNewsletterSubscriber).where(
                func.lower(AdsNewsletterSubscriber.email) == email
            )
        )
        if subscriber is not None:
            subscriber.is_active = False
            await session.commit()

    return web.Response(
        text="""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Вы отписаны — Podslushano.nl</title><style>body{margin:0;background:#f3eee5;color:#19211e;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;display:grid;place-items:center;min-height:100vh;padding:18px}.card{width:min(480px,100%);background:#fffdf8;border:1px solid #d8ccba;border-radius:22px;padding:26px;box-shadow:0 18px 56px rgba(45,37,25,.10)}h1{font-size:30px;line-height:1;margin:0 0 12px}p{color:#5d5851;line-height:1.5}</style></head><body><main class="card"><h1>Вы отписались</h1><p>Рекламные обновления Podslushano.nl больше не будут приходить на этот e-mail.</p></main></body></html>""",
        content_type="text/html",
        headers={"Cache-Control": "no-store"},
    )


def _install_routes(app: web.Application) -> None:
    app.router.add_post("/ads-season/subscribe", newsletter_subscribe)
    app.router.add_get("/ads-season/status", newsletter_status)
    app.router.add_get("/ads-newsletter/unsubscribe", newsletter_unsubscribe_page)
    app.router.add_post("/ads-newsletter/unsubscribe", newsletter_unsubscribe)


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
