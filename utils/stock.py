"""Подбор реального тематического фото из фотостока (Pexels / Unsplash).

Используется для картинок к постам в канал (/post) и слайдам Instagram-каруселей
(/ig). Нужен один бесплатный API-ключ: PEXELS_API_KEY (проще) или
UNSPLASH_ACCESS_KEY. Возвращает URL картинки или None.
"""
import logging

import aiohttp

import config

log = logging.getLogger(__name__)


def stock_enabled() -> bool:
    return bool(config.PEXELS_API_KEY or config.UNSPLASH_ACCESS_KEY)


async def fetch_stock_candidates(query: str, orientation: str = "landscape",
                                 n: int = 8) -> list[str]:
    """Список URL фото по запросу, в порядке РЕЛЕВАНТНОСТИ (для выбора/дедупа)."""
    query = (query or "").strip()
    if not query:
        return []
    urls: list[str] = []
    if config.PEXELS_API_KEY:
        urls += await _pexels_list(query, orientation, n)
    if len(urls) < n and config.UNSPLASH_ACCESS_KEY:
        urls += await _unsplash_list(query, orientation, n)
    seen: set[str] = set()
    out: list[str] = []
    for u in urls:
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return out[:n]


async def fetch_stock_photo(query: str, orientation: str = "landscape") -> str | None:
    """Самое релевантное фото по запросу (англ. ключевые слова) или None."""
    c = await fetch_stock_candidates(query, orientation, 3)
    return c[0] if c else None


def _pexels_pick(p: dict) -> str | None:
    src = p.get("src") or {}
    return src.get("large2x") or src.get("large") or src.get("original") or src.get("medium")


async def _pexels_list(query: str, orientation: str = "landscape", n: int = 8) -> list[str]:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://api.pexels.com/v1/search",
                params={"query": query, "per_page": str(max(n, 10)), "orientation": orientation},
                headers={"Authorization": config.PEXELS_API_KEY},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as r:
                if r.status >= 300:
                    log.warning("Pexels HTTP %s", r.status)
                    return []
                data = await r.json()
        photos = data.get("photos") or []
        return [u for u in (_pexels_pick(p) for p in photos) if u]
    except Exception as e:  # noqa: BLE001
        log.warning("Pexels error: %s", e)
        return []


async def _unsplash_list(query: str, orientation: str = "landscape", n: int = 8) -> list[str]:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://api.unsplash.com/search/photos",
                params={"query": query, "per_page": str(max(n, 10)), "orientation": orientation},
                headers={"Authorization": f"Client-ID {config.UNSPLASH_ACCESS_KEY}"},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as r:
                if r.status >= 300:
                    log.warning("Unsplash HTTP %s", r.status)
                    return []
                data = await r.json()
        results = data.get("results") or []
        out = []
        for p in results:
            u = (p.get("urls") or {})
            out.append(u.get("full") or u.get("regular") or u.get("small"))
        return [u for u in out if u]
    except Exception as e:  # noqa: BLE001
        log.warning("Unsplash error: %s", e)
        return []
