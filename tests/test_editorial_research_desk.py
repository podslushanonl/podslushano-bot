import asyncio
import json
from datetime import datetime, time

from utils import editorial_research_desk as desk
from utils import editorial_verified_search as verified


def _idea(**overrides):
    value = {
        "headline": "Поезда остановятся в трёх провинциях",
        "verdict": "now",
        "score": 10,
        "hook": "Маршрут на работу придётся менять уже завтра",
        "what_happened": "NS подтвердил остановку движения.",
        "why_now": "Изменение вступает в силу завтра утром.",
        "audience_value": "Затрагивает дорогу на работу и вызывает обсуждение.",
        "format": "карусель",
        "visual": "Карта участков и официальный скриншот NS.",
        "source_urls": ["https://www.ns.nl/example"],
    }
    value.update(overrides)
    return value


def test_nine_distinct_research_streams_and_schedule():
    assert len(desk.STREAMS) == 9
    assert len({stream.key for stream in desk.STREAMS}) == 9
    assert desk.STREAM_BY_KEY["morning"].starts_at == time(7, 30)
    assert desk.STREAM_BY_KEY["day"].starts_at == time(12, 0)
    assert desk.STREAM_BY_KEY["evening"].starts_at == time(17, 0)
    assert {"people", "events", "provinces", "calendar", "buzz", "evergreen"}.issubset(desk.STREAM_BY_KEY)
    assert desk.STREAM_BY_KEY["morning"].automatic_weekdays == tuple(range(7))
    assert desk.STREAM_BY_KEY["day"].automatic_weekdays == ()
    assert desk.STREAM_BY_KEY["evening"].automatic_weekdays == ()
    assert all(
        len(desk.STREAM_BY_KEY[key].automatic_weekdays) == 2
        for key in ("people", "events", "provinces", "calendar", "buzz", "evergreen")
    )


def test_due_windows_use_amsterdam_wall_clock():
    # Monday is an automatic People day; Tuesday is not.
    assert desk._is_due(desk.STREAM_BY_KEY["people"], datetime(2026, 9, 14, 8, 0))
    assert not desk._is_due(desk.STREAM_BY_KEY["people"], datetime(2026, 9, 15, 8, 0))
    assert not desk._is_due(desk.STREAM_BY_KEY["people"], datetime(2026, 9, 14, 12, 0))
    # Day/evening news stay available manually but never run automatically.
    assert not desk._is_due(desk.STREAM_BY_KEY["day"], datetime(2026, 9, 16, 14, 0))


def test_parser_keeps_only_strong_complete_sourced_ideas():
    raw = json.dumps({
        "editor_note": "Одна тема прошла отбор.",
        "ideas": [
            _idea(),
            _idea(headline="Слабый анонс", score=7),
            _idea(headline="Без источника", source_urls=[]),
        ],
    }, ensure_ascii=False)
    payload = desk._parse_payload(raw)
    assert payload["editor_note"] == "Одна тема прошла отбор."
    assert [item["headline"] for item in payload["ideas"]] == ["Поезда остановятся в трёх провинциях"]


def test_parser_can_use_verified_tool_source():
    raw = json.dumps({"editor_note": "", "ideas": [_idea(source_urls=[])]}, ensure_ascii=False)
    payload = desk._parse_payload(raw, ["https://www.rijksoverheid.nl/example"])
    assert payload["ideas"][0]["source_urls"] == ["https://www.rijksoverheid.nl/example"]


def test_card_has_visual_hierarchy_and_escapes_html():
    card = desk._card_text(_idea(headline="Цена < €20"))
    assert "<b>10/12</b>" in card
    assert "<blockquote>" in card
    assert "<b>Почему сейчас</b>" in card
    assert "Цена &lt; €20" in card


def test_card_actions_cover_editorial_decision():
    keyboard = desk._idea_kb(42, _idea())
    callbacks = [button.callback_data for row in keyboard.inline_keyboard for button in row if button.callback_data]
    assert {"ideawork:42", "ideadeep:42", "ideareserve:42", "ideareject:42"}.issubset(callbacks)


def test_rejection_reasons_are_specific():
    assert set(desk._REJECTION_LABELS) == {"boring", "audience", "visual", "late"}


def test_verified_pipeline_does_not_trim_valid_json():
    raw = json.dumps({"editor_note": "Есть тема.", "ideas": [_idea()]}, ensure_ascii=False)
    assert verified._trim_incomplete_tail(raw) == raw


def test_verified_pipeline_extracts_valid_json_from_wrapper():
    raw = 'Результат поиска:\n' + json.dumps({"ideas": [_idea()]}, ensure_ascii=False) + '\nГотово'
    trimmed = verified._trim_incomplete_tail(raw)
    assert json.loads(trimmed)["ideas"][0]["score"] == 10


def test_radar_gets_more_searches_than_regular_post():
    assert verified._search_limit([], 1600) == 2
    assert verified._search_limit([], 900) == 2


async def _test_feedback_and_dedup_reach_generator():
    calls = []
    old_generate = desk.editorial._generate
    old_recent = desk._recent_ideas
    old_published = desk.editorial._recent_topics
    old_feedback = desk._feedback_prompt
    old_now = desk._now
    try:
        async def fake_generate(system, user, domains, max_tokens):
            calls.append((system, user, domains, max_tokens))
            return json.dumps({"editor_note": "Есть тема", "ideas": [_idea()]}, ensure_ascii=False), []

        desk.editorial._generate = fake_generate
        desk._recent_ideas = lambda: asyncio.sleep(0, result=["Старая идея"])
        desk.editorial._recent_topics = lambda: asyncio.sleep(0, result=["Опубликованная тема"])
        desk._feedback_prompt = lambda: asyncio.sleep(0, result="[банально] Отклонённая тема")
        desk._now = lambda: datetime(2026, 9, 16, 8, 0)
        result = await desk._generate_digest(desk.STREAM_BY_KEY["people"])
    finally:
        desk.editorial._generate = old_generate
        desk._recent_ideas = old_recent
        desk.editorial._recent_topics = old_published
        desk._feedback_prompt = old_feedback
        desk._now = old_now

    assert result["ideas"][0]["score"] == 10
    assert "Старая идея" in calls[0][1]
    assert "Опубликованная тема" in calls[0][1]
    assert "[банально] Отклонённая тема" in calls[0][1]
    assert calls[0][3] == 1600
    assert len(calls) == 1


def test_feedback_and_dedup_reach_generator():
    asyncio.run(_test_feedback_and_dedup_reach_generator())
