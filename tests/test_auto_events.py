import json
import unittest
from datetime import date

from utils import auto_events as a


def _page(*events):
    data = {"@context": "https://schema.org", "@type": "ItemList",
            "itemListElement": [{"@type": "ListItem", "position": i + 1, "item": e} for i, e in enumerate(events)]}
    return f'<script type="application/ld+json">{json.dumps(data)}</script>'


EV = {"@type": "Event", "name": "Jazz in de kelder", "startDate": "2026-11-20", "endDate": "2026-11-20",
      "url": "https://www.eventbrite.nl/e/jazz-tickets-1234567890?aff=x", "image": "https://img/x.jpg",
      "location": {"@type": "Place", "name": "De Kelder", "address": {
          "addressLocality": "eindhoven", "addressRegion": "NB", "addressCountry": "NL", "streetAddress": "Straat 1"}}}


class AutoEventsTest(unittest.TestCase):
    def test_parse_eventbrite(self):
        rows = a.parse_eventbrite(_page(EV), "Концерт")
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["key"], "eb-1234567890")
        self.assertEqual(r["province"], "nb")
        self.assertEqual(r["city"], "Eindhoven")
        self.assertEqual(r["url"], "https://www.eventbrite.nl/e/jazz-tickets-1234567890")
        self.assertEqual(r["date"], "2026-11-20")

    def test_region_names_and_foreign(self):
        fr = {**EV, "location": {"address": {"addressRegion": "Fryslân", "addressLocality": "Sneek", "addressCountry": "NL"}}}
        be = {**EV, "location": {"address": {"addressRegion": "Vlaams Gewest", "addressLocality": "Gent", "addressCountry": "BE"}}}
        rows = a.parse_eventbrite(_page(fr, be), "Событие")
        self.assertEqual([r["province"] for r in rows], ["fr"])

    def test_clean_filters_business_past_long_and_duplicates(self):
        today = date(2026, 11, 5)
        base = a.parse_eventbrite(_page(EV), "Концерт")[0]
        rows = [
            base,
            {**base, "key": "eb-2"},                                              # дубль: то же название, тот же день
            {**base, "key": "eb-3", "h": "Enterprise UX Conference 2026"},       # бизнес
            {**base, "key": "eb-4", "h": "Oud", "date": "2026-10-01", "end": "2026-10-01"},  # прошло
            {**base, "key": "eb-5", "h": "Elke dag", "date": "2026-01-01", "end": "2026-12-31"},  # «весь год»
            {**base, "key": "eb-6", "h": "Ver weg", "date": "2027-09-01", "end": ""},  # слишком далеко
            {**base, "key": "eb-7", "h": "Zonder provincie", "province": ""},
        ]
        self.assertEqual([r["key"] for r in a.clean(rows, today)], ["eb-1234567890"])

    def test_parse_ticketmaster(self):
        data = {"_embedded": {"events": [{
            "id": "Z1", "name": "Band", "url": "https://tm/1",
            "dates": {"start": {"localDate": "2026-12-01", "localTime": "20:00:00"}},
            "classifications": [{"segment": {"name": "Music"}}],
            "priceRanges": [{"min": 39.5}],
            "images": [{"url": "https://i/1.jpg", "ratio": "16_9", "width": 1024}],
            "_embedded": {"venues": [{"name": "Ziggo Dome", "city": {"name": "Amsterdam"}, "state": {"name": "Noord-Holland"}}]},
        }]}}
        r = a.parse_ticketmaster(data)[0]
        self.assertEqual((r["key"], r["province"], r["time"], r["cat"], r["price"]), ("tm-Z1", "nh", "20:00", "Концерт", "от €40"))


if __name__ == "__main__":
    unittest.main()
