"""Diversity guard for scheduled editorial posts.

The old runtime remembered only the first line of the last 12 posts. That was too
weak: the model could write the same subject again with a different headline.
This layer rotates broad topic lanes and rejects near-duplicate generated text
before it reaches the admin preview.
"""
from __future__ import annotations

import re

from utils import editorial_channel as editorial

RECENT_BODY_SLOTS = 30

TOPIC_LANES = (
    "городская среда и архитектура: конкретный дом, улица, мост, станция, знак или необычная деталь города",
    "повседневные правила и бюрократия: конкретное правило, привычка учреждения или устройство сервиса",
    "язык и выражения: происхождение одного слова, названия, выражения или языковой привычки",
    "еда и повседневные покупки: один продукт, магазинная привычка, упаковка, рынок или бытовая деталь",
    "транспорт и инфраструктура: железная дорога, дороги, вода, инженерное решение или организация движения",
    "дом и бытовая жизнь: жильё, отопление, окна, мусор, почта, коммунальная или соседская практика",
    "история одного предмета или места: конкретный объект с проверяемой историей и связью с сегодняшним днём",
    "природа и общественное пространство: парк, дюны, вода, животные, озеленение или управление публичным пространством",
    "культура и досуг: музейный объект, локальная традиция, театр, музыка, праздник или городской ритуал",
    "работа и социальная жизнь: одна конкретная рабочая, школьная или общественная практика в Нидерландах",
)

_STOP = {
    "это", "как", "что", "для", "или", "при", "его", "она", "они", "был", "была", "были",
    "есть", "так", "уже", "ещё", "этот", "эта", "эти", "того", "только", "очень", "один", "одна",
    "нидерланды", "нидерландах", "голландии", "голландский", "голландцы", "сегодня", "почему",
}


def _tokens(text: str) -> set[str]:
    words = re.findall(r"[a-zа-яё0-9]{4,}", (text or "").casefold())
    return {w for w in words if w not in _STOP}


def _signature(text: str) -> str:
    clean = re.sub(r"\s+", " ", (text or "").strip())
    clean = re.sub(r"Если .*?[❤️🔥]$", "", clean).strip()
    return clean[:100]


async def _recent_bodies() -> list[str]:
    out = []
    for i in range(RECENT_BODY_SLOTS):
        value = await editorial._meta_get(f"editorial_body_{i}")
        if value:
            out.append(value)
    return out


async def _remember_body(text: str) -> None:
    sig = _signature(text)
    if not sig:
        return
    recent = await _recent_bodies()
    values = [sig] + [x for x in recent if x.casefold() != sig.casefold()]
    for i, value in enumerate(values[:RECENT_BODY_SLOTS]):
        await editorial._meta_set(f"editorial_body_{i}", value)


def _too_similar(candidate: str, recent: list[str]) -> bool:
    cand = _tokens(candidate)
    if len(cand) < 4:
        return False
    for old in recent:
        prev = _tokens(old)
        if len(prev) < 3:
            continue
        overlap = len(cand & prev)
        union = len(cand | prev)
        jaccard = overlap / union if union else 0.0
        containment = overlap / min(len(cand), len(prev))
        if jaccard >= 0.34 or (overlap >= 4 and containment >= 0.58):
            return True
    return False


async def _diverse_evening_post() -> str | None:
    recent = await _recent_bodies()
    lane_index = editorial._now().date().toordinal() % len(TOPIC_LANES)
    lane = TOPIC_LANES[lane_index]
    recent_text = " | ".join(recent[:18]) or "нет"

    system = (
        "Ты вечерний редактор Telegram-канала для русскоязычных жителей Нидерландов. "
        "Нужен ОДИН самостоятельный сюжет, а не вариация вчерашней темы. "
        f"Сегодня обязательное направление: {lane}. "
        "Выбери конкретный объект, правило, место, вещь, слово или практику. Нельзя брать ту же сущность, "
        "тот же город+объект или тот же объяснительный тезис, который уже встречался в недавних постах. "
        "Запрещены банальности про тюльпаны, велосипеды, мельницы, уровень моря, кофешопы, красные фонари, "
        "деревянные башмаки и прямолинейность. Проверь факты веб-поиском. 520-780 знаков. "
        "Живой русский язык, один сюжет, без markdown, HTML и маркетингового CTA."
    )
    user = (
        f"Сегодня {editorial._now():%d.%m.%Y}. Недавние темы/начала постов, которые нельзя повторять: {recent_text}. "
        "Сначала мысленно сравни новую тему с этим списком и выбери действительно другой сюжет."
    )
    result = await editorial._generate(system, user, editorial.EVENING_SOURCES, 850)
    if not result:
        return None
    text = result[0]
    if not _too_similar(text, recent):
        return text

    # Only duplicates pay for one retry. Normal days still use one generation.
    retry = await editorial._generate(
        system + " Первая попытка оказалась слишком похожа на недавний пост. Выбери ДРУГУЮ сущность и другой угол.",
        user,
        editorial.EVENING_SOURCES,
        850,
    )
    if not retry or _too_similar(retry[0], recent):
        return None
    return retry[0]


async def _diverse_curiosity_post() -> str | None:
    recent = await _recent_bodies()
    lane_index = (editorial._now().date().toordinal() + 4) % len(TOPIC_LANES)
    lane = TOPIC_LANES[lane_index]
    system = (
        "Ты редактор познавательного Telegram-поста о Нидерландах. Нужен небанальный проверяемый сюжет, "
        f"сегодня направление: {lane}. Не повторяй сущности и тезисы из недавних постов. "
        "Никаких общих фактов и туристических клише. Сначала конкретная деталь, затем объяснение и связь с сегодняшней жизнью. "
        "Проверь факты по надёжным нидерландским источникам. 650-950 знаков, без markdown и HTML."
    )
    result = await editorial._generate(
        system,
        f"Недавние темы: {' | '.join(recent[:18]) or 'нет'}.",
        editorial.FACT_SOURCES,
        900,
    )
    if not result or _too_similar(result[0], recent):
        return None
    return result[0]


def install_editorial_diversity() -> None:
    editorial._evening_post = _diverse_evening_post
    editorial._curiosity_post = _diverse_curiosity_post

    original_publish = editorial._publish_editorial

    async def publish_with_memory(bot, kind: str, text: str, button: bool) -> bool:
        ok = await original_publish(bot, kind, text, button)
        if ok and kind in {"event", "curiosity", "evening"}:
            await _remember_body(text)
        return ok

    editorial._publish_editorial = publish_with_memory
