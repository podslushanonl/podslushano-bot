"""Автоновости сайта: RSS, первый запуск, дубли, лимиты, HTML и публикация."""
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import config
from database.models import Base, SiteNewsItem
from utils import site_news

NOW = datetime(2026, 10, 12, 10, 0, tzinfo=timezone.utc)


def rss(items):
    body = "".join(
        f"""<item><title><![CDATA[{title}]]></title><link>{link}</link>
        <description><![CDATA[{desc}]]></description>
        <enclosure type="image/webp" url="https://images.cdn.nos.nl/{n}.webp"/>
        <pubDate>{date}</pubDate><guid isPermaLink="true">{link}</guid></item>"""
        for n, (title, link, desc, date) in enumerate(items)
    )
    return (f'<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>'
            f"<title>NOS Nieuws</title>{body}</channel></rss>").encode()


def rfc822(dt):
    return dt.astimezone(timezone(timedelta(hours=2))).strftime("%a, %d %b %Y %H:%M:%S +0200")


LONG_NL = "<p>" + "De NS rijdt vandaag minder treinen door werkzaamheden. " * 20 + "</p>"
ARTICLE = {
    "cat": "Транспорт",
    "h": "NS отменяет часть поездов в Utrecht",
    "lead": "Из-за ремонта путей в выходные поездов будет меньше.",
    "blocks": [["p", "Первый абзац."], ["h2", "Что меняется"],
               ["p", "Второй абзац."], ["quote", "Цитата представителя NS."]],
}


def item(url, title="Treinen", desc="", published=NOW):
    return site_news.FeedItem(url=url, title=title, description=desc,
                              published=published, source="NOS")


class ParseTests(unittest.TestCase):
    def test_parse_rss(self):
        xml = rss([
            ("Storing bij NS &amp; Schiphol", "https://nos.nl/l/1?utm_source=rss#x", LONG_NL,
             rfc822(NOW)),
            ("", "https://nos.nl/l/2", "x", rfc822(NOW)),  # без заголовка — пропуск
        ])
        items = site_news.parse_feed(xml, "https://feeds.nos.nl/nosnieuwsalgemeen")
        self.assertEqual(len(items), 1)
        it = items[0]
        self.assertEqual(it.url, "https://nos.nl/l/1")
        self.assertEqual(it.title, "Storing bij NS & Schiphol")
        self.assertEqual(it.source, "NOS")
        self.assertEqual(it.published, NOW)
        self.assertEqual(it.image, "https://images.cdn.nos.nl/0.webp")
        self.assertTrue(it.description.startswith("De NS rijdt"))
        self.assertNotIn("<p>", it.description)

    def test_bad_xml_and_source_names(self):
        self.assertEqual(site_news.parse_feed(b"<rss><oops", "https://x.nl/f"), [])
        self.assertEqual(site_news.source_name("https://www.nu.nl/rss"), "NU.nl")
        self.assertEqual(site_news.source_name("https://feeds.example.nl/x"), "Example")

    def test_freshness(self):
        self.assertTrue(site_news.is_fresh(item("u", published=NOW - timedelta(hours=5)), NOW))
        self.assertFalse(site_news.is_fresh(item("u", published=NOW - timedelta(hours=7)), NOW))

    def test_build_html_escapes(self):
        art = {"h": "x", "blocks": [("p", "A < B & \"C\""), ("h2", "<script>"),
                                     ("quote", "«Да»")]}
        out = site_news.build_html(art, 'https://nos.nl/a?b=1&c="2"', "NOS")
        self.assertIn("<!-- wp:paragraph -->\n<p>A &lt; B &amp; &quot;C&quot;</p>", out)
        self.assertIn("<!-- wp:heading -->\n<h2>&lt;script&gt;</h2>\n<!-- /wp:heading -->", out)
        self.assertIn('<!-- wp:quote -->\n<blockquote class="wp-block-quote"><p>«Да»</p>'
                      "</blockquote>\n<!-- /wp:quote -->", out)
        self.assertIn('href="https://nos.nl/a?b=1&amp;c=&quot;2&quot;"', out)
        self.assertTrue(out.endswith(
            "rel=\"noopener\">NOS</a>. Текст подготовила редакция podslushano.nl.</em></p>\n"
            "<!-- /wp:paragraph -->"))
        self.assertNotIn("<script>", out)

    def test_validate_article(self):
        self.assertIsNotNone(site_news.validate_article(ARTICLE))
        self.assertIsNone(site_news.validate_article({**ARTICLE, "cat": "Политика"}))
        self.assertIsNone(site_news.validate_article({**ARTICLE, "blocks": ARTICLE["blocks"][:3]}))
        self.assertIsNone(site_news.validate_article("not a dict"))
        cleaned = site_news.validate_article({**ARTICLE, "lead": "Читайте на **Podslushano.NL** 🚆"})
        self.assertEqual(cleaned["lead"], "Читайте на podslushano.nl")

    def test_slug(self):
        self.assertEqual(site_news.make_slug("Жара в Amsterdam: KNMI объявил «оранжевый» код"),
                         "zhara-v-amsterdam-knmi-obyavil-oranzhevyy-kod")
        self.assertLessEqual(len(site_news.make_slug("очень длинный заголовок " * 10)), 60)


class RunTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{Path(self.tmp.name) / 't.db'}")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.patches = [
            patch.object(site_news, "get_session", self.sessions),
            patch.object(config, "SITE_NEWS_PER_RUN", 2),
            patch.object(config, "SITE_NEWS_DAILY_MAX", 20),
            patch.object(config, "ADMIN_IDS", [111]),
        ]
        for p in self.patches:
            p.start()
        site_news._category_ids.clear()
        self.feed = []
        self.collect = patch.object(site_news, "collect_items", AsyncMock(side_effect=lambda: list(self.feed)))
        self.collect.start()
        self.bot = SimpleNamespace(send_message=AsyncMock())

    async def asyncTearDown(self):
        self.collect.stop()
        for p in self.patches:
            p.stop()
        await self.engine.dispose()
        self.tmp.cleanup()

    async def rows(self):
        async with self.sessions() as s:
            return {r.source_url: r for r in (await s.scalars(select(SiteNewsItem))).all()}

    async def seed(self, url, status="skipped", created=None):
        async with self.sessions() as s:
            s.add(SiteNewsItem(source_url=url, title_nl="t", status=status,
                               created_at=created or NOW.replace(tzinfo=None)))
            await s.commit()

    async def test_first_run_marks_everything_initial(self):
        self.feed = [item("https://nos.nl/l/1"), item("https://nos.nl/l/2", published=NOW - timedelta(days=2))]
        ask = AsyncMock()
        with patch.object(site_news, "_ask_claude", ask):
            await site_news.run_once(self.bot, NOW)
        rows = await self.rows()
        self.assertEqual({r.status for r in rows.values()}, {"skipped"})
        self.assertEqual({r.reason for r in rows.values()}, {"initial"})
        self.assertEqual(len(rows), 2)
        ask.assert_not_called()

    async def test_dedup_and_old_items_ignored(self):
        await self.seed("https://nos.nl/l/1")
        self.feed = [item("https://nos.nl/l/1"),
                     item("https://nos.nl/l/old", published=NOW - timedelta(hours=8))]
        ask = AsyncMock()
        with patch.object(site_news, "_ask_claude", ask):
            await site_news.run_once(self.bot, NOW)
        ask.assert_not_called()
        self.assertEqual(set(await self.rows()), {"https://nos.nl/l/1"})

    async def test_daily_cap_skips_without_claude(self):
        await self.seed("https://nos.nl/l/0", "published", NOW.replace(tzinfo=None) - timedelta(hours=1))
        self.feed = [item("https://nos.nl/l/5")]
        ask = AsyncMock()
        with patch.object(config, "SITE_NEWS_DAILY_MAX", 1), patch.object(site_news, "_ask_claude", ask):
            await site_news.run_once(self.bot, NOW)
        ask.assert_not_called()
        row = (await self.rows())["https://nos.nl/l/5"]
        self.assertEqual((row.status, row.reason), ("skipped", "дневной лимит"))

    async def test_daily_count_uses_amsterdam_day(self):
        # 23:30 UTC накануне = 01:30 по Амстердаму сегодня → считается; 21:00 UTC — вчера.
        await self.seed("a", "published", datetime(2026, 10, 11, 23, 30))
        await self.seed("b", "published", datetime(2026, 10, 11, 21, 0))
        await self.seed("c", "skipped", datetime(2026, 10, 12, 9, 0))
        self.assertEqual(await site_news.published_today(NOW), 1)

    async def test_publish_flow_with_photo(self):
        await self.seed("https://nos.nl/l/seen")
        self.feed = [item("https://nos.nl/l/10", "NS-storing", site_news._plain(LONG_NL)),
                     item("https://nos.nl/l/11", "Verkiezingsdebat", site_news._plain(LONG_NL)),
                     item("https://nos.nl/l/12", "Ajax wint", site_news._plain(LONG_NL))]
        triage = json.dumps({"chosen": ["https://nos.nl/l/10"],
                             "skipped": {"https://nos.nl/l/11": "политика"}})
        ask = AsyncMock(side_effect=[triage, json.dumps(ARTICLE, ensure_ascii=False)])
        page = {"title": "t", "text": "", "url": "https://nos.nl/artikel/10-ns",
                "image": "https://images.cdn.nos.nl/og.webp"}
        upload = AsyncMock(return_value=({"id": 77, "source_url": "u"}, ""))
        create = AsyncMock(return_value=({"id": 501, "link": "https://podslushano.nl/ns/",
                                          "edit": "e", "status": "publish"}, ""))
        cats = AsyncMock(side_effect=[5, 9])
        with patch.object(site_news, "_ask_claude", ask), \
                patch.object(site_news, "fetch_article", AsyncMock(return_value=page)), \
                patch.object(site_news, "download_image",
                             AsyncMock(return_value=(b"img", "image/webp"))) as dl, \
                patch.object(site_news.wp, "upload_media", upload), \
                patch.object(site_news.wp, "create_post", create), \
                patch.object(site_news.wp, "ensure_category", cats):
            await site_news.run_once(self.bot, NOW)

        dl.assert_awaited_once_with("https://images.cdn.nos.nl/og.webp")
        self.assertEqual(upload.await_args.kwargs["caption"], "Фото: NOS")
        self.assertTrue(upload.await_args.args[0].endswith(".webp"))
        self.assertEqual(cats.await_args_list[0].args, ("Новости",))
        self.assertEqual(cats.await_args_list[1].args, ("Транспорт",))
        self.assertEqual(cats.await_args_list[1].kwargs, {"parent_id": 5})
        kw = create.await_args.kwargs
        self.assertEqual(kw["status"], "publish")
        self.assertEqual(kw["featured_media"], 77)
        self.assertEqual(kw["category_ids"], [9])
        self.assertEqual(kw["excerpt"], ARTICLE["lead"])
        self.assertTrue(kw["slug"].startswith("ns-otmenyaet"))
        self.assertIn("https://nos.nl/artikel/10-ns", create.await_args.args[1])

        rows = await self.rows()
        self.assertEqual((rows["https://nos.nl/l/10"].status, rows["https://nos.nl/l/10"].wp_post_id),
                         ("published", 501))
        self.assertEqual(rows["https://nos.nl/l/10"].wp_link, "https://podslushano.nl/ns/")
        self.assertEqual(rows["https://nos.nl/l/11"].reason, "политика")
        self.assertEqual(rows["https://nos.nl/l/12"].status, "skipped")
        self.bot.send_message.assert_awaited_once()
        self.assertEqual(self.bot.send_message.await_args.args[0], 111)
        self.assertIn("https://podslushano.nl/ns/", self.bot.send_message.await_args.args[1])

    async def test_publish_without_photo(self):
        await self.seed("https://nos.nl/l/seen")
        it = item("https://nos.nl/l/20", "Hitte", site_news._plain(LONG_NL))
        self.feed = [it]
        ask = AsyncMock(side_effect=[json.dumps({"chosen": [it.url]}), json.dumps(ARTICLE)])
        create = AsyncMock(return_value=({"id": 1, "link": "l"}, ""))
        upload = AsyncMock()
        with patch.object(site_news, "_ask_claude", ask), \
                patch.object(site_news, "fetch_article", AsyncMock(return_value=None)), \
                patch.object(site_news.wp, "upload_media", upload), \
                patch.object(site_news.wp, "create_post", create), \
                patch.object(site_news.wp, "ensure_category", AsyncMock(return_value=3)):
            await site_news.run_once(self.bot, NOW)
        upload.assert_not_called()
        self.assertIsNone(create.await_args.kwargs["featured_media"])
        self.assertEqual((await self.rows())[it.url].status, "published")

    async def test_invalid_json_marks_failed_and_continues(self):
        await self.seed("https://nos.nl/l/seen")
        a = item("https://nos.nl/l/30", "A", site_news._plain(LONG_NL))
        b = item("https://nos.nl/l/31", "B", site_news._plain(LONG_NL))
        self.feed = [a, b]
        ask = AsyncMock(side_effect=[json.dumps({"chosen": [a.url, b.url]}),
                                     "извините, не могу", json.dumps(ARTICLE)])
        create = AsyncMock(return_value=({"id": 2, "link": "l"}, ""))
        with patch.object(site_news, "_ask_claude", ask), \
                patch.object(site_news, "fetch_article", AsyncMock(return_value=None)), \
                patch.object(site_news.wp, "create_post", create), \
                patch.object(site_news.wp, "ensure_category", AsyncMock(return_value=3)):
            await site_news.run_once(self.bot, NOW)
        rows = await self.rows()
        self.assertEqual(rows[a.url].status, "failed")
        self.assertEqual(rows[b.url].status, "published")
        create.assert_awaited_once()

    async def test_per_run_cap_leaves_extra_for_next_run(self):
        await self.seed("https://nos.nl/l/seen")
        its = [item(f"https://nos.nl/l/4{i}", f"T{i}", site_news._plain(LONG_NL)) for i in range(3)]
        self.feed = its
        ask = AsyncMock(side_effect=[json.dumps({"chosen": [i.url for i in its]}),
                                     json.dumps(ARTICLE), json.dumps(ARTICLE)])
        create = AsyncMock(return_value=({"id": 2, "link": "l"}, ""))
        with patch.object(site_news, "_ask_claude", ask), \
                patch.object(site_news, "fetch_article", AsyncMock(return_value=None)), \
                patch.object(site_news.wp, "create_post", create), \
                patch.object(site_news.wp, "ensure_category", AsyncMock(return_value=3)):
            await site_news.run_once(self.bot, NOW)
        rows = await self.rows()
        self.assertEqual(create.await_count, 2)
        self.assertNotIn(its[2].url, rows)

    async def test_triage_failure_records_nothing(self):
        await self.seed("https://nos.nl/l/seen")
        self.feed = [item("https://nos.nl/l/50", "X", site_news._plain(LONG_NL))]
        with patch.object(site_news, "_ask_claude", AsyncMock(side_effect=RuntimeError("down"))):
            await site_news.run_once(self.bot, NOW)
        self.assertNotIn("https://nos.nl/l/50", await self.rows())


if __name__ == "__main__":
    unittest.main()
