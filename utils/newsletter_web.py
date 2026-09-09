"""Публичные страницы подписки и управления e-mail рассылкой."""
from __future__ import annotations

import html
import time
from datetime import datetime

from aiohttp import web
from sqlalchemy import select

import config
from database.db import get_session
from database.models import NewsletterSubscriber
from utils.newsletter import (
    DEFAULT_TOPICS,
    FREQUENCIES,
    TOPICS,
    hash_ip,
    new_token,
    normalize_email,
    send_confirmation,
    send_manage_link,
    topic_set,
    topics_csv,
    valid_email,
)

_attempts: dict[str, list[float]] = {}
_CSS = """
:root{--ink:#1d1916;--muted:#6c6259;--paper:#f5efe8;--card:#fff;--line:#e5d8cb;--orange:#ef6c2f}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif}
.shell{min-height:100vh;padding:28px 16px 50px}.wrap{max-width:760px;margin:auto}.brand{font-size:22px;font-weight:850;letter-spacing:-.03em;margin-bottom:28px}
.hero{background:var(--ink);color:#fff;border-radius:26px;padding:42px 38px}.kicker{color:#ffad78;font-size:13px;font-weight:800;letter-spacing:.09em;text-transform:uppercase}.hero h1{font-size:46px;line-height:1.04;letter-spacing:-.045em;max-width:620px;margin:14px 0}.hero p{color:#ded5ce;font-size:18px;line-height:1.55;max-width:590px;margin:0}
.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:18px 0}.promise{background:#fff7f1;border:1px solid #f3d6c1;border-radius:16px;padding:17px;font-size:14px;line-height:1.4}.promise b{display:block;font-size:18px;margin-bottom:4px}
.card{background:var(--card);border:1px solid var(--line);border-radius:22px;padding:30px;margin-top:18px;box-shadow:0 16px 45px rgba(71,43,23,.06)}h2{font-size:27px;letter-spacing:-.025em;margin:0 0 8px}.lead{color:var(--muted);line-height:1.55;margin:0 0 24px}
label.title{display:block;font-weight:750;margin:19px 0 8px}.input{width:100%;border:1px solid #cfc0b2;border-radius:12px;padding:14px 15px;font:inherit;background:#fff}.choices{display:grid;gap:9px}.choice{display:flex;gap:11px;align-items:flex-start;border:1px solid var(--line);border-radius:13px;padding:13px;cursor:pointer}.choice input{width:18px;height:18px;margin-top:1px;accent-color:var(--orange)}.choice span{line-height:1.35}.choice small{display:block;color:var(--muted);margin-top:3px}.consent{display:flex;gap:10px;color:var(--muted);font-size:13px;line-height:1.45;margin:21px 0}.consent input{width:18px;height:18px;flex:0 0 auto;accent-color:var(--orange)}a{color:#a44217}.button{border:0;border-radius:12px;background:var(--orange);color:#fff;padding:15px 20px;font:800 16px inherit;cursor:pointer;width:100%}.button.secondary{background:#312a25}.note{color:var(--muted);font-size:12px;line-height:1.5;text-align:center;margin-top:13px}.success{text-align:center;padding:44px 30px}.success .icon{width:62px;height:62px;margin:0 auto 16px;border-radius:50%;display:grid;place-items:center;background:#fff1e7;color:#cb511d;font-size:29px;font-weight:900}.error{background:#fff0ed;color:#a53620;border-radius:10px;padding:11px 13px;margin-bottom:15px}.hp{position:absolute;left:-10000px}.footer{text-align:center;color:#897d73;font-size:12px;line-height:1.6;padding:24px}
@media(max-width:620px){.shell{padding:12px 10px 35px}.brand{margin:14px 8px 20px}.hero{padding:30px 23px;border-radius:21px}.hero h1{font-size:35px}.hero p{font-size:16px}.grid{grid-template-columns:1fr}.card{padding:23px 19px;border-radius:19px}h2{font-size:24px}}
"""


def _page(body: str, title: str = "Письма Podslushano.nl") -> str:
    return f'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="index,follow"><title>{html.escape(title)}</title><style>{_CSS}</style></head><body><main class="shell"><div class="wrap"><div class="brand">Podslushano.nl</div>{body}
<div class="footer">Podslushano.nl · {html.escape(config.COMPANY_ADDRESS)}<br><a href="{html.escape(config.privacy_url(), quote=True)}">Конфиденциальность</a></div></div></main></body></html>'''


def _topics_form(selected: set[str]) -> str:
    descriptions = {
        "news": "Самое важное без пересказа всей новостной ленты",
        "events": "Куда сходить, билеты, даты и полезные ссылки",
        "useful": "Инструкции о жизни, работе и документах",
        "community": "Allo Walks, истории и новые проекты",
        "announcements": "Только действительно важные обновления",
    }
    return "".join(
        f'''<label class="choice"><input type="checkbox" name="topics" value="{key}" {'checked' if key in selected else ''}>
<span><b>{html.escape(label)}</b><small>{html.escape(descriptions[key])}</small></span></label>'''
        for key, label in TOPICS.items()
    )


def _frequency_form(selected: str) -> str:
    details = {
        "weekly": "По четвергам вечером: итоги недели и планы на выходные",
        "monthly": "Один большой выпуск в начале каждого месяца",
    }
    return "".join(
        f'''<label class="choice"><input type="radio" name="frequency" value="{key}" {'checked' if key == selected else ''} required>
<span><b>{html.escape(label)}</b><small>{html.escape(details[key])}</small></span></label>'''
        for key, label in FREQUENCIES.items()
    )


def _signup_page(error: str = "", email_value: str = "") -> str:
    error_html = f'<div class="error">{html.escape(error)}</div>' if error else ""
    body = f'''<section class="hero"><div class="kicker">Письмо от редакции</div><h1>Нидерланды без информационного шума</h1>
<p>Главное, полезное и интересное — в красивом письме, которое действительно хочется открыть.</p></section>
<div class="grid"><div class="promise"><b>1 письмо</b>в выбранном вами ритме</div><div class="promise"><b>Только польза</b>ссылки, даты и конкретика</div><div class="promise"><b>Без ловушек</b>настройки и отписка в один клик</div></div>
<section class="card"><h2>Настройте свою подборку</h2><p class="lead">Выберите частоту и темы. Адрес начнёт получать письма только после подтверждения.</p>{error_html}
<form method="post" action="/newsletter/subscribe"><label class="title" for="name">Как к вам обращаться <small>(необязательно)</small></label><input class="input" id="name" name="name" maxlength="120" autocomplete="name">
<label class="title" for="email">E-mail</label><input class="input" id="email" name="email" value="{html.escape(email_value, quote=True)}" maxlength="254" type="email" autocomplete="email" required>
<label class="title">Как часто</label><div class="choices">{_frequency_form('weekly')}</div>
<label class="title">Что включать</label><div class="choices">{_topics_form(set(DEFAULT_TOPICS))}</div>
<label class="hp">Не заполняйте<input name="website" tabindex="-1" autocomplete="off"></label>
<label class="consent"><input type="checkbox" name="consent" value="yes" required><span>Я согласен(на) получать выбранные редакционные письма Podslushano.nl. Согласие можно отозвать в любой момент. Подробнее — в <a href="{html.escape(config.privacy_url(), quote=True)}">политике конфиденциальности</a>.</span></label>
<button class="button" type="submit">Подписаться и подтвердить e-mail</button><div class="note">Мы не продаём адреса и не добавляем в рассылку без подтверждения.</div></form></section>'''
    return _page(body)


def _message_page(title: str, text: str, button: str = "", url: str = "") -> str:
    action = f'<a class="button" style="display:block;text-decoration:none" href="{html.escape(url, quote=True)}">{html.escape(button)}</a>' if button else ""
    return _page(f'<section class="card success"><div class="icon">✓</div><h2>{html.escape(title)}</h2><p class="lead">{html.escape(text)}</p>{action}</section>', title)


def _client_ip(request: web.Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For", "").split(",", 1)[0].strip()
    return forwarded or request.remote or "unknown"


def _rate_limited(ip: str) -> bool:
    now = time.monotonic()
    recent = [stamp for stamp in _attempts.get(ip, []) if now - stamp < 3600]
    recent.append(now)
    _attempts[ip] = recent
    return len(recent) > 5


async def page(request: web.Request) -> web.Response:
    return web.Response(text=_signup_page(), content_type="text/html")


async def subscribe(request: web.Request) -> web.Response:
    data = await request.post()
    email_value = normalize_email(data.get("email") or "")
    selected = {value for value in data.getall("topics", []) if value in TOPICS}
    frequency = (data.get("frequency") or "").strip()
    ip = _client_ip(request)
    if data.get("website"):
        return web.Response(text=_message_page("Проверьте почту", "Если адрес корректный, на него придёт письмо для подтверждения."), content_type="text/html")
    if _rate_limited(ip):
        return web.Response(text=_signup_page("Слишком много попыток. Попробуйте позже.", email_value), content_type="text/html", status=429)
    if not valid_email(email_value):
        return web.Response(text=_signup_page("Проверьте e-mail: похоже, в адресе есть ошибка.", email_value), content_type="text/html", status=400)
    if frequency not in FREQUENCIES or not selected or data.get("consent") != "yes":
        return web.Response(text=_signup_page("Выберите частоту, хотя бы одну тему и подтвердите согласие.", email_value), content_type="text/html", status=400)
    async with get_session() as session:
        subscriber = await session.scalar(select(NewsletterSubscriber).where(NewsletterSubscriber.email == email_value))
        if subscriber is not None and subscriber.status == "active":
            active_subscriber = subscriber
        else:
            active_subscriber = None
        if active_subscriber is not None:
            # Настройки нельзя менять, зная только чужой адрес. Ссылка управления
            # отправляется на сам подтверждённый e-mail.
            pass
        else:
            if subscriber is None:
                subscriber = NewsletterSubscriber(email=email_value, manage_token=new_token())
                session.add(subscriber)
            subscriber.name = (data.get("name") or "").strip()[:120] or None
            subscriber.frequency = frequency
            subscriber.topics_csv = topics_csv(selected)
            subscriber.consent_source = "newsletter-page"
            subscriber.consent_ip_hash = hash_ip(ip)
            subscriber.consent_at = datetime.utcnow()
            subscriber.status = "pending"
            subscriber.unsubscribed_at = None
            await session.commit()
            await session.refresh(subscriber)
    if active_subscriber is not None:
        await send_manage_link(active_subscriber)
        return web.Response(text=_message_page("Проверьте почту", "Если адрес уже подписан, мы отправили на него защищённую ссылку управления."), content_type="text/html")
    sent, error = await send_confirmation(subscriber)
    if not sent:
        return web.Response(
            text=_message_page(
                "Не удалось отправить письмо",
                "Адрес сохранён, но письмо подтверждения сейчас не отправилось. Попробуйте оформить подписку ещё раз немного позже.",
                "Вернуться к подписке", "/newsletter",
            ),
            content_type="text/html", status=503,
        )
    return web.Response(text=_message_page("Проверьте почту", "Мы отправили письмо со ссылкой подтверждения. До нажатия на неё рассылка не начнётся."), content_type="text/html")


async def confirm(request: web.Request) -> web.Response:
    token = request.match_info["token"]
    async with get_session() as session:
        subscriber = await session.scalar(select(NewsletterSubscriber).where(NewsletterSubscriber.manage_token == token))
        if subscriber is None:
            raise web.HTTPNotFound(text=_message_page("Ссылка недействительна", "Оформите подписку ещё раз."), content_type="text/html")
        subscriber.status = "active"
        subscriber.confirmed_at = datetime.utcnow()
        subscriber.unsubscribed_at = None
        await session.commit()
    return web.Response(text=_message_page("Подписка подтверждена", "Готово. Первое письмо придёт по выбранному расписанию.", "Настроить подборку", f"/newsletter/preferences/{token}"), content_type="text/html")


async def preferences(request: web.Request) -> web.Response:
    token = request.match_info["token"]
    async with get_session() as session:
        subscriber = await session.scalar(select(NewsletterSubscriber).where(NewsletterSubscriber.manage_token == token))
    if subscriber is None:
        raise web.HTTPNotFound()
    body = f'''<section class="card"><h2>Настройки писем</h2><p class="lead">{html.escape(subscriber.email)} · изменения применяются сразу.</p>
<form method="post"><label class="title">Как часто</label><div class="choices">{_frequency_form(subscriber.frequency)}</div>
<label class="title">Что включать</label><div class="choices">{_topics_form(topic_set(subscriber.topics_csv))}</div>
<button class="button" type="submit" style="margin-top:22px">Сохранить настройки</button></form>
<form method="post" action="/newsletter/unsubscribe-one-click/{html.escape(token, quote=True)}" style="margin-top:10px"><button class="button secondary" type="submit">Отписаться от всех писем</button></form></section>'''
    return web.Response(text=_page(body, "Настройки писем"), content_type="text/html")


async def save_preferences(request: web.Request) -> web.Response:
    token = request.match_info["token"]
    data = await request.post()
    selected = {value for value in data.getall("topics", []) if value in TOPICS}
    frequency = (data.get("frequency") or "").strip()
    if not selected or frequency not in FREQUENCIES:
        return web.Response(text=_message_page("Ничего не изменено", "Выберите хотя бы одну тему и частоту."), content_type="text/html", status=400)
    async with get_session() as session:
        subscriber = await session.scalar(select(NewsletterSubscriber).where(NewsletterSubscriber.manage_token == token))
        if subscriber is None:
            raise web.HTTPNotFound()
        subscriber.frequency = frequency
        subscriber.topics_csv = topics_csv(selected)
        await session.commit()
    return web.Response(text=_message_page("Настройки сохранены", "Следующее письмо будет собрано с учётом нового выбора.", "Вернуться к настройкам", f"/newsletter/preferences/{token}"), content_type="text/html")


async def unsubscribe_page(request: web.Request) -> web.Response:
    token = request.match_info["token"]
    async with get_session() as session:
        exists = await session.scalar(select(NewsletterSubscriber.id).where(NewsletterSubscriber.manage_token == token))
    if not exists:
        raise web.HTTPNotFound()
    body = f'''<section class="card success"><h2>Отписаться от писем?</h2><p class="lead">После подтверждения регулярные письма Podslushano.nl больше не будут приходить.</p>
<form method="post" action="/newsletter/unsubscribe-one-click/{html.escape(token, quote=True)}"><button class="button secondary" type="submit">Да, отписаться</button></form></section>'''
    return web.Response(text=_page(body, "Отписка"), content_type="text/html")


async def unsubscribe(request: web.Request) -> web.Response:
    token = request.match_info["token"]
    async with get_session() as session:
        subscriber = await session.scalar(select(NewsletterSubscriber).where(NewsletterSubscriber.manage_token == token))
        if subscriber is not None:
            subscriber.status = "unsubscribed"
            subscriber.unsubscribed_at = datetime.utcnow()
            await session.commit()
    return web.Response(text=_message_page("Вы отписаны", "Регулярные письма больше не будут приходить. Вернуться можно в любой момент через страницу подписки.", "Подписаться снова", "/newsletter"), content_type="text/html")


def register_routes(app: web.Application) -> None:
    app.router.add_get("/newsletter", page)
    app.router.add_post("/newsletter/subscribe", subscribe)
    app.router.add_get("/newsletter/confirm/{token}", confirm)
    app.router.add_get("/newsletter/preferences/{token}", preferences)
    app.router.add_post("/newsletter/preferences/{token}", save_preferences)
    app.router.add_get("/newsletter/unsubscribe/{token}", unsubscribe_page)
    app.router.add_post("/newsletter/unsubscribe-one-click/{token}", unsubscribe)
