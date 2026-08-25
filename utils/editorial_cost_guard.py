"""Hard cost guard for editorial AI usage.

Editorial content must never silently use an expensive Sonnet model or fan out
into many paid web-search calls. User chat already uses Haiku; editorial now
uses the same low-cost model and one web-search use per generation.
"""
from __future__ import annotations

from aiogram.types import Message

import config
from utils import editorial_channel as editorial
from utils import editorial_overrides as overrides
from utils import editorial_websearch_fix as webfix
from utils.ai import (
    _create_with_server_tool_continuation,
    _extract_text_and_sources,
    _get_client,
    _web_search_errors,
    _web_search_tool,
    ai_enabled,
)

# One server-side search per generation. No hidden 6-search fan-out.
EDITORIAL_WEB_MAX_USES = 1


async def _economy_generate(system: str, user: str, domains: list[str], max_tokens: int = 900):
    if not ai_enabled() or not config.AI_WEB_SEARCH:
        return None
    tools = _web_search_tool(domains, max_uses=EDITORIAL_WEB_MAX_USES)
    if not tools:
        return None
    try:
        response = await _create_with_server_tool_continuation(
            _get_client(),
            # HARD RULE: editorial uses Haiku-class chat model, never AI_POST_MODEL/Sonnet.
            model=config.AI_CHAT_MODEL,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            tools=tools,
            max_continuations=1,
        )
    except Exception as exc:  # noqa: BLE001
        editorial.log.warning("Economy editorial generation failed: %s", exc)
        return None
    if _web_search_errors(response):
        return None
    text, sources = _extract_text_and_sources(response)
    text = editorial._clean_text(text)
    return (text, sources) if text and sources else None


async def _cheap_health(message: Message) -> None:
    """Zero-token health check. A real paid probe must never run by accident."""
    if message.from_user.id not in config.ADMIN_IDS:
        return
    openai_ok, openai_detail = await overrides._check_openai_image_access()
    channel_ok, channel_detail = await overrides._channel_health(message.bot)
    anthropic_key = bool(config.ANTHROPIC_API_KEY)
    lines = [
        "🩺 Editorial Health · ECONOMY",
        "",
        f"{'✅' if anthropic_key else '❌'} Anthropic key: {'задан' if anthropic_key else 'отсутствует'}",
        f"✅ Editorial model: {config.AI_CHAT_MODEL} (Haiku / economy)",
        f"✅ Web Search limit: {EDITORIAL_WEB_MAX_USES} на генерацию",
        f"{'✅' if openai_ok else '❌'} OpenAI Images: {openai_detail}",
        f"{'✅' if channel_ok else '❌'} Канал/права: {channel_detail}",
        "",
        "Важно: эта команда НЕ делает платный Anthropic-запрос.",
    ]
    await message.answer("\n".join(lines), parse_mode=None)


def _replace_health_handler() -> None:
    try:
        for handler in overrides.router.message.handlers:
            callback = getattr(handler, "callback", None)
            if getattr(callback, "__name__", "") in {"editorial_health_command", "editorial_health_real"}:
                handler.callback = _cheap_health
    except Exception as exc:  # noqa: BLE001
        editorial.log.warning("Could not replace editorial health with economy version: %s", exc)


def install_editorial_cost_guard() -> None:
    # All editorial generators resolve editorial._generate at runtime.
    editorial._generate = _economy_generate
    # Keep only two evening source families: maximum two paid model attempts.
    webfix.EVENING_SOURCE_GROUPS = webfix.EVENING_SOURCE_GROUPS[:2]
    _replace_health_handler()
