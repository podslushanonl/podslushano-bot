"""Практические справки сайта: проверка ответа Claude, HTML, очередь тем, публикация и обновление."""
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import config
from database.models import Base, SiteGuide
from utils import site_guides

LONG = "Это подробный абзац о том, как всё устроено и что нужно сделать читателю шаг за шагом. " * 16


def guide_json(sections=6, faq=5, steps=True):
    secs = []
    for i in range(sections):
        blocks = [["p", f"**Важно** {LONG}"], ["list", ["пункт один", "пункт два"]], ["tip", "Совет <b>с тегом</b>"]]
        if i == 1 and steps:
            blocks.append(["steps", [{"t": "Запишитесь", "d": "На сайте gemeente."}, {"t": "Придите", "d": "С паспортом."}]])
        if i == 2:
            blocks += [["check", ["Паспорт", "Договор аренды"]],
                       ["table", {"head": ["Что", "Срок"], "rows": [["BSN", "сразу"], ["DigiD", "5 дней", "лишнее"]]}],
                       ["bogus", "x"]]
        secs.append({"h": f"Раздел {i + 1}", "blocks": blocks})
    return {
        "title": "Как получить BSN в Нидерландах в 2026 году",
        "lead": "Пошагово: где оформить BSN, какие документы нужны и сколько ждать.",
        "summary": [["Где", "В gemeente"], ["Срок", "1–2 недели"]],
        "sections": secs,
        "faq": [{"q": f"Вопрос {i}?", "a": "Ответ на вопрос в двух предложениях. Ещё одно."} for i in range(faq)],
        "sources": [{"t": "Rijksoverheid", "url": "https://www.rijksoverheid.nl/bsn"},
                    {"t": "плохая", "url": "javascript:alert(1)"}],
    }


class ValidateTests(unittest.TestCase):
    def test_valid_guide_is_cleaned(self):
        g = site_guides.validate(guide_json())
        self.assertIsNotNone(g)
        self.assertEqual(len(g["sections"]), 6)
        table = [b for b in g["sections"][2]["blocks"] if b[0] == "table"][0][1]
        self.assertEqual(table["rows"][1], ["DigiD", "5 дней"])  # лишняя ячейка отрезана
        self.assertNotIn("bogus", [b[0] for s in g["sections"] for b in s["blocks"]])
        self.assertEqual([x["url"] for x in g["sources"]], ["https://www.rijksoverheid.nl/bsn"])

    def test_incomplete_guides_are_rejected(self):
        self.assertIsNone(site_guides.validate(guide_json(sections=3)))
        self.assertIsNone(site_guides.validate(guide_json(faq=2)))
        self.assertIsNone(site_guides.validate(guide_json(steps=False)))
        self.assertIsNone(site_guides.validate(guide_json(), min_words=100000))
        self.assertIsNone(site_guides.validate("text"))

    def test_html(self):
        h = site_guides.build_html(site_guides.validate(guide_json()), datetime(2026, 10, 21, 12, 0))
        self.assertTrue(h.startswith("<!-- wp:html -->"))
        for part in ('class="pg-sum"', 'class="pg-toc"', '<a href="#pg-1">', '<h2 id="pg-1">', 'class="pg-steps"',
                     'class="pg-check"', 'class="pg-table"', 'class="pg-note pg-tip"', 'class="pg-faq-i"',
                     'href="https://www.rijksoverheid.nl/bsn"', "Обновлено 21 октября 2026", "<strong>Важно</strong>"):
            self.assertIn(part, h)
        self.assertNotIn("<b>с тегом</b>", h)  # текст от модели экранируется
        self.assertIn("&lt;b&gt;с тегом&lt;/b&gt;", h)


class RunTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{Path(self.tmp.name) / 't.db'}")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.patches = [
            patch.object(site_guides, "get_session", self.sessions),
            patch.object(site_guides, "TOPICS", [("bsn", "Как получить BSN"), ("digid", "Как получить DigiD")]),
            patch.object(site_guides, "_category_id", 7),
            patch.object(config, "ADMIN_IDS", [111]),
            patch.object(config, "SITE_GUIDES_INTERVAL", 8 * 3600),
            patch.object(config, "SITE_GUIDES_REFRESH_DAYS", 120),
        ]
        for p in self.patches:
            p.start()
        self.write = patch.object(site_guides, "write_guide", AsyncMock(return_value=site_guides.validate(guide_json())))
        self.write.start()
        self.bot = SimpleNamespace(send_message=AsyncMock())

    async def asyncTearDown(self):
        self.write.stop()
        for p in self.patches:
            p.stop()
        await self.engine.dispose()
        self.tmp.cleanup()

    async def rows(self):
        async with self.sessions() as s:
            return {g.key: g for g in (await s.scalars(select(SiteGuide))).all()}

    async def test_publishes_topics_in_order_once_per_interval(self):
        create = AsyncMock(return_value=({"id": 5, "link": "https://site/bsn/"}, ""))
        with patch.object(site_guides.wp, "create_post", create):
            now = site_guides._now()   # время попытки пишется по настоящим часам
            await site_guides.run_once(self.bot, now)
            await site_guides.run_once(self.bot, now + timedelta(hours=2))   # интервал не прошёл
            self.assertEqual(create.await_count, 1)
            await site_guides.run_once(self.bot, now + timedelta(hours=9))
        self.assertEqual(create.await_count, 2)
        args, kw = create.await_args_list[0]
        self.assertEqual(args[0], "Как получить BSN в Нидерландах в 2026 году")
        self.assertEqual(kw["category_ids"], [7])
        self.assertTrue(kw["slug"].startswith("kak-poluchit-bsn"))
        rows = await self.rows()
        self.assertEqual(rows["bsn"].status, "published")
        self.assertEqual(rows["bsn"].wp_post_id, 5)
        self.bot.send_message.assert_awaited()

    async def test_failed_topic_retried_next_day_and_stale_guide_refreshed(self):
        now = datetime(2026, 10, 21, 10)
        async with self.sessions() as s:
            s.add(SiteGuide(key="bsn", query="Как получить BSN", status="failed", tried_at=now - timedelta(hours=10)))
            s.add(SiteGuide(key="digid", query="Как получить DigiD", status="published", wp_post_id=9,
                            wp_link="https://site/digid/", updated_at=now - timedelta(days=200),
                            tried_at=now - timedelta(days=200)))
            await s.commit()
        job = await site_guides.next_job(now)
        self.assertEqual(job[0], "digid")   # BSN упал меньше суток назад — сначала обновление старой справки
        update = AsyncMock(return_value=({"id": 9}, ""))
        with patch.object(site_guides.wp, "update_post", update):
            self.assertTrue(await site_guides.publish(self.bot, *job))
        self.assertEqual(update.await_args.args[0], 9)
        self.assertIn("title", update.await_args.kwargs)
        rows = await self.rows()
        self.assertEqual(rows["digid"].updated_at.date(), datetime.now().date())
        job = await site_guides.next_job(now + timedelta(days=1))
        self.assertEqual(job[0], "bsn")

    async def test_failed_refresh_keeps_guide_stale_and_suggested_topic_retried(self):
        now = datetime(2026, 10, 21, 10)
        async with self.sessions() as s:
            for k in ("bsn", "digid"):
                s.add(SiteGuide(key=k, query=k, status="published", wp_post_id=1, updated_at=now, tried_at=now))
            s.add(SiteGuide(key="vog", query="Как получить VOG", status="failed", tried_at=now - timedelta(days=2)))
            s.add(SiteGuide(key="old", query="Старая", status="published", wp_post_id=3,
                            updated_at=now - timedelta(days=300), tried_at=now - timedelta(days=300)))
            await s.commit()
        self.assertEqual((await site_guides.next_job(now))[0], "vog")   # предложенная тема повторяется
        self.write.stop()
        with patch.object(site_guides, "write_guide", AsyncMock(return_value=None)):
            await site_guides.publish(self.bot, "vog", "Как получить VOG", None)
            await site_guides.publish(self.bot, "old", "Старая", (await self.rows())["old"])
        self.write.start()
        old = (await self.rows())["old"]
        self.assertEqual(old.status, "published")
        self.assertLess(old.updated_at, now - timedelta(days=200))   # срок свежести не сдвинулся
        later = site_guides._now() + timedelta(days=2)
        job = await site_guides.next_job(later)
        self.assertIn(job[0], ("vog", "old"))

    async def test_bad_answer_is_recorded_as_failed(self):
        self.write.stop()
        with patch.object(site_guides, "write_guide", AsyncMock(return_value=None)):
            self.assertFalse(await site_guides.publish(self.bot, "bsn", "Как получить BSN", None))
        self.write.start()
        self.assertEqual((await self.rows())["bsn"].status, "failed")

    async def test_new_topic_suggested_when_list_done(self):
        now = datetime(2026, 10, 21, 10)
        async with self.sessions() as s:
            for k in ("bsn", "digid"):
                s.add(SiteGuide(key=k, query=k, status="published", wp_post_id=1, updated_at=now))
            await s.commit()
        with patch.object(site_guides, "suggest_topic", AsyncMock(return_value=("vog", "Как получить VOG"))):
            self.assertEqual(await site_guides.next_job(now), ("vog", "Как получить VOG", None))
        with patch.object(site_guides, "suggest_topic", AsyncMock(return_value=("bsn", "дубль"))):
            self.assertIsNone(await site_guides.next_job(now))


if __name__ == "__main__":
    unittest.main()
