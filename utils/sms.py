"""Доставка кода входа SMS-сообщением на номер телефона.

Канал — Twilio (twilio.com). Включается переменными в Railway:
TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN и TWILIO_FROM — отправитель: номер Twilio (+31…) или имя
до 11 латинских букв (например, podslushano; в Нидерландах, Германии и Бельгии имя работает без регистрации).
OTP_DEBUG=1 — без отправки, код пишется в лог сервера (только для теста, не включать в бою).
"""
from __future__ import annotations

import logging
import os

import aiohttp

log = logging.getLogger(__name__)

API = "https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"


def _creds() -> tuple[str, str, str]:
    return (os.getenv("TWILIO_ACCOUNT_SID", "").strip(), os.getenv("TWILIO_AUTH_TOKEN", "").strip(),
            os.getenv("TWILIO_FROM", "").strip())


def _debug() -> bool:
    return os.getenv("OTP_DEBUG", "").strip() == "1"


def available() -> bool:
    """Можно ли сейчас входить по номеру телефона."""
    return all(_creds()) or _debug()


def text(code: str) -> str:
    return f"podslushano.nl: ваш код для входа {code}. Никому его не сообщайте."


async def send_code(phone: str, code: str, ttl_min: int) -> bool:
    sid, token, sender = _creds()
    if not (sid and token and sender):
        if _debug():
            log.warning("OTP_DEBUG: код входа для %s — %s", phone, code)
            return True
        return False
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as s:
            async with s.post(API.format(sid=sid), auth=aiohttp.BasicAuth(sid, token),
                              data={"To": phone, "From": sender, "Body": text(code)}) as r:
                data = await r.json(content_type=None)
                ok = r.status < 300
    except Exception:
        log.exception("SMS: сбой отправки кода")
        return False
    if not ok:
        log.warning("SMS: код не отправлен: %s %s", data.get("code"), data.get("message"))
        return False
    return True
