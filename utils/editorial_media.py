"""Фотографии для редакционных Telegram-постов.

Правила:
- morning/evening: изображение ВСЕГДА создаётся динамически под конкретный текст поста;
- event/curiosity: сначала ищем точную реальную фотографию Wikimedia Commons, затем AI;
- никаких фиксированных fallback-фото, Pillow, flat-design или универсальных каналов Амстердама.
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
    fallback = {
        "event": "Netherlands event festival",
        "curiosity": "Netherlands heritage architecture",
    }.get(kind, "Netherlands")
    if not ai_enabled():
        return fallback
    try:
        response = await _get_client().messages.create(
            model=config.AI_MODEL,
            max_tokens=90,
            system=(
                "Из текста Telegram-поста выдели ОДИН конкретный визуальный объект, место, событие или явление. "
                "Верни ТОЛЬКО короткий запрос для Wikimedia Commons на английском или нидерландском, 2-6 слов. "
                "Если есть собственное название — обязательно используй его. Без пояснений и markdown."
            ),
            messages=[{"role": "user", "content": f"Тип: {kind}\n\n{text[:1800]}"}],
        )
        raw, _ = _extract_text_and_sources(response)
        return _plain(raw).strip("\"'")[:120] or fallback
    except Exception as exc:
        log.info("Image query generation failed: %s", exc)
        return fallback


async def _download_image(url: str, mime: str) -> BufferedInputFile | None:
    timeout = aiohttp.ClientTimeout(total=30)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers={"User-Agent": "PodslushanoNLBot/1.5"}) as response:
                if response.status != 200:
                    return None
                data = await response.read()
                if len(data) < 20_000 or len(data) > 9_500_000:
                    return None
    except Exception as exc:
        log.info("Commons image download failed: %s", exc)
        return None
    ext = ".png" if "png" in mime else ".webp" if "webp" in mime else ".jpg"
    return BufferedInputFile(data, filename=f"editorial-real{ext}")


async def _commons_image(query: str) -> EditorialImage | None:
    params = {
        "action": "query", "format": "json", "generator": "search",
        "gsrsearch": query, "gsrnamespace": "6", "gsrlimit": "35",
        "prop": "imageinfo", "iiprop": "url|mime|size|extmetadata",
        "iiurlwidth": "1800", "origin": "*",
    }
    try:
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(COMMONS_API, params=params, headers={"User-Agent": "PodslushanoNLBot/1.5"}) as response:
                if response.status != 200:
                    return None
                payload = await response.json(content_type=None)
    except Exception as exc:
        log.info("Commons image search failed: %s", exc)
        return None

    for page in list((payload.get("query") or {}).get("pages", {}).values()):
        infos = page.get("imageinfo") or []
        if not infos:
            continue
        info = infos[0]
        mime = str(info.get("mime") or "").lower()
        if mime not in {"image/jpeg", "image/png", "image/webp"}:
            continue
        width, height = int(info.get("width") or 0), int(info.get("height") or 0)
        if width and height and (width < 1100 or height < 650):
            continue
        meta = info.get("extmetadata") or {}
        license_name = _plain((meta.get("LicenseShortName") or {}).get("value", ""))
        usage = _plain((meta.get("UsageTerms") or {}).get("value", ""))
        if not any(x in f"{license_name} {usage}".lower() for x in ("cc by", "cc-by", "cc0", "public domain", "publiek domein")):
            continue
        image_url = info.get("thumburl") or info.get("url")
        if not image_url:
            continue
        photo = await _download_image(image_url, mime)
        if not photo:
            continue
        artist = _plain((meta.get("Artist") or {}).get("value", ""))
        credit = [artist[:65]] if artist else []
        credit += ["Wikimedia Commons"]
        if license_name:
            credit.append(license_name[:28])
        return EditorialImage(photo=photo, attribution="Фото: " + " / ".join(credit), source=info.get("descriptionurl") or "")
    return None


def _generation_prompt(text: str, kind: str) -> str:
    base = (
        "Create ONE premium photorealistic editorial photograph for Podslushano.nl, a modern Russian-language Netherlands media publication. "
        "The result must be indistinguishable from a professional documentary/news photograph shot on a full-frame camera in the Netherlands in 2026. "
        "Absolutely no illustration, vector art, flat design, 3D render, collage, poster, infographic, typography, captions, logos, watermarks, fake UI or decorative flags. "
        "Use natural optics, believable perspective, physically realistic weather, materials and reflections, restrained editorial color grading, authentic Dutch architecture and infrastructure. "
        "Do not invent readable signs, train destinations, delay boards, street names or factual visual claims that are not explicitly supported by the supplied post. "
    )
    if kind == "morning":
        rules = (
            "This image is for TODAY'S MORNING BRIEF. Read the supplied brief and make its most important real-world condition the visual story. "
            "If rain is important, show an authentic wet Dutch morning; if wind is important, make wind visibly credible; if clear weather, show the actual calm morning mood. "
            "If rail disruption is central, use a plausible Dutch station/NS railway environment without fabricating readable disruption information. "
            "If roads are central, use a plausible Dutch motorway/road scene. Do NOT try to show weather, train and motorway as three separate objects: choose one coherent photographic scene. "
            "Early-morning documentary light, candid people only where natural, horizontal 3:2 composition. "
        )
    elif kind == "evening":
        rules = (
            "This image is for the 21:00 story. Visually depict THE EXACT subject of the supplied story, not a generic Amsterdam canal. "
            "If the story is about a specific place or object, make that place/object the unmistakable hero of the frame. "
            "If the subject cannot be reproduced with factual confidence, create a plausible atmospheric documentary reconstruction of the concept without adding false identifying details. "
            "Evening/blue-hour light only when appropriate to the subject; premium magazine-documentary photography, horizontal 3:2 composition. "
        )
    elif kind == "event":
        rules = "Create a believable documentary photograph matching the exact event and its distinctive atmosphere; do not fabricate branding or readable event signage. "
    else:
        rules = "Create a believable documentary photograph of the exact Dutch place/object/historical subject described in the post. "
    return base + rules + "\nPOST CONTENT:\n" + text[:2400]


async def _generated_image(text: str, kind: str) -> EditorialImage | None:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        log.warning("OPENAI_API_KEY missing; dynamic editorial image cannot be generated")
        return None
    model = os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1.5").strip() or "gpt-image-1.5"
    body = {
        "model": model,
        "prompt": _generation_prompt(text, kind),
        "size": "1536x1024",
        "quality": "high",
        "output_format": "jpeg",
    }
    try:
        timeout = aiohttp.ClientTimeout(total=180)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(OPENAI_IMAGES_API, json=body, headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}) as response:
                if response.status >= 300:
                    log.warning("Image generation HTTP %s: %s", response.status, (await response.text())[:500])
                    return None
                payload = await response.json(content_type=None)
        encoded = ((payload.get("data") or [{}])[0]).get("b64_json")
        if not encoded:
            return None
        return EditorialImage(photo=BufferedInputFile(base64.b64decode(encoded), filename=f"editorial-{kind}.jpg"), attribution="Изображение создано ИИ", generated=True)
    except Exception as exc:
        log.warning("Dynamic editorial image generation failed: %s", exc)
        return None


async def choose_editorial_image(text: str, kind: str) -> EditorialImage | None:
    """Morning/evening are dynamically generated; event/curiosity prefer exact real photos."""
    if kind in {"morning", "evening"}:
        return await _generated_image(text, kind)

    primary = await _image_search_query(text, kind)
    real = await _commons_image(primary)
    if real:
        return real
    return await _generated_image(text, kind)
