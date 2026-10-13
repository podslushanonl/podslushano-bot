"""Раздел «Сэкономить»: подсказки анкеты, ссылки, напоминания и счётчик переходов."""
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from aiohttp import web
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from database.models import Base, LinkClick, SavingsReminder
from utils import savings


class TextTests(unittest.TestCase):
    def test_quiz_hints(self):
        h = " ".join(savings.quiz_hints("111111"))
        self.assertIn("бесплатно", h)
        self.assertIn("tandartsverzekering", h)
        self.assertIn("Не берите добровольный", h)
        self.assertIn("restitutiepolis", h)
        self.assertIn("Физиотерапия, очки", h)
        self.assertIn("zorgtoeslag", h)
        self.assertNotIn("лишняя", h)
        h = " ".join(savings.quiz_hints("000000"))
        self.assertIn("лишняя", h)
        self.assertNotIn("zorgtoeslag", h)
        self.assertIn("до €900", h)
        self.assertIn("naturapolis", h)
        self.assertNotIn("Детей", h)

    def test_quiz_flow_and_callback_size(self):
        text, kb = savings.question("")
        self.assertIn("Вопрос 1 из 6", text)
        self.assertEqual(kb.inline_keyboard[0][0].callback_data, "sv:q:1")
        text, kb = savings.question("10101")
        self.assertIn("Вопрос 6 из 6", text)
        self.assertIn("€43 000", text)
        text, kb = savings.result("101011")
        self.assertIn("не персональный финансовый совет", text)
        for row in kb.inline_keyboard:
            for b in row:
                self.assertLessEqual(len((b.callback_data or "").encode()), 64)

    def test_partner_links(self):
        with patch.dict(os.environ, {"SAVINGS_LINKS": ""}):
            self.assertFalse(savings.is_partner("zorg_compare"))
            self.assertEqual(savings.target("zorg_compare"), "https://www.zorgwijzer.nl/")
            self.assertEqual(savings.label("Сравнить", "zorg_compare"), "Сравнить")
        with patch.dict(os.environ, {"SAVINGS_LINKS": '{"zorg_compare": "https://p.example/x", "bad": "https://e", '
                                                       '"esim_saily": "http://insecure"}'}):
            self.assertTrue(savings.is_partner("zorg_compare"))
            self.assertEqual(savings.target("zorg_compare"), "https://p.example/x")
            self.assertFalse(savings.is_partner("esim_saily"))
            self.assertIsNone(savings.target("bad"))
            self.assertEqual(savings.label("Сравнить", "zorg_compare"), "Сравнить · партнёр")
            self.assertEqual(savings.zorg_kb().inline_keyboard[1][0].text, "🔍 Сравнить цены · партнёр")
            self.assertNotIn("партнёр", savings.ESIM_TEXT + savings.result("000000")[0])
        with patch.dict(os.environ, {"SAVINGS_LINKS": "{oops"}):
            self.assertEqual(savings.target("esim_saily"), "https://saily.com/")


class DbTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{Path(self.tmp.name) / 't.db'}")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.p = patch.object(savings, "get_session", self.sessions)
        self.p.start()

    async def asyncTearDown(self):
        self.p.stop()
        await self.engine.dispose()
        self.tmp.cleanup()

    async def test_reminder_once_and_sent_on_day(self):
        msg = await savings.add_reminder(7, date(2026, 11, 20))
        self.assertIn("12 декабря", msg)
        await savings.add_reminder(7, date(2026, 11, 21))
        late = await savings.add_reminder(8, date(2026, 12, 20))
        self.assertIn("поздно", late)
        bot = SimpleNamespace(send_message=AsyncMock())
        self.assertEqual(await savings.send_due(bot, date(2026, 12, 11)), 0)
        self.assertEqual(await savings.send_due(bot, date(2026, 12, 12)), 1)
        self.assertEqual(bot.send_message.await_args.args[0], 7)
        self.assertEqual(await savings.send_due(bot, date(2026, 12, 13)), 0)
        async with self.sessions() as s:
            self.assertEqual(len((await s.scalars(select(SavingsReminder))).all()), 1)

    async def test_go_counts_and_redirects(self):
        req = SimpleNamespace(match_info={"key": "esim_saily"}, query={"s": "IG<script>"})
        with self.assertRaises(web.HTTPFound) as cm:
            await savings.go(req)
        self.assertEqual(cm.exception.location, "https://saily.com/")
        with self.assertRaises(web.HTTPFound) as cm:
            await savings.go(SimpleNamespace(match_info={"key": "nope"}, query={}))
        self.assertEqual(cm.exception.location, savings.SITE_PAGE)
        async with self.sessions() as s:
            rows = (await s.scalars(select(LinkClick))).all()
        self.assertEqual([(r.key, r.source) for r in rows], [("esim_saily", "igscript")])
        text = await savings.stats_text()
        self.assertIn("Saily: <b>1</b>", text)



class PartnersApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_partners_flags(self):
        import json
        with patch.dict(os.environ, {"SAVINGS_LINKS": '{"esim_saily": "https://p.example/s"}'}):
            resp = await savings.partners(SimpleNamespace(headers={}))
        data = json.loads(resp.body)
        self.assertTrue(data["esim_saily"])
        self.assertFalse(data["zorg_compare"])


if __name__ == "__main__":
    unittest.main()
