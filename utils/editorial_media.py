"""Фотографии для редакционных Telegram-постов.

Приоритет:
1. Точное реальное фото из Wikimedia Commons.
2. Для утренних и вечерних постов — проверенный резерв реальных CC0-фото.
3. Фотореалистичная генерация через OpenAI Images API, если ключ настроен.

Никаких Pillow/flat-design иллюстраций.
"""
from __future__ import annotations

import base64
import html
import logging
import os
import re
from dataclasses import dataclass

import aiohttp
from aiogram.types import BufferedInputFile

import config
from utils.ai import _extract_text_and_sources, _get_client, ai_enabled
from utils.editorial_curated_photos import curated_photo

log = logging.getLogger(__name__)

COMMONS_API = "https://commons.wikimedia.org/w/api.php"
OPENAI_IMAGES_API = "https://api.openai.com/v1/images/generations"


@dataclass
class EditorialImage:
    photo: BufferedInputFile
    attribution: str = ""
    source: str = ""
    generated: bool = False


def _plain(value: str) -> str:
    value = re.sub(r"<[^>]+>", "", html.unescape(value or ""))
    return re.sub(r"\s+", " ", value).strip()


async def _image_search_query(text: str, kind: str) -> str:
    fallback_by_kind = {
        "morning": "Dutch train Netherlands",
        "event": "Netherlands event festival",
        "curiosity": "Netherlands heritage architecture",
        "evening": "Netherlands historic place",
    }
    fallback = fallback_by_kind.get(kind, "Netherlands")
    if not ai_enabled():
        return fallback
    try:
        response = await _get_client().messages.create(
            model=config.AI_MODEL,
            max_tokens=90,
            system=(
                "Из текста Telegram-поста выдели ОДИН конкретный визуальный объект, место, событие или явление. "
                "Верни ТОЛЬКО короткий запрос для Wikimedia Commons на английском или нидерландском, 2-6 слов. "
                "Если есть собственное название места/здания/музея/предмета — обязательно используй его. "
                "Не перечисляй несколько тем одновременно. Без пояснений, кавычек и markdown."
            ),
            messages=[{"role": "user", "content": f"Тип: {kind}\n\n{text[:1800]}"}],
        )
        raw, _ = _extract_text_and_sources(response)
        query = _plain(raw).strip("\"'")
        return query[:120] or fallback
    except Exception as exc:  # noqa: BLE001
        log.info("Image query generation failed: %s", exc)
        return fallback


def _search_variants(primary: str, text: str, kind: str) -> list[str]:
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    latin = " ".join(re.findall(r"[A-Za-zÀ-ÿ0-9][A-Za-zÀ-ÿ0-9'’.-]*", first_line))[:100]
    generic = {
        "morning": ["NS train Netherlands", "Dutch railway station", "Netherlands motorway"],
        "event": ["Netherlands festival", "Dutch cultural event"],
        "curiosity": ["Netherlands heritage", "Dutch architecture"],
        "evening": ["Netherlands historic building", "Dutch city street"],
    }.get(kind, ["Netherlands"])
    values = [primary]
    if latin:
        values.append(latin)
    values.extend(generic)
    result: list[str] = []
    for value in values:
        value = re.sub(r"\s+", " ", value).strip()
        if value and value.casefold() not in {x.casefold() for x in result}:
            result.append(value)
    return result[:5]


async def _download_image(url: str, mime: str = "image/jpeg") -> BufferedInputFile | None:
    timeout = aiohttp.ClientTimeout(total=35)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers={"User-Agent": "PodslushanoNLBot/1.4"}, allow_redirects=True) as response:
                if response.status != 200:
                    log.info("Image download HTTP %s: %s", response.status, url[:180])
                    return None
                data = await response.read()
                content_type = (response.headers.get("Content-Type") or mime).lower()
                if not content_type.startswith("image/"):
                    log.info("Image URL returned non-image content: %s", content_type)
                    return None
                if len(data) < 20_000 or len(data) > 9_500_000:
                    log.info("Image size rejected: %d bytes", len(data))
                    return None
    except Exception as exc:  # noqa: BLE001
        log.info("Image download failed: %s", exc)
        return None
    ext = ".jpg"
    if "png" in content_type:
        ext = ".png"
    elif "webp" in content_type:
        ext = ".webp"
    return BufferedInputFile(data, filename=f"editorial-real{ext}")


async def _commons_image(query: str) -> EditorialImage | None:
    params = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": query,
        "gsrnamespace": "6",
        "gsrlimit": "35",
        "prop": "imageinfo",
        "iiprop": "url|mime|size|extmetadata",
        "iiurlwidth": "1800",
        "origin": "*",
    }
    timeout = aiohttp.ClientTimeout(total=20)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(COMMONS_API, params=params, headers={"User-Agent": "PodslushanoNLBot/1.4"}) as response:
                if response.status != 200:
                    return None
                payload = await response.json(content_type=None)
    except Exception as exc:  # noqa: BLE001
        log.info("Commons image search failed: %s", exc)
        return None

    pages = list((payload.get("query") or {}).get("pages", {}).values())
    for page in pages:
        infos = page.get("imageinfo") or []
        if not infos:
            continue
        info = infos[0]
        mime = str(info.get("mime") or "").lower()
        if mime not in {"image/jpeg", "image/png", "image/webp"}:
            continue
        width = int(info.get("width") or 0)
        height = int(info.get("height") or 0)
        if width and height and (width < 1100 or height < 650):
            continue
        meta = info.get("extmetadata") or {}
        license_name = _plain((meta.get("LicenseShortName") or {}).get("value", ""))
        usage = _plain((meta.get("UsageTerms") or {}).get("value", ""))
        artist = _plain((meta.get("Artist") or {}).get("value", ""))
        license_text = f"{license_name} {usage}".lower()
        if not any(mark in license_text for mark in ("cc by", "cc-by", "cc0", "public domain", "publiek domein")):
            continue
        image_url = info.get("thumburl") or info.get("url")
        if not image_url:
            continue
        photo = await _download_image(image_url, mime)
        if not photo:
            continue
        credit = [artist[:65]] if artist else []
        credit.append("Wikimedia Commons")
        if license_name:
            credit.append(license_name[:28])
        return EditorialImage(
            photo=photo,
            attribution="Фото: " + " / ".join(credit),
            source=info.get("descriptionurl") or "",
            generated=False,
        )
    return None


async def _curated_real_image(text: str, kind: str) -> EditorialImage | None:
    selected = curated_photo(kind, text)
    if not selected:
        return None
    url, credit = selected
    photo = await _download_image(url)
    if not photo:
        return None
    return EditorialImage(photo=photo, attribution=credit, source=url, generated=False)


def _generation_prompt(text: str, kind: str) -> str:
    common = (
        "Create a premium photorealistic editorial photograph for a modern Netherlands media publication. "
        "It must look like a real photograph made by a professional editorial photographer, not an illustration, "
        "not vector art, not 3D, not a poster, not flat design. Natural optics, realistic materials, subtle depth of field, "
        "credible Dutch architecture/infrastructure, contemporary 2026 atmosphere. No text, typography, logos, watermarks, "
        "decorative flags or fake UI. Avoid generic stock-photo poses and exaggerated cinematic color grading. "
    )
    if kind == "morning":
        specific = (
            "Scene: an authentic early morning in the Netherlands matching the weather described below. Include believable Dutch "
            "transport/infrastructure naturally in the scene, but do not make a collage and do not add icons. "
            "The weather and natural morning light must be the main visual story. "
        )
    elif kind == "evening":
        specific = (
            "Scene: visually tell the exact historical/place/object story below. If a concrete building, museum, street, object or "
            "Dutch location is named, depict that subject plausibly and prominently. Warm documentary editorial mood, still fully realistic. "
        )
    elif kind == "event":
        specific = "Scene: depict the exact event or its distinctive atmosphere as a believable documentary event photograph. "
    else:
        specific = "Scene: depict the exact Dutch object/place/historical subject from the text as a believable documentary photograph. "
    return common + specific + "Topic:\n" + text[:1800]


async def _generated_image(text: str, kind: str) -> EditorialImage | None:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None
    model = os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1.5").strip() or "gpt-image-1.5"
    body = {
        "model": model,
        "prompt": _generation_prompt(text, kind),
        "size": "1536x1024",
        "quality": "high",
        "output_format": "jpeg",
    }
    timeout = aiohttp.ClientTimeout(total=180)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                OPENAI_IMAGES_API,
                json=body,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            ) as response:
                if response.status >= 300:
                    log.warning("Image generation HTTP %s: %s", response.status, (await response.text())[:500])
                    return None
                payload = await response.json(content_type=None)
        encoded = ((payload.get("data") or [{}])[0]).get("b64_json")
        if not encoded:
            return None
        return EditorialImage(
            photo=BufferedInputFile(base64.b64decode(encoded), filename=f"editorial-{kind}.jpg"),
            attribution="Изображение создано ИИ",
            generated=True,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("Photorealistic image generation failed: %s", exc)
        return None


async def choose_editorial_image(text: str, kind: str) -> EditorialImage | None:
    """Точное реальное фото → проверенное реальное фото → AI-фото."""
    primary = await _image_search_query(text, kind)
    for query in _search_variants(primary, text, kind):
        real = await _commons_image(query)
        if real:
            return real

    curated = await _curated_real_image(text, kind)
    if curated:
        return curated

    return await _generated_image(text, kind)
