"""Учёт расходов на Claude API: цена ответа и сумма за день."""
import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from database import db
from database.models import Base
from utils import ai_usage


def usage(i, o, search=0):
    return SimpleNamespace(input_tokens=i, output_tokens=o, cache_creation_input_tokens=0, cache_read_input_tokens=0,
                           server_tool_use=SimpleNamespace(web_search_requests=search))


class UsageTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{Path(self.tmp.name) / 't.db'}")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.p = patch.object(db, "get_session", async_sessionmaker(self.engine, expire_on_commit=False))
        self.p.start()

    async def asyncTearDown(self):
        self.p.stop()
        await self.engine.dispose()
        self.tmp.cleanup()

    def test_cost(self):
        _, usd = ai_usage.cost("claude-sonnet-5-5", usage(100_000, 10_000, search=5))
        self.assertAlmostEqual(usd, 0.2 + 0.1 + 0.05)
        _, usd = ai_usage.cost("claude-haiku-5-5", usage(1_000_000, 0))
        self.assertAlmostEqual(usd, 0.10)

    async def test_wrapped_client_records_per_day(self):
        resp = SimpleNamespace(usage=usage(10_000, 2_000))
        client = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock(return_value=resp)))
        ai_usage.instrument(client)
        self.assertIs(await client.messages.create(model="claude-sonnet-5-5", max_tokens=10), resp)
        await client.messages.create(model="claude-sonnet-5-5", max_tokens=10)
        (_, models), = await ai_usage.days()
        self.assertEqual(models["claude-sonnet-5-5"]["calls"], 2)
        self.assertAlmostEqual(models["claude-sonnet-5-5"]["usd"], 2 * (0.02 + 0.02))

    async def test_concurrent_records_are_all_counted(self):
        resp = SimpleNamespace(usage=usage(1_000, 100))
        await ai_usage.record("claude-haiku-5-5", resp)
        await asyncio.gather(*(ai_usage.record("claude-haiku-5-5", resp) for _ in range(10)))
        (_, models), = await ai_usage.days()
        self.assertEqual(models["claude-haiku-5-5"]["calls"], 11)


if __name__ == "__main__":
    unittest.main()
