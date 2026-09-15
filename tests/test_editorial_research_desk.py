import asyncio
from datetime import datetime, time

from utils import editorial_research_desk as desk


def test_nine_distinct_research_streams_and_schedule():
    assert len(desk.STREAMS) == 9
    assert len({stream.key for stream in desk.STREAMS}) == 9
    assert desk.STREAM_BY_KEY["morning"].starts_at == time(7, 30)
    assert desk.STREAM_BY_KEY["day"].starts_at == time(12, 0)
    assert desk.STREAM_BY_KEY["evening"].starts_at == time(17, 0)
    assert {"people", "events", "provinces", "calendar", "buzz", "evergreen"}.issubset(desk.STREAM_BY_KEY)


def test_due_windows_use_amsterdam_wall_clock():
    assert desk._is_due(desk.STREAM_BY_KEY["people"], datetime(2026, 9, 16, 8, 0))
    assert not desk._is_due(desk.STREAM_BY_KEY["people"], datetime(2026, 9, 16, 12, 0))
    assert desk._is_due(desk.STREAM_BY_KEY["day"], datetime(2026, 9, 16, 14, 0))
    assert desk._is_due(desk.STREAM_BY_KEY["evening"], datetime(2026, 9, 16, 18, 0))


def test_telegram_chunking_never_exceeds_limit():
    text = "\n\n".join(["x" * 900] * 10)
    chunks = desk._split_messages(text)
    assert len(chunks) > 1
    assert all(len(chunk) <= 3800 for chunk in chunks)
    assert "".join(chunks).replace("\n", "") == text.replace("\n", "")


def test_sources_are_appended_once():
    text = desk._append_sources("Тема", ["https://example.nl/a", "https://example.nl/b"])
    assert "Источники поиска:" in text
    assert text.count("https://example.nl/a") == 1
    same = desk._append_sources(text, ["https://example.nl/a"])
    assert same.count("https://example.nl/a") == 1


async def _test_global_dedup_context_reaches_generator():
    calls = []
    old_generate = desk.editorial._generate
    old_recent = desk._recent_ideas
    old_published = desk.editorial._recent_topics
    old_now = desk._now
    try:
        async def fake_generate(system, user, domains, max_tokens):
            calls.append((system, user, domains, max_tokens))
            return "1. Новая тема\nПроверенное описание.", ["https://example.nl/source"]

        desk.editorial._generate = fake_generate
        desk._recent_ideas = lambda: asyncio.sleep(0, result=["Старая идея"])
        desk.editorial._recent_topics = lambda: asyncio.sleep(0, result=["Опубликованная тема"])
        desk._now = lambda: datetime(2026, 9, 16, 8, 0)
        result = await desk._generate_digest(desk.STREAM_BY_KEY["people"])
    finally:
        desk.editorial._generate = old_generate
        desk._recent_ideas = old_recent
        desk.editorial._recent_topics = old_published
        desk._now = old_now

    assert result and "https://example.nl/source" in result
    assert "Старая идея" in calls[0][1]
    assert "Опубликованная тема" in calls[0][1]
    assert calls[0][3] == 1900


def test_global_dedup_context_reaches_generator():
    asyncio.run(_test_global_dedup_context_reaches_generator())
