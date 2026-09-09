"""Редакционная e-mail рассылка Podslushano.nl.

Один подписчик выбирает одну частоту (weekly или monthly) и нужные темы. Выпуск
собирается из опубликованных материалов сайта и будущих событий в базе бота.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import html
import logging
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

import aiohttp
from sqlalchemy import func, select

import config
from database.db import get_session
from database.models import (
    DiscoveredEvent,
    EventListing,
    NewsletterDeliveryLog,
    NewsletterSubscriber,
)
from utils.invoices import send_email_message

log = logging.getLogger(__name__)
_INTERVAL_SECONDS = 15 * 60
TOPICS = {
    "news": "Главное в Нидерландах",
    "events": "Афиша и мероприятия",
    "useful": "Полезное и гайды",
    "community": "Проекты сообщества",
    "announcements": "Важные анонсы",
}
DEFAULT_TOPICS = tuple(TOPICS)
FREQUENCIES = {"weekly": "Раз в неделю", "monthly": "Раз в месяц"}
_MONTHS = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)


@dataclass(frozen=True)
class NewsletterItem:
    topic: str
    title: str
    description: str
    url: str
    image_url: str = ""
    meta: str = ""


@dataclass(frozen=True)
class NewsletterContent:
    frequency: str
    campaign_key: str
    subject: str
    preheader: str
    items: tuple[NewsletterItem, ...]


def normalize_email(value: str) -> str:
    return (value or "").strip().casefold()


def valid_email(value: str) -> bool:
    email_value = normalize_email(value)
    return bool(
        len(email_value) <= 254
        and re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email_value)
    )


def topic_set(csv: str | None) -> set[str]:
    return {item for item in (csv or "").split(",") if item in TOPICS}


def topics_csv(items: Iterable[str]) -> str:
    selected = set(items)
    return ",".join(key for key in TOPICS if key in selected)


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_ip(ip: str) -> str:
    # Хэш нужен только для антиспам-аудита; исходный IP не сохраняется.
    salt = config.BOT_TOKEN[-16:] or "podslushano-newsletter"
    return hashlib.sha256(f"{salt}:{ip}".encode()).hexdigest()


def _plain(value: str, limit: int = 260) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", value or ""))
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(".,:;—-") + "…"


def _utm(url: str, campaign_key: str) -> str:
    if not url.startswith(("https://", "http://")):
        return url
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update({
        "utm_source": "podslushano_newsletter",
        "utm_medium": "email",
        "utm_campaign": campaign_key.replace(":", "_"),
    })
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _topic_for_post(title: str, excerpt: str, categories: list[str]) -> str:
    haystack = " ".join([title, excerpt, *categories]).casefold()
    if any(x in haystack for x in ("афиш", "мероприят", "фестив", "концерт", "куда сход")):
        return "events"
    if any(x in haystack for x in ("гайд", "полез", "инструкц", "как ", "налог", "документ", "работ", "жиль")):
        return "useful"
    if any(x in haystack for x in ("allo", "истори", "сообществ", "подписчик", "проект")):
        return "community"
    if any(x in haystack for x in ("анонс", "объявляем", "запуск", "важно")):
        return "announcements"
    return "news"


async def _wordpress_items(since: datetime, limit: int = 24) -> list[NewsletterItem]:
    base = (config.WP_URL or config.SITE_URL).rstrip("/")
    if not base:
        return []
    url = f"{base}/wp-json/wp/v2/posts"
    params = {
        "status": "publish", "per_page": str(limit), "_embed": "1",
        "_fields": "date,link,title,excerpt,_embedded",
    }
    headers = {
        "Accept": "application/json",
        "User-Agent": "Podslushano.nl newsletter/1.0",
    }
    if config.WP_USER and config.WP_APP_PASSWORD:
        raw = f"{config.WP_USER}:{config.WP_APP_PASSWORD.replace(' ', '')}"
        headers["Authorization"] = "Basic " + base64.b64encode(raw.encode()).decode()
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, params=params, headers=headers,
                ssl=None if config.WP_VERIFY_SSL else False,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as response:
                if response.status != 200:
                    log.warning("Не удалось получить материалы для рассылки: HTTP %s", response.status)
                    return []
                rows = await response.json()
    except Exception as exc:  # noqa: BLE001
        log.warning("Не удалось получить материалы для рассылки: %s", exc)
        return []

    result: list[NewsletterItem] = []
    for row in rows if isinstance(rows, list) else []:
        try:
            published_at = datetime.fromisoformat((row.get("date") or "").replace("Z", "+00:00"))
            if published_at.tzinfo is not None:
                published_at = published_at.replace(tzinfo=None)
        except (TypeError, ValueError):
            continue
        if published_at < since:
            continue
        title = _plain((row.get("title") or {}).get("rendered", ""), 120)
        excerpt = _plain((row.get("excerpt") or {}).get("rendered", ""), 220)
        link = (row.get("link") or "").strip()
        if not title or not link:
            continue
        embedded = row.get("_embedded") or {}
        media = (embedded.get("wp:featuredmedia") or [{}])[0] or {}
        image_url = (media.get("source_url") or "").strip()
        terms = embedded.get("wp:term") or []
        category_names = [
            item.get("name", "") for group in terms for item in (group or [])
            if isinstance(item, dict)
        ]
        result.append(NewsletterItem(
            topic=_topic_for_post(title, excerpt, category_names),
            title=title,
            description=excerpt or "Читайте подробности на Podslushano.nl.",
            url=link,
            image_url=image_url,
            meta=f"Podslushano.nl · {published_at:%d.%m}",
        ))
    return result


async def _event_items(until: datetime, limit: int = 8) -> list[NewsletterItem]:
    now = datetime.utcnow()
    result: list[NewsletterItem] = []
    async with get_session() as session:
        discovered = list((await session.scalars(
            select(DiscoveredEvent).where(
                DiscoveredEvent.expires_at > now,
                DiscoveredEvent.starts_at.is_not(None),
                DiscoveredEvent.starts_at <= until,
            ).order_by(DiscoveredEvent.starts_at).limit(limit * 3)
        )).all())
        manual = list((await session.scalars(
            select(EventListing).where(
                EventListing.status == "approved",
                EventListing.link.is_not(None),
                EventListing.starts_at.is_not(None),
                EventListing.starts_at <= until,
            ).order_by(EventListing.starts_at, EventListing.id.desc()).limit(limit)
        )).all())
    seen: set[str] = set()
    for item in discovered:
        if item.ends_at and item.ends_at < now:
            continue
        if item.ends_at is None and item.starts_at and item.starts_at < now - timedelta(hours=6):
            continue
        link = (item.ticket_url or item.link or "").strip()
        if not link or link in seen:
            continue
        seen.add(link)
        date_label = item.event_date or (
            item.starts_at.strftime("%d.%m") if item.starts_at else ""
        )
        place = " · ".join(x for x in (date_label, item.city or item.venue) if x)
        result.append(NewsletterItem(
            topic="events", title=_plain(item.title, 120),
            description=_plain(item.description, 210), url=link,
            image_url=(item.photo_url or "").strip(), meta=place,
        ))
        if len(result) >= limit:
            return result
    for item in manual:
        link = (item.link or "").strip()
        if not link or link in seen:
            continue
        if item.ends_at and item.ends_at < now:
            continue
        if item.ends_at is None and item.starts_at and item.starts_at < now - timedelta(hours=6):
            continue
        seen.add(link)
        result.append(NewsletterItem(
            topic="events", title=_plain(item.title, 120),
            description=_plain(item.description or "", 210), url=link,
            meta=" · ".join(x for x in (item.event_date or "", item.city) if x),
        ))
        if len(result) >= limit:
            break
    return result


def _campaign_identity(frequency: str, now: datetime) -> tuple[str, str, str]:
    if frequency == "monthly":
        key = f"newsletter:monthly:{now:%Y-%m}"
        subject = f"Что важно в Нидерландах в {_MONTHS[now.month - 1]} · Podslushano.nl"
        preheader = "Главное, полезное и события месяца — в одном спокойном письме."
    else:
        year, week, _ = now.isocalendar()
        key = f"newsletter:weekly:{year}-W{week:02d}"
        subject = f"Неделя в Нидерландах + планы на выходные · {now:%d.%m}"
        preheader = "Главное за неделю, полезные материалы и события — коротко и по делу."
    return key, subject, preheader


async def build_content(frequency: str, now: datetime | None = None) -> NewsletterContent:
    current = now or datetime.now(ZoneInfo("Europe/Amsterdam"))
    key, subject, preheader = _campaign_identity(frequency, current)
    local_naive = current.replace(tzinfo=None)
    lookback = timedelta(days=35 if frequency == "monthly" else 8)
    horizon = timedelta(days=40 if frequency == "monthly" else 10)
    posts, events = await asyncio.gather(
        _wordpress_items(local_naive - lookback),
        _event_items(datetime.utcnow() + horizon),
    )
    # В афише используем ближайшие события из базы; дубли постов с афишей не добавляем.
    items = [item for item in posts if item.topic != "events"] + events
    if not any(item.topic == "useful" for item in items) and config.GUIDE_URL:
        items.append(NewsletterItem(
            topic="useful", title="Проверенные контакты в Нидерландах",
            description="Каталог русскоязычных специалистов и полезных сервисов по городам.",
            url=config.GUIDE_URL, meta="Гайд Podslushano.nl",
        ))
    return NewsletterContent(frequency, key, subject, preheader, tuple(items))


def _selected_items(content: NewsletterContent, topics: set[str]) -> list[NewsletterItem]:
    limits = {
        "weekly": {"news": 2, "events": 3, "useful": 2, "community": 1, "announcements": 1},
        "monthly": {"news": 3, "events": 5, "useful": 3, "community": 2, "announcements": 2},
    }[content.frequency]
    selected: list[NewsletterItem] = []
    for topic in TOPICS:
        if topic not in topics:
            continue
        selected.extend([x for x in content.items if x.topic == topic][:limits[topic]])
    return selected


def render_email(
    subscriber: NewsletterSubscriber,
    content: NewsletterContent,
) -> tuple[str, str]:
    topics = topic_set(subscriber.topics_csv) or set(DEFAULT_TOPICS)
    selected = _selected_items(content, topics)
    base = (config.WEBHOOK_BASE_URL or config.SITE_URL).rstrip("/")
    manage = f"{base}/newsletter/preferences/{subscriber.manage_token}"
    unsubscribe = f"{base}/newsletter/unsubscribe/{subscriber.manage_token}"
    if subscriber.manage_token == "preview-only":
        manage = unsubscribe = config.newsletter_url()
    logo = html.escape(config.LOGO_URL, quote=True) if config.LOGO_URL else ""
    name = _plain(subscriber.name or "", 80)
    greeting = f"Здравствуйте, {html.escape(name)}!" if name else "Здравствуйте!"
    grouped: dict[str, list[NewsletterItem]] = {key: [] for key in TOPICS}
    for item in selected:
        grouped[item.topic].append(item)
    sections: list[str] = []
    text_sections: list[str] = []
    for topic, label in TOPICS.items():
        rows = grouped[topic]
        if not rows:
            continue
        cards: list[str] = []
        text_rows: list[str] = []
        for item in rows:
            url = html.escape(_utm(item.url, content.campaign_key), quote=True)
            image = ""
            if item.image_url.startswith(("https://", "http://")):
                image = (
                    f'<a href="{url}" style="text-decoration:none">'
                    f'<img src="{html.escape(item.image_url, quote=True)}" alt="" width="560" '
                    'style="display:block;width:100%;max-height:310px;object-fit:cover;border-radius:16px 16px 0 0"></a>'
                )
            meta = (
                f'<div style="color:#c75a17;font-size:13px;font-weight:700;margin-bottom:7px">{html.escape(item.meta)}</div>'
                if item.meta else ""
            )
            cards.append(
                '<div style="margin:0 0 18px;background:#fff;border:1px solid #eadfd3;border-radius:16px;overflow:hidden">'
                f'{image}<div style="padding:20px 20px 22px">{meta}'
                f'<a href="{url}" style="color:#171411;text-decoration:none;font-size:21px;line-height:1.25;font-weight:800">{html.escape(item.title)}</a>'
                f'<p style="margin:10px 0 16px;color:#5c554f;font-size:15px;line-height:1.55">{html.escape(item.description)}</p>'
                f'<a href="{url}" style="display:inline-block;background:#ef6c2f;color:#fff;text-decoration:none;padding:11px 16px;border-radius:10px;font-size:14px;font-weight:750">Открыть →</a>'
                '</div></div>'
            )
            text_rows.append(f"• {item.title}\n{item.description}\n{_utm(item.url, content.campaign_key)}")
        sections.append(
            f'<h2 style="margin:32px 0 14px;color:#171411;font-size:23px;line-height:1.25">{html.escape(label)}</h2>'
            + "".join(cards)
        )
        text_sections.append(f"{label}\n" + "\n\n".join(text_rows))
    empty_note = ""
    if not sections:
        empty_note = (
            '<div style="padding:20px;background:#fff;border-radius:16px">'
            'В выбранных темах пока нет новых материалов. Мы не заполняем письма '
            'случайным контентом — следующий выпуск придёт по вашему расписанию.'
            '</div>'
        )
    logo_html = (
        f'<img src="{logo}" alt="Podslushano.nl" width="168" style="display:block;max-width:168px;height:auto">'
        if logo else '<div style="font-size:23px;font-weight:850">Podslushano.nl</div>'
    )
    html_body = f'''<!doctype html><html lang="ru"><body style="margin:0;background:#f4eee7;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;color:#171411">
<div style="display:none;max-height:0;overflow:hidden;opacity:0">{html.escape(content.preheader)}</div>
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f4eee7"><tr><td align="center" style="padding:24px 12px">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:620px"><tr><td>
<div style="background:#1e1a17;color:#fff;padding:26px 28px;border-radius:20px 20px 0 0">{logo_html}
<div style="margin-top:28px;color:#ffb07c;font-size:13px;font-weight:800;letter-spacing:.08em;text-transform:uppercase">Письмо от редакции</div>
<h1 style="margin:8px 0 10px;font-size:31px;line-height:1.15;color:#fff">{html.escape(content.subject.split(' · ')[0])}</h1>
<p style="margin:0;color:#d9d0c9;font-size:16px;line-height:1.5">{html.escape(content.preheader)}</p></div>
<div style="padding:26px 28px 10px"><p style="font-size:16px;line-height:1.55;margin:0 0 8px">{greeting}</p>
<p style="font-size:16px;line-height:1.55;margin:0;color:#5c554f">Мы отобрали то, что действительно стоит открыть. Без бесконечной ленты и повторов.</p>
{''.join(sections)}{empty_note}
<div style="margin:30px 0 18px;padding:22px;background:#ef6c2f;border-radius:16px;color:#fff">
<div style="font-size:20px;font-weight:800;margin-bottom:7px">Хотите больше?</div>
<div style="font-size:15px;line-height:1.5;margin-bottom:15px">Новости, афиша и полезные материалы появляются на сайте и в Telegram раньше следующего письма.</div>
<a href="{html.escape(config.SITE_URL, quote=True)}" style="display:inline-block;background:#fff;color:#b54412;text-decoration:none;padding:11px 16px;border-radius:10px;font-weight:800">Открыть Podslushano.nl →</a></div>
<div style="border-top:1px solid #ded2c6;padding:18px 0 28px;color:#756d66;font-size:12px;line-height:1.6">
Вы получили это письмо, потому что подтвердили подписку Podslushano.nl.<br>
<a href="{html.escape(manage, quote=True)}" style="color:#8b481f">Настроить темы и частоту</a> ·
<a href="{html.escape(unsubscribe, quote=True)}" style="color:#8b481f">Отписаться</a><br>
{html.escape(config.COMPANY_NAME)} · {html.escape(config.COMPANY_ADDRESS)}</div>
</div></td></tr></table></td></tr></table></body></html>'''
    text_body = (
        f"{greeting}\n\n{content.preheader}\n\n"
        + "\n\n---\n\n".join(text_sections)
        + f"\n\nPodslushano.nl: {config.SITE_URL}\n"
          f"Настройки: {manage}\nОтписаться: {unsubscribe}"
    )
    return html_body, text_body


def _simple_email(title: str, body: str, button: str, url: str) -> tuple[str, str]:
    safe_url = html.escape(url, quote=True)
    html_body = f'''<!doctype html><html lang="ru"><body style="margin:0;background:#f4eee7;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0"><tr><td align="center" style="padding:28px 12px"><div style="max-width:560px;background:#fff;border-radius:20px;overflow:hidden">
<div style="background:#1e1a17;color:#fff;padding:28px"><div style="color:#ffb07c;font-weight:800">Podslushano.nl</div><h1 style="font-size:28px;line-height:1.2;margin:16px 0 0">{html.escape(title)}</h1></div>
<div style="padding:28px;color:#514a44;font-size:16px;line-height:1.6"><p>{html.escape(body)}</p><a href="{safe_url}" style="display:inline-block;margin-top:8px;background:#ef6c2f;color:#fff;text-decoration:none;padding:13px 18px;border-radius:10px;font-weight:800">{html.escape(button)}</a>
<p style="margin-top:28px;color:#8a8179;font-size:12px">Если вы не оформляли подписку, просто не нажимайте кнопку — письма приходить не будут.</p></div></div></td></tr></table></body></html>'''
    return html_body, f"{title}\n\n{body}\n\n{button}: {url}"


async def send_confirmation(subscriber: NewsletterSubscriber) -> tuple[bool, str]:
    base = (config.WEBHOOK_BASE_URL or config.SITE_URL).rstrip("/")
    url = f"{base}/newsletter/confirm/{subscriber.manage_token}"
    body = "Подтвердите адрес, чтобы получать выбранную подборку. Без подтверждения мы ничего не отправим."
    html_body, text_body = _simple_email("Подтвердите подписку", body, "Подтвердить e-mail", url)
    return await send_email_message(
        subscriber.email, "Подтвердите подписку на Podslushano.nl",
        html_body, text_body, from_email=config.NEWSLETTER_FROM_EMAIL,
    )


async def send_manage_link(subscriber: NewsletterSubscriber) -> tuple[bool, str]:
    base = (config.WEBHOOK_BASE_URL or config.SITE_URL).rstrip("/")
    url = f"{base}/newsletter/preferences/{subscriber.manage_token}"
    body = "По этому защищённому переходу можно изменить темы, частоту или полностью отключить письма."
    html_body, text_body = _simple_email(
        "Управление подпиской", body, "Открыть настройки", url
    )
    return await send_email_message(
        subscriber.email, "Настройки писем Podslushano.nl",
        html_body, text_body, from_email=config.NEWSLETTER_FROM_EMAIL,
    )


async def campaign_stats() -> dict[str, int]:
    async with get_session() as session:
        rows = (await session.execute(
            select(NewsletterSubscriber.status, NewsletterSubscriber.frequency, func.count())
            .group_by(NewsletterSubscriber.status, NewsletterSubscriber.frequency)
        )).all()
    result = {"active_weekly": 0, "active_monthly": 0, "pending": 0, "unsubscribed": 0}
    for status, frequency, count in rows:
        key = f"active_{frequency}" if status == "active" else status
        result[key] = result.get(key, 0) + int(count)
    return result


async def send_campaign(frequency: str, now: datetime | None = None) -> dict[str, int | str]:
    if frequency not in FREQUENCIES:
        raise ValueError("frequency must be weekly or monthly")
    content = await build_content(frequency, now)
    current = datetime.utcnow()
    async with get_session() as session:
        subscribers = list((await session.scalars(
            select(NewsletterSubscriber).where(
                NewsletterSubscriber.status == "active",
                NewsletterSubscriber.frequency == frequency,
            ).order_by(NewsletterSubscriber.id)
        )).all())
    stats: dict[str, int | str] = {
        "campaign_key": content.campaign_key, "recipients": len(subscribers),
        "sent": 0, "failed": 0, "skipped": 0,
    }
    for subscriber in subscribers:
        async with get_session() as session:
            row = await session.scalar(select(NewsletterDeliveryLog).where(
                NewsletterDeliveryLog.subscriber_id == subscriber.id,
                NewsletterDeliveryLog.campaign_key == content.campaign_key,
            ))
            if row and row.status in {"sent", "skipped"}:
                stats["skipped"] = int(stats["skipped"]) + 1
                continue
            if row and row.updated_at and (current - row.updated_at).total_seconds() < 6 * 3600:
                stats["skipped"] = int(stats["skipped"]) + 1
                continue
        if not _selected_items(content, topic_set(subscriber.topics_csv)):
            stats["skipped"] = int(stats["skipped"]) + 1
            continue
        html_body, text_body = render_email(subscriber, content)
        base = (config.WEBHOOK_BASE_URL or config.SITE_URL).rstrip("/")
        one_click = f"{base}/newsletter/unsubscribe-one-click/{subscriber.manage_token}"
        ok, error = await send_email_message(
            subscriber.email, content.subject, html_body, text_body,
            extra_headers={
                "List-Unsubscribe": f"<{one_click}>",
                "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
            },
            from_email=config.NEWSLETTER_FROM_EMAIL,
        )
        async with get_session() as session:
            row = await session.scalar(select(NewsletterDeliveryLog).where(
                NewsletterDeliveryLog.subscriber_id == subscriber.id,
                NewsletterDeliveryLog.campaign_key == content.campaign_key,
            ))
            if row is None:
                row = NewsletterDeliveryLog(
                    subscriber_id=subscriber.id, campaign_key=content.campaign_key,
                    frequency=frequency, subject=content.subject, status="sent" if ok else "failed",
                    error_text=error or None,
                )
                session.add(row)
            else:
                row.status = "sent" if ok else "failed"
                row.error_text = error or None
            if ok:
                saved = await session.get(NewsletterSubscriber, subscriber.id)
                if saved:
                    saved.last_sent_at = current
            await session.commit()
        stats["sent" if ok else "failed"] = int(stats["sent" if ok else "failed"]) + 1
        await asyncio.sleep(0.08)
    return stats


def _scheduled_frequencies(now: datetime) -> list[str]:
    due: list[str] = []
    if (
        now.day == config.NEWSLETTER_MONTHLY_DAY
        and now.hour >= config.NEWSLETTER_MONTHLY_HOUR
    ):
        due.append("monthly")
    if (
        now.weekday() == config.NEWSLETTER_WEEKLY_WEEKDAY
        and now.hour >= config.NEWSLETTER_WEEKLY_HOUR
    ):
        due.append("weekly")
    return due


async def newsletter_loop(bot) -> None:
    await asyncio.sleep(45)
    while True:
        try:
            now = datetime.now(ZoneInfo("Europe/Amsterdam"))
            frequencies = _scheduled_frequencies(now) if config.NEWSLETTER_AUTO_SEND else []
            for frequency in frequencies:
                result = await send_campaign(frequency, now)
                if int(result["sent"]) or int(result["failed"]):
                    text = (
                        f"✉️ <b>E-mail рассылка: {frequency}</b>\n\n"
                        f"Отправлено: {result['sent']}\nОшибок: {result['failed']}\n"
                        f"Уже было отправлено: {result['skipped']}"
                    )
                    for admin_id in config.ADMIN_IDS:
                        try:
                            await bot.send_message(admin_id, text)
                        except Exception:  # noqa: BLE001
                            pass
        except Exception as exc:  # noqa: BLE001
            log.exception("Ошибка цикла e-mail рассылки: %s", exc)
        await asyncio.sleep(_INTERVAL_SECONDS)
