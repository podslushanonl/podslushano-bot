"""Подбор реального тематического фото из фотостока (Pexels / Unsplash).

Используется для картинок к постам в канал (/post). Нужен один бесплатный
API-ключ: PEXELS_API_KEY (проще) или UNSPLASH_ACCESS_KEY. Возвращает URL
картинки (Telegram сам её скачает при send_photo) или None.
"""
import logging

import aiohttp

import config

log = logging.getLogger(__name__)


def stock_enabled() -> bool:
    return bool(config.PEXELS_API_KEY or config.UNSPLASH_ACCESS_KEY)


async def fetch_stock_photo(query: str) -> str | None:
    """URL подходящего фото по запросу (англ. ключевые слова) или None."""
    query = (query or "").strip()
    if not query:
        return None
    if config.PEXELS_API_KEY:
        url = await _pexels(query)
        if url:
            return url
    if config.UNSPLASH_ACCESS_KEY:
        return await _unsplash(query)
    return None


async def _pexels(query: str) -> str | None:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://api.pexels.com/v1/search",
                params={"query": query, "per_page": "1", "orientation": "landscape"},
                headers={"Authorization": config.PEXELS_API_KEY},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as r:
                if r.status >= 300:
                    log.warning("Pexels HTTP %s", r.status)
                    return None
                data = await r.json()
        photos = data.get("photos") or []
        if not photos:
            return None
        src = photos[0].get("src") or {}
        return src.get("large") or src.get("original") or src.get("medium")
    except Exception as e:  # noqa: BLE001
        log.warning("Pexels error: %s", e)
        return None


async def _unsplash(query: str) -> str | None:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://api.unsplash.com/search/photos",
                params={"query": query, "per_page": "1", "orientation": "landscape"},
                headers={"Authorization": f"Client-ID {config.UNSPLASH_ACCESS_KEY}"},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as r:
                if r.status >= 300:
                    log.warning("Unsplash HTTP %s", r.status)
                    return None
                data = await r.json()
        results = data.get("results") or []
        if not results:
            return None
        urls = results[0].get("urls") or {}
        return urls.get("regular") or urls.get("full") or urls.get("small")
    except Exception as e:  # noqa: BLE001
        log.warning("Unsplash error: %s", e)
        return None
