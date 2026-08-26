"""Robust verified Web Search for every editorial format.

Sonnet 5 can successfully execute Anthropic server Web Search and return a
factually grounded final text without attaching citation objects to that text.
Also, one crawler-blocked domain in allowed_domains causes Anthropic to reject
the entire request. This module verifies actual Web Search execution instead of
requiring citation metadata, and keeps the existing hard cost ceiling.
"""
from __future__ import annotations

import os
import re

import config
from utils import editorial_channel as editorial


def _editorial_model() -> str:
    return os.getenv("AI_EDITORIAL_MODEL", "claude-sonnet-5").strip() or "claude-sonnet-5"


def _search_limit() -> int:
    try:
        configured = int(os.getenv("AI_EDITORIAL_WEB_MAX_USES", "2"))
    except ValueError:
        configured = 2
    return max(1, min(configured, 2))


def _value(obj, name: str, default=None):
    return obj.get(name, default) if isinstance(obj, dict) else getattr(obj, name, default)


def _used_real_web_search(response) -> bool:
    for block in _value(response, "content", []) or []:
        btype = _value(block, "type", "")
        if btype == "web_search_tool_result":
            return True
        if btype == "server_tool_use" and _value(block, "name", "") == "web_search":
            return True
    return False


def _urls_from_text(text: str) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for url in re.findall(r"https?://[^\s<>\])}]+", text or ""):
        clean = url.rstrip(".,;:!?\"'")
        if clean and clean not in seen:
            seen.add(clean)
            result.append(clean)
    return result


async def _verified_generate(system: str, user: str, domains: list[str], max_tokens: int = 900):
    if not editorial.ai_enabled() or not config.AI_WEB_SEARCH:
        return None

    # Do NOT send allowed_domains. Anthropic rejects the whole request when even
    # one listed site blocks its crawler. Keep the desired source set as editorial
    # guidance instead, so the search can fall back gracefully.
    preferred = ", ".join(dict.fromkeys(domains or []))
    source_guidance = (
        "\n\nSOURCE POLICY: Perform a real Web Search before answering. "
        "Prioritize these Dutch sources when relevant: " + preferred + ". "
        "If one of them is inaccessible, continue with another trustworthy Dutch or official source. "
        "Never invent facts or URLs."
        if preferred
        else "\n\nSOURCE POLICY: Perform a real Web Search before answering and use trustworthy Dutch sources."
    )

    tools = editorial._web_search_tool(None, max_uses=_search_limit())
    if not tools:
        return None

    try:
        response = await editorial._create_with_server_tool_continuation(
            editorial._get_client(),
            model=_editorial_model(),
            max_tokens=max_tokens,
            system=system + source_guidance,
            messages=[{"role": "user", "content": user}],
            tools=tools,
            max_continuations=1,
        )
    except Exception as exc:  # noqa: BLE001
        editorial.log.warning("Verified editorial Web Search failed: %s", exc)
        return None

    errors = editorial._web_search_errors(response)
    if errors:
        editorial.log.warning("Verified editorial Web Search tool errors: %s", ", ".join(errors))
        return None
    if not _used_real_web_search(response):
        editorial.log.warning("Editorial response rejected: no actual Web Search execution")
        return None

    text, sources = editorial._extract_text_and_sources(response)
    text = editorial._clean_text(text)
    if not text:
        editorial.log.warning("Editorial Web Search succeeded but final text was empty")
        return None

    # Citation objects are useful but are NOT a validity requirement. Sonnet 5
    # may omit them even after a real server-side search. Preserve explicit URLs
    # present in the final text as source metadata where available.
    if not sources:
        sources = _urls_from_text(text)

    editorial.log.info(
        "Verified editorial text accepted: %d chars, %d source URL(s), model=%s, search_limit=%d",
        len(text), len(sources), _editorial_model(), _search_limit(),
    )
    return text, sources


def install_editorial_verified_search() -> None:
    # Must be installed after budget_photo, which otherwise replaces _generate.
    editorial._generate = _verified_generate
