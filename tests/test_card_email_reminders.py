"""Карточки КонтактGuide без Telegram (оформлены на сайте): письмо-напоминание и истечение."""
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from database.models import Base, Specialist
from handlers import selfadd


class CardEmailReminderTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{Path(self.tmp.name) / 't.db'}")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.mail = AsyncMock(return_value=(True, ""))
        self.patches = [patch.object(selfadd, "get_session", self.sessions),
                        patch("utils.invoices.send_email_message", self.mail)]
        for p in self.patches:
            p.start()
        self.bot = SimpleNamespace(send_message=AsyncMock())

    async def asyncTearDown(self):
        for p in self.patches:
            p.stop()
        await self.engine.dispose()
        self.tmp.cleanup()

    async def add(self, days: float) -> int:
        async with self.sessions() as s:
            sp = Specialist(name="Салон Анна", category="мастер маникюра", city="Utrecht", province="Utrecht",
                            description="Маникюр", contact="x", source="self", status="active",
                            plan="year", invoice_email="anna@example.nl", submitter_user_id=None,
                            paid_until=datetime.utcnow() + timedelta(days=days))
            s.add(sp)
            await s.commit()
            return sp.id

    async def test_renewal_email_once_without_telegram(self):
        await self.add(3)
        await selfadd._send_renewal_reminders(self.bot)
        await selfadd._send_renewal_reminders(self.bot)
        self.assertEqual(self.mail.await_count, 1)
        to, subject, html_body, _ = self.mail.await_args.args
        self.assertEqual(to, "anna@example.nl")
        self.assertIn("осталось 7 дней", subject)
        self.assertIn("/cabinet/?t=", html_body)
        self.bot.send_message.assert_not_awaited()

    async def test_expired_site_card_is_hidden_and_emailed(self):
        sid = await self.add(-1)
        await selfadd._send_expiry_notices(self.bot)
        async with self.sessions() as s:
            self.assertEqual((await s.get(Specialist, sid)).status, "expired")
        self.assertIn("скрыта из поиска", self.mail.await_args.args[1])


if __name__ == "__main__":
    unittest.main()
