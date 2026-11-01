"""Хорошие новости: окно 07:30–12:00, фильтр, валидация, точный текст, однократность, команда."""
import os
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

os.environ.setdefault("BOT_TOKEN", "123456:test")

import config  # noqa: E402
from utils import digest_core as core  # noqa: E402
from utils import good_news as gn  # noqa: E402

AMS = ZoneInfo("Europe/Amsterdam")


def _ams(hour: int, minute: int = 0, day: int = 2) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=AMS)


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
            ("Twee doden bij ongeluk", ""),
            ("Погибли двое в ДТП", ""),
            ("Пожар в доме", ""),
            ("Повышение цен на газ", ""),
            ("Забастовка в аэропорту", ""),
            ("Новости", "речь о войне"),
            ("Пациент с болезнью", ""),
        ]:
            self.assertTrue(gn.excluded(title, lead), title)

    def test_excludes_dutch_bad_news(self):
        for title in ["Drie doden bij brand", "Gewonde na ongeluk", "Politie onderzoekt diefstal"]:
            self.assertTrue(gn.excluded(title, ""), title)

    def test_dutch_deaths_and_accidents_excluded(self):
        for title in ["Man overleden na val", "Vrouw overleden in ziekenhuis",
                      "Twee doden bij ongeluk", "Dode bij brand"]:
            self.assertTrue(gn.excluded(title, ""), title)

    def test_positive_rescue_stories_not_excluded(self):
        for title, lead in [
            ("Собаку спасли из канала", ""),
            ("Hond gered uit het kanaal", "Brandweer hielp"),
            ("Brandweer redde kat uit boom", ""),
            ("Пожарные спасли кота с дерева", ""),
        ]:
            self.assertFalse(gn.excluded(title, lead), title)

    def test_keeps_good_news(self):
        for title, lead in [
            ("Собаку спасли из канала", "Пожарные помогли"),
            ("Соседи собрали деньги на ремонт центра", ""),
            ("Рекорд: самый большой тюльпан в Лейдене", ""),
            ("Пожарные спасли кота с дерева", ""),
            ("Brandweer helpt buurt", ""),
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
            1: {"id": 1, "link": "https://www.podslushano.nl/a/", "title": "A", "lead": ""},
            2: {"id": 2, "link": "https://www.podslushano.nl/b/", "title": "B", "lead": ""},
        }

    def _entry(self, pid=1, **kw):
        base = {"wp_post_id": pid, "emoji": "🐕", "headline": "Собака нашлась", "text": "Пёс вернулся домой. Соседи радовались."}
        base.update(kw)
        return base

    def test_link_comes_from_wordpress_not_model(self):
        got = gn.validate([self._entry(1, link="https://evil.example")], self.by_id)
        self.assertEqual(got[0]["link"], "https://www.podslushano.nl/a/")

    def test_drops_unknown_duplicate_and_bad_entries(self):
        raw = [self._entry(99), self._entry(1), self._entry(1), "junk",
               self._entry(2, text="Раз. Два. Три."),
               self._entry(2, headline="слово " * 11),
               self._entry(2, text="См. https://x.nl сейчас.")]
        self.assertEqual([i["id"] for i in gn.validate(raw, self.by_id)], [1])

    def test_caps_at_three(self):
        by_id = {i: {"id": i, "link": f"l{i}", "title": "t", "lead": ""} for i in range(1, 6)}
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

