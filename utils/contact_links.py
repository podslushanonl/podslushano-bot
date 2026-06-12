"""Разбор строки контакта на типовые ссылки (для кнопок в боте и для сайта).

Возвращает список ссылок [{"type", "label", "url"}]. В Telegram-кнопках можно
использовать только http/https (instagram, telegram, website, whatsapp), а на
сайте — все, включая tel: и mailto:.
"""
import re

_IG_RE = re.compile(r"(?:instagram|инстаграм)\b[:\s]*@?([A-Za-z0-9_.]+)", re.I)
_IG_URL_RE = re.compile(r"instagram\.com/([A-Za-z0-9_.]+)", re.I)
_TG_RE = re.compile(r"(?:telegram|телеграм|tg)\b[:\s]*@?([A-Za-z0-9_]{3,})", re.I)
_TG_URL_RE = re.compile(r"t\.me/([A-Za-z0-9_]+)", re.I)
_URL_RE = re.compile(r"https?://[^\s,)]+", re.I)
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"(\+?\d[\d\s\-]{7,}\d)")

# Типы, которые допустимы в inline-кнопках Telegram (только http/https)
TELEGRAM_TYPES = {"instagram", "telegram", "website", "whatsapp"}


def _normalize_phone(raw: str) -> str | None:
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("00"):
        digits = digits[2:]
    elif digits.startswith("0"):
        digits = "31" + digits[1:]  # NL: 06… → 316…
    return digits if 8 <= len(digits) <= 15 else None


def parse_contact_links(contact: str | None) -> list[dict]:
    """Разбирает строку контакта на ссылки. Каждая — {type, label, url}."""
    if not contact:
        return []
    links: list[dict] = []

    m = _IG_RE.search(contact) or _IG_URL_RE.search(contact)
    if m:
        handle = m.group(1).strip(".")
        links.append({"type": "instagram", "label": "📷 Instagram",
                      "url": f"https://instagram.com/{handle}"})

    m = _TG_RE.search(contact) or _TG_URL_RE.search(contact)
    if m:
        links.append({"type": "telegram", "label": "✈️ Telegram",
                      "url": f"https://t.me/{m.group(1)}"})

    for um in _URL_RE.finditer(contact):
        url = um.group(0)
        if "instagram.com" in url or "t.me/" in url:
            continue
        links.append({"type": "website", "label": "🌐 Сайт", "url": url})
        break

    pm = _PHONE_RE.search(contact)
    if pm:
        digits = _normalize_phone(pm.group(1))
        if digits:
            links.append({"type": "whatsapp", "label": "💬 WhatsApp",
                          "url": f"https://wa.me/{digits}"})
            links.append({"type": "phone", "label": "📞 Позвонить",
                          "url": f"tel:+{digits}"})

    em = _EMAIL_RE.search(contact)
    if em:
        links.append({"type": "email", "label": "✉️ Email",
                      "url": f"mailto:{em.group(0)}"})

    return links
