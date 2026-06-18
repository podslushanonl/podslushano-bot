"""Отправка данных в сценарии Make (Integromat) через вебхук.

Бот формирует контент (текст + реальные фото) и шлёт его JSON-ом на вебхук
Make, а уже Make рисует слайды по шаблону (Placid/Bannerbear/HTML-to-image) и
публикует Instagram-карусель. Нужна переменная MAKE_WEBHOOK_URL.
"""
import logging

import aiohttp

import config

log = logging.getLogger(__name__)


def make_enabled() -> bool:
    return bool(config.MAKE_WEBHOOK_URL)


async def send_to_make(payload: dict) -> bool:
    """POST JSON на вебхук Make. True — если приняли (HTTP 2xx)."""
    if not make_enabled():
        return False
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                config.MAKE_WEBHOOK_URL,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as r:
                ok = r.status < 300
                if not ok:
                    body = (await r.text())[:300]
                    log.warning("Make webhook HTTP %s: %s", r.status, body)
                return ok
    except Exception as e:  # noqa: BLE001
        log.warning("Make webhook error: %s", e)
        return False
