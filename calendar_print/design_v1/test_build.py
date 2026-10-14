"""Smoke tests for the selected v1 specimen; no bot imports or network."""
import calendar
import unittest
from pathlib import Path
from pypdf import PdfReader
import build_calendar as build

class CalendarDesignTest(unittest.TestCase):
    def test_data(self):
        self.assertEqual(build.DATA["year"], 2027)
        self.assertEqual(len(build.CONTENT), 12)
        self.assertTrue(all("Z" in v["regions"] for v in build.VAC))
        self.assertTrue(any(e["m"] == 1 and e["d"] == 31 and e["kind"] == "dead" for e in build.EV))
        self.assertEqual(sum(calendar.monthrange(2027, m)[1] for m in range(1, 13)), 365)

    def test_assets(self):
        for name in ["Onest.ttf", "Rubik.ttf", "photo_cover.jpg"] + [f"photo_{m}.jpg" for m in range(1, 13)]:
            self.assertTrue((build.ASSETS / name).is_file(), name)

    def test_outputs(self):
        import json
        report=json.loads((build.OUT / "layout-checks.json").read_text())
        self.assertGreater(report["checks"], 0)
        self.assertEqual(report["violations"], [])
        for name, width, height in [("Nederland-2027-new-design.pdf",297,210),("Nederland-2027-bleed-3mm.pdf",303,216)]:
            reader=PdfReader(build.OUT / name)
            self.assertEqual(len(reader.pages),14)
            for page in reader.pages:
                self.assertAlmostEqual(float(page.mediabox.width)/build.MM,width,places=2)
                self.assertAlmostEqual(float(page.mediabox.height)/build.MM,height,places=2)
            self.assertIn("Январь", reader.pages[1].extract_text())
            self.assertIn("Koningsdag", reader.pages[4].extract_text())
        for n in range(1,15):
            self.assertTrue((build.OUT / f"page-{n:02d}.png").is_file())

if __name__ == "__main__":
    unittest.main()
