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
