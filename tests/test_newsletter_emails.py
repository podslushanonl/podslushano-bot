"""Фирменные письма и подписка «Неделя в Нидерландах» с подтверждением почты."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from database.models import Base, WeekSubscriber
from utils import email_brand, email_templates, newsletter


class Req:
    def __init__(self, data=None, query=None, method="GET"):
        self.data, self.query, self.method = data or {}, query or {}, method
        self.headers = {"Origin": "https://www.podslushano.nl"}
        self.content_length, self.remote = 100, "1.2.3.4"

    async def json(self):
        return self.data


class BrandTests(unittest.TestCase):
    def test_every_template_is_branded(self):
        built = [
            email_templates.digest(week_label="w", items=[{"title": "t", "text": "x", "url": "https://a"}], unsubscribe_url="https://u"),
            email_templates.payment_received(kind="guide", item="Карточка", amount="99,00", invoice_no="1"),
            email_templates.welcome_week(unsubscribe_url="https://u", gift_url="https://g"),
            email_templates.card_renewal(name="n", until="d", plan="p", url="https://c"),
            email_templates.cabinet_login(link="https://login"),
            email_templates.donation_thanks(amount="5,00"),
        ]
        for subject, html, text in built:
            self.assertIn(email_brand.MARK, html)
            self.assertIn("/email-assets/logo.png", html.replace("deer.png", "logo.png"))
            self.assertIn("instagram.png", html)
            self.assertNotRegex(html + text + subject, r"Podslushano|\bNL\b|Mollie|iDEAL")
            self.assertTrue(text)

    def test_legacy_wrap(self):
        out = email_brand.wrap_legacy("<p>Привет</p>", "Тема · podslushano.nl")
        self.assertIn(email_brand.MARK, out)
        self.assertIn("Привет", out)
        self.assertEqual(email_brand.wrap_legacy(out), out)


class NewsletterFlowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{Path(self.tmp.name) / 't.db'}")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.mail = AsyncMock(return_value=(True, ""))
        self.patches = [patch.object(newsletter, "get_session", self.sessions),
                        patch.object(newsletter, "send_email_message", self.mail)]
        for p in self.patches:
            p.start()
        newsletter._hits.clear()

    async def asyncTearDown(self):
        for p in self.patches:
            p.stop()
        await self.engine.dispose()
        self.tmp.cleanup()

    async def status(self):
        async with self.sessions() as s:
            return (await s.execute(select(WeekSubscriber.status))).scalar_one()

    async def test_double_opt_in_welcome_and_unsubscribe(self):
        r = await newsletter.subscribe(Req({"email": "Anna@Example.nl"}))
        self.assertTrue(json.loads(r.text)["ok"])
        self.assertEqual(await self.status(), "pending")
        to, subject, html, text = self.mail.await_args.args[:4]
        self.assertEqual(to, "anna@example.nl")
        self.assertIn("Подтвердите", subject)
        token = text.split("confirm?t=")[1].split()[0]
        await newsletter.confirm(Req(query={"t": token}))
        await newsletter.confirm(Req(query={"t": token}))  # повторный клик — второго приветствия нет
        self.assertEqual(await self.status(), "active")
        welcomes = [c for c in self.mail.await_args_list if "Добро пожаловать" in c.args[1]]
        self.assertEqual(len(welcomes), 1)
        unsub = welcomes[0].kwargs["unsubscribe_url"]
        self.assertIn(unsub.replace("&", "&amp;"), welcomes[0].args[2])
        await newsletter.unsubscribe(Req(query={"t": unsub.split("t=")[1]}, method="POST"))
        self.assertEqual(await self.status(), "unsubscribed")

    async def test_bad_email_and_rate_limit(self):
        r = await newsletter.subscribe(Req({"email": "nope"}))
        self.assertEqual(r.status, 400)
        for _ in range(3):
            await newsletter.subscribe(Req({"email": "x@example.nl"}))
        r = await newsletter.subscribe(Req({"email": "x@example.nl"}))
        self.assertEqual(r.status, 429)


if __name__ == "__main__":
    unittest.main()
