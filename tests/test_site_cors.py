"""CORS for checkout APIs called from the WordPress site."""
import asyncio
import os
import unittest
from types import SimpleNamespace

from aiohttp import web

import ad_contact_guide_web_runtime as cg
import config
from utils import allo_v2


class SiteCorsTests(unittest.TestCase):
    def setUp(self):
        self.orig = (config.WP_URL, config.SITE_URL, os.environ.get("SITE_EXTRA_ORIGINS"))
        config.WP_URL = "https://www.podslushano.nl/"
        config.SITE_URL = "https://www.podslushano.nl"

    def tearDown(self):
        config.WP_URL, config.SITE_URL, extra = self.orig
        if extra is None:
            os.environ.pop("SITE_EXTRA_ORIGINS", None)
        else:
            os.environ["SITE_EXTRA_ORIGINS"] = extra

    def test_www_and_bare_domain(self):
        o = allo_v2.allowed_origins()
        self.assertIn("https://www.podslushano.nl", o)
        self.assertIn("https://podslushano.nl", o)
        self.assertNotIn("https://evil.example", o)

    def test_extra_origins(self):
        os.environ["SITE_EXTRA_ORIGINS"] = "https://staging.podslushano.nl, https://new.podslushano.nl/"
        o = allo_v2.allowed_origins()
        self.assertIn("https://staging.podslushano.nl", o)
        self.assertIn("https://new.podslushano.nl", o)

    def test_contact_guide_preflight(self):
        req = SimpleNamespace(headers={"Origin": "https://podslushano.nl"})
        resp = asyncio.run(cg.contact_guide_options(req))
        self.assertEqual(resp.status, 204)
        self.assertEqual(resp.headers.get("Access-Control-Allow-Origin"), "https://podslushano.nl")
        req = SimpleNamespace(headers={"Origin": "https://evil.example"})
        resp = asyncio.run(cg.contact_guide_options(req))
        self.assertNotIn("Access-Control-Allow-Origin", resp.headers)


if __name__ == "__main__":
    unittest.main()
