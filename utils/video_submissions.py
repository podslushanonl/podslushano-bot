"""Структурированные пользовательские видео и передача одобренных Reels в Make."""
from __future__ import annotations

import html
import json
import logging
import re
from typing import Any

import aiohttp

import config

log = logging.getLogger(__name__)

CONSENT_VERSION = "video-instagram-v1"
_IG_HANDLE_RE = re.compile(r"^[A-Za-z0-9._]{1,30}$")


def normalize_instagram(value: str) -> str | None:
    """Нормализует @username или ссылку Instagram до @username."""
    raw = (value or "").strip()
    raw = re.sub(r"^https?://(?:www\.)?instagram\.com/", "", raw, flags=re.I)
    raw = raw.split("?", 1)[0].strip("/@ ")
    if not _IG_HANDLE_RE.fullmatch(raw):
        return None
    return f"@{raw}"


def load_details(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def credit_text(details: dict[str, Any]) -> str:
    credit = details.get("credit") or {}
    value = str(credit.get("value") or "").strip()
    return value or "автор не указан"


def instagram_caption(details: dict[str, Any]) -> str:
    """Готовая подпись, которую админ получает вместе с видео."""
    context = str(details.get("context") or "").strip()
    credit = credit_text(details)
    parts = ["Нидерланды глазами наших подписчиков 🇳🇱"]
    if context:
        parts.extend(["", context])
    parts.extend([
        "",
        f"🎥 Автор: {credit}",
        "",
        "Тоже сняли что-то интересное в Нидерландах? Присылайте видео через нашего бота — ссылка в шапке профиля.",
    ])
    return "\n".join(parts)


def technical_summary(details: dict[str, Any]) -> str:
    media = details.get("media") or {}
    pieces: list[str] = []
    duration = media.get("duration")
    width, height = media.get("width"), media.get("height")
    size = media.get("file_size")
    if duration:
        pieces.append(f"{duration} сек.")
    if width and height:
        orientation = "вертикальное" if height > width else "горизонтальное"
        pieces.append(f"{width}×{height}, {orientation}")
    if size:
        pieces.append(f"{round(int(size) / 1024 / 1024, 1)} МБ")
    return " · ".join(pieces) or "параметры не определены"


def admin_caption(submission: Any) -> str:
    """Полная карточка видео для модерации; умещается в caption Telegram."""
    details = load_details(getattr(submission, "details", None))
    author = f"@{submission.username}" if submission.username else "без username"
    context = str(details.get("context") or submission.text or "—").strip()
    preview_details = dict(details)
    preview_details["context"] = context[:420]
    consent = details.get("consent") or {}
    status = {
        "pending": "🆕 На проверке",
        "approved": "🗂 В контент-банке",
        "published": "✅ Передано в публикацию",
        "rejected": "❌ Отклонено",
    }.get(getattr(submission, "status", "pending"), str(getattr(submission, "status", "—")))
    lines = [
        "<b>🎬 Новое видео подписчика</b>",
        f"🆔 Заявка №{submission.id}",
        f"👤 Telegram: {html.escape(author)} (id {submission.user_id})",
        f"🎥 Авторство: <b>{html.escape(credit_text(details))}</b>",
        f"📹 Файл: {html.escape(technical_summary(details))}",
        f"📌 Статус: {status}",
        "",
        "✅ Автор подтвердил права и разрешил монтаж и публикацию в Instagram "
        f"@podslushano.nl ({html.escape(str(consent.get('accepted_at') or 'дата не записана'))})",
        "",
        "<b>Готовая подпись:</b>",
        html.escape(instagram_caption(preview_details)),
    ]
    return "\n".join(lines)


def make_payload(submission: Any) -> dict[str, Any]:
    details = load_details(getattr(submission, "details", None))
    media = details.get("media") or {}
    credit = details.get("credit") or {}
    base_url = (config.WEBHOOK_BASE_URL or "").rstrip("/")
    media_url = (
        f"{base_url}/submission-video/{submission.media_token}"
        if base_url and getattr(submission, "media_token", None) else ""
    )
    return {
        "type": "user_reel",
        "source": "podslushano_telegram_bot",
        "submission_id": submission.id,
        "telegram_file_id": submission.file_id,
        "video_url": media_url,
        "telegram_user_id": submission.user_id,
        "telegram_username": submission.username or "",
        "caption": instagram_caption(details),
        "context": details.get("context") or submission.text or "",
        "credit": credit,
        "media": media,
        "consent": details.get("consent") or {},
        "submitted_at": submission.created_at.isoformat() if submission.created_at else "",
    }


def video_make_enabled() -> bool:
    return bool(config.VIDEO_MAKE_WEBHOOK_URL)


async def send_video_to_make(submission: Any) -> tuple[bool, str]:
    """Передаёт одобренное админом видео отдельному сценарию Make."""
    details = load_details(getattr(submission, "details", None))
    if not (details.get("consent") or {}).get("accepted"):
        return False, "у видео нет зафиксированного разрешения автора"
    if credit_text(details) == "автор не указан":
        return False, "не указано авторство"
    if not video_make_enabled():
        return False, "VIDEO_MAKE_WEBHOOK_URL не задан"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                config.VIDEO_MAKE_WEBHOOK_URL,
                json=make_payload(submission),
                timeout=aiohttp.ClientTimeout(total=30),
            ) as response:
                body = (await response.text())[:300]
                if response.status < 300:
                    return True, body
                log.warning("Video Make webhook HTTP %s: %s", response.status, body)
                return False, f"HTTP {response.status}: {body}"
    except Exception as exc:  # noqa: BLE001
        log.warning("Video Make webhook error: %s", exc)
        return False, str(exc)
