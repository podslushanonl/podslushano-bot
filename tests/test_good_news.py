"""Хорошие новости: источники, токены, отбор, валидация, точный текст, однократность, команда."""
import os
import unittest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

os.environ.setdefault("BOT_TOKEN", "123456:test")

import config  # noqa: E402
from utils import digest_core as core  # noqa: E402
from utils import good_news as gn  # noqa: E402
from utils.site_news import FeedItem  # noqa: E402

AMS = ZoneInfo("Europe/Amsterdam")
NOW = datetime(2026, 11, 2, 8, 0, tzinfo=AMS)


def _ams(hour: int, minute: int = 0, day: int = 2) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=AMS)


def _feed_item(title, hours_ago=1, desc="Описание.", url=None, published="ago"):
    pub = None if published is None else NOW - timedelta(hours=hours_ago)
    return FeedItem(url=url or f"https://ex.nl/{abs(hash(title)) % 10**8}", title=title,
                    description=desc, published=pub, source="NOS")


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append((chat_id, text, kwargs))


class WindowTests(unittest.TestCase):
    def test_due_from_0730_until_noon_only(self):
        self.assertFalse(gn.is_due(_ams(7, 29)))
        self.assertTrue(gn.is_due(_ams(7, 30)))
        self.assertTrue(gn.is_due(_ams(11, 59)))
        self.assertFalse(gn.is_due(_ams(12, 0)))

    def test_default_toggle_is_on(self):
        self.assertTrue(config.GOOD_NEWS_ENABLED)


class FilterTests(unittest.TestCase):
    def test_excludes_bad_news(self):
        for title, lead in [
            ("Погибли двое в ДТП", ""),
            ("Пожар в доме", ""),
            ("Повышение цен на газ", ""),
            ("Забастовка в аэропорту", ""),
            ("Новости", "речь о войне"),
            ("Пациент с болезнью", ""),
        ]:
            self.assertTrue(gn.excluded(title, lead), title)

    def test_excludes_dutch_bad_news(self):
        for title in ["Drie doden bij brand", "Gewonde na ongeluk", "Politie onderzoekt diefstal",
                      "Twee doden bij ongeluk", "Dode bij brand"]:
            self.assertTrue(gn.excluded(title, ""), title)

    def test_excludes_deaths_in_dutch_and_russian(self):
        for title in ["Man overleden na val", "Vrouw overleden in ziekenhuis"]:
            self.assertTrue(gn.excluded(title, ""), title)

    def test_positive_rescue_stories_not_excluded(self):
        for title, lead in [
            ("Собаку спасли из канала", ""),
            ("Hond gered uit het kanaal", "Brandweer hielp"),
            ("Brandweer redde kat uit boom", ""),
            ("Пожарные спасли кота с дерева", ""),
            ("Соседи собрали деньги на ремонт центра", ""),
            ("Рекорд: самый большой тюльпан в Лейдене", ""),
        ]:
            self.assertFalse(gn.excluded(title, lead), title)


class PromptTests(unittest.TestCase):
    def test_prompt_lists_exclusions_and_empty_option(self):
        p = gn._system_prompt()
        for word in ["преступления", "ДТП", "смерти", "болезни", "политику", "забастовки", "повышение цен"]:
            self.assertIn(word, p)
        self.assertIn("[]", p)
        self.assertIn("не больше 8 слов", p)


class ValidateTests(unittest.TestCase):
    def setUp(self):
        self.by_id = {
            1: {"id": 1, "link": "https://ex.nl/a", "title": "A", "desc": ""},
            2: {"id": 2, "link": "https://ex.nl/b", "title": "B", "desc": ""},
        }

    def _entry(self, pid=1, **kw):
        base = {"id": pid, "emoji": "🐕", "headline": "Собака нашлась", "text": "Пёс вернулся домой. Соседи радовались."}
        base.update(kw)
        return base

    def test_link_comes_from_source_not_model(self):
        got = gn.validate([self._entry(1, link="https://evil.example")], self.by_id)
        self.assertEqual(got[0]["link"], "https://ex.nl/a")

    def test_drops_unknown_duplicate_and_bad_entries(self):
        raw = [self._entry(99), self._entry(1), self._entry(1), "junk",
               self._entry(2, text="Раз. Два. Три."),
               self._entry(2, headline="слово " * 11),
               self._entry(2, text="См. https://x.nl сейчас.")]
        self.assertEqual([i["id"] for i in gn.validate(raw, self.by_id)], [1])

    def test_caps_at_three(self):
        by_id = {i: {"id": i, "link": f"l{i}", "title": "t", "desc": ""} for i in range(1, 6)}
        got = gn.validate([self._entry(i) for i in range(1, 6)], by_id)
        self.assertEqual(len(got), gn.MAX_ITEMS)

    def test_emoji_fallback(self):
        got = gn.validate([self._entry(1, emoji="ab1")], self.by_id)
        self.assertEqual(got[0]["emoji"], "🌟")

    def test_empty_model_output_is_none(self):
        self.assertEqual(gn.validate(core.parse_array("[]"), self.by_id), [])


class RenderTests(unittest.TestCase):
    def test_empty_exact(self):
        self.assertEqual(gn.render([]), "Сегодня хороших новостей не нашлось 🙈")

    def test_items_exact_plain_text(self):
        items = [
            {"emoji": "🐕", "headline": "Собака нашлась", "text": "Пёс вернулся домой.", "link": "https://www.podslushano.nl/a/"},
            {"emoji": "🌷", "headline": "Тюльпаны в Лейдене", "text": "Рекорд в Keukenhof.", "link": "https://www.podslushano.nl/b/"},
        ]
        expected = (
            "☀️ Хорошие новости для «Голландского перекрёстка»\n\n"
            "Доброе утро ☕️ Немного хорошего на сегодня:\n\n"
            "🐕 Собака нашлась\nПёс вернулся домой.\nhttps://www.podslushano.nl/a/\n\n"
            "🌷 Тюльпаны в Лейдене\nРекорд в Keukenhof.\nhttps://www.podslushano.nl/b/\n\n"
            "Хорошего дня 🧡"
        )
        self.assertEqual(gn.render(items), expected)

    def test_plain_text_passes_through_unchanged(self):
        item = {"emoji": "🐕", "headline": "A <b>", "text": "*x* [y](z)", "link": "https://w.nl/"}
        out = gn.render([item])
        self.assertIn("🐕 A <b>\n*x* [y](z)\nhttps://w.nl/", out)
        self.assertNotIn("<a ", out)


class CollectTests(unittest.IsolatedAsyncioTestCase):
    FEEDS = ["https://a.nl/rss", "https://b.nl/rss", "https://c.nl/rss"]

    def _patch(self, raw_by_feed, items_by_feed):
        fetch = AsyncMock(side_effect=lambda url: raw_by_feed.get(url))
        parse = MagicMock(side_effect=lambda raw, feed: items_by_feed[feed])
        p1 = patch.object(gn, "fetch_feed", fetch)
        p2 = patch.object(gn, "parse_feed", parse)
        p3 = patch.object(gn.config, "GOOD_NEWS_FEEDS", self.FEEDS)
        for p in (p1, p2, p3):
            p.start()
            self.addCleanup(p.stop)
        return fetch, parse

    async def test_dedupes_by_title_across_feeds_and_sorts_newest_first(self):
        self._patch(
            {"https://a.nl/rss": b"A", "https://b.nl/rss": b"B"},
            {"https://a.nl/rss": [_feed_item("Тюльпан", 2, url="https://a.nl/1"),
                                  _feed_item("Собака нашлась", 1, url="https://a.nl/2")],
             "https://b.nl/rss": [_feed_item("  тюльпан!! ", 3, url="https://b.nl/1")]},
        )
        got = await gn.collect(NOW)
        self.assertEqual([c["title"] for c in got], ["Собака нашлась", "Тюльпан"])
        self.assertEqual(got[1]["link"], "https://a.nl/1")

    async def test_drops_old_undated_and_bad_news(self):
        self._patch(
            {"https://a.nl/rss": b"A"},
            {"https://a.nl/rss": [_feed_item("Старое", 30), _feed_item("Без даты", published=None),
                                  _feed_item("Погибли двое в ДТП", 1), _feed_item("Собаку спасли", 1)]},
        )
        self.assertEqual([c["title"] for c in await gn.collect(NOW)], ["Собаку спасли"])

    async def test_failed_or_broken_feed_is_skipped_silently(self):
        async def boom(url):
            if url == "https://b.nl/rss":
                raise OSError("network down")
            return None if url == "https://c.nl/rss" else b"A"

        fetch = AsyncMock(side_effect=boom)
        with patch.object(gn, "fetch_feed", fetch), \
                patch.object(gn, "parse_feed", MagicMock(return_value=[_feed_item("Хорошая новость", 1)])), \
                patch.object(gn.config, "GOOD_NEWS_FEEDS", self.FEEDS):
            got = await gn.collect(NOW)
        self.assertEqual([c["title"] for c in got], ["Хорошая новость"])
        self.assertEqual(fetch.await_count, 3)

    async def test_description_is_one_line_and_capped(self):
        self._patch({"https://a.nl/rss": b"A"},
                    {"https://a.nl/rss": [_feed_item("Новость", 1, desc="x" * 500 + "\n\nконец")]})
        got = await gn.collect(NOW)
        self.assertEqual(len(got[0]["desc"]), gn.DESC_CHARS)
        self.assertNotIn("\n", got[0]["desc"])


class BuildTests(unittest.IsolatedAsyncioTestCase):
    async def test_caps_candidates_and_sends_compact_lines_in_one_call(self):
        cands = [{"title": f"T{i}", "desc": "d" * 200, "link": f"https://ex.nl/{i}", "published": NOW}
                 for i in range(100)]
        call = AsyncMock(return_value=("[]", None))
        with patch.object(gn, "collect", AsyncMock(return_value=cands)), \
                patch.object(gn, "_call_claude", call):
            self.assertEqual(await gn.build(NOW), [])
        call.assert_awaited_once()
        lines = call.await_args.args[1].split("\n")[1:]
        self.assertEqual(len(lines), gn.MAX_CANDIDATES)
        self.assertEqual(lines[0], "1 | T0 | " + "d" * 200)
        self.assertTrue(all(line.count(" | ") == 2 for line in lines))

    async def test_selection_validated_and_link_from_source(self):
        cands = [{"title": "A", "desc": "", "link": "https://ex.nl/a", "published": NOW},
                 {"title": "B", "desc": "", "link": "https://ex.nl/b", "published": NOW}]
        reply = ('[{"id": 2, "emoji": "🌷", "headline": "Тюльпаны", "text": "Рекорд."},'
                 ' {"id": 9, "emoji": "🐕", "headline": "X", "text": "Y."}]')
        with patch.object(gn, "collect", AsyncMock(return_value=cands)), \
                patch.object(gn, "_call_claude", AsyncMock(return_value=(reply, None))):
            got = await gn.build(NOW)
        self.assertEqual([(i["id"], i["link"]) for i in got], [(2, "https://ex.nl/b")])

    async def test_logs_token_counts(self):
        cands = [{"title": "A", "desc": "", "link": "https://ex.nl/a", "published": NOW}]
        usage = MagicMock(input_tokens=7000, output_tokens=210)
        with patch.object(gn, "collect", AsyncMock(return_value=cands)), \
                patch.object(gn, "_call_claude", AsyncMock(return_value=("[]", usage))), \
                self.assertLogs(gn.log, level="INFO") as logs:
            await gn.build(NOW)
        self.assertTrue(any("вход=7000" in m and "выход=210" in m for m in logs.output))

    async def test_no_candidates_means_no_claude_call(self):
        call = AsyncMock()
        with patch.object(gn, "collect", AsyncMock(return_value=[])), patch.object(gn, "_call_claude", call):
            self.assertEqual(await gn.build(NOW), [])
        call.assert_not_awaited()


class ClaudeCallTests(unittest.IsolatedAsyncioTestCase):
    async def test_uses_goodnews_model_and_token_cap(self):
        resp = MagicMock(usage=MagicMock(input_tokens=1, output_tokens=2))
        client = MagicMock()
        client.messages.create = AsyncMock(return_value=resp)
        with patch.object(gn, "_get_client", return_value=client), \
                patch.object(gn, "_extract_text_and_sources", return_value=("[]", [])):
            text, usage = await gn._call_claude("sys", "user")
        kwargs = client.messages.create.await_args.kwargs
        self.assertEqual(kwargs["model"], config.GOOD_NEWS_MODEL)
        self.assertEqual(kwargs["max_tokens"], 600)
        self.assertEqual((text, usage.input_tokens), ("[]", 1))

    def test_default_model_is_haiku_and_feeds_are_https(self):
        self.assertEqual(config.GOOD_NEWS_MODEL, "claude-haiku-5-5")
        self.assertGreaterEqual(len(config.GOOD_NEWS_FEEDS), 9)
        self.assertTrue(all(u.startswith("https://") for u in config.GOOD_NEWS_FEEDS))


class DigestModelTests(unittest.IsolatedAsyncioTestCase):
    async def test_digest_selection_uses_digest_model_and_titles_only(self):
        call = AsyncMock(return_value="[]")
        with patch.object(core, "_ask_claude", call):
            await core.select_items(core.DAILY, [{"id": 1, "title": "Т", "link": "l", "lead": "секрет"}])
        model, _system, content = call.await_args.args[:3]
        self.assertEqual(model, config.DIGEST_MODEL)
        self.assertNotIn("секрет", content)
        self.assertIn("заголовок", content)


class ScheduleGuardTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.store = {}

        async def fake_get(key):
            return self.store.get(key)

        async def fake_set(key, value):
            self.store[key] = value

        for p in [
            patch.object(core, "meta_get", side_effect=fake_get),
            patch.object(core, "meta_set", side_effect=fake_set),
            patch.object(gn, "enabled", return_value=True),
        ]:
            p.start()
            self.addCleanup(p.stop)

    async def test_runs_once_per_day_within_window(self):
        run = AsyncMock(return_value="sent")
        with patch.object(gn, "run", run):
            await gn.scheduled_pass(FakeBot(), _ams(8, 0))
            await gn.scheduled_pass(FakeBot(), _ams(9, 0))
        self.assertEqual(run.await_count, 1)
        self.assertEqual(self.store[gn.LAST_DAY_KEY], "2026-11-02")

    async def test_0730_is_first_run_slot_and_0729_is_not(self):
        run = AsyncMock(return_value="sent")
        with patch.object(gn, "run", run):
            await gn.scheduled_pass(FakeBot(), _ams(7, 29))
            run.assert_not_awaited()
            await gn.scheduled_pass(FakeBot(), _ams(7, 30))
        run.assert_awaited_once()

    async def test_no_catchup_after_noon(self):
        run = AsyncMock(return_value="sent")
        with patch.object(gn, "run", run):
            await gn.scheduled_pass(FakeBot(), _ams(13, 0))
        run.assert_not_awaited()

    async def test_disabled_does_nothing(self):
        run = AsyncMock(return_value="sent")
        with patch.object(gn, "enabled", return_value=False), patch.object(gn, "run", run):
            await gn.scheduled_pass(FakeBot(), _ams(8, 0))
        run.assert_not_awaited()


class RunTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.bot = FakeBot()
        patcher = patch.object(gn.config, "ADMIN_IDS", [1, 2])
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_sends_digest_to_all_admins_as_plain_text(self):
        items = [{"id": 1, "link": "https://w.nl/a", "emoji": "🐕", "headline": "H", "text": "T."}]
        with patch.object(gn, "build", AsyncMock(return_value=items)):
            status = await gn.run(self.bot, _ams(8))
        self.assertEqual(status, "sent")
        self.assertEqual([c for c, _, _ in self.bot.sent], [1, 2])
        for _, text, kwargs in self.bot.sent:
            self.assertEqual(text, gn.render(items))
            self.assertNotIn("parse_mode", kwargs)

    async def test_none_sends_empty_message(self):
        with patch.object(gn, "build", AsyncMock(return_value=[])):
            status = await gn.run(self.bot, _ams(8))
        self.assertEqual(status, "none")
        self.assertEqual(self.bot.sent[0][1], "Сегодня хороших новостей не нашлось 🙈")

    async def test_error_is_reported_not_raised(self):
        with patch.object(gn, "build", AsyncMock(side_effect=RuntimeError("boom"))):
            status = await gn.run(self.bot, _ams(8))
        self.assertEqual(status, "error")
        self.assertIn("RuntimeError: boom", self.bot.sent[0][1])


if __name__ == "__main__":
    unittest.main()

