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
        msgs, ids = a.station_alerts(tokens, items)
        self.assertEqual([m["to"] for m in msgs], ["t1", "t3"])
        self.assertEqual(ids, ["d1", "d2"])
        self.assertEqual(msgs[0]["title"], "Поезда · Oss: сбой")
        self.assertEqual(msgs[0]["data"], {"url": "/trains"})
        # Expo не принял второе сообщение — его сбой не помечается и повторится
        self.assertEqual(a.new_marks(tokens, msgs, ids, [True, False]), {"t1": "d1"})


class MorningRoundTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import tempfile
        from pathlib import Path
        from unittest import mock
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
        from database.models import AppPushToken, Base
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{Path(self.tmp.name) / 't.db'}")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.sessions() as s:
            s.add_all([AppPushToken(token="t1", province="nb"), AppPushToken(token="t2", province="nb")])
            await s.commit()
        self.p = mock.patch.object(a, "get_session", self.sessions)
        self.p.start()

    async def asyncTearDown(self):
        self.p.stop()
        await self.engine.dispose()
        self.tmp.cleanup()

    async def test_retries_only_undelivered_and_stops_when_all_got_it(self):
        from datetime import datetime
        from unittest import mock
        calls = []

        async def fake(day, skip):
            calls.append(set(skip))
            return [t for t in ("t1", "t2") if t not in skip][:1]   # за раз доходит одно

        now = datetime(2026, 11, 6, 7, 35, tzinfo=a.TZ)
        with mock.patch.object(a, "send_morning", fake):
            self.assertEqual(await a.morning_round(now), 1)
            self.assertEqual(await a.morning_round(now), 1)
            self.assertEqual(await a.morning_round(now), 0)      # всем дошло — больше не шлём
            self.assertEqual(await a.morning_round(datetime(2026, 11, 6, 11, 5, tzinfo=a.TZ)), 0)
        self.assertEqual(calls, [set(), {"t1"}])


if __name__ == "__main__":
    unittest.main()
