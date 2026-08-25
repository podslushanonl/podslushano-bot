"""Проверенный резерв реальных фотографий для утренних и вечерних постов.

Все файлы находятся на Wikimedia Commons и допускают повторное использование
согласно лицензии, указанной для конкретного файла. Это не иллюстрации и не
генерация: только реальные фотографии Нидерландов.
"""
from __future__ import annotations

from urllib.parse import quote

COMMONS_REDIRECT = "https://commons.wikimedia.org/wiki/Special:Redirect/file/"

CURATED_PHOTOS = {
    "morning_rain": {
        "file": "Amsterdam photo 2023 - a look-through under the train bridge in the city center on on a grey rainy day. This is the water of the old canal Prinsengracht at the start. Free download street photography, Fons Heijnsbroek, CCO Netherlands.tif",
        "credit": "Фото: Fons Heijnsbroek / Wikimedia Commons / CC0",
    },
    "morning_clear": {
        "file": "Amsterdam Canal Houses (Unsplash).jpg",
        "credit": "Фото: Wikimedia Commons / CC0",
    },
    "evening": {
        "file": "Amsterdam Canal.png",
        "credit": "Фото: Supertrouper33 / Wikimedia Commons / CC0",
    },
    "evening_blue_hour": {
        "file": "Water reflection of canal houses at blue hour in Damrak Amsterdam the Netherlands.jpg",
        "credit": "Фото: Basile Morin / Wikimedia Commons",
    },
}


def curated_photo(kind: str, text: str) -> tuple[str, str] | None:
    lower = (text or "").lower()
    if kind == "morning":
        rainy = any(word in lower for word in ("дожд", "лив", "осад", "гроз", "regen", "buien"))
        item = CURATED_PHOTOS["morning_rain" if rainy else "morning_clear"]
    elif kind == "evening":
        item = CURATED_PHOTOS["evening_blue_hour" if "амстердам" in lower or "amsterdam" in lower else "evening"]
    else:
        return None
    url = COMMONS_REDIRECT + quote(item["file"], safe="") + "?width=1800"
    return url, item["credit"]
