"""NS departures normalisation and route guards."""
import os
import unittest
from types import SimpleNamespace

from utils import ns_trains

SAMPLE = {"payload": {"departures": [
    {"direction": "Amsterdam Centraal", "plannedDateTime": "2026-10-12T08:16:00+0200",
     "actualDateTime": "2026-10-12T08:19:00+0200", "plannedTrack": "5", "actualTrack": "7",
     "product": {"categoryCode": "IC", "shortCategoryName": "NS Intercity", "operatorName": "NS"}, "cancelled": False,
     "routeStations": [{"mediumName": "Amsterdam Amstel"}]},
    {"direction": "Den Haag Centraal", "plannedDateTime": "2026-10-12T08:20:00+0200",
     "plannedTrack": "11", "product": {"categoryCode": "SPR", "shortCategoryName": "NS Sprinter"}, "cancelled": True},
]}}


class NsTrainsTests(unittest.IsolatedAsyncioTestCase):
    def test_normalize(self):
        out = ns_trains.normalize_departures(SAMPLE, 6)
        self.assertEqual(out[0]["time"], "08:16")
        self.assertEqual(out[0]["delay"], 3)
        self.assertEqual(out[0]["track"], "7")
        self.assertTrue(out[0]["track_changed"])
        self.assertEqual(out[0]["category"], "Интерсити")
        self.assertEqual(out[1]["category"], "Спринтер")
        self.assertTrue(out[1]["cancelled"])
        self.assertEqual(len(ns_trains.normalize_departures(SAMPLE, 1)), 1)

    async def test_missing_key_and_bad_station(self):
        old = os.environ.pop("NS_API_KEY", None)
        try:
            r = await ns_trains.departures(SimpleNamespace(query={"station": "UT"}))
            self.assertEqual(r.status, 503)
            r = await ns_trains.departures(SimpleNamespace(query={"station": "../x"}))
            self.assertEqual(r.status, 400)
        finally:
            if old is not None:
                os.environ["NS_API_KEY"] = old

    async def test_uses_cache(self):
        calls = []

        async def fake(path, params):
            calls.append(path)
            return SAMPLE
        orig = ns_trains._ns_get
        ns_trains._ns_get = fake
        ns_trains._cache.clear()
        os.environ["NS_API_KEY"] = "test"
        try:
            for _ in range(2):
                r = await ns_trains.departures(SimpleNamespace(query={"station": "ut"}))
                self.assertEqual(r.status, 200)
            self.assertEqual(calls, ["/v2/departures"])
        finally:
            ns_trains._ns_get = orig
            os.environ.pop("NS_API_KEY", None)
            ns_trains._cache.clear()


if __name__ == "__main__":
    unittest.main()


DIS = [
    {"id": "d1", "type": "DISRUPTION", "title": "Den Haag - Rotterdam.", "isActive": True,
     "start": "2026-10-12T15:10:00+0200", "end": "2026-10-12T18:00:00+0200",
     "expectedDuration": {"description": "Tot ongeveer 18:00"},
     "summaryAdditionalTravelTime": {"minimumDurationInMinutes": 15, "maximumDurationInMinutes": 30},
     "timespans": [{"situation": {"label": "Er rijden minder treinen"},
                    "cause": {"label": "door een defect aan het spoor"},
                    "alternativeTransport": {"label": "Er rijden bussen"}, "advices": []}]},
    {"id": "m1", "type": "MAINTENANCE", "title": "Amsterdam - Alkmaar.", "isActive": False,
     "start": "2099-01-01T06:00:00+0100", "end": "2099-01-02T23:00:00+0100",
     "timespans": [{"situation": {"label": "Er rijden geen treinen"}, "cause": {"label": "werkzaamheden"}}]},
    {"id": "c1", "type": "CALAMITY", "title": "Staking in België", "description": "Treinen naar België rijden niet.",
     "isActive": True},
]


class NsDisruptionTests(unittest.IsolatedAsyncioTestCase):
    def test_dictionary_translation_and_fields(self):
        n = ns_trains.normalize_disruption(DIS[0])
        self.assertEqual(n["title"], "Den Haag - Rotterdam")
        self.assertEqual(n["situation"], "Поездов меньше обычного")
        self.assertEqual(n["cause"], "неисправность пути")
        self.assertEqual((n["extra_min"], n["extra_max"]), (15, 30))
        self.assertTrue(n["buses"])
        self.assertTrue(n["start_ru"].endswith("15:10"))

    async def test_split_now_and_planned_without_api_key(self):
        old = os.environ.pop("ANTHROPIC_API_KEY", None)
        orig = ns_trains._ns_get

        async def fake(path, params):
            return DIS
        ns_trains._ns_get = fake
        try:
            data = await ns_trains._load_disruptions()
        finally:
            ns_trains._ns_get = orig
            if old is not None:
                os.environ["ANTHROPIC_API_KEY"] = old
        self.assertEqual([x["id"] for x in data["now"]], ["c1", "d1"])  # calamity first
        self.assertEqual(data["planned"], [])  # 2099 is beyond the 7-day window
        self.assertEqual(data["now"][0]["title"], "Staking in België")  # untranslated fallback
