"""Дайджесты: точная вёрстка, фрагменты ссылок, проверка ответа Claude, тестовый режим, расписание."""
import json
import os
import re
import unittest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch
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
            "#pnl_новости"
        )
        self.assertEqual(core.render(core.DAILY, items), expected)

    def test_weekly_exact_string(self):
        items = [_item("Belastingen 2027: wat verandert", "Belastingen", "💶")]
        expected = (
            "<b>Дайджест новостей</b>\n\n"
            "Главные события недели в Нидерландах\n\n"
            f'💶 <a href="{LINK}">Belastingen</a> 2027: wat verandert\n\n'
            "Вот такие новости. Не забывайте ставить огонечки 🔥\n\n"
            "#pnl_дайджест"
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


class DailyMaxItemsTests(unittest.TestCase):
    def test_default_daily_max_is_10(self):
        self.assertEqual(core.config.DAILY_DIGEST_MAX_ITEMS, 10)
        self.assertEqual(core.DAILY.max_items, 10)

    def test_daily_min_stays_3_and_weekly_unchanged(self):
        self.assertEqual(core.DAILY.min_items, 3)
        self.assertEqual(core.WEEKLY.max_items, 20)

    def test_daily_prompt_asks_for_exactly_10_and_fewer_only_if_not_enough(self):
        prompt = core._select_system(core.DAILY)
        self.assertIn("РОВНО 10", prompt)
        self.assertIn("не останавливайся раньше", prompt)
        self.assertNotIn("от 5", prompt)

    def test_weekly_prompt_keeps_plain_cap(self):
        self.assertIn("не больше 20", core._select_system(core.WEEKLY))

    def test_daily_selection_capped_at_max(self):
        by_id = {i: {"id": i, "link": f"l{i}", "title": f"Titel {i}"} for i in range(1, 11)}
        raw = [{"wp_post_id": i, "emoji": "🏠", "link_text": "Titel"} for i in range(1, 11)]
        got = core.validate_selection(raw, by_id, core.DAILY.max_items)
        self.assertEqual(len(got), core.DAILY.max_items)


EVENING = datetime(2026, 11, 4, 19, 0, tzinfo=AMS)  # ср 04.11, вечерний выпуск


def _news(i, title, *, published, excerpt=""):
    return {"id": i, "link": f"https://www.podslushano.nl/n/{i}", "title": title,
            "published": published, "excerpt": excerpt}


class FreshnessTests(unittest.TestCase):
    def test_yesterdays_weather_is_stale(self):
        # Тот самый случай: вчера вечером вышел прогноз «на завтра» — к сегодняшним 19:00 день прошёл.
        item = _news(1, "Завтра в Нидерландах ожидается гроза и ливни", published=EVENING - timedelta(hours=22))
        self.assertTrue(core.is_stale_weather(item, EVENING))

    def test_weather_detected_by_excerpt_too(self):
        item = _news(1, "KNMI предупреждает", published=EVENING - timedelta(days=1))
        self.assertTrue(core.is_stale_weather(item, EVENING))
        item = _news(2, "Предупреждение на дорогах", excerpt="Код оранжевый: сильный ветер до 90 км/ч",
                     published=EVENING - timedelta(days=1))
        self.assertTrue(core.is_stale_weather(item, EVENING))

    def test_todays_weather_left_to_claude(self):
        item = _news(1, "Прогноз погоды на завтра: до +15", published=EVENING - timedelta(hours=2))
        self.assertFalse(core.is_stale_weather(item, EVENING))

    def test_long_range_forecast_kept(self):
        item = _news(1, "Синоптики: на выходных будет до +20", published=EVENING - timedelta(days=1))
        self.assertFalse(core.is_stale_weather(item, EVENING))

    def test_non_weather_and_unknown_time_kept(self):
        self.assertFalse(core.is_stale_weather(
            _news(1, "Аренда жилья в Амстердаме подорожала", published=EVENING - timedelta(days=1)), EVENING))
        self.assertFalse(core.is_stale_weather(_news(2, "Гроза и ливни", published=None), EVENING))
        # «пожар» не путается с «жарой»
        self.assertFalse(core.is_stale_weather(
            _news(3, "Пожар в центре Роттердама потушен", published=EVENING - timedelta(days=1)), EVENING))

    def test_day_boundary_is_amsterdam_midnight(self):
        just_before = datetime(2026, 11, 3, 23, 59, tzinfo=AMS)
        just_after = datetime(2026, 11, 4, 0, 1, tzinfo=AMS)
        self.assertTrue(core.is_stale_weather(_news(1, "Дождь весь день", published=just_before), EVENING))
        self.assertFalse(core.is_stale_weather(_news(1, "Дождь весь день", published=just_after), EVENING))

    def test_drop_stale_keeps_order(self):
        items = [_news(1, "Новые правила аренды", published=EVENING - timedelta(days=1)),
                 _news(2, "Завтра снег и гололёд", published=EVENING - timedelta(days=1)),
                 _news(3, "NS меняет расписание", published=EVENING - timedelta(hours=3))]
        self.assertEqual([i["id"] for i in core.drop_stale(items, EVENING)], [1, 3])


class DailyPromptTests(unittest.TestCase):
    def test_when_label(self):
        self.assertEqual(core.when_label(datetime(2026, 11, 4, 8, 15, tzinfo=AMS), EVENING), "сегодня 08:15")
        self.assertEqual(core.when_label(datetime(2026, 11, 3, 21, 40, tzinfo=AMS), EVENING), "вчера (вт 03.11) 21:40")
        self.assertEqual(core.when_label(datetime(2026, 11, 2, 10, 0, tzinfo=AMS), EVENING), "пн 02.11 10:00")
        self.assertEqual(core.when_label(None, EVENING), "время неизвестно")

    def test_label_uses_amsterdam_time_for_utc_input(self):
        utc = datetime(2026, 11, 3, 23, 30, tzinfo=core.timezone.utc)  # 00:30 04.11 по Амстердаму
        self.assertEqual(core.when_label(utc, EVENING), "сегодня 00:30")

    def test_daily_prompt_has_now_and_staleness_rules(self):
        prompt = core._select_system(core.DAILY, EVENING)
        self.assertIn("ср 04.11.2026, 19:00", prompt)
        self.assertIn("НЕ БЕРЁМ УСТАРЕВШЕЕ", prompt)
        self.assertIn("это СЕГОДНЯ", prompt)

    def test_weekly_prompt_has_no_evening_rules(self):
        self.assertNotIn("УСТАРЕВШЕЕ", core._select_system(core.WEEKLY, EVENING))

    def test_daily_listing_shows_publish_time_and_excerpt(self):
        items = [_news(7, "Гроза над Утрехтом", excerpt="Завтра днём ожидаются ливни",
                       published=datetime(2026, 11, 4, 9, 5, tzinfo=AMS))]
        line = core.listing(core.DAILY, items, EVENING)
        self.assertEqual(line, "- wp_post_id: 7 | вышла: сегодня 09:05 | заголовок: Гроза над Утрехтом"
                               " | кратко: Завтра днём ожидаются ливни")
        self.assertEqual(core.listing(core.WEEKLY, items, EVENING), "- wp_post_id: 7 | заголовок: Гроза над Утрехтом")


class FitTests(unittest.TestCase):
    def test_trims_from_bottom_to_fit_telegram(self):
        long_title = "Очень длинный заголовок новости " * 12
        items = [{"id": i, "link": f"https://www.podslushano.nl/n/{i}", "title": f"{i} {long_title}",
                  "link_text": f"{i}", "emoji": "📰"} for i in range(1, 11)]
        self.assertGreater(len(core.render(core.DAILY, items)), core.MAX_TEXT)
        fitted = core.fit_to_telegram(core.DAILY, items)
        self.assertLessEqual(len(core.render(core.DAILY, fitted)), core.MAX_TEXT)
        self.assertEqual([i["id"] for i in fitted], list(range(1, len(fitted) + 1)))  # убраны нижние
        self.assertGreaterEqual(len(fitted), core.DAILY.min_items)

    def test_short_digest_untouched(self):
        items = [_item(f"Titel {i}", "Titel") for i in range(10)]
        self.assertEqual(core.fit_to_telegram(core.DAILY, items), items)


class ProduceDailyTests(unittest.IsolatedAsyncioTestCase):
    """Сборка «Новостей дня» целиком: WordPress, база и Claude подменены."""

    async def asyncSetUp(self):
        self.now = EVENING
        rows = [(i, f"https://www.podslushano.nl/n/{i}", self.now - timedelta(hours=2 + i)) for i in range(1, 13)]
        rows.append((99, "https://www.podslushano.nl/n/99", self.now - timedelta(hours=22)))  # вчерашняя погода
        posts = {i: {"status": "publish", "title": {"rendered": f"Новость номер {i}"},
                     "excerpt": {"rendered": f"<p>Подробности {i}</p>"}} for i in range(1, 13)}
        posts[99] = {"status": "publish", "title": {"rendered": "Завтра гроза и ливни по всей стране"},
                     "excerpt": {"rendered": "<p>KNMI объявил жёлтый код</p>"}}
        self.asked = {}

        async def fake_get_post(pid):
            return posts.get(pid)

        async def fake_ask(model, system, content, max_tokens):
            self.asked = {"system": system, "content": content, "max_tokens": max_tokens}
            ids = [int(x) for x in re.findall(r"wp_post_id: (\d+)", content)]
            return json.dumps([{"wp_post_id": i, "emoji": "📰", "link_text": "Новость"} for i in ids])

        class FakeDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return EVENING.astimezone(tz) if tz else EVENING.replace(tzinfo=None)

        for p in [patch.object(core, "candidates", AsyncMock(return_value=rows)),
                  patch.object(core.wp, "get_post", side_effect=fake_get_post),
                  patch.object(core, "_ask_claude", side_effect=fake_ask),
                  patch.object(core, "in_test_mode", AsyncMock(return_value=False)),
                  patch.object(core, "publish_text", AsyncMock(return_value="https://t.me/c/1")),
                  patch.object(core, "datetime", FakeDatetime)]:
            p.start()
            self.addCleanup(p.stop)

    async def test_publishes_10_and_never_sends_stale_weather_to_claude(self):
        result = await core.produce(FakeBot(), core.DAILY, self.now - timedelta(hours=24))
        self.assertEqual(result["status"], "posted")
        text = core.publish_text.await_args.args[1]
        self.assertEqual(text.count('<a href="'), 10)
        self.assertNotIn("гроза", text)
        self.assertNotIn("wp_post_id: 99", self.asked["content"])
        self.assertIn("вышла: сегодня", self.asked["content"])
        self.assertIn("кратко: Подробности 1", self.asked["content"])
        self.assertIn("ср 04.11.2026, 19:00", self.asked["system"])
        self.assertEqual(self.asked["max_tokens"], core.SELECT_MAX_TOKENS)


class FakeBot:
    pass


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

