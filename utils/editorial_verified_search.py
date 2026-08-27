"""Robust verified Web Search for every editorial format.

Keeps Web Search evidence across Anthropic pause_turn responses and never treats
an output cut by max_tokens as a finished editorial post.
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


def _trim_incomplete_tail(text: str) -> str:
    """Remove only a genuinely unfinished tail, preserving complete paragraphs."""
    clean = (text or "").strip()
    if not clean:
        return ""
    if clean.endswith((".", "!", "?", "…", ":", ")", "]", "❤️", "🔥")):
        return clean
    # A raw URL, date/price line or short label can validly end without punctuation.
    last_line = clean.splitlines()[-1].strip()
    if re.fullmatch(r"(?:https?://\S+|\d{1,2}[.\-/]\d{1,2}(?:[.\-/]\d{2,4})?|€\s?\d[\d,.]*)", last_line):
        return clean

    # Prefer the final complete sentence. Do not keep a visibly cut fragment such
    # as "Вечером в Лимбурге и Браб".
    boundaries = [m.end() for m in re.finditer(r"[.!?…](?=\s|$)", clean)]
    if boundaries:
        cut = boundaries[-1]
        if cut >= max(120, int(len(clean) * 0.55)):
            return clean[:cut].rstrip()
    return ""


async def _run_verified_search(client, **kwargs):
    """Run one paid generation and preserve search evidence across pause_turn."""
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
        "If one is inaccessible, continue with another trustworthy Dutch or official source. "
        "Never invent facts or URLs. Return ONLY the finished publication. "
        "Finish every sentence; never stop mid-word or mid-sentence."
        if preferred
        else "\n\nSOURCE POLICY: Perform a real Web Search before answering using trustworthy Dutch sources. "
             "Return ONLY the finished publication and finish every sentence."
    )

    tools = editorial._web_search_tool(None, max_uses=_search_limit())
    if not tools:
        return None

    # max_tokens is only a ceiling; raising it does not spend tokens unless the
    # model actually emits them. 1200 prevents the observed hard cut while the
    # format prompts still constrain normal post length.
    output_ceiling = max(1200, max_tokens)

    try:
        response, saw_search, errors, continuations = await _run_verified_search(
            editorial._get_client(),
            model=_editorial_model(),
            max_tokens=output_ceiling,
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
    stop_reason = _value(response, "stop_reason", "")

    if stop_reason == "max_tokens":
        completed = _trim_incomplete_tail(text)
        if not completed:
            editorial.log.warning("Editorial output hit max_tokens and has no safe completed ending")
            return None
        editorial.log.warning(
            "Editorial output hit max_tokens; safely removed unfinished tail (%d -> %d chars)",
            len(text), len(completed),
        )
        text = completed
    elif text:
        # Defensive check even for end_turn: never preview a visibly broken final
        # fragment if a provider/SDK edge case returned one.
        completed = _trim_incomplete_tail(text)
        if completed:
            text = completed

    if not text:
        editorial.log.warning(
            "Editorial Web Search ran but final text was empty/incomplete (stop_reason=%s, continuations=%d)",
            stop_reason, continuations,
        )
        return None

    if not sources:
        sources = _urls_from_text(text)

    editorial.log.info(
        "Verified editorial text accepted: %d chars, %d source URL(s), model=%s, search_limit=%d, continuations=%d, stop=%s",
        len(text), len(sources), _editorial_model(), _search_limit(), continuations, stop_reason,
    )
    return text, sources


def install_editorial_verified_search() -> None:
    # Installed last: every editorial format must use this one generator.
    editorial._generate = _verified_generate
