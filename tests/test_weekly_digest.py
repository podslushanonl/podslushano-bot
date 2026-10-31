"""Дайджесты: точная вёрстка, фрагменты ссылок, проверка ответа Claude, тестовый режим, расписание."""
import os
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

os.environ.setdefault("BOT_TOKEN", "123456:test")

from utils import daily_digest as daily  # noqa: E402
from utils import digest_core as core  # noqa: E402
from utils import weekly_digest as weekly  # noqa: E402

AMS = ZoneInfo("Europe/Amsterdam")
LINK = "https://www.podslushano.nl/a/"


def _item(title, link_text, emoji="🚆", link=LINK):
    return {"id": 1, "link": link, "title": title, "link_text": link_text, "emoji": emoji}


class ExactOutputTests(unittest.TestCase):
    def test_daily_exact_string(self):
        items = [
            _item("NS vertraagd bij Utrecht", "NS", "🚆"),
            _item("Huur stijgt in Amsterdam", "Huur", "🏠"),
        ]
        expected = (
            "<b>Новости дня</b>\n\n"
            f'🚆 <a href="{LINK}">NS</a> vertraagd bij Utrecht\n\n'
            f'🏠 <a href="{LINK}">Huur</a> stijgt in Amsterdam\n\n'
            "#новости"
        )
        self.assertEqual(core.render(core.DAILY, items), expected)

    def test_weekly_exact_string(self):
        items = [_item("Belastingen 2027: wat verandert", "Belastingen", "💶")]
        expected = (
            "<b>Дайджест новостей</b>\n\n"
            "Главные события недели в Нидерландах\n\n"
            f'💶 <a href="{LINK}">Belastingen</a> 2027: wat verandert\n\n'
            "Вот такие новости. Не забывайте ставить огонечки 🔥\n\n"
            "#дайджест"
        )
        self.assertEqual(core.render(core.WEEKLY, items), expected)

    def test_weekly_fire_emoji_and_item_emoji_present(self):
        out = core.render(core.WEEKLY, [_item("A b", "A", "🚆"), _item("C d", "C", "🏠")])
        self.assertIn("огонечки 🔥", out)
        self.assertIn("🚆 <a", out)
        self.assertIn("🏠 <a", out)

    def test_only_fragment_is_linked_and_rest_escaped(self):
        out = core.render(core.DAILY, [_item("Tax & <benefits> rise", "benefits")])
        self.assertIn(f'Tax &amp; &lt;<a href="{LINK}">benefits</a>&gt; rise', out)

    def test_link_href_is_escaped(self):
        out = core.render(core.DAILY, [_item("Hallo", "Hallo", link='https://x.nl/a"b')])
        self.assertIn('href="https://x.nl/a&quot;b"', out)


class LinkTextTests(unittest.TestCase):
    def test_accepts_exact_one_or_two_word_substring(self):
        self.assertEqual(core.pick_link_text("NS vertraagd bij Utrecht", "NS vertraagd"), "NS vertraagd")
        self.assertEqual(core.pick_link_text("NS vertraagd bij Utrecht", "Utrecht"), "Utrecht")

    def test_rejects_case_mismatch_fallbacks_to_first_word(self):
        self.assertEqual(core.pick_link_text("NS vertraagd bij Utrecht", "ns"), "NS")

    def test_rejects_more_than_two_words(self):
        self.assertEqual(core.pick_link_text("A b c d", "A b c"), "A")

    def test_rejects_non_substring(self):
        self.assertEqual(core.pick_link_text("Huur stijgt", "Huurprijs"), "Huur")

    def test_rejects_empty_and_non_string(self):
        self.assertEqual(core.pick_link_text("Huur stijgt", ""), "Huur")
        self.assertEqual(core.pick_link_text("Huur stijgt", None), "Huur")

    def test_title_text_never_changes(self):
        title = "Schiphol & <NS> 2027"
        out = core.render(core.DAILY, [_item(title, "NS")])
        self.assertIn("Schiphol &amp; &lt;", out)
        self.assertIn("&gt; 2027", out)


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.by_id = {
            1: {"id": 1, "link": "l1", "title": "NS vertraagd"},
            2: {"id": 2, "link": "l2", "title": "Huur stijgt"},
        }

    def test_drops_unknown_and_duplicate_ids(self):
        raw = [{"wp_post_id": 1, "emoji": "🚆", "link_text": "NS"},
               {"wp_post_id": 1, "emoji": "🏠", "link_text": "NS"},
               {"wp_post_id": 99, "emoji": "💶", "link_text": "x"},
               "junk",
               {"wp_post_id": "2", "emoji": "💶", "link_text": "Huur"}]
        got = core.validate_selection(raw, self.by_id, 10)
        self.assertEqual([p["id"] for p in got], [1, 2])
        self.assertEqual(got[0]["title"], "NS vertraagd")  # заголовок — свой, не из ответа модели

    def test_emoji_fallback_and_cap(self):
        raw = [{"wp_post_id": 1, "emoji": "ABC", "link_text": "NS"}, {"wp_post_id": 2, "emoji": "🏠"}]
        got = core.validate_selection(raw, self.by_id, 1)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["emoji"], "📰")

    def test_missing_link_text_falls_back_to_first_word(self):
        got = core.validate_selection([{"wp_post_id": 2, "emoji": "🏠"}], self.by_id, 10)
        self.assertEqual(got[0]["link_text"], "Huur")

    def test_parse_array_extracts_json_from_text(self):
        self.assertEqual(core.parse_array('Ответ:\n[{"wp_post_id": 1}]\nготово')[0]["wp_post_id"], 1)
        self.assertEqual(core.parse_array("нет json"), [])

    def test_selection_prompt_excludes_war_and_geopolitics(self):
        prompt = core._select_system(core.WEEKLY)
        self.assertIn("войны", prompt)
        self.assertIn("геополитику", prompt)
        self.assertIn("link_text", prompt)


class TestModeTests(unittest.IsolatedAsyncioTestCase):
    async def test_zero_runs_means_no_draft_even_with_zero_approvals(self):
        with patch.object(core.config, "DIGEST_TEST_RUNS", 0), \
                patch.object(core, "approved_count", return_value=0):
            self.assertFalse(await core.in_test_mode("daily"))

    async def test_positive_runs_draft_until_approved(self):
        with patch.object(core.config, "DIGEST_TEST_RUNS", 2):
            with patch.object(core, "approved_count", return_value=1):
                self.assertTrue(await core.in_test_mode("weekly"))
            with patch.object(core, "approved_count", return_value=2):
                self.assertFalse(await core.in_test_mode("weekly"))

    def test_default_config_is_zero(self):
        self.assertEqual(core.config.DIGEST_TEST_RUNS, 0)


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

