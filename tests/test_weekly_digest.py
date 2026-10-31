"""Дайджесты: вёрстка, проверка отбора Claude, расписание недельного и ежедневного."""
import os
import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

os.environ.setdefault("BOT_TOKEN", "123456:test")

from utils import daily_digest as daily  # noqa: E402
from utils import digest_core as core  # noqa: E402
from utils import weekly_digest as weekly  # noqa: E402

AMS = ZoneInfo("Europe/Amsterdam")


class RenderTests(unittest.TestCase):
    def test_weekly_layout_and_escaping(self):
        items = [
            {"id": 1, "link": "https://www.podslushano.nl/a/", "title": "NS & Schiphol <test>", "emoji": "🚆"},
            {"id": 2, "link": "https://www.podslushano.nl/b/", "title": "Huur stijgt", "emoji": "🏠"},
        ]
        out = core.render(core.WEEKLY, items)
        self.assertTrue(out.startswith("<b>Дайджест новостей</b>\nГлавные события недели в Нидерландах\n🚆 "))
        self.assertIn('<a href="https://www.podslushano.nl/a/">NS &amp; Schiphol &lt;test&gt;</a>', out)
        self.assertIn("\n\n🏠 ", out)
        self.assertTrue(out.endswith("огонечки 🔥\n#дайджест"))

    def test_daily_layout(self):
        out = core.render(core.DAILY, [{"id": 1, "link": "https://x.nl/", "title": "Т", "emoji": "📰"}])
        self.assertEqual(out, '<b>Новости дня</b>\n📰 <a href="https://x.nl/">Т</a>\n#новости')

    def test_title_is_unescaped_then_plain(self):
        self.assertEqual(core.plain_title("<p>Цены&nbsp;&amp; жильё</p>"), "Цены & жильё")


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.by_id = {1: {"id": 1, "link": "l1", "title": "A"}, 2: {"id": 2, "link": "l2", "title": "B"}}

    def test_only_known_ids_no_duplicates_and_emoji_fallback(self):
        raw = [
            {"wp_post_id": "2", "emoji": "💶"},
            {"wp_post_id": 2, "emoji": "dup"},
            {"wp_post_id": 99, "emoji": "🔥"},
            {"wp_post_id": 1, "emoji": "abc"},
            "junk",
        ]
        got = core.validate_selection(raw, self.by_id, 10)
        self.assertEqual([(i["id"], i["emoji"]) for i in got], [(2, "💶"), (1, "📰")])

    def test_respects_max_items(self):
        raw = [{"wp_post_id": 1, "emoji": "🚆"}, {"wp_post_id": 2, "emoji": "🏠"}]
        self.assertEqual(len(core.validate_selection(raw, self.by_id, 1)), 1)

    def test_parse_array_extracts_json_from_text(self):
        self.assertEqual(core.parse_array('Ответ:\n[{"wp_post_id": 1, "emoji": "🚆"}]\nготово')[0]["wp_post_id"], 1)
        self.assertEqual(core.parse_array("нет json"), [])

    def test_selection_prompt_excludes_war_and_geopolitics(self):
        prompt = core._select_system(core.WEEKLY)
        self.assertIn("войны", prompt)
        self.assertIn("геополитику", prompt)


class ScheduleTests(unittest.TestCase):
    def test_weekly_due_only_monday_from_0900(self):
        self.assertFalse(weekly.is_due_time(datetime(2026, 11, 2, 8, 59, tzinfo=AMS)))
        self.assertTrue(weekly.is_due_time(datetime(2026, 11, 2, 9, 0, tzinfo=AMS)))
        self.assertTrue(weekly.is_due_time(datetime(2026, 11, 2, 23, 0, tzinfo=AMS)))
        self.assertFalse(weekly.is_due_time(datetime(2026, 11, 3, 10, 0, tzinfo=AMS)))

    def test_iso_week(self):
        self.assertEqual(weekly.iso_week(datetime(2026, 11, 2, 9, 0, tzinfo=AMS)), "2026-W45")

    def test_daily_window_fallback_and_lookback_cap(self):
        now = datetime(2026, 11, 2, 19, 0, tzinfo=AMS)
        self.assertEqual(daily.window_start(now, None), now - timedelta(hours=24))
        last = now - timedelta(hours=5)
        self.assertEqual(daily.window_start(now, last), last)
        self.assertEqual(daily.window_start(now, now - timedelta(hours=72)), now - timedelta(hours=24))


if __name__ == "__main__":
    unittest.main()

