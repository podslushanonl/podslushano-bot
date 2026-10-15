"""Доставка кода входа на номер телефона.

Канал — Telegram Gateway (gateway.telegram.org): код приходит в Telegram на аккаунт с этим номером,
стоит ~0,01 $ за код. Включается переменной TELEGRAM_GATEWAY_TOKEN (задаётся в Railway).
OTP_DEBUG=1 — без отправки, код пишется в лог сервера (только для теста, не включать в бою).
"""
from __future__ import annotations

import logging
import os

import aiohttp

log = logging.getLogger(__name__)

GATEWAY_URL = "https://gatewayapi.telegram.org/sendVerificationMessage"


def _token() -> str:
    return os.getenv("TELEGRAM_GATEWAY_TOKEN", "").strip()


def _debug() -> bool:
    return os.getenv("OTP_DEBUG", "").strip() == "1"


def available() -> bool:
    """Можно ли сейчас входить по номеру телефона."""
    return bool(_token()) or _debug()


async def send_code(phone: str, code: str, ttl_min: int) -> bool:
    token = _token()
    if not token:
        if _debug():
            log.warning("OTP_DEBUG: код входа для %s — %s", phone, code)
            return True
        return False
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as s:
            async with s.post(GATEWAY_URL, headers={"Authorization": f"Bearer {token}"},
                              json={"phone_number": phone, "code": code, "ttl": ttl_min * 60}) as r:
                data = await r.json(content_type=None)
    except Exception:
        log.exception("Telegram Gateway: сбой отправки кода")
        return False
    if not data.get("ok"):
        log.warning("Telegram Gateway: код не отправлен: %s", data.get("error"))
        return False
    return True
