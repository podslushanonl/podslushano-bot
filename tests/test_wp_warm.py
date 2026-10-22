"""Прогрев кэша сайта после публикации."""
import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from utils import wordpress as wp


class WarmTests(unittest.IsolatedAsyncioTestCase):
    async def test_warms_post_home_and_news_once(self):
        warm = AsyncMock()
        with patch.object(wp, "_wp_url", return_value="https://site"), patch.object(wp, "_warm", warm):
            wp.warm_cache("https://site/post/")
            await asyncio.gather(*list(wp._WARM_TASKS))
        warm.assert_awaited_once_with(["https://site/post/", "https://site/", "https://site/news/"])
        self.assertFalse(wp._WARM_TASKS)

    async def test_no_site_no_warm(self):
        warm = AsyncMock()
        with patch.object(wp, "_wp_url", return_value=""), patch.object(wp, "_warm", warm):
            wp.warm_cache("x")
        warm.assert_not_called()


if __name__ == "__main__":
    unittest.main()
