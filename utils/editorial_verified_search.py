"""Robust verified Web Search for every editorial format.

The editorial pipeline must accept Anthropic server Web Search that spans a
``pause_turn`` continuation. Search tool blocks can live in the first response
while the final prose lives in the continuation, so validating only the last
response incorrectly rejects successful generations.
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


async def _run_verified_search(client, **kwargs):
    """Run one request and preserve search evidence across pause_turn.

    Anthropic can return tool-use/search-result blocks in the first response and
    the final prose only in a continuation. The old code inspected only the last
    response and falsely concluded that Web Search had not happened.
    """
    request = dict(kwargs)
    messages = list(request.get("messages") or [])
    saw_search = False
    all_errors: list[str] = []

    response = await client.messages.create(**request)
    saw_search = saw_search or _used_real_web_search(response)
    for code in editorial._web_search_errors(response):
        if code not in all_errors:
            all_errors.append(code)

    continuations = 0
    while _value(response, "stop_reason", None) == "pause_turn" and continuations < 1:
        messages.append({"role": "assistant", "content": _value(response, "content", [])})
        request["messages"] = messages
        continuations += 1
        response = await client.messages.create(**request)
        saw_search = saw_search or _used_real_web_search(response)
        for code in editorial._web_search_errors(response):
            if code not in all_errors:
                all_errors.append(code)

    return response, saw_search, all_errors, continuations


async def _verified_generate(system: str, user: str, domains: list[str], max_tokens: int = 900):
    if not editorial.ai_enabled() or not config.AI_WEB_SEARCH:
        return None

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
        response, saw_search, errors, continuations = await _run_verified_search(
            editorial._get_client(),
            model=_editorial_model(),
            max_tokens=max_tokens,
            system=system + source_guidance,
            messages=[{"role": "user", "content": user}],
            tools=tools,
        )
    except Exception as exc:  # noqa: BLE001
        editorial.log.warning("Verified editorial Web Search failed: %s", exc)
        return None

    if errors:
        editorial.log.warning("Verified editorial Web Search tool errors: %s", ", ".join(errors))
        return None
    if not saw_search:
        editorial.log.warning("Editorial response rejected: no Web Search execution across all turns")
        return None

    text, sources = editorial._extract_text_and_sources(response)
    text = editorial._clean_text(text)
    if not text:
        editorial.log.warning(
            "Editorial Web Search ran but final text was empty (stop_reason=%s, continuations=%d)",
            _value(response, "stop_reason", ""), continuations,
        )
        return None

    if not sources:
        sources = _urls_from_text(text)

    editorial.log.info(
        "Verified editorial text accepted: %d chars, %d source URL(s), model=%s, search_limit=%d, continuations=%d",
        len(text), len(sources), _editorial_model(), _search_limit(), continuations,
    )
    return text, sources


def install_editorial_verified_search() -> None:
    # Must be installed after budget_photo, which otherwise replaces _generate.
    editorial._generate = _verified_generate
