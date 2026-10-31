"""Тесты недельного дайджеста: чистая логика без сети и базы."""
import os
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

os.environ.setdefault("BOT_TOKEN", "123456:test")

import utils.weekly_digest as wd  # noqa: E402

AMS = ZoneInfo("Europe/Amsterdam")


def _items(n, link_base="https://www.podslushano.nl/n"):
    return [
        {"emoji": "🚆", "text": f"Текст новости номер {i} про Amsterdam и NS.",
         "link_word": "Amsterdam", "wp_link": f"{link_base}{i}/"}
        for i in range(n)
    ]


class RenderTests(unittest.TestCase):
    def test_header_footer_and_link(self):
        out = wd.render(_items(4))
        self.assertTrue(out.startswith("<b>Дайджест новостей</b>\nГлавные события недели в Нидерландах\n\n"))
        self.assertTrue(out.endswith("Вот такие новости. Не забывайте ставить огонечки 🔥"))
        self.assertIn('<a href="https://www.podslushano.nl/n0/">Amsterdam</a>', out)
        self.assertEqual(out.count("\n\n🚆 "), 4)

    def test_escapes_text_and_attribute(self):
        items = [{"emoji": "🔥", "text": "A & B <script> про Den Haag ok здесь",
                  "link_word": "Den Haag", "wp_link": 'https://x.nl/a"b'}]
        out = wd.render(items)
        self.assertIn("A &amp; B &lt;script&gt;", out)
        self.assertIn('href="https://x.nl/a&quot;b"', out)


class ValidationTests(unittest.TestCase):
    def test_drops_unknown_links_and_bad_link_words(self):
        allowed = {"https://www.podslushano.nl/n0/", "https://www.podslushano.nl/n1/"}
        raw = [
            {"emoji": "🚆", "text": "Поезда NS меняют расписание с ноября.",
             "link_word": "NS", "wp_link": "https://www.podslushano.nl/n0/"},
            {"emoji": "💶", "text": "Цены на жильё выросли заметно за месяц.",
             "link_word": "нет такого", "wp_link": "https://www.podslushano.nl/n1/"},
            {"emoji": "🏠", "text": "Выдуманная ссылка без пары в списке.",
             "link_word": "ссылка", "wp_link": "https://evil.example/"},
            "not-a-dict",
        ]
        got = wd._valid_items(raw, allowed)
        self.assertEqual([i["wp_link"] for i in got], ["https://www.podslushano.nl/n0/"])

    def test_parse_items_extracts_array_from_text(self):
        raw = 'Вот результат:\n[{"emoji": "🔥", "text": "x", "link_word": "x", "wp_link": "u"}]\nготово'
        self.assertEqual(wd._parse_items(raw)[0]["emoji"], "🔥")
        self.assertEqual(wd._parse_items("нет json"), [])


class ScheduleTests(unittest.TestCase):
    def test_week_key_is_iso(self):
        # 2026-11-02 — понедельник, 2026-W45
        self.assertEqual(wd._iso_week(datetime(2026, 11, 2, 9, 0, tzinfo=AMS)), "2026-W45")

    def test_plain_text_helper_strips_tags(self):
        self.assertEqual(wd._plain("<p>Привет&nbsp;&amp; мир</p>"), "Привет & мир")


if __name__ == "__main__":
    unittest.main()

