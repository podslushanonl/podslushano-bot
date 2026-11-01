"""Хорошие новости: источники, разбор, проверка по коду, дедупликация, причины, расписание, команда."""
import json
import os
import unittest
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch
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


def _item(title, *, url=None, desc="Описание.", hours_ago=1, source="NOS", published=True):
    pub = (NOW - timedelta(hours=hours_ago)).astimezone(gn.timezone.utc) if published else None
    return FeedItem(url=url or f"https://www.nos.nl/a/{abs(hash(title)) % 10**8}",
                    title=title, description=desc, published=pub, source=source)


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


class FeedSourceTests(unittest.TestCase):
    def test_feed_list_has_working_outlets_only(self):
        feeds = config.GOOD_NEWS_FEEDS
        self.assertGreaterEqual(len(feeds), 10)
        for dead in ("nhnieuws", "omroepflevoland"):
            self.assertFalse(any(dead in f for f in feeds), dead)

    def test_broadcaster_names(self):
        self.assertEqual(gn.broadcaster("https://www.rtvoost.nl/rss"), "RTV Oost")
        self.assertEqual(gn.broadcaster("https://feeds.nos.nl/nosnieuwsbinnenland"), "NOS")
        self.assertEqual(gn.broadcaster("https://www.omropfryslan.nl/rss/index.xml"), "Omrop Fryslân")

    def test_sanitize_makes_bad_feed_parse(self):
        # Похоже на NH Nieuws в проде: недопустимый управляющий символ и голый «&» в ленте.
        raw = ('<?xml version="1.0" encoding="iso-8859-1"?><rss><channel>'
               "<item><title>Tom & Jerry \x0b rescue</title><link>https://www.nhnieuws.nl/1</link>"
               "<description>Hond gered</description></item></channel></rss>").encode("utf-8")
        with self.assertRaises(ET.ParseError):
            ET.fromstring(raw)
        items = gn.parse_feed(gn.sanitize_feed(raw), "https://www.nhnieuws.nl/rss")
        self.assertEqual(len(items), 1)
        self.assertIn("Tom & Jerry", items[0].title)

    def test_url_key_ignores_utm_slash_and_host_case(self):
        a = gn.url_key("https://WWW.Omroep.nl/nieuws/1/?utm_source=x#top")
        b = gn.url_key("https://www.omroep.nl/nieuws/1")
        self.assertEqual(a, b)


class CollectTests(unittest.TestCase):
    def test_keeps_24h_dedupes_and_skips_sent_and_negatives(self):
        items = [
            _item("Собаку спасли из канала", url="https://a.nl/1"),
            _item("Соседи собрали деньги на ремонт", url="https://a.nl/2"),
            _item("Соседи собрали деньги на ремонт", url="https://b.nl/2"),  # тот же заголовок
            _item("Рекорд в Лейдене", url="https://a.nl/3", hours_ago=30),  # старше 24 ч
            _item("Пожар в доме", url="https://a.nl/4"),  # негатив
            _item("Кошка нашлась", url="https://a.nl/5"),  # уже отправлена
            _item("Без даты", url="https://a.nl/6", published=False),
        ]
        sent = {gn.url_key("https://a.nl/5")}
        got = gn.collect(NOW, sent, items)
        self.assertEqual([i.url for i in got], ["https://a.nl/1", "https://a.nl/2"])

    def test_cap_at_max_candidates(self):
        items = [_item(f"Новость номер {i} хорошая", url=f"https://a.nl/{i}", hours_ago=1) for i in range(100)]
        self.assertEqual(len(gn.collect(NOW, set(), items)), gn.MAX_CANDIDATES)


class RegexBackstopTests(unittest.TestCase):
    def test_excludes_bad_news(self):
        for title in ["Погибли двое в ДТП", "Пожар в доме", "Повышение цен на газ", "Забастовка в аэропорту",
                      "Twee doden bij ongeluk", "Drie doden bij brand", "Man overleden na val"]:
            self.assertTrue(gn.excluded(title, ""), title)

    def test_keeps_rescue_and_good_news(self):
        for title in ["Собаку спасли из канала", "Hond gered uit het kanaal",
                      "Brandweer redde kat uit boom", "Соседи собрали деньги на ремонт"]:
            self.assertFalse(gn.excluded(title, ""), title)



class VerificationTests(unittest.TestCase):
    def test_numbers_and_latin_names_must_be_in_source(self):
        src = "Omroep Brabant: 3 honden gered in Den Bosch, 12 maart."
        self.assertEqual(gn.verify_item("Три собаки 3 нашлись в Den Bosch", src), [])
        self.assertEqual(gn.verify_item("5 собак нашлись в Den Bosch", src), ["5"])
        self.assertEqual(gn.verify_item("Собаки нашлись в Eindhoven", src), ["Eindhoven"])

    def test_cyrillic_capitals_are_not_checked(self):
        self.assertEqual(gn.verify_item("Собаки нашлись", "dogs found"), [])

    def test_verify_all_drops_unsupported_and_adds_footer_fields(self):
        picked = {1: _item("Hond gevonden", url="https://www.omroepbrabant.nl/n/1",
                           desc="Hond na 3 dagen gevonden.", source="Omroep Brabant")}
        items = [{"id": 1, "emoji": "🐕", "headline": "Собака нашлась", "text": "Нашлась через 3 дня."}]
        kept, dropped = gn.verify_all(items, picked)
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["url"], "https://www.omroepbrabant.nl/n/1")
        bad = [{"id": 1, "emoji": "🐕", "headline": "Собака", "text": "Нашлась через 5 дней."}]
        kept, dropped = gn.verify_all(bad, picked)
        self.assertEqual(kept, [])
        self.assertEqual(len(dropped), 1)


class ParseTests(unittest.TestCase):
    def test_ids_from_small_answer(self):
        self.assertEqual(gn.parse_ids("[3, 7]"), [3, 7])
        self.assertEqual(gn.parse_ids("[]"), [])
        self.assertEqual(gn.parse_ids("[3, 3, 9, 1, 2]"), [3, 9, 1])  # уникальные, не больше 3
        self.assertIsNone(gn.parse_ids("ответ без списка"))
        self.assertIsNone(gn.parse_ids('[3, "x"'))

    def test_truncated_text_is_detected_as_parse_error(self):
        truncated = '[{"id": 1, "emoji": "🐕", "headline": "Собака", "text": "Нашлась и'
        self.assertIsNone(gn.parse_json_array(truncated))
        self.assertEqual(gn.parse_json_array('[{"id": 1}]'), [{"id": 1}])


class ValidateTests(unittest.TestCase):
    def _picked(self):
        return {1: _item("A", url="https://a.nl/1"), 2: _item("B", url="https://a.nl/2")}

    def test_link_and_source_never_from_model(self):
        raw = [{"id": 1, "emoji": "🐕", "headline": "Собака", "text": "Нашлась.", "url": "https://evil.example"}]
        out = gn.validate(raw, self._picked())
        self.assertEqual(len(out), 1)
        self.assertNotIn("url", out[0])

    def test_drops_unknown_duplicate_long_and_url_text(self):
        raw = [{"id": 9, "headline": "x", "text": "y."},
               {"id": 1, "headline": "Собака", "text": "Нашлась."},
               {"id": 1, "headline": "Собака", "text": "Нашлась."},
               {"id": 2, "headline": "слово " * 11, "text": "Нашлась."},
               {"id": 2, "headline": "Собака", "text": "См. https://x.nl сейчас."}]
        self.assertEqual([i["id"] for i in gn.validate(raw, self._picked())], [1])


class RenderTests(unittest.TestCase):
    def test_empty_exact(self):
        self.assertEqual(gn.render([]), "Сегодня хороших новостей не нашлось 🙈")

    def test_footer_format_and_url_last(self):
        items = [{"emoji": "🐕", "headline": "Собака нашлась", "text": "Пёс вернулся домой.",
                  "source": "Omroep Brabant", "date": "02.11.2026", "url": "https://www.omroepbrabant.nl/n/1"}]
        expected = (
            "☀️ Хорошие новости для «Голландского перекрёстка»\n\n"
            "Доброе утро ☕️ Немного хорошего на сегодня:\n\n"
            "🐕 Собака нашлась\nПёс вернулся домой.\n"
            "Источник: Omroep Brabant · 02.11.2026\n"
            "https://www.omroepbrabant.nl/n/1\n\n"
            "Хорошего дня 🧡"
        )
        self.assertEqual(gn.render(items), expected)

    def test_date_converted_to_amsterdam(self):
        pub = datetime(2026, 11, 1, 23, 30, tzinfo=gn.timezone.utc)  # 02.11 по Амстердаму
        item = FeedItem(url="https://www.nos.nl/a", title="T", description="", published=pub, source="NOS")
        kept, _ = gn.verify_all([{"id": 1, "emoji": "🌟", "headline": "Текст", "text": "Текст."}], {1: item})
        self.assertEqual(kept[0]["date"], "02.11.2026")


class SentStoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.store = {}

        async def fake_get(key):
            return self.store.get(key)

        async def fake_set(key, value):
            self.store[key] = value

        for p in [patch.object(core, "meta_get", side_effect=fake_get),
                  patch.object(core, "meta_set", side_effect=fake_set)]:
            p.start()
            self.addCleanup(p.stop)

    async def test_sent_url_is_stored_and_reloaded(self):
        await gn._save_sent(NOW, ["https://www.nos.nl/a/1?utm_source=x"])
        loaded = await gn._load_sent(NOW)
        self.assertIn(gn.url_key("https://www.nos.nl/a/1"), loaded)

    async def test_old_entries_pruned(self):
        old = (NOW.date() - timedelta(days=gn.SENT_KEEP_DAYS + 1)).isoformat()
        self.store[gn.SENT_KEY] = json.dumps({"https://old.nl/x": old})
        self.assertEqual(await gn._load_sent(NOW), {})

    async def test_corrupt_store_is_ignored(self):
        self.store[gn.SENT_KEY] = "{не json"
        self.assertEqual(await gn._load_sent(NOW), {})


class BuildTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.store = {}

        async def fake_get(key):
            return self.store.get(key)

        async def fake_set(key, value):
            self.store[key] = value

        for p in [patch.object(core, "meta_get", side_effect=fake_get),
                  patch.object(core, "meta_set", side_effect=fake_set),
                  patch.object(gn, "_site_items", AsyncMock(return_value=[]))]:
            p.start()
            self.addCleanup(p.stop)

    def _feeds(self, items):
        return patch.object(gn, "_load_all_feeds", AsyncMock(return_value=items))

    async def test_backstop_applies_to_rss_items_before_model(self):
        bad = _item("Погибли двое в ДТП", url="https://a.nl/x")
        call = AsyncMock()
        with self._feeds([bad]), patch.object(gn, "_call", call):
            _, reason = await gn.build(NOW)
        call.assert_not_awaited()
        self.assertEqual(reason, "no_candidates")

    async def test_two_calls_and_ok(self):
        item = _item("Собаку нашли 3 дня спустя", url="https://www.omroepbrabant.nl/n/1",
                     desc="Hond na 3 dagen teruggevonden in Tilburg.", source="Omroep Brabant")
        calls = [("[1]", "end_turn"),
                 ('[{"id": 1, "emoji": "🐕", "headline": "Собака нашлась", "text": "Пёс вернулся через 3 дня."}]',
                  "end_turn")]
        call = AsyncMock(side_effect=calls)
        with self._feeds([item]), patch.object(gn, "_call", call):
            items, reason = await gn.build(NOW)
        self.assertEqual(reason, "ok")
        self.assertEqual(call.await_count, 2)
        self.assertEqual(items[0]["url"], "https://www.omroepbrabant.nl/n/1")

    async def test_no_llm_without_candidates(self):
        call = AsyncMock()
        with self._feeds([]), patch.object(gn, "_call", call):
            items, reason = await gn.build(NOW)
        self.assertEqual(reason, "no_sources")
        call.assert_not_awaited()

    async def test_model_none(self):
        item = _item("Соседи помогли", url="https://a.nl/1")
        with self._feeds([item]), patch.object(gn, "_call", AsyncMock(return_value=("[]", "end_turn"))):
            _, reason = await gn.build(NOW)
        self.assertEqual(reason, "model_none")

    async def test_truncated_select_is_parse_error(self):
        item = _item("Соседи помогли", url="https://a.nl/1")
        with self._feeds([item]), patch.object(gn, "_call", AsyncMock(return_value=("[1", "max_tokens"))):
            _, reason = await gn.build(NOW)
        self.assertEqual(reason, "parse_error_select")

    async def test_truncated_write_is_parse_error(self):
        item = _item("Соседи помогли", url="https://a.nl/1")
        calls = [("[1]", "end_turn"), ('[{"id": 1, "headline": "Собака', "max_tokens")]
        with self._feeds([item]), patch.object(gn, "_call", AsyncMock(side_effect=calls)):
            _, reason = await gn.build(NOW)
        self.assertEqual(reason, "parse_error_write")

    async def test_dropped_by_verification(self):
        item = _item("Собаку нашли", url="https://a.nl/1", desc="Нашли через 3 дня.")
        calls = [("[1]", "end_turn"), ('[{"id": 1, "emoji": "🐕", "headline": "Собака", "text": "Через 9 дней."}]',
                                       "end_turn")]
        with self._feeds([item]), patch.object(gn, "_call", AsyncMock(side_effect=calls)):
            _, reason = await gn.build(NOW)
        self.assertEqual(reason, "dropped_by_verification")


class RunTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.bot = FakeBot()
        p = patch.object(gn.config, "ADMIN_IDS", [1, 2])
        p.start()
        self.addCleanup(p.stop)

    async def test_sends_digest_to_all_admins_plain(self):
        items = [{"emoji": "🐕", "headline": "H", "text": "T.", "source": "NOS", "date": "02.11.2026", "url": "https://a.nl/1"}]
        with patch.object(gn, "build", AsyncMock(return_value=(items, "ok"))), \
             patch.object(gn, "_save_sent", AsyncMock()):
            status = await gn.run(self.bot, NOW)
        self.assertEqual(status, "sent")
        self.assertEqual([c for c, _, _ in self.bot.sent], [1, 2])
        for _, text, kwargs in self.bot.sent:
            self.assertEqual(text, gn.render(items))
            self.assertNotIn("parse_mode", kwargs)

    async def test_none_sends_empty_message(self):
        with patch.object(gn, "build", AsyncMock(return_value=([], "model_none"))):
            status = await gn.run(self.bot, NOW)
        self.assertEqual(status, "none")
        self.assertEqual(self.bot.sent[0][1], gn.EMPTY)

    async def test_parse_error_is_not_reported_as_no_news(self):
        with patch.object(gn, "build", AsyncMock(return_value=([], "parse_error_write"))):
            status = await gn.run(self.bot, NOW)
        self.assertEqual(status, "error")
        text = self.bot.sent[0][1]
        self.assertTrue(text.startswith(gn.ERROR_PREFIX))
        self.assertNotIn("не нашлось", text)

    async def test_api_error_reported_with_prefix(self):
        with patch.object(gn, "build", AsyncMock(side_effect=RuntimeError("boom"))):
            status = await gn.run(self.bot, NOW)
        self.assertEqual(status, "error")
        self.assertIn("RuntimeError: boom", self.bot.sent[0][1])
        self.assertTrue(self.bot.sent[0][1].startswith(gn.ERROR_PREFIX))

    async def test_sent_urls_recorded_only_after_send(self):
        save = AsyncMock()
        with patch.object(gn, "build", AsyncMock(return_value=([], "model_none"))), \
             patch.object(gn, "_save_sent", save):
            await gn.run(self.bot, NOW)
        save.assert_not_awaited()


class ScheduleGuardTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.store = {}

        async def fake_get(key):
            return self.store.get(key)

        async def fake_set(key, value):
            self.store[key] = value

        for p in [patch.object(core, "meta_get", side_effect=fake_get),
                  patch.object(core, "meta_set", side_effect=fake_set),
                  patch.object(gn, "enabled", return_value=True)]:
            p.start()
            self.addCleanup(p.stop)

    async def test_runs_once_per_day_within_window(self):
        run = AsyncMock(return_value="sent")
        with patch.object(gn, "run", run):
            await gn.scheduled_pass(FakeBot(), _ams(8, 0))
            await gn.scheduled_pass(FakeBot(), _ams(9, 0))
        self.assertEqual(run.await_count, 1)
        self.assertEqual(self.store[gn.LAST_DAY_KEY], "2026-11-02")

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


if __name__ == "__main__":
    unittest.main()

