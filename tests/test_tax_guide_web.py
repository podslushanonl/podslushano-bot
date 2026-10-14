"""Гайд «Налоги и субсидии 2026» скачивается с сайта по прямой ссылке, без Telegram."""
import io
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from aiohttp import web

from handlers import tax_guide


class GuidePdfTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tax_guide._pdf_cache.clear()

    async def test_missing_pdf_is_404(self):
        with patch.object(tax_guide, "_get_meta", AsyncMock(return_value=None)):
            with self.assertRaises(web.HTTPNotFound):
                await tax_guide.guide_pdf(SimpleNamespace(app={}))

    async def test_serves_pdf_and_caches(self):
        bot = SimpleNamespace(get_file=AsyncMock(return_value=SimpleNamespace(file_path="d/f.pdf")),
                              download_file=AsyncMock(return_value=io.BytesIO(b"%PDF-1.7 test")))
        req = SimpleNamespace(app={"bot": bot})
        with patch.object(tax_guide, "_get_meta", AsyncMock(return_value="FILEID")):
            r1 = await tax_guide.guide_pdf(req)
            r2 = await tax_guide.guide_pdf(req)
        self.assertEqual((r1.body, r1.content_type), (b"%PDF-1.7 test", "application/pdf"))
        self.assertEqual(r2.body, b"%PDF-1.7 test")
        bot.get_file.assert_awaited_once()

    async def test_route_registered(self):
        app = web.Application()
        tax_guide.install_routes(app)
        self.assertIn("/guide/nalogi-2026.pdf", [r.resource.canonical for r in app.router.routes()])


if __name__ == "__main__":
    unittest.main()
