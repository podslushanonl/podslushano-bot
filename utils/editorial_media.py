"""Надёжный подбор изображения для редакционных Telegram-постов.

Приоритет:
1. Реальное тематическое фото из Wikimedia Commons со свободной лицензией.
2. Если задан OPENAI_API_KEY — AI-иллюстрация.
3. Всегда доступный локальный fallback на Pillow: собственная редакционная графика.

Таким образом утренний и вечерний пост больше не могут остаться без изображения
из-за внешнего API или пустой выдачи Wikimedia.
"""
from __future__ import annotations

import base64
import html
import io
import logging
import math
import os
import re
from dataclasses import dataclass

import aiohttp
from aiogram.types import BufferedInputFile
from PIL import Image, ImageDraw

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
            async with session.get(url, headers={"User-Agent": "PodslushanoNLBot/1.2"}) as response:
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
        "action": "query", "format": "json", "generator": "search",
        "gsrsearch": query, "gsrnamespace": "6", "gsrlimit": "20",
        "prop": "imageinfo", "iiprop": "url|mime|size|extmetadata",
        "iiurlwidth": "1600", "origin": "*",
    }
    timeout = aiohttp.ClientTimeout(total=20)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(COMMONS_API, params=params, headers={"User-Agent": "PodslushanoNLBot/1.2"}) as response:
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
        width = int(info.get("width") or 0)
        height = int(info.get("height") or 0)
        if width and height and (width < 700 or height < 450):
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
    body = {"model": model, "prompt": prompt, "size": "1536x1024", "quality": "medium", "output_format": "jpeg"}
    timeout = aiohttp.ClientTimeout(total=120)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                OPENAI_IMAGES_API,
                json=body,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            ) as response:
                if response.status >= 300:
                    return None
                payload = await response.json(content_type=None)
        item = (payload.get("data") or [{}])[0]
        encoded = item.get("b64_json")
        if not encoded:
            return None
        return EditorialImage(
            photo=BufferedInputFile(base64.b64decode(encoded), filename=f"editorial-{kind}.jpg"),
            attribution="Иллюстрация создана ИИ",
            generated=True,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("OpenAI image generation failed: %s", exc)
        return None


def _gradient(img: Image.Image, top: tuple[int, int, int], bottom: tuple[int, int, int]) -> None:
    draw = ImageDraw.Draw(img)
    w, h = img.size
    for y in range(h):
        t = y / max(1, h - 1)
        color = tuple(int(top[i] * (1 - t) + bottom[i] * t) for i in range(3))
        draw.line((0, y, w, y), fill=color)


def _cloud(draw: ImageDraw.ImageDraw, x: int, y: int, scale: float = 1.0) -> None:
    c = (238, 240, 242)
    draw.ellipse((x, y, x + int(150 * scale), y + int(90 * scale)), fill=c)
    draw.ellipse((x + int(55 * scale), y - int(45 * scale), x + int(175 * scale), y + int(85 * scale)), fill=c)
    draw.ellipse((x + int(120 * scale), y + int(5 * scale), x + int(245 * scale), y + int(92 * scale)), fill=c)


def _local_artwork(text: str, kind: str) -> EditorialImage:
    """Собственная иллюстрация без внешних сервисов. Всегда возвращает изображение."""
    w, h = 1536, 1024
    img = Image.new("RGB", (w, h))
    draw = ImageDraw.Draw(img)
    lower = text.lower()

    if kind == "morning":
        rain = any(x in lower for x in ("дожд", "лив", "гроз", "buien", "regen"))
        sunny = any(x in lower for x in ("солнеч", "ясн", "zonnig", "sun")) and not rain
        windy = any(x in lower for x in ("ветр", "шторм", "wind"))
        _gradient(img, (176, 210, 230), (237, 218, 189))
        # horizon + Dutch road
        draw.rectangle((0, 660, w, h), fill=(86, 105, 88))
        draw.polygon([(500, h), (1030, h), (890, 650), (660, 650)], fill=(65, 67, 70))
        for y in range(690, 1020, 95):
            width = int((y - 620) * 0.15 + 18)
            draw.rectangle((765 - width // 2, y, 765 + width // 2, y + 35), fill=(235, 228, 202))
        # rail line
        draw.line((180, h, 540, 650), fill=(45, 45, 45), width=12)
        draw.line((340, h, 610, 650), fill=(45, 45, 45), width=12)
        if sunny:
            draw.ellipse((1120, 115, 1320, 315), fill=(245, 193, 73))
        else:
            _cloud(draw, 980, 140, 1.25)
        if rain:
            for x in range(990, 1370, 70):
                draw.line((x, 330, x - 20, 400), fill=(94, 138, 179), width=9)
        if windy:
            for off in (0, 60, 120):
                draw.arc((880, 250 + off, 1380, 430 + off), 190, 340, fill=(248, 248, 248), width=8)
        # compact train silhouette
        draw.rounded_rectangle((170, 500, 620, 690), radius=42, fill=(236, 225, 192))
        draw.rectangle((230, 535, 545, 605), fill=(61, 91, 111))
        draw.ellipse((230, 655, 285, 710), fill=(28, 28, 28))
        draw.ellipse((500, 655, 555, 710), fill=(28, 28, 28))

    elif kind == "event":
        _gradient(img, (40, 24, 61), (126, 58, 70))
        draw.ellipse((540, 120, 1000, 580), fill=(222, 156, 80))
        draw.rectangle((0, 690, w, h), fill=(25, 24, 30))
        # stage + crowd silhouettes
        draw.rectangle((420, 380, 1110, 700), fill=(34, 34, 44))
        for x in range(40, w, 90):
            y = 730 + (x % 180)
            draw.ellipse((x, y, x + 52, y + 52), fill=(18, 18, 22))
            draw.rectangle((x + 8, y + 45, x + 44, h), fill=(18, 18, 22))

    else:
        evening = kind == "evening"
        _gradient(img, (32, 38, 68) if evening else (135, 165, 174), (104, 55, 63) if evening else (210, 190, 156))
        # canal water
        draw.rectangle((0, 710, w, h), fill=(37, 70, 85) if evening else (83, 120, 132))
        # Amsterdam-style house silhouettes
        house_colors = [(102, 66, 57), (83, 71, 75), (118, 83, 66), (72, 79, 78), (121, 92, 70)]
        x = 90
        for i, hw in enumerate((220, 190, 235, 180, 230, 190)):
            hh = 360 + (i % 3) * 70
            y0 = 710 - hh
            color = house_colors[i % len(house_colors)]
            draw.rectangle((x, y0, x + hw, 710), fill=color)
            draw.polygon([(x, y0), (x + hw // 2, y0 - 85), (x + hw, y0)], fill=color)
            for wy in range(y0 + 70, 650, 105):
                for wx in range(x + 35, x + hw - 30, 75):
                    fill = (242, 196, 100) if evening else (205, 220, 211)
                    draw.rectangle((wx, wy, wx + 34, wy + 52), fill=fill)
            x += hw - 18
        # bridge / foreground
        draw.arc((300, 610, 1240, 970), 185, 355, fill=(47, 49, 52), width=42)
        if evening:
            draw.ellipse((1220, 130, 1360, 270), fill=(232, 218, 170))
            for i in range(12):
                px = 120 + i * 120
                py = 820 + int(25 * math.sin(i))
                draw.line((px, py, px + 45, py + 10), fill=(221, 181, 94), width=5)

    out = io.BytesIO()
    img.save(out, format="JPEG", quality=91, optimize=True)
    out.seek(0)
    return EditorialImage(
        photo=BufferedInputFile(out.read(), filename=f"editorial-local-{kind}.jpg"),
        attribution="Иллюстрация Podslushano.nl",
        generated=True,
    )


async def choose_editorial_image(text: str, kind: str) -> EditorialImage:
    """Реальное фото → AI → собственная локальная иллюстрация. Никогда не возвращает None."""
    primary = await _image_search_query(text, kind)
    for query in _search_variants(primary, text, kind):
        real = await _commons_image(query)
        if real:
            return real
    generated = await _generated_image(text, kind)
    if generated:
        return generated
    log.info("Using local editorial artwork fallback: kind=%s", kind)
    return _local_artwork(text, kind)
