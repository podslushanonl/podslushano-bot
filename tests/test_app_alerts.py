import unittest
from datetime import date

from utils import app_alerts as a


class AppAlertsTest(unittest.TestCase):
    def test_morning_text(self):
        title, body = a.morning_text("nb", {"code": 61, "min": 3.4, "max": 9.6, "rain": 80}, 5, "Цены на газ снизились")
        self.assertEqual(title, "Noord-Brabant: +3…+10°, дождь, возьмите зонт")
        self.assertEqual(body, "Сегодня 5 событий в провинции. Цены на газ снизились")
        title, body = a.morning_text("ut", None, 1, "")
        self.assertEqual((title, body), ("Доброе утро, Utrecht", "Сегодня 1 событие в провинции"))

    def test_events_on(self):
        ev = [{"province": "nb", "date": "2026-11-05"}, {"province": "nb", "date": "2026-11-01", "end": "2026-11-10"},
              {"province": "ut", "date": "2026-11-05"}, {"province": "nb", "date": "2026-11-06"}]
        self.assertEqual(a.events_on(ev, "nb", date(2026, 11, 5)), 2)

    def test_station_alerts_once_per_disruption(self):
        items = [{"id": "d1", "type_ru": "Сбой", "title": "Между Oss и Nijmegen не ходят поезда", "stations": ["O", "NM"]},
                 {"id": "d2", "type_ru": "Ремонтные работы", "title": "Работы", "stations": ["UT"], "active": False}]
        tokens = [("t1", "O", "Oss", ""), ("t2", "O", "Oss", "d1"), ("t3", "UT", "Utrecht Centraal", "")]
        msgs, marks = a.station_alerts(tokens, items)
        self.assertEqual([m["to"] for m in msgs], ["t1", "t3"])
        self.assertEqual(msgs[0]["title"], "Поезда · Oss: сбой")
        self.assertEqual(msgs[0]["data"], {"url": "/trains"})
        self.assertEqual(marks, {"t1": "d1", "t3": "d2"})


if __name__ == "__main__":
    unittest.main()
