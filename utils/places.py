"""Подбор реального фото места через Google Places API (New).

Используется для картинок к постам в канал (/post) и слайдам Instagram-каруселей
(/ig). В отличие от фотостоков, отдаёт фотографии КОНКРЕТНЫХ мест (кафе, парки,
города), про которые пишет бот. Нужен один ключ: GOOGLE_MAPS_API_KEY
(с включённым Places API и биллингом). Возвращает URL картинки или None.

Замечание по лицензии: фотографии Google Places предназначены для показа с
атрибуцией Google; ответственность за републикацию — на стороне владельца ключа.
"""
import logging

import aiohttp

import config

log = logging.getLogger(__name__)

_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
_MEDIA_BASE = "https://places.googleapis.com/v1"


def places_enabled() -> bool:
    return bool(config.GOOGLE_MAPS_API_KEY)


async def _search_photos(query: str, n: int) -> list[dict]:
    """Возвращает список метаданных фото [{name,width,height}] для запроса."""
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": config.GOOGLE_MAPS_API_KEY,
        "X-Goog-FieldMask": "places.photos,places.displayName",
    }
    body = {"textQuery": query, "pageSize": min(max(n, 3), 10), "languageCode": "en"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                _SEARCH_URL, json=body, headers=headers,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as r:
                if r.status >= 300:
                    log.warning("Places searchText HTTP %s", r.status)
                    return []
                data = await r.json()
    except Exception as e:  # noqa: BLE001
        log.warning("Places search error: %s", e)
        return []
    out: list[dict] = []
    for place in data.get("places", []) or []:
        for ph in place.get("photos", []) or []:
            name = ph.get("name")
            if name:
                out.append({
                    "name": name,
                    "width": ph.get("widthPx") or 0,
                    "height": ph.get("heightPx") or 0,
                })
    return out


async def _resolve_uri(session: aiohttp.ClientSession, photo_name: str,
                       orientation: str) -> str | None:
    """Превращает имя фото (places/.../photos/...) в прямой URL картинки."""
    if orientation == "portrait":
        params = {"maxHeightPx": "1600", "skipHttpRedirect": "true"}
    else:
        params = {"maxWidthPx": "1600", "skipHttpRedirect": "true"}
    try:
        async with session.get(
            f"{_MEDIA_BASE}/{photo_name}/media",
            params=params,
            headers={"X-Goog-Api-Key": config.GOOGLE_MAPS_API_KEY},
            timeout=aiohttp.ClientTimeout(total=15),
        ) as r:
            if r.status >= 300:
                log.warning("Places media HTTP %s", r.status)
                return None
            data = await r.json()
            return data.get("photoUri")
    except Exception as e:  # noqa: BLE001
        log.warning("Places media error: %s", e)
        return None


async def fetch_place_candidates(query: str, orientation: str = "landscape",
                                 n: int = 8) -> list[str]:
    """URL фотографий мест по запросу. Сортирует под нужную ориентацию."""
    query = (query or "").strip()
    if not query or not places_enabled():
        return []
    photos = await _search_photos(query, n)
    if not photos:
        return []
    # сначала фото подходящей ориентации
    want_portrait = orientation == "portrait"

    def fits(p: dict) -> int:
        w, h = p["width"], p["height"]
        if not w or not h:
            return 1
        is_portrait = h > w
        return 0 if is_portrait == want_portrait else 2

    photos.sort(key=fits)
    out: list[str] = []
    seen: set[str] = set()
    async with aiohttp.ClientSession() as session:
        for p in photos:
            if len(out) >= n:
                break
            uri = await _resolve_uri(session, p["name"], orientation)
            if uri and uri not in seen:
                seen.add(uri)
                out.append(uri)
    return out


async def fetch_place_photo(query: str, orientation: str = "landscape") -> str | None:
    """Самое релевантное фото места по запросу или None."""
    c = await fetch_place_candidates(query, orientation, 3)
    return c[0] if c else None
