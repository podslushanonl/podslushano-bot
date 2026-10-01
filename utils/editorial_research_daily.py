"""One low-cost automatic editorial radar run per day at 08:00 Amsterdam time.

Manual /ideas searches remain available through editorial_research_desk, but the
automatic scheduler no longer launches several independent Sonnet searches on
different days/times. One Haiku request performs a combined morning scan and
routes the strongest findings to the existing newsroom topics.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, time
from zoneinfo import ZoneInfo

import config
from utils import editorial_channel as editorial
from utils import editorial_research_desk as desk
from utils.ai import (
    _create_with_server_tool_continuation,
    _extract_text_and_sources,
    _get_client,
    _web_search_errors,
    _web_search_tool,
)

log = logging.getLogger(__name__)
AMSTERDAM = ZoneInfo("Europe/Amsterdam")
DAILY_START = time(8, 0)
DAILY_END = time(9, 0)
DAILY_META_KEY = "research_daily_0800_date"
DAILY_ATTEMPT_KEY = "research_daily_0800_attempt_date"
AUTO_STREAM_KEYS = (
    "morning",
    "people",
    "events",
    "provinces",
    "calendar",
    "buzz",
    "evergreen",
)
MAX_DAILY_IDEAS = 8


def _now() -> datetime:
    return datetime.now(AMSTERDAM).replace(tzinfo=None)


def _is_due(now: datetime) -> bool:
    return DAILY_START <= now.time() < DAILY_END


def _automatic_streams() -> list[desk.ResearchStream]:
    return [desk.STREAM_BY_KEY[key] for key in AUTO_STREAM_KEYS]


def _batch_system_prompt() -> str:
    categories = "\n".join(
        f"- {stream.key} — {stream.label}: {stream.instructions}"
        for stream in _automatic_streams()
    )
    return f"""Ты — выпускающий редактор Podslushano.nl, русскоязычного медиа о Нидерландах.
Сделай ОДИН объединённый утренний веб-поиск вместо отдельных запросов по рубрикам.

Рубрики:
{categories}

Отбери максимум {MAX_DAILY_IDEAS} действительно сильных тем СУММАРНО по всем рубрикам.
Не обязан заполнять каждую рубрику. Лучше 3 сильные темы, чем 8 проходных. На одну рубрику —
не более двух тем. Не дублируй одну историю в разных рубриках.

Тема проходит только если есть конкретное новое событие/решение/редкость/неожиданный факт,
понятная ценность для русскоязычных жителей Нидерландов и проверяемая доказательная база.
Отбрасывай рутинные анонсы gemeente, бытовую криминальную хронику без широкой значимости,
банальности про велосипеды/тюльпаны/каналы, слухи и единичные вирусные посты без подтверждения.
Оцени по 12 баллам: актуальность 0–3, эмоция 0–3, польза 0–2, визуал/доказательства 0–2,
срочность 0–2. Не возвращай темы ниже 8 баллов.

Для официальных правил, денег, документов, транспорта и госрешений опирайся прежде всего на
официальные источники. Для каждой темы дай хотя бы одну прямую подтверждающую ссылку.

Верни ТОЛЬКО валидный JSON без markdown:
{{
  "editor_note": "одна короткая строка о результате утреннего поиска",
  "ideas": [
    {{
      "stream_key": "morning|people|events|provinces|calendar|buzz|evergreen",
      "headline": "короткий конкретный заголовок",
      "verdict": "now|develop",
      "score": 10,
      "hook": "сильный угол будущей публикации",
      "what_happened": "2–3 предложения с конкретикой",
      "why_now": "почему тема актуальна именно сейчас",
      "audience_value": "почему это важно или интересно аудитории",
      "format": "карусель|пост|Stories|Reels|Telegram",
      "visual": "конкретные реальные материалы для визуала",
      "source_urls": ["прямая подтверждающая ссылка"]
    }}
  ]
}}
Не пиши готовые посты."""


def _parse_batch(raw: str, tool_sources: list[str]) -> tuple[str, dict[str, list[dict]]] | None:
    clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", (raw or "").strip())
    start, end = clean.find("{"), clean.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        source = json.loads(clean[start:end + 1])
    except (TypeError, ValueError):
        return None
    raw_ideas = source.get("ideas")
    if not isinstance(raw_ideas, list):
        return None

    grouped: dict[str, list[dict]] = {key: [] for key in AUTO_STREAM_KEYS}
    for raw_item in raw_ideas[:MAX_DAILY_IDEAS]:
        if not isinstance(raw_item, dict):
            continue
        stream_key = str(raw_item.get("stream_key") or "").strip()
        if stream_key not in grouped or len(grouped[stream_key]) >= 2:
            continue
        # Reuse the existing strict card validator so manual and automatic radar
        # have exactly the same quality floor and field limits.
        normalized = desk._parse_payload(
            json.dumps({"editor_note": "", "ideas": [raw_item]}, ensure_ascii=False),
            tool_sources,
        )
        if normalized and normalized.get("ideas"):
            grouped[stream_key].append(normalized["ideas"][0])

    note = str(source.get("editor_note") or "").strip()[:500]
    return note, grouped


async def _generate_daily_batch() -> tuple[str, dict[str, list[dict]]] | None:
    recent = await desk._recent_ideas()
    published = await editorial._recent_topics()
    exclusions = " | ".join((recent + published)[:30]) or "нет"
    feedback = await desk._feedback_prompt()
    user = (
        f"Сегодня {_now():%d.%m.%Y}, Europe/Amsterdam. Это единственная автоматическая проверка за день.\n"
        f"Не повторяй без существенного развития: {exclusions}.\n{feedback}"
    )
    tools = _web_search_tool(max_uses=4)
    kwargs = dict(
        model=config.AI_CHAT_MODEL,
        max_tokens=3600,
        system=_batch_system_prompt(),
        messages=[{"role": "user", "content": user}],
    )
    if tools:
        kwargs["tools"] = tools

    try:
        async with desk._generation_lock:
            response = await _create_with_server_tool_continuation(
                _get_client(), max_continuations=1, **kwargs
            )
    except Exception as exc:  # noqa: BLE001
        log.exception("Daily editorial research failed: %s", exc)
        return None

    if _web_search_errors(response):
        return None
    text, sources = _extract_text_and_sources(response)
    return _parse_batch(text, sources)


async def _deliver_batch(bot, note: str, grouped: dict[str, list[dict]]) -> bool:
    delivered_any = False
    total = sum(len(items) for items in grouped.values())
    for key in AUTO_STREAM_KEYS:
        items = grouped.get(key) or []
        if not items:
            continue
        stream = desk.STREAM_BY_KEY[key]
        payload = {
            "editor_note": (
                f"Единый утренний поиск 08:00 · всего отобрано {total}. "
                + (note or "Ниже только темы, прошедшие отбор.")
            )[:500],
            "ideas": items,
        }
        if await desk._deliver_digest(bot, stream, payload):
            delivered_any = True
            await desk._remember_ideas(payload)

    if delivered_any:
        return True

    # Valid search with zero strong ideas: send exactly one lightweight status
    # message instead of empty notices to every newsroom topic.
    morning = desk.STREAM_BY_KEY["morning"]
    payload = {
        "editor_note": (
            "Единый утренний поиск 08:00 завершён. "
            + (note or "Сегодня тем, прошедших жёсткий отбор, нет.")
        )[:500],
        "ideas": [],
    }
    return await desk._deliver_digest(bot, morning, payload)


async def _alert_failure(bot) -> None:
    for admin_id in config.ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                "⚠️ Утренний радар инфоповодов: поиск в 08:00 не завершён. "
                "Автоматического повтора сегодня не будет, чтобы не тратить бюджет. "
                "При необходимости запусти нужную рубрику вручную через /ideas.",
                parse_mode=None,
            )
        except Exception:  # noqa: BLE001
            pass


async def _run_once_if_due(bot, now: datetime) -> bool:
    today = now.date().isoformat()
    if not _is_due(now):
        return False
    if await editorial._meta_get(DAILY_META_KEY) == today:
        return False
    if await editorial._meta_get(DAILY_ATTEMPT_KEY) == today:
        return False

    # Mark BEFORE the paid request. Even if the provider fails, there is no
    # automatic retry loop and therefore no accidental spend spike.
    await editorial._meta_set(DAILY_ATTEMPT_KEY, today)
    result = await _generate_daily_batch()
    if result is None:
        await _alert_failure(bot)
        return False

    note, grouped = result
    if not await _deliver_batch(bot, note, grouped):
        await _alert_failure(bot)
        return False

    await editorial._meta_set(DAILY_META_KEY, today)
    return True


async def editorial_research_loop(bot) -> None:
    """Check the clock cheaply; make at most one paid research attempt per day."""
    await asyncio.sleep(20)
    while True:
        try:
            await _run_once_if_due(bot, _now())
        except Exception as exc:  # noqa: BLE001
            log.exception("Daily editorial scheduler failed: %s", exc)
        await asyncio.sleep(30)
