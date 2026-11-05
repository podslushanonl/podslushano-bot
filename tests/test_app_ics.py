"""Файл события для календаря (.ics): время по Амстердаму, события на весь день, экранирование."""
import unittest
from datetime import datetime

from utils.app_ics import build_ics


class IcsTests(unittest.TestCase):
    def test_timed_event(self):
        ics = build_ics({"key": "little-big", "h": "Little Big; концерт, 18+", "date": "2026-11-08", "time": "20:00",
                         "venue": "Patronaat", "city": "Haarlem"}, now=datetime(2026, 11, 5, 12, 0))
        self.assertIn("DTSTART;TZID=Europe/Amsterdam:20261108T200000", ics)
        self.assertIn("DTEND;TZID=Europe/Amsterdam:20261108T220000", ics)
        self.assertIn("SUMMARY:Little Big\; концерт\\, 18+", ics)
        self.assertIn("LOCATION:Patronaat\\, Haarlem", ics)
        self.assertTrue(all(len(line.encode()) <= 75 for line in ics.split("\r\n")))

    def test_all_day_multi_day(self):
        ics = build_ics({"key": "idfa", "h": "IDFA", "date": "2026-11-12", "end": "2026-11-23", "city": "Amsterdam"})
        self.assertIn("DTSTART;VALUE=DATE:20261112", ics)
        self.assertIn("DTEND;VALUE=DATE:20261124", ics)   # конец не включается — следующий день

    def test_no_date(self):
        with self.assertRaises(ValueError):
            build_ics({"key": "x", "h": "x", "date": ""})


if __name__ == "__main__":
    unittest.main()
