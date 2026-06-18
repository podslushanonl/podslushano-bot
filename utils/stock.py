"""Подбор реального тематического фото из фотостоков (Pexels / Unsplash / Pixabay).

Используется для картинок к постам в канал (/post) и слайдам Instagram-каруселей
(/ig). Достаточно одного бесплатного ключа: PEXELS_API_KEY (проще), либо
UNSPLASH_ACCESS_KEY, либо PIXABAY_API_KEY. Чем больше ключей — тем разнообразнее
выдача (разные ракурсы). Возвращает URL картинки или None.
"""
import logging
from itertools import zip_longest

import aiohttp

import config

log = logging.getLogger(__name__)


def stock_enabled() -> bool:
    return bool(config.PEXELS_API_KEY or config.UNSPLASH_ACCESS_KEY
                or config.PIXABAY_API_KEY)


async def fetch_stock_candidates(query: str, orientation: str = "landscape",
                                 n: int = 8) -> list[str]:
    """URL фото по запросу из ВСЕХ доступных стоков, ПЕРЕМЕШАННО (разнообразие)."""
    query = (query or "").strip()
    if not query:
        return []
    per = max(n, 6)
    lists: list[list[str]] = []
    if config.PEXELS_API_KEY:
        lists.append(await _pexels_list(query, orientation, per))
    if config.UNSPLASH_ACCESS_KEY:
        lists.append(await _unsplash_list(query, orientation, per))
    if config.PIXABAY_API_KEY:
        lists.append(await _pixabay_list(query, orientation, per))
    # перемешиваем по одному из каждого источника — чтобы вверху были разные стоки
    merged: list[str] = []
    for trio in zip_longest(*lists):
        merged.extend([u for u in trio if u])
    seen: set[str] = set()
    out: list[str] = []
    for u in merged:
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


async def _pixabay_list(query: str, orientation: str = "landscape", n: int = 8) -> list[str]:
    orient = "vertical" if orientation == "portrait" else "horizontal"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://pixabay.com/api/",
                params={
                    "key": config.PIXABAY_API_KEY,
                    "q": query,
                    "image_type": "photo",
                    "orientation": orient,
                    "per_page": str(max(n, 10)),
                    "safesearch": "true",
                },
                timeout=aiohttp.ClientTimeout(total=15),
            ) as r:
                if r.status >= 300:
                    log.warning("Pixabay HTTP %s", r.status)
                    return []
                data = await r.json()
        hits = data.get("hits") or []
        return [h.get("largeImageURL") or h.get("webformatURL") for h in hits
                if h.get("largeImageURL") or h.get("webformatURL")]
    except Exception as e:  # noqa: BLE001
        log.warning("Pixabay error: %s", e)
        return []
