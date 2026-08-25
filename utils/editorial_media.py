"""Подбор изображения для редакционных постов.

Приоритет:
1. Реальное тематическое фото из Wikimedia Commons с лицензией/атрибуцией.
2. Если подходящего фото нет и задан OPENAI_API_KEY — сгенерированная иллюстрация.

Модуль возвращает объект, который aiogram может передать в send_photo(), и короткую
атрибуцию. После отправки предпросмотра Telegram file_id сохраняется основным модулем,
поэтому при публикации изображение не скачивается/генерируется второй раз.
"""
from __future__ import annotations

import base64
import html
import logging
import os
import re
from dataclasses import dataclass
from urllib.parse import quote

import aiohttp
from aiogram.types import BufferedInputFile

import config
from utils.ai import _extract_text_and_sources, _get_client, ai_enabled

log = logging.getLogger(__name__)

COMMONS_API = "https://commons.wikimedia.org/w/api.php"
OPENAI_IMAGES_API = "https://api.openai.com/v1/images/generations"


@dataclass
class EditorialImage:
    photo: str | BufferedInputFile
    attribution: str = ""
    source: str = ""
    generated: bool = False


def _plain(value: str) -> str:
    value = re.sub(r"<[^>]+>", "", html.unescape(value or ""))
    return re.sub(r"\s+", " ", value).strip()


async def _image_search_query(text: str, kind: str) -> str:
    """Делает короткий точный запрос для поиска фотографии, без второго web-search."""
    fallback = "Netherlands " + " ".join(re.findall(r"[A-Za-zÀ-ÿ0-9-]+", text)[:8])
    if not ai_enabled():
        return fallback[:120]
    try:
        response = await _get_client().messages.create(
            model=config.AI_MODEL,
            max_tokens=80,
            system=(
                "Из текста Telegram-поста выдели объект, место, событие или явление, которое лучше всего "
                "показать на реальной фотографии. Верни ТОЛЬКО короткий поисковый запрос на английском "
                "или нидерландском, 3-8 слов. Обязательно добавь Netherlands или конкретный город. "
                "Не пиши пояснений, кавычек и markdown."
            ),
            messages=[{"role": "user", "content": f"Тип: {kind}\n\n{text[:1800]}"}],
        )
        raw, _ = _extract_text_and_sources(response)
        query = _plain(raw).strip('"\'')
        return query[:140] or fallback[:120]
    except Exception as exc:  # noqa: BLE001
        log.info("Не удалось сформировать запрос фотографии: %s", exc)
        return fallback[:120]


async def _commons_image(query: str) -> EditorialImage | None:
    params = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": query,
        "gsrnamespace": "6",
        "gsrlimit": "10",
        "prop": "imageinfo",
        "iiprop": "url|mime|extmetadata",
        "iiurlwidth": "1600",
        "origin": "*",
    }
    timeout = aiohttp.ClientTimeout(total=15)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(COMMONS_API, params=params, headers={"User-Agent": "PodslushanoNLBot/1.0"}) as response:
                if response.status != 200:
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
        meta = info.get("extmetadata") or {}
        license_name = _plain((meta.get("LicenseShortName") or {}).get("value", ""))
        usage = _plain((meta.get("UsageTerms") or {}).get("value", ""))
        artist = _plain((meta.get("Artist") or {}).get("value", ""))
        # Берём только изображения с явной свободной лицензией/PD.
        license_text = f"{license_name} {usage}".lower()
        if not any(mark in license_text for mark in ("cc by", "cc0", "public domain", "publiek domein")):
            continue
        image_url = info.get("thumburl") or info.get("url")
        if not image_url:
            continue
        credit_parts = []
        if artist:
            credit_parts.append(artist[:80])
        credit_parts.append("Wikimedia Commons")
        if license_name:
            credit_parts.append(license_name[:35])
        return EditorialImage(
            photo=image_url,
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
        "media channel about life in the Netherlands. No text, no logos, no flags used as decoration, "
        "no stock-photo look, no exaggerated cinematic effects. Natural Dutch environment, contemporary "
        "2026 visual language, believable lighting and details. The image must illustrate this exact topic:\n\n"
        + text[:1800]
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
    """Ищет реальную фотографию; при неудаче генерирует иллюстрацию, если это настроено."""
    query = await _image_search_query(text, kind)
    real = await _commons_image(query)
    if real:
        return real
    return await _generated_image(text, kind)
