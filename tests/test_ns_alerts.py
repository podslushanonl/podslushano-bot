"""NS: станции, затронутые сбоем, и уведомления подписчикам."""
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from database.models import Base, NsAlertSent, NsSubscription
from utils import ns_alerts, ns_trains

DIS = {"id": "d1", "type": "DISRUPTION", "title": "Alkmaar - Hoorn", "isActive": True,
       "publicationSections": [{"section": {"stations": [{"stationCode": "AMR"}, {"stationCode": "hn"}]}}],
       "timespans": [{"situation": {"label": "Door een defecte bovenleiding: tussen Heerhugowaard en Hoorn rijden er geen treinen."},
                      "cause": {"label": "defecte bovenleiding"}, "alternativeTransport": {"label": "bussen"},
                      "advices": ["Plan uw reis in de app."]}]}


class StationsTests(unittest.TestCase):
    def test_disruption_stations(self):
        n = ns_trains.normalize_disruption(DIS)
        self.assertEqual(n["stations"], ["AMR", "HN"])

    def test_normalize_stations(self):
        rows = ns_trains.normalize_stations({"payload": [
            {"code": "UT", "namen": {"lang": "Utrecht Centraal"}, "land": "NL"},
            {"code": "BRUSN", "namen": {"lang": "Brussel-Noord"}, "land": "B"},
            {"code": "ASD", "namen": {"lang": "Amsterdam Centraal"}, "land": "NL"}]})
        self.assertEqual(rows, [["ASD", "Amsterdam Centraal"], ["UT", "Utrecht Centraal"]])

    def test_relevant_and_text(self):
        now = datetime(2026, 10, 12, 12, tzinfo=timezone.utc)
        cur = ns_trains.normalize_disruption(DIS)
        soon = {"id": "p1", "type": "MAINTENANCE", "active": False, "stations": ["UT"],
                "start": (now + timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M:%S%z")}
        later = {**soon, "id": "p2", "start": (now + timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%S%z")}
        ids = [x["id"] for x in ns_alerts.relevant({"now": [cur], "planned": [soon, later]}, now)]
        self.assertEqual(ids, ["d1", "p1"])
        text = ns_alerts.alert_text(cur, "Hoorn")
        self.assertIn("Между Heerhugowaard и Hoorn не ходят поезда.", text)
        self.assertIn("Вместо поездов ходят автобусы.", text)
        self.assertIn("Совет: Планируйте поездку в приложении NS", text)


class NowLineTests(unittest.TestCase):
    def test_wording(self):
        f = ns_alerts._now_line
        self.assertEqual(f(0, 0), "Сейчас на этой станции всё спокойно.")
        self.assertEqual(f(1, 0), "Сейчас на этой станции есть сбой. Подробности ниже.")
        self.assertEqual(f(3, 0), "Сейчас на этой станции 3 сбоя. Подробности ниже.")
        self.assertEqual(f(0, 1), "В ближайшие сутки начнётся ремонт. Подробности ниже.")
        self.assertEqual(f(5, 1), "Сейчас на этой станции 5 сбоев, в ближайшие сутки начнётся ремонт. Подробности ниже.")


class AlertLoopTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{Path(self.tmp.name) / 't.db'}")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        data = {"now": [ns_trains.normalize_disruption(DIS)], "planned": []}
        self.patches = [patch.object(ns_alerts, "get_session", self.sessions),
                        patch.object(ns_trains, "get_disruptions", AsyncMock(return_value=data))]
        for p in self.patches:
            p.start()
        async with self.sessions() as s:
            s.add_all([NsSubscription(user_id=1, station_code="HN", station_name="Hoorn"),
                       NsSubscription(user_id=2, station_code="UT", station_name="Utrecht Centraal")])
            await s.commit()
        self.bot = SimpleNamespace(send_message=AsyncMock())

    async def asyncTearDown(self):
        for p in self.patches:
            p.stop()
        await self.engine.dispose()
        self.tmp.cleanup()

    async def test_sends_once_to_affected_station_only(self):
        self.assertEqual(await ns_alerts.check_once(self.bot), 1)
        self.assertEqual(self.bot.send_message.await_args.args[0], 1)
        self.assertIn("Hoorn", self.bot.send_message.await_args.args[1])
        self.assertEqual(await ns_alerts.check_once(self.bot), 0)
        async with self.sessions() as s:
            self.assertEqual(len((await s.scalars(select(NsAlertSent))).all()), 1)


if __name__ == "__main__":
    unittest.main()
