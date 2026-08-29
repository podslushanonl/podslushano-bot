import asyncio
import os
import sys
from importlib.metadata import version
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("BOT_TOKEN", "123456:test")
os.environ.setdefault("ADMIN_IDS", "1")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("AI_WEB_SEARCH", "true")
os.environ.setdefault("AI_EDITORIAL_MODEL", "claude-sonnet-5")

import config
from utils import editorial_channel as editorial
from utils import editorial_websearch_fix as webfix
from utils import editorial_verified_search as verified
from utils import editorial_budget_photo as budget


class FakeMessages:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self.responses:
            raise AssertionError("unexpected extra Anthropic call")
        return self.responses.pop(0)


class FakeClient:
    def __init__(self, responses):
        self.messages = FakeMessages(responses)


def block(kind, **kwargs):
    return SimpleNamespace(type=kind, **kwargs)


def response(stop_reason, content):
    return SimpleNamespace(stop_reason=stop_reason, content=content)


def test_modern_anthropic_sdk_is_installed():
    parts = version("anthropic").split(".")
    major = int(parts[0])
    minor = int(parts[1]) if len(parts) > 1 else 0
    assert major >= 1 or (major == 0 and minor >= 121), version("anthropic")


async def test_pause_turn_and_sonnet5_request_shape():
    r1 = response("pause_turn", [
        block("server_tool_use", name="web_search"),
        block("web_search_tool_result", content=[]),
    ])
    r2 = response("pause_turn", [
        block("server_tool_use", name="web_search"),
        block("web_search_tool_result", content=[]),
    ])
    r3 = response("end_turn", [block("text", text="Готовый проверенный пост.", citations=[])])
    client = FakeClient([r1, r2, r3])

    old_get_client = editorial._get_client
    old_ai_enabled = editorial.ai_enabled
    old_web = config.AI_WEB_SEARCH
    old_meta_set = editorial._meta_set
    try:
        editorial._get_client = lambda: client
        editorial.ai_enabled = lambda: True
        config.AI_WEB_SEARCH = True
        editorial._meta_set = lambda key, value: asyncio.sleep(0)
        result = await verified._verified_generate("system", "user", ["knmi.nl"], 700)
    finally:
        editorial._get_client = old_get_client
        editorial.ai_enabled = old_ai_enabled
        config.AI_WEB_SEARCH = old_web
        editorial._meta_set = old_meta_set

    assert result and result[0] == "Готовый проверенный пост."
    assert len(client.messages.calls) == 3
    first, second, third = client.messages.calls
    assert first["model"] == "claude-sonnet-5"
    assert first["thinking"] == {"type": "disabled"}
    assert first["max_tokens"] >= 1200
    # Do not depend on optional tool_choice request shapes: Web Search is required
    # by the prompt and independently verified from actual server-tool blocks.
    assert "tool_choice" not in first
    assert "tool_choice" not in second
    assert "tool_choice" not in third
    assert first["tools"][0]["max_uses"] <= 2


async def test_successful_search_survives_later_nonfatal_tool_error():
    ok = block("web_search_tool_result", content=[])
    error_item = block("web_search_tool_result_error", error_code="max_uses_exceeded")
    r1 = response("pause_turn", [block("server_tool_use", name="web_search"), ok])
    r2 = response("end_turn", [
        block("web_search_tool_result", content=[error_item]),
        block("text", text="Финальный текст после уже успешного поиска.", citations=[]),
    ])
    client = FakeClient([r1, r2])
    old_get_client = editorial._get_client
    old_ai_enabled = editorial.ai_enabled
    old_web = config.AI_WEB_SEARCH
    old_meta_set = editorial._meta_set
    try:
        editorial._get_client = lambda: client
        editorial.ai_enabled = lambda: True
        config.AI_WEB_SEARCH = True
        editorial._meta_set = lambda key, value: asyncio.sleep(0)
        result = await verified._verified_generate("system", "user", ["knmi.nl"], 700)
    finally:
        editorial._get_client = old_get_client
        editorial.ai_enabled = old_ai_enabled
        config.AI_WEB_SEARCH = old_web
        editorial._meta_set = old_meta_set
    assert result and result[0].endswith("поиска.")


async def test_truncated_output_never_keeps_broken_tail():
    r1 = response("max_tokens", [
        block("server_tool_use", name="web_search"),
        block("web_search_tool_result", content=[]),
        block("text", text="Первое предложение полностью закончено. Второе тоже закончено. Вечером в Лимбурге и Браб", citations=[]),
    ])
    client = FakeClient([r1])
    old_get_client = editorial._get_client
    old_ai_enabled = editorial.ai_enabled
    old_web = config.AI_WEB_SEARCH
    old_meta_set = editorial._meta_set
    try:
        editorial._get_client = lambda: client
        editorial.ai_enabled = lambda: True
        config.AI_WEB_SEARCH = True
        editorial._meta_set = lambda key, value: asyncio.sleep(0)
        result = await verified._verified_generate("system", "user", ["knmi.nl"], 700)
    finally:
        editorial._get_client = old_get_client
        editorial.ai_enabled = old_ai_enabled
        config.AI_WEB_SEARCH = old_web
        editorial._meta_set = old_meta_set
    assert result
    assert "Браб" not in result[0]
    assert result[0].endswith("закончено.")


async def test_all_four_formats_share_one_generator():
    calls = []
    sample = (
        "Это тестовый проверенный редакционный материал о Нидерландах с конкретным сюжетом, "
        "контекстом и практической деталью. Он намеренно длиннее минимального порога вечерней "
        "рубрики, чтобы интеграционный тест проверял реальный production-путь, а не обходил "
        "защиту от слишком коротких публикаций. В конце остаётся ещё одна содержательная фраза."
    )

    async def fake_generate(system, user, domains, max_tokens=900):
        calls.append((system, tuple(domains), max_tokens))
        return sample, ["https://example.nl/source"]

    old_generate = editorial._generate
    old_recent = editorial._recent_topics
    try:
        webfix.install_editorial_websearch_fix()
        budget.install_editorial_budget_photo()
        verified.install_editorial_verified_search()
        assert editorial._generate is verified._verified_generate
        assert editorial._run_generated is budget._budgeted_run_generated
        assert editorial._run_morning is budget._budgeted_run_morning
        assert editorial._run_evening is budget._budgeted_run_evening

        editorial._generate = fake_generate
        editorial._recent_topics = lambda: asyncio.sleep(0, result=[])

        morning = await editorial._morning_brief()
        event = await editorial._event_spotlight()
        curiosity = await editorial._curiosity_post()
        evening = await editorial._evening_post()

        assert morning and event and curiosity and evening
        assert len(calls) == 4, f"expected 4 shared generator calls, got {len(calls)}"
    finally:
        editorial._generate = old_generate
        editorial._recent_topics = old_recent


async def test_budget_revision_ignores_broken_old_counter():
    store = {
        "editorial_morning_date_attempts_sonnet5-editorial-v3_2026-08-29": "2",
        "editorial_morning_date_try_sonnet5-editorial-v3": "2026-08-29T06:45",
    }
    sent = []

    async def meta_get(key):
        return store.get(key, "")

    async def meta_set(key, value):
        store[key] = str(value)

    async def attempt_allowed(key, now, cooldown=20):
        store[key] = now.isoformat(timespec="minutes")
        return True

    async def generator():
        return "Утренний тест"

    async def send_for_approval(bot, kind, text, button=False):
        sent.append((kind, text))
        return True

    old_get = editorial._meta_get
    old_set = editorial._meta_set
    old_attempt = editorial._attempt_allowed
    old_send = editorial._send_for_approval
    try:
        editorial._meta_get = meta_get
        editorial._meta_set = meta_set
        editorial._attempt_allowed = attempt_allowed
        editorial._send_for_approval = send_for_approval
        from datetime import datetime
        await budget._budgeted_run_generated(
            object(), datetime(2026, 8, 29, 7, 0), "утренний бриф",
            "editorial_morning_date", generator,
        )
    finally:
        editorial._meta_get = old_get
        editorial._meta_set = old_set
        editorial._attempt_allowed = old_attempt
        editorial._send_for_approval = old_send

    assert sent == [("утренний бриф", "Утренний тест")]
    new_key = f"editorial_morning_date_attempts_{budget.BUDGET_REVISION}_2026-08-29"
    assert store.get(new_key) == "1"
    assert "v4" in budget.BUDGET_REVISION


def test_photo_choice_keyboards():
    draft = "abc123"
    first = [button.callback_data for row in budget._draft_choice_kb(draft).inline_keyboard for button in row]
    after_photo = [button.callback_data for row in budget._photo_choice_kb(draft).inline_keyboard for button in row]
    assert f"edpubtext:{draft}" in first
    assert f"edphoto:{draft}" in first
    assert f"edpub:{draft}" in after_photo
    assert f"edpubtext:{draft}" in after_photo
    assert f"edretry:{draft}" in after_photo


async def main():
    test_modern_anthropic_sdk_is_installed()
    await test_pause_turn_and_sonnet5_request_shape()
    await test_successful_search_survives_later_nonfatal_tool_error()
    await test_truncated_output_never_keeps_broken_tail()
    await test_all_four_formats_share_one_generator()
    await test_budget_revision_ignores_broken_old_counter()
    test_photo_choice_keyboards()
    print("[OK] full editorial runtime: SDK + Sonnet 5 + Web Search + truncation + 4 formats + scheduler + photo choice")


if __name__ == "__main__":
    asyncio.run(main())
