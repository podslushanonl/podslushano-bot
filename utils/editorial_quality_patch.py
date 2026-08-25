"""Quality patch for editorial text and image generation.

- Evening posts retry focused verified web-search paths instead of failing after one attempt.
- Morning/evening image generation first converts the post into ONE visual scene.
- The image model never receives a multi-block morning brief directly.
"""
from __future__ import annotations

import base64
import logging
import os

import aiohttp
from aiogram.types import BufferedInputFile

import config
from utils import editorial_channel as editorial
from utils import editorial_media as media
from utils import editorial_overrides as overrides
from utils.ai import _extract_text_and_sources, _get_client

log = logging.getLogger(__name__)
OPENAI_IMAGES_API = "https://api.openai.com/v1/images/generations"


async def _robust_evening_post() -> str | None:
    """Generate one of the two approved evening formats with focused retries."""
    recent = await editorial._recent_topics()
    date = editorial._now()
    history_first = date.toordinal() % 2 == 0

    formats = ["history", "why"] if history_first else ["why", "history"]
    domain_sets = {
        "history": [
            "cultureelerfgoed.nl", "rijksmuseum.nl", "canonvannederland.nl",
            "stadsarchief.amsterdam.nl", "openluchtmuseum.nl", "archieven.nl",
        ],
        "why": [
            "rijksoverheid.nl", "government.nl", "cbs.nl", "cultureelerfgoed.nl",
            "openluchtmuseum.nl", "holland.com",
        ],
    }

    for format_key in formats:
        if format_key == "history":
            format_instruction = (
                "Напиши ТОЛЬКО формат «История одного места/предмета»: выбери одно конкретное место, "
                "здание, улицу, сооружение, знак, предмет или элемент городской среды в Нидерландах. "
                "Нужна неожиданная, но проверяемая история именно этого объекта."
            )
        else:
            format_instruction = (
                "Напиши ТОЛЬКО формат «Почему здесь так?»: выбери одну конкретную деталь повседневной "
                "жизни в Нидерландах, которую люди регулярно видят, но редко знают причину её появления."
            )

        system = (
            "Ты вечерний редактор Telegram-канала для русскоязычных людей, уже живущих в Нидерландах. "
            + format_instruction + " "
            "Это не новости, не подборка и не туристическая реклама. Запрещены банальности про уровень моря, "
            "велосипеды, тюльпаны, кофешопы, красные фонари, мельницы, деревянные башмаки и прямолинейность. "
            "Не начинай с «А вы знали?». Все факты проверь веб-поиском. Один сюжет, 520–760 знаков. "
            "Пиши живым русским языком, без markdown, HTML и маркетингового CTA."
        )
        user = (
            f"Сегодня {date:%d.%m.%Y}. Не повторяй последние темы: {', '.join(recent) or 'нет'}. "
            "Выбери тему, для которой есть надёжный нидерландский источник, и не пытайся охватить несколько историй."
        )

        # Two attempts per format: focused sources first, then a slightly broader verified set.
        attempts = [domain_sets[format_key], list(dict.fromkeys(domain_sets[format_key] + editorial.FACT_SOURCES))]
        for domains in attempts:
            result = await editorial._generate(system, user, domains, 850)
            if result and result[0] and len(result[0].strip()) >= 280:
                return result[0].strip()
            log.warning("Evening editorial attempt failed: format=%s domains=%s", format_key, domains)
    return None


async def _visual_brief(text: str, kind: str) -> str:
    """Turn a post into exactly one photographic scene before image generation."""
    if kind == "morning":
        system = (
            "Ты фоторедактор. Из утреннего брифа выбери РОВНО ОДНУ главную визуальную тему дня. "
            "Приоритет: экстремальная/заметная погода; если её нет — крупный транспортный сбой; если и его нет — "
            "главная дорожная ситуация; если всё спокойно — просто характерная погода утра. "
            "Нельзя объединять дождь, поезд, трассу и другие события в одном кадре. Никаких коллажей. "
            "Верни только подробное описание ОДНОЙ реалистичной фотографии на английском, 45–90 слов. "
            "Не добавляй текст, табло, подписи и не выдумывай конкретные названия/цифры."
        )
    else:
        system = (
            "Ты фоторедактор. Из вечернего поста выдели РОВНО ОДИН главный объект/место/явление, о котором весь текст. "
            "Сформулируй одну реалистичную editorial-фотосцену на английском, 45–90 слов. "
            "Один объект, одна локация, один момент. Никаких коллажей, нескольких сюжетов, инфографики или текста на изображении. "
            "Если точная историческая деталь не гарантирована, опиши нейтральную документальную сцену без выдуманных идентификаторов."
        )
    try:
        response = await _get_client().messages.create(
            model=config.AI_POST_MODEL,
            max_tokens=180,
            system=system,
            messages=[{"role": "user", "content": text[:2600]}],
        )
        raw, _ = _extract_text_and_sources(response)
        brief = (raw or "").strip().replace("**", "")
        if brief:
            return brief[:1200]
    except Exception as exc:  # noqa: BLE001
        log.warning("Visual brief generation failed: %s", exc)

    # Safe fallback: one generic scene, never the whole multi-block brief.
    if kind == "morning":
        return "A single authentic early-morning documentary photograph in the Netherlands, showing the day's prevailing weather naturally in one coherent Dutch street or station environment, realistic light, no readable signs, no collage, no text."
    return "A single premium documentary photograph focused on the one Dutch place or object discussed in the story, one location and one moment, realistic natural detail, no collage, no text or invented signage."


def _single_scene_prompt(brief: str, kind: str) -> str:
    context = "early morning" if kind == "morning" else "editorial evening feature"
    return (
        f"Create ONE premium photorealistic {context} photograph for a modern Netherlands media publication. "
        "ONE scene only. ONE location only. ONE dominant subject only. Never combine multiple events, transport modes, "
        "weather situations, locations, panels, split screens or symbolic elements. This must look like a real professional "
        "editorial photograph shot on a full-frame camera in the Netherlands in 2026. No illustration, vector, 3D, collage, "
        "poster, infographic, typography, captions, logos, watermarks, fake UI or decorative flags. Natural optics and restrained "
        "editorial grading. Do not invent readable signs, delay boards, street names, statistics or factual claims.\n\n"
        "PHOTOGRAPHIC SCENE:\n" + brief
    )


async def _single_scene_image(text: str, kind: str) -> media.EditorialImage | None:
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key:
        return None
    brief = await _visual_brief(text, kind)
    model = os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1.5").strip() or "gpt-image-1.5"
    body = {
        "model": model,
        "prompt": _single_scene_prompt(brief, kind),
        "size": "1536x1024",
        "quality": "high",
        "output_format": "jpeg",
    }
    try:
        timeout = aiohttp.ClientTimeout(total=180)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                OPENAI_IMAGES_API,
                json=body,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            ) as response:
                if response.status >= 300:
                    log.warning("Single-scene image HTTP %s: %s", response.status, (await response.text())[:500])
                    return None
                payload = await response.json(content_type=None)
        encoded = ((payload.get("data") or [{}])[0]).get("b64_json")
        if not encoded:
            return None
        return media.EditorialImage(
            photo=BufferedInputFile(base64.b64decode(encoded), filename=f"editorial-{kind}.jpg"),
            attribution="Изображение создано ИИ",
            generated=True,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("Single-scene image generation failed: %s", exc)
        return None


_original_choose = media.choose_editorial_image


async def _quality_choose_editorial_image(text: str, kind: str):
    if kind in {"morning", "evening"}:
        return await _single_scene_image(text, kind)
    return await _original_choose(text, kind)


def install() -> None:
    # callback globals resolve these module attributes at runtime, so replacing them is sufficient.
    overrides._focused_evening_post = _robust_evening_post
    overrides.choose_editorial_image = _quality_choose_editorial_image
    editorial._evening_post = _robust_evening_post
    media.choose_editorial_image = _quality_choose_editorial_image
