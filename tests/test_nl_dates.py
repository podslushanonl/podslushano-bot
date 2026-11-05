import unittest
from datetime import date

from utils import nl_dates as d


class NlDatesTest(unittest.TestCase):
    def test_easter(self):
        self.assertEqual(d.easter(2026), date(2026, 4, 5))
        self.assertEqual(d.easter(2027), date(2027, 3, 28))

    def test_year_dates(self):
        rows = {r["nl"] or r["title"]: r for r in d.year_dates(2027)}
        self.assertEqual(rows["Hemelvaartsdag"]["date"], "2027-05-06")
        self.assertEqual(rows["Pinksteren"]["end"], "2027-05-17")
        self.assertEqual(rows["Koningsdag"]["date"], "2027-04-27")
        self.assertEqual(rows["Prinsjesdag"]["date"], "2027-09-21")
        self.assertEqual(rows["Переход на зимнее время"]["date"], "2027-10-31")
        self.assertEqual(rows["Переход на летнее время"]["date"], "2027-03-28")
        # Koningsdag 2031 выпадает на воскресенье — переносится на субботу 26 апреля
        self.assertEqual({r["nl"]: r for r in d.year_dates(2031)}["Koningsdag"]["date"], "2031-04-26")

    def test_parse_holidays_and_upcoming(self):
        data = [{"content": [{"vacations": [
            {"type": "Kerstvakantie ", "regions": [{"region": "heel Nederland", "startdate": "2026-12-19T00:00:00.000Z", "enddate": "2027-01-03T00:00:00.000Z"}]},
            {"type": "Herfstvakantie", "regions": [{"region": "noord", "startdate": "2026-10-10T00:00:00.000Z", "enddate": "2026-10-18T00:00:00.000Z"}]},
        ]}]}]
        rows = d.parse_holidays(data, "2026-2027")
        self.assertEqual(rows[0]["title"], "Рождественские каникулы")
        self.assertEqual(rows[0]["region"], "all")
        self.assertEqual([r["title"] for r in d.upcoming(rows, date(2026, 11, 5))], ["Рождественские каникулы"])


if __name__ == "__main__":
    unittest.main()
