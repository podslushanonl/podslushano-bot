import unittest
from unittest import mock

from utils import site_pages as sp


class SitePagesTest(unittest.IsolatedAsyncioTestCase):
    async def _run(self, existing):
        calls = []

        async def fake(method, path, params=None, payload=None):
            calls.append((method, path))
            if method == "GET":
                return 200, existing
            return 201 if path == "pages" else 200, {"id": 7}

        with mock.patch.object(sp.wp, "wp_enabled", return_value=True), mock.patch.object(sp.wp, "_wp_json", fake):
            done = await sp.sync_pages()
        return calls, done

    async def test_creates_missing_page(self):
        calls, done = await self._run([])
        self.assertIn(("POST", "pages"), calls)
        self.assertIn("privacy-app: создана", done)

    async def test_skips_identical_and_updates_changed(self):
        page = sp.read_pages()[0]
        calls, done = await self._run([{"id": 5, "status": "publish", "content": {"raw": page["content"] + "\n"}}])
        self.assertEqual(done, [])
        calls, done = await self._run([{"id": 5, "status": "publish", "content": {"raw": "<p>старый</p>"}}])
        self.assertIn(("POST", "pages/5"), calls)
        self.assertIn("privacy-app: обновлена", done)


if __name__ == "__main__":
    unittest.main()
