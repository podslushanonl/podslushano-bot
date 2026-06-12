"""Платежи через Mollie (асинхронно, без блокировки бота).

Используем REST API Mollie напрямую через aiohttp. Создаём платёж, получаем
ссылку на оплату (checkout), а статус узнаём по webhook + проверке платежа.
"""
from __future__ import annotations

import logging

import aiohttp

import config

log = logging.getLogger(__name__)

MOLLIE_API = "https://api.mollie.com/v2"


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {config.MOLLIE_API_KEY}",
        "Content-Type": "application/json",
    }


async def create_payment(description: str, metadata: dict, amount: str) -> dict | None:
    """Создаёт платёж в Mollie на сумму amount. Возвращает id и ссылку на оплату.

    {"id": "tr_...", "checkout_url": "https://..."} или None при ошибке.
    """
    body = {
        "amount": {"currency": config.LISTING_CURRENCY, "value": amount},
        "description": description,
        "redirectUrl": (
            f"{config.WEBHOOK_BASE_URL}/thanks"
            if config.WEBHOOK_BASE_URL
            else (config.SITE_URL or "https://www.mollie.com")
        ),
        "webhookUrl": f"{config.WEBHOOK_BASE_URL}/mollie-webhook",
        "metadata": metadata,
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{MOLLIE_API}/payments", json=body, headers=_headers()
            ) as resp:
                data = await resp.json()
                if resp.status >= 300:
                    log.warning("Mollie create error %s: %s", resp.status, data)
                    return None
                checkout = data.get("_links", {}).get("checkout", {}).get("href")
                return {"id": data.get("id"), "checkout_url": checkout}
    except Exception as e:  # noqa: BLE001
        log.warning("Ошибка создания платежа Mollie: %s", e)
        return None


async def get_payment(payment_id: str) -> dict | None:
    """Возвращает данные платежа (в т.ч. status и metadata) или None."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{MOLLIE_API}/payments/{payment_id}", headers=_headers()
            ) as resp:
                if resp.status >= 300:
                    log.warning("Mollie get error %s", resp.status)
                    return None
                return await resp.json()
    except Exception as e:  # noqa: BLE001
        log.warning("Ошибка проверки платежа Mollie: %s", e)
        return None
