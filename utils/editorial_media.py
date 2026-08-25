"""Надёжный подбор изображения для редакционных Telegram-постов.

Приоритет:
1. Реальное тематическое фото из Wikimedia Commons со свободной лицензией.
2. Если реальное фото не найдено и задан OPENAI_API_KEY — генерация изображения.

В Telegram всегда отправляются байты изображения, а не внешний URL: это устраняет
сбои send_photo(), когда Telegram не может скачать картинку с Wikimedia напрямую.
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
    fallback_by_kind = {
        "morning": "Netherlands weather train traffic",
        "event": "Netherlands event festival",
        "curiosity": "Netherlands history architecture object",
        "evening": "Netherlands street architecture daily life",
    }
    fallback = fallback_by_kind.get(kind, "Netherlands")
    if not ai_enabled():
        return fallback
    try:
        response = await _get_client().messages.create(
            model=config.AI_MODEL,
            max_tokens=90,
            system=(
                "Из текста Telegram-поста выдели ОДИН конкретный объект, место, событие или явление, "
                "которое лучше всего показать на реальной фотографии. Верни ТОЛЬКО поисковый запрос "
                "для Wikimedia Commons на английском или нидерландском, 3-8 слов. Если в тексте есть "
                "конкретное название места, здания, события или предмета — обязательно используй его. "
                "Добавь Netherlands или конкретный город. Без пояснений, кавычек и markdown."
            ),
            messages=[{"role": "user", "content": f"Тип: {kind}\n\n{text[:1800]}"}],
        )
        raw, _ = _extract_text_and_sources(response)
        query = _plain(raw).strip("\"'")
        return query[:140] or fallback
    except Exception as exc:  # noqa: BLE001
        log.info("Не удалось сформировать запрос фотографии: %s", exc)
        return fallback


def _search_variants(primary: str, text: str, kind: str) -> list[str]:
    """Несколько попыток вместо одного хрупкого Wikimedia-запроса."""
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    latin_title = " ".join(re.findall(r"[A-Za-zÀ-ÿ0-9][A-Za-zÀ-ÿ0-9'’.-]*", first_line))[:100]
    generic = {
        "morning": "Netherlands railway weather road",
        "event": "Netherlands cultural event",
        "curiosity": "Netherlands heritage architecture",
        "evening": "Netherlands urban daily life",
    }.get(kind, "Netherlands")
    variants = [primary]
    if latin_title:
        variants.append(f"{latin_title} Netherlands")
    variants.append(generic)
    result = []
    for value in variants:
        value = re.sub(r"\s+", " ", value).strip()
        if value and value.lower() not in {x.lower() for x in result}:
            result.append(value)
    return result[:3]


async def _download_image(url: str, mime: str) -> BufferedInputFile | None:
    timeout = aiohttp.ClientTimeout(total=25)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers={"User-Agent": "PodslushanoNLBot/1.1"}) as response:
                if response.status != 200:
                    return None
                data = await response.read()
                if len(data) < 12_000 or len(data) > 9_500_000:
                    return None
    except Exception as exc:  # noqa: BLE001
        log.info("Wikimedia image download failed: %s", exc)
        return None
    ext = ".jpg"
    if "png" in mime:
        ext = ".png"
    elif "webp" in mime:
        ext = ".webp"
    return BufferedInputFile(data, filename=f"editorial-real{ext}")


async def _commons_image(query: str) -> EditorialImage | None:
    params = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": query,
        "gsrnamespace": "6",
        "gsrlimit": "20",
        "prop": "imageinfo",
        "iiprop": "url|mime|size|extmetadata",
        "iiurlwidth": "1600",
        "origin": "*",
    }
    timeout = aiohttp.ClientTimeout(total=20)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(
                COMMONS_API,
                params=params,
                headers={"User-Agent": "PodslushanoNLBot/1.1"},
            ) as response:
                if response.status != 200:
                    log.info("Wikimedia search HTTP %s for %s", response.status, query)
                    return None
                payload = await response.json(content_type=None)
    except Exception as exc:  # noqa: BLE001
        log.info("Wikimedia image search failed: %s", exc)
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
        if width and height and (width < 700 or height < 450):
            continue

        meta = info.get("extmetadata") or {}
        license_name = _plain((meta.get("LicenseShortName") or {}).get("value", ""))
        usage = _plain((meta.get("UsageTerms") or {}).get("value", ""))
        artist = _plain((meta.get("Artist") or {}).get("value", ""))
        license_text = f"{license_name} {usage}".lower()
        if not any(mark in license_text for mark in (
            "cc by", "cc-by", "cc0", "public domain", "publiek domein",
        )):
            continue

        image_url = info.get("thumburl") or info.get("url")
        if not image_url:
            continue
        photo = await _download_image(image_url, mime)
        if not photo:
            continue

        credit_parts = []
        if artist:
            credit_parts.append(artist[:70])
        credit_parts.append("Wikimedia Commons")
        if license_name:
            credit_parts.append(license_name[:30])
        return EditorialImage(
            photo=photo,
            attribution="Фото: " + " / ".join(credit_parts),
            source=info.get("descriptionurl") or "",
            generated=False,
        )
    return None


async def _generated_image(text: str, kind: str) -> EditorialImage | None:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None
    model = os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1.5").strip() or "gpt-image-1.5"
    prompt = (
        "Create a high-quality editorial documentary-style horizontal photograph for a Russian-language "
        "media channel about life in the Netherlands. No text, no logos, no decorative flags, no stock-photo "
        "look, no exaggerated cinematic effects. Natural Dutch environment, contemporary 2026 visual language, "
        "believable lighting and details. It must clearly illustrate this exact topic:\n\n" + text[:1800]
    )
    body = {
        "model": model,
        "prompt": prompt,
        "size": "1536x1024",
        "quality": "medium",
        "output_format": "jpeg",
    }
    timeout = aiohttp.ClientTimeout(total=120)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                OPENAI_IMAGES_API,
                json=body,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            ) as response:
                if response.status >= 300:
                    log.warning("OpenAI image generation failed: HTTP %s %s", response.status, (await response.text())[:300])
                    return None
                payload = await response.json(content_type=None)
        item = (payload.get("data") or [{}])[0]
        encoded = item.get("b64_json")
        if not encoded:
            return None
        image_bytes = base64.b64decode(encoded)
        return EditorialImage(
            photo=BufferedInputFile(image_bytes, filename=f"editorial-{kind}.jpg"),
            attribution="Иллюстрация создана ИИ",
            generated=True,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("OpenAI image generation failed: %s", exc)
        return None


async def choose_editorial_image(text: str, kind: str) -> EditorialImage | None:
    """Несколько раз ищет реальное фото; только потом использует генерацию."""
    primary = await _image_search_query(text, kind)
    for query in _search_variants(primary, text, kind):
        log.info("Editorial image search: kind=%s query=%s", kind, query)
        real = await _commons_image(query)
        if real:
            return real
    return await _generated_image(text, kind)
