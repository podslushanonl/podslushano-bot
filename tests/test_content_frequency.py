"""Ежедневные посты контент-календаря: пропущенный пост не создаётся заново (UNIQUE campaign_key)."""
import tempfile
import unittest
from datetime import datetime, time
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import handlers  # noqa: F401 — ставит обёртку ежедневных постов на seed_content_calendar
from database.models import Base, ContentPost
from handlers import content
from utils import content_frequency


class DailySeedTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{Path(self.tmp.name) / 't.db'}")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.patches = [patch.object(content, "get_session", self.sessions),
                        patch.object(content_frequency, "get_session", self.sessions)]
        for p in self.patches:
            p.start()

    async def asyncTearDown(self):
        for p in self.patches:
            p.stop()
        await self.engine.dispose()
        self.tmp.cleanup()

    async def test_skipped_daily_post_is_not_recreated(self):
        await content.seed_content_calendar()
        today = content._local_now().date()
        async with self.sessions() as s:
            row = (await s.scalars(select(ContentPost).where(
                ContentPost.campaign_key.like(f"autodaily_{today:%y%m%d}_%")))).first()
            if row is None:  # сегодня занят другим постом — пропускаем его, чтобы день освободился
                row = (await s.scalars(select(ContentPost).where(
                    func.date(ContentPost.scheduled_at) == today.isoformat()))).first()
            row.status = "skipped"
            await s.commit()
            before = await s.scalar(select(func.count()).select_from(ContentPost))
        await content.seed_content_calendar()  # раньше: IntegrityError UNIQUE campaign_key
        await content.seed_content_calendar()
        async with self.sessions() as s:
            after = await s.scalar(select(func.count()).select_from(ContentPost))
            today_daily = (await s.scalars(select(ContentPost).where(
                ContentPost.scheduled_at == datetime.combine(today, time(15, 0))))).all()
        self.assertLessEqual(after - before, 1)
        self.assertLessEqual(len(today_daily), 1)


if __name__ == "__main__":
    unittest.main()
