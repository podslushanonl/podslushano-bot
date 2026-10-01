"""Small production follow-up for the Q4 advertising page.

This module intentionally sits on top of the existing Q4 runtime instead of
rewriting it: it adds the visual density pass, sends a branded Resend welcome
e-mail after newsletter signup, and can send that welcome once to subscribers
who opted in before the e-mail feature was deployed.
"""
from __future__ import annotations

import html
import json
import logging
import os
from urllib.parse import quote

import aiohttp
from aiohttp import web
from sqlalchemy import func, select

import ad_season_campaign_runtime as season
import config
from database.db import get_session
from utils import webserver as ws

log = logging.getLogger(__name__)

_CLEANUP_CSS = "/ads-static/q4-cleanup.css"
_CLEANUP_JS = "/ads-static/q4-cleanup.js"
_RESEND_ENDPOINT = "https://api.resend.com/emails"


def _public_base_url(request: web.Request) -> str:
    configured = (getattr(config, "WEBHOOK_BASE_URL", "") or "").strip().rstrip("/")
    if configured:
        return configured
    return f"{request.scheme}://{request.host}".rstrip("/")


def _newsletter_from() -> str:
    return (
        os.getenv("ADS_NEWSLETTER_FROM_EMAIL", "").strip()
        or "Podslushano.nl <ads@podslushano.nl>"
    )


def _welcome_email_html(base_url: str, unsubscribe_url: str) -> str:
    ads_url = html.escape(base_url.rstrip("/") + "/ads", quote=True)
    unsubscribe = html.escape(unsubscribe_url, quote=True)
    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="X-UA-Compatible" content="IE=edge">
<title>Podslushano.nl — рекламные обновления</title>
</head>
<body style="margin:0;padding:0;background-color:#f3eee5;font-family:Arial,Helvetica,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="#f3eee5" style="width:100%;background-color:#f3eee5;">
<tr><td align="center" style="padding-top:28px;padding-right:14px;padding-bottom:28px;padding-left:14px;">
<table width="100%" cellpadding="0" cellspacing="0" border="0" style="width:100%;max-width:600px;background-color:#fffdf8;border-radius:24px;overflow:hidden;">
<tr><td bgcolor="#fffdf8" style="background-color:#fffdf8;padding-top:24px;padding-right:28px;padding-bottom:20px;padding-left:28px;font-family:Arial,Helvetica,sans-serif;font-size:23px;line-height:28px;color:#19211e;font-weight:800;">Podslushano.nl</td></tr>
<tr><td bgcolor="#183a31" style="background-color:#183a31;padding-top:32px;padding-right:28px;padding-bottom:32px;padding-left:28px;">
<p style="margin-top:0;margin-right:0;margin-bottom:10px;margin-left:0;font-family:Arial,Helvetica,sans-serif;font-size:11px;line-height:16px;color:#bdd0c8;font-weight:700;letter-spacing:1.5px;">РЕКЛАМА · ДО КОНЦА 2026</p>
<p style="margin-top:0;margin-right:0;margin-bottom:14px;margin-left:0;font-family:Arial,Helvetica,sans-serif;font-size:34px;line-height:37px;color:#ffffff;font-weight:800;">Спасибо за подписку.</p>
<p style="margin-top:0;margin-right:0;margin-bottom:22px;margin-left:0;font-family:Arial,Helvetica,sans-serif;font-size:16px;line-height:24px;color:#dce7e2;">Сезонная цена уже активна. На рекламные форматы Podslushano.nl действует скидка <strong style="font-size:16px;line-height:24px;color:#ffd99c;">−26%</strong> до 31 декабря 2026 года.</p>
<table cellpadding="0" cellspacing="0" border="0"><tr><td bgcolor="#fff4df" style="background-color:#fff4df;border-radius:999px;padding-top:12px;padding-right:20px;padding-bottom:12px;padding-left:20px;"><a href="{ads_url}" style="font-family:Arial,Helvetica,sans-serif;font-size:14px;line-height:18px;color:#183a31;font-weight:700;text-decoration:none;display:inline-block;">Выбрать рекламный формат →</a></td></tr></table>
</td></tr>
<tr><td bgcolor="#fffdf8" style="background-color:#fffdf8;padding-top:26px;padding-right:28px;padding-bottom:12px;padding-left:28px;">
<p style="margin-top:0;margin-right:0;margin-bottom:18px;margin-left:0;font-family:Arial,Helvetica,sans-serif;font-size:15px;line-height:23px;color:#393733;">Писать будем редко и по делу: обычно одно письмо в начале месяца — новые форматы, свободные даты и сезонные возможности для рекламодателей.</p>
<table width="100%" cellpadding="0" cellspacing="0" border="0" style="width:100%;">
<tr><td bgcolor="#f3eee5" style="background-color:#f3eee5;border-radius:14px;padding-top:13px;padding-right:15px;padding-bottom:13px;padding-left:15px;font-family:Arial,Helvetica,sans-serif;font-size:13px;line-height:19px;color:#514d47;"><strong style="font-size:13px;line-height:19px;color:#19211e;">Что дальше?</strong><br>Когда появится подходящий повод для рекламы, просто откройте страницу — скидка будет привязана к вашей подписке.</td></tr>
</table>
</td></tr>
<tr><td bgcolor="#fffdf8" style="background-color:#fffdf8;padding-top:16px;padding-right:28px;padding-bottom:28px;padding-left:28px;font-family:Arial,Helvetica,sans-serif;font-size:11px;line-height:17px;color:#777168;">Вы получили это письмо после подписки на рекламные обновления Podslushano.nl. <a href="{unsubscribe}" style="font-size:11px;line-height:17px;color:#713b36;text-decoration:underline;">Отписаться</a></td></tr>
</table>
</td></tr>
</table>
</body>
</html>"""


def _welcome_email_text(base_url: str, unsubscribe_url: str) -> str:
    return (
        "Спасибо за подписку на рекламные обновления Podslushano.nl.\n\n"
        "Скидка −26% на рекламные форматы активна до 31 декабря 2026 года.\n"
        f"Выбрать формат: {base_url.rstrip('/')}/ads\n\n"
        "Обычно мы отправляем одно письмо в начале месяца: новые форматы, "
        "свободные даты и сезонные возможности.\n\n"
        f"Отписаться: {unsubscribe_url}"
    )


async def _send_welcome_email(email: str, base_url: str) -> bool:
    api_key = os.getenv("RESEND_API_KEY", "").strip()
    if not api_key:
        log.warning("Ads welcome e-mail skipped: RESEND_API_KEY is missing")
        return False

    unsubscribe_token = season._issue_unsubscribe_token(email)
    unsubscribe_url = (
        base_url.rstrip("/")
        + "/ads-newsletter/unsubscribe?token="
        + quote(unsubscribe_token, safe="")
    )
    payload = {
        "from": _newsletter_from(),
        "to": [email],
        "subject": "Ваша скидка −26% активна — Podslushano.nl",
        "html": _welcome_email_html(base_url, unsubscribe_url),
        "text": _welcome_email_text(base_url, unsubscribe_url),
        "headers": {"List-Unsubscribe": f"<{unsubscribe_url}>"},
        "tags": [{"name": "type", "value": "ads_welcome"}],
    }
    reply_to = (getattr(config, "COMPANY_EMAIL", "") or "").strip()
    if reply_to:
        payload["reply_to"] = reply_to

    timeout = aiohttp.ClientTimeout(total=15)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                _RESEND_ENDPOINT,
                json=payload,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "User-Agent": "PodslushanoAds/2026",
                },
            ) as response:
                body = await response.text()
                if response.status >= 300:
                    log.error(
                        "Ads welcome e-mail failed for subscriber: HTTP %s %s",
                        response.status,
                        body[:500],
                    )
                    return False
    except Exception as exc:  # noqa: BLE001
        log.warning("Ads welcome e-mail request failed: %s: %s", type(exc).__name__, exc)
        return False
    return True


async def _subscriber_is_active(email: str) -> bool:
    async with get_session() as session:
        subscriber_id = await session.scalar(
            select(season.AdsNewsletterSubscriber.id).where(
                func.lower(season.AdsNewsletterSubscriber.email) == email.lower(),
                season.AdsNewsletterSubscriber.is_active.is_(True),
            )
        )
    return bool(subscriber_id)


_ORIGINAL_SUBSCRIBE = season.newsletter_subscribe


async def _newsletter_subscribe_with_welcome(request: web.Request) -> web.Response:
    posted = await request.post()
    email = (posted.get("email") or "").strip().lower()
    response = await _ORIGINAL_SUBSCRIBE(request)
    if response.status >= 300 or not email:
        return response
    try:
        payload = json.loads(response.text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return response
    if not payload.get("ok"):
        return response

    sent = await _send_welcome_email(email, _public_base_url(request))
    payload["email_sent"] = sent
    return web.json_response(payload, headers={"Cache-Control": "no-store"})


_newsletter_subscribe_with_welcome._ads_welcome_wrapper = True  # type: ignore[attr-defined]
if not getattr(season.newsletter_subscribe, "_ads_welcome_wrapper", False):
    season.newsletter_subscribe = _newsletter_subscribe_with_welcome


async def newsletter_welcome_existing(request: web.Request) -> web.Response:
    posted = await request.post()
    token = (posted.get("token") or "").strip()
    email = season._token_email(token) if season._campaign_active() else None
    if not email or not await _subscriber_is_active(email):
        return web.json_response(
            {"ok": False, "error": "Подписка не подтверждена."}, status=403
        )
    sent = await _send_welcome_email(email, _public_base_url(request))
    return web.json_response(
        {"ok": True, "email_sent": sent},
        headers={"Cache-Control": "no-store"},
    )


_ORIGINAL_INSTALL_ROUTES = season._install_routes


def _install_routes_with_welcome(app: web.Application) -> None:
    _ORIGINAL_INSTALL_ROUTES(app)
    app.router.add_post("/ads-season/welcome", newsletter_welcome_existing)


_install_routes_with_welcome._ads_welcome_wrapper = True  # type: ignore[attr-defined]
if not getattr(season._install_routes, "_ads_welcome_wrapper", False):
    season._install_routes = _install_routes_with_welcome


_ORIGINAL_ADS_PAGE = ws._ads


async def _ads_page_with_density_cleanup(request: web.Request) -> web.Response:
    response = await _ORIGINAL_ADS_PAGE(request)
    try:
        text = response.text
    except Exception:
        return response

    if "q4-cleanup.css" not in text:
        text = text.replace(
            "</head>",
            f'<link rel="stylesheet" href="{_CLEANUP_CSS}">\n</head>',
            1,
        )
    if "q4-cleanup.js" not in text:
        text = text.replace(
            "</body>",
            f'<script src="{_CLEANUP_JS}"></script>\n</body>',
            1,
        )
    return web.Response(
        text=text,
        content_type="text/html",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


_ads_page_with_density_cleanup._ads_density_wrapper = True  # type: ignore[attr-defined]
if not getattr(ws._ads, "_ads_density_wrapper", False):
    ws._ads = _ads_page_with_density_cleanup
