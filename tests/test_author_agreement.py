"""Анкета автора: страница, соглашение о неразглашении, приём формы и миграция базы.

Временная SQLite, без реальных отправок в Telegram. Запуск: python -m unittest tests.test_author_agreement
"""
import hashlib
import html
import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("BOT_TOKEN", "123456:test")
os.environ.setdefault("ADMIN_IDS", "1")

from aiohttp import web  # noqa: E402
from aiohttp.test_utils import TestClient, TestServer  # noqa: E402
from multidict import MultiDict  # noqa: E402
from sqlalchemy import inspect, select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

import database.db as db  # noqa: E402
from database.models import AuthorAgreementAcceptance, Base  # noqa: E402
from utils import authors_web as aw  # noqa: E402


def _valid_form(**overrides) -> MultiDict:
    fields = [
        ("full_name", "Anna Test"), ("city", "Utrecht"), ("email", "Anna@Example.org"),
        ("telegram", "@anna_test"), ("instagram", ""), ("phone_model", "iPhone 15"),
        ("years_nl", "1-3"), ("occupation", "Дизайнер"), ("languages", "ru"), ("languages", "nl"),
        ("about", "Люблю гулять по Утрехту и снимать новые места для друзей."),
        ("formats", "stories"), ("formats", "reviews"), ("topics", "food"),
        ("experience", "personal"), ("portfolio", "https://instagram.com/anna_test"),
        ("on_camera", "sometimes"), ("travel", "region"), ("frequency", "weekly"), ("source", "telegram"),
        ("adult", "1"), ("nda", "1"), ("accept", "1"),
    ]
    data = MultiDict(fields)
    for key, value in overrides.items():
        data.popall(key, None)
        if value is None:
            continue
        for item in value if isinstance(value, list) else [value]:
            data.add(key, item)
    return data


class AuthorPageTests(unittest.TestCase):
    def test_page_has_operator_versions_and_both_documents(self):
        page = aw._form_page()
        for text in ("Aleksei Maksimovich Egorov", "98882317", "NL005359099B74", "Karel Doormanstraat 63",
                     aw._EMAIL, f"версия {aw.AGREEMENT_VERSION}", aw.AGREEMENT_DATE,
                     aw.NDA_TITLE, f"версия {aw.NDA_VERSION}", aw.AGREEMENT_SHA256[:12], aw.NDA_SHA256[:12],
                     "независимого участия", "каждая платная задача отдельно", "не означает автоматическое принятие",
                     "Принять условия и отправить анкету"):
            self.assertIn(text, page)

    def test_page_has_every_questionnaire_field_and_three_consents(self):
        page = aw._form_page()
        for name in list(aw._TEXT_FIELDS) + list(aw._SINGLE_FIELDS) + list(aw._MULTI_FIELDS):
            self.assertIn(f'name="{name}"', page)
        for consent in ("adult", "nda", "accept"):
            self.assertIn(f'name="{consent}" value="1" required', page)

    def test_nda_shown_on_page_is_exactly_what_is_hashed(self):
        page = aw._form_page()
        standalone = aw._nda_page()
        for title, paragraphs in aw._NDA_SECTIONS:
            self.assertIn(html.escape(title), page)
            for line in paragraphs:
                shown = html.escape(line[2:] if line.startswith("• ") else line)
                self.assertIn(shown, page)
                self.assertIn(shown, standalone)
        self.assertEqual(aw.NDA_SHA256, hashlib.sha256(aw._nda_canonical().encode("utf-8")).hexdigest())

    def test_nda_covers_anonymous_senders_and_durations(self):
        text = aw._nda_canonical()
        for phrase in ("анонимн", "закрытых чатов", "24 месяца", "бессрочно", "Wet bescherming klokkenluiders",
                       "AVG/GDPR"):
            self.assertIn(phrase, text)

    def test_hashes_are_sha256(self):
        for digest in (aw.AGREEMENT_SHA256, aw.NDA_SHA256):
            self.assertEqual(len(digest), 64)
            int(digest, 16)
        self.assertIn(f"Non-Disclosure Agreement v{aw.NDA_VERSION}", aw._AGREEMENT_CANONICAL)


class ParseFormTests(unittest.TestCase):
    def test_valid_form_passes_and_maps_codes_to_labels(self):
        values, error = aw._parse_form(_valid_form())
        self.assertEqual(error, "")
        self.assertEqual(values["email"], "anna@example.org")
        answers = aw._questionnaire(values)
        self.assertEqual(answers["languages"], ["Русский", "Нидерландский"])
        self.assertEqual(answers["formats"], ["Сторис и короткие видео", "Обзоры мест, кафе и магазинов"])
        self.assertEqual(answers["years_in_nl"], "1–3 года")
        self.assertEqual(answers["source"], "Telegram")

    def test_unknown_options_are_dropped_and_order_follows_page(self):
        values, _ = aw._parse_form(_valid_form(formats=["reviews", "hack", "stories", "stories"]))
        self.assertEqual(values["formats"], ["stories", "reviews"])

    def test_errors(self):
        cases = {
            "Не заполнено": _valid_form(full_name="", travel=None),
            "хотя бы один формат": _valid_form(formats=None),
            "Выбери вариант из списка": _valid_form(experience="guru"),
            "корректный e-mail": _valid_form(email="not-an-email"),
            "подробнее": _valid_form(about="Привет"),
            "Слишком длинный": _valid_form(about="я" * 2001),
            "18 лет": _valid_form(adult=None),
            "неразглашении": _valid_form(nda=None),
            "условия участия": _valid_form(accept=None),
        }
        for expected, data in cases.items():
            with self.subTest(expected=expected):
                _, error = aw._parse_form(data)
                self.assertIn(expected, error)

    def test_rerender_keeps_answers_but_not_consents(self):
        values, error = aw._parse_form(_valid_form(nda=None))
        page = aw._form_page(error, values)
        self.assertIn('value="stories" checked', page)
        self.assertIn('value="sometimes" checked', page)
        self.assertIn('value="telegram" selected', page)
        self.assertIn("Люблю гулять по Утрехту", page)
        self.assertIn('name="nda" value="1" required>', page)   # согласие ставится заново, не заранее

    def test_admin_message_fits_telegram_limit(self):
        values, _ = aw._parse_form(_valid_form(about="а" * 2000, portfolio="b" * 1000, full_name="Я" * 200))
        message = aw._admin_message(values, aw._questionnaire(values), 7)
        self.assertLess(len(message), 4096)
        self.assertIn("PNL-AUTHOR-00007", message)


class SubmitFlowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{self.temp.name}/authors.db")
        async with self.engine.begin() as conn:
            await conn.run_sync(AuthorAgreementAcceptance.__table__.create)
        self.patches = [
            patch.object(aw, "get_session", async_sessionmaker(self.engine, expire_on_commit=False)),
            patch.object(aw.config, "ADMIN_IDS", [123]),
        ]
        for p in self.patches:
            p.start()
        self.bot = SimpleNamespace(send_message=AsyncMock())
        app = web.Application()
        app["bot"] = self.bot
        aw.install_routes(app)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        for p in self.patches:
            p.stop()
        await self.engine.dispose()
        self.temp.cleanup()

    async def rows(self):
        async with async_sessionmaker(self.engine)() as session:
            return (await session.scalars(select(AuthorAgreementAcceptance))).all()

    async def test_documents_and_short_link(self):
        for path in ("/authors/agreement", "/authors/nda", "/authors/terms"):
            resp = await self.client.get(path)
            self.assertEqual(resp.status, 200, path)
        resp = await self.client.get("/authors", allow_redirects=False)
        self.assertEqual(resp.headers["Location"], "/authors/agreement")

    async def test_submit_saves_questionnaire_nda_and_notifies_admin(self):
        resp = await self.client.post("/authors/agreement", data=_valid_form(), headers={"User-Agent": "UA/1"})
        body = await resp.text()
        self.assertEqual(resp.status, 200)
        self.assertIn("Анкета получена", body)
        self.assertIn(aw.NDA_SHA256, body)

        [row] = await self.rows()
        self.assertEqual(row.email, "anna@example.org")
        self.assertIsNone(row.instagram)
        self.assertEqual((row.agreement_version, row.agreement_sha256), (aw.AGREEMENT_VERSION, aw.AGREEMENT_SHA256))
        self.assertEqual((row.nda_version, row.nda_sha256), (aw.NDA_VERSION, aw.NDA_SHA256))
        self.assertEqual(row.user_agent, "UA/1")
        answers = json.loads(row.questionnaire)
        self.assertEqual(answers["on_camera"], "Иногда, если нужно")
        self.assertEqual(answers["topics"], ["Еда, кафе, рестораны"])

        self.bot.send_message.assert_awaited_once()
        admin_id, text = self.bot.send_message.await_args.args
        self.assertEqual(admin_id, 123)
        self.assertIn("Новая анкета автора", text)
        self.assertIn("Люблю гулять по Утрехту", text)

        again = await self.client.post("/authors/agreement", data=_valid_form(email="anna@example.org"))
        self.assertEqual(again.status, 200)
        self.assertEqual(len(await self.rows()), 1)
        self.bot.send_message.assert_awaited_once()

    async def test_invalid_submit_is_rejected_and_not_saved(self):
        resp = await self.client.post("/authors/agreement", data=_valid_form(nda=None))
        self.assertEqual(resp.status, 400)
        self.assertIn("Нужно принять соглашение о неразглашении", await resp.text())
        self.assertEqual(await self.rows(), [])
        self.bot.send_message.assert_not_awaited()


class MigrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_old_table_gets_new_columns(self):
        with tempfile.TemporaryDirectory() as temp:
            engine = create_async_engine(f"sqlite+aiosqlite:///{temp}/old.db")
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
                await conn.exec_driver_sql("DROP TABLE author_agreement_acceptances")
                await conn.exec_driver_sql(
                    "CREATE TABLE author_agreement_acceptances (id INTEGER PRIMARY KEY, full_name VARCHAR(200), "
                    "city VARCHAR(120), email VARCHAR(200), telegram VARCHAR(200), instagram VARCHAR(200), "
                    "phone_model VARCHAR(120), agreement_version VARCHAR(20), agreement_sha256 VARCHAR(64), "
                    "user_agent VARCHAR(500), accepted_at DATETIME)")
            with patch.object(db, "engine", engine):
                await db._migrate()
            async with engine.connect() as conn:
                cols = await conn.run_sync(
                    lambda c: {x["name"] for x in inspect(c).get_columns("author_agreement_acceptances")})
            await engine.dispose()
        self.assertTrue({"questionnaire", "nda_version", "nda_sha256"} <= cols)


if __name__ == "__main__":
    unittest.main()
