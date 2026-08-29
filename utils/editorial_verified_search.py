"""Single verified Anthropic Web Search pipeline for every editorial format.

One implementation owns text generation for morning, event, curiosity and evening.
It keeps search evidence across pause_turn, records a free diagnostic of the last
real failure, and never accepts a visibly truncated final post.
"""
from __future__ import annotations

import os
import re

import config
from utils import editorial_channel as editorial

MAX_CONTINUATIONS = 2
LAST_ERROR_KEY = "editorial_last_error"
LAST_STATUS_KEY = "editorial_last_status"


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


def _search_state(response) -> tuple[bool, bool, list[str]]:
    """Return (tool_used, successful_result_seen, error_codes)."""
    used = False
    success = False
    errors: list[str] = []
    for block in _value(response, "content", []) or []:
        btype = _value(block, "type", "")
        if btype == "server_tool_use" and _value(block, "name", "") == "web_search":
            used = True
            continue
        if btype != "web_search_tool_result":
            continue
        used = True
        content = _value(block, "content")
        items = content if isinstance(content, list) else [content]
        if not items:
            # The server executed the search but returned no result items.
            success = True
            continue
        block_had_success = False
        for item in items:
            if item and _value(item, "type", "") == "web_search_tool_result_error":
                code = _value(item, "error_code", "unknown")
                if code not in errors:
                    errors.append(code)
            elif item is not None:
                block_had_success = True
        success = success or block_had_success
    return used, success, errors


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
    """Drop an obviously unfinished tail without shortening a complete post."""
    clean = (text or "").strip()
    if not clean:
        return ""
    if clean.endswith((".", "!", "?", "…", ":", ")", "]", "❤️", "🔥")):
        return clean
    last_line = clean.splitlines()[-1].strip()
    if re.fullmatch(r"(?:https?://\S+|\d{1,2}[.\-/]\d{1,2}(?:[.\-/]\d{2,4})?|€\s?\d[\d,.]*)", last_line):
        return clean
    boundaries = [m.end() for m in re.finditer(r"[.!?…](?=\s|$)", clean)]
    if boundaries:
        cut = boundaries[-1]
        if cut >= max(120, int(len(clean) * 0.55)):
            return clean[:cut].rstrip()
    return ""


async def _diag(status: str, detail: str = "") -> None:
    """Persist a short diagnostic for /editorialhealth without another API call."""
    try:
        await editorial._meta_set(LAST_STATUS_KEY, status[:95])
        await editorial._meta_set(LAST_ERROR_KEY, detail[:95] if detail else "")
    except Exception:  # diagnostics must never break generation
        pass


async def _run_verified_search(client, **kwargs):
    """Run one controlled server Web Search conversation.

    We intentionally do not force tool_choice. The system prompt requires a
    search, and the verifier below rejects a response where the server tool did
    not actually run. This avoids coupling production to optional tool-choice
    request shapes while keeping factual verification mandatory.
    """
    request = dict(kwargs)
    messages = list(request.get("messages") or [])
    saw_use = False
    saw_success = False
    all_errors: list[str] = []

    response = await client.messages.create(**request)

    def inspect(resp) -> None:
        nonlocal saw_use, saw_success
        used, successful, errors = _search_state(resp)
        saw_use = saw_use or used
        saw_success = saw_success or successful
        for code in errors:
            if code not in all_errors:
                all_errors.append(code)

    inspect(response)
    continuations = 0
    while _value(response, "stop_reason", None) == "pause_turn" and continuations < MAX_CONTINUATIONS:
        messages.append({"role": "assistant", "content": _value(response, "content", [])})
        request["messages"] = messages
        continuations += 1
        response = await client.messages.create(**request)
        inspect(response)

    return response, saw_use, saw_success, all_errors, continuations


async def _verified_generate(system: str, user: str, domains: list[str], max_tokens: int = 900):
    if not editorial.ai_enabled() or not config.AI_WEB_SEARCH:
        await _diag("disabled", "Anthropic key or AI_WEB_SEARCH disabled")
        editorial.log.warning("Editorial generation unavailable: AI or Web Search disabled")
        return None

    preferred = ", ".join(dict.fromkeys(domains or []))
    source_guidance = (
        "\n\nSOURCE POLICY: You MUST use Web Search before answering. "
        "Prioritize these Dutch sources when relevant: " + preferred + ". "
        "If one is inaccessible, continue with another trustworthy Dutch or official source. "
        "Never invent facts or URLs. Return only the finished publication, never your search process. "
        "Finish every sentence; never stop mid-word or mid-sentence."
        if preferred
        else "\n\nSOURCE POLICY: You MUST use Web Search before answering and rely on trustworthy Dutch sources. "
             "Return only the finished publication and finish every sentence."
    )

    tools = editorial._web_search_tool(None, max_uses=_search_limit())
    if not tools:
        await _diag("tool_missing", "web_search tool was not constructed")
        return None

    # Ceiling only: Anthropic bills generated tokens, not an unused max_tokens allowance.
    output_ceiling = max(int(max_tokens), 1200)
    try:
        response, saw_use, saw_success, errors, continuations = await _run_verified_search(
            editorial._get_client(),
            model=_editorial_model(),
            max_tokens=output_ceiling,
            thinking={"type": "disabled"},
            system=system + source_guidance,
            messages=[{"role": "user", "content": user}],
            tools=tools,
        )
    except Exception as exc:  # noqa: BLE001
        detail = f"{type(exc).__name__}: {exc}"
        await _diag("request_error", detail)
        editorial.log.exception("Editorial Anthropic request failed: %s", exc)
        return None

    stop_reason = _value(response, "stop_reason", "")
    if not saw_use:
        await _diag("no_search", f"stop={stop_reason}; continuations={continuations}")
        editorial.log.warning("Editorial response rejected: Web Search was not observed")
        return None
    if not saw_success:
        detail = ",".join(errors) or "no successful web_search result"
        await _diag("search_error", detail)
        editorial.log.warning("Editorial Web Search had no successful result: %s", detail)
        return None
    # A later max_uses/rate error must not destroy already researched final prose.
    if errors:
        editorial.log.warning("Editorial Web Search also reported non-fatal errors after a successful search: %s", ", ".join(errors))
    if stop_reason == "pause_turn":
        await _diag("pause_turn", f"still paused after {continuations} continuations")
        return None
    if stop_reason == "refusal":
        await _diag("refusal", "Anthropic refused editorial request")
        return None

    text, sources = editorial._extract_text_and_sources(response)
    text = editorial._clean_text(text)
    if stop_reason == "max_tokens":
        completed = _trim_incomplete_tail(text)
        if not completed:
            await _diag("truncated", "max_tokens with no safe completed ending")
            return None
        editorial.log.warning("Editorial output hit max_tokens; trimmed unfinished tail %d -> %d chars", len(text), len(completed))
        text = completed
    elif text:
        completed = _trim_incomplete_tail(text)
        if completed:
            text = completed

    if not text:
        await _diag("empty_text", f"stop={stop_reason}; continuations={continuations}")
        editorial.log.warning("Editorial Web Search completed but final text was empty/incomplete")
        return None
    if not sources:
        sources = _urls_from_text(text)

    await _diag("ok", f"{len(text)} chars; stop={stop_reason or 'unknown'}")
    editorial.log.info(
        "Editorial text accepted: %d chars, %d URL(s), model=%s, search_limit=%d, continuations=%d, stop=%s",
        len(text), len(sources), _editorial_model(), _search_limit(), continuations, stop_reason,
    )
    return text, sources


def install_editorial_verified_search() -> None:
    editorial._generate = _verified_generate
