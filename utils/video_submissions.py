"""Структурированные пользовательские видео для ручного отбора редакцией."""
from __future__ import annotations

import html
import json
import re
from typing import Any

CONSENT_VERSION = "video-instagram-v1"
MAX_ORIGINAL_VIDEO_BYTES = 200 * 1024 * 1024
_VIDEO_EXTENSIONS = (".mp4", ".mov", ".m4v", ".webm")
_IG_HANDLE_RE = re.compile(r"^[A-Za-z0-9._]{1,30}$")


def normalize_instagram(value: str) -> str | None:
    """Нормализует @username или ссылку Instagram до @username."""
    raw = (value or "").strip()
    raw = re.sub(r"^https?://(?:www\.)?instagram\.com/", "", raw, flags=re.I)
    raw = raw.split("?", 1)[0].strip("/@ ")
    if not _IG_HANDLE_RE.fullmatch(raw):
        return None
    return f"@{raw}"


def is_video_document(document: Any) -> bool:
    """Принимаем только видео, отправленное документом без сжатия Telegram."""
    if document is None:
        return False
    mime_type = str(getattr(document, "mime_type", "") or "").lower()
    file_name = str(getattr(document, "file_name", "") or "").lower()
    return mime_type.startswith("video/") or file_name.endswith(_VIDEO_EXTENSIONS)


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
        "published": "✅ Опубликовано",
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
