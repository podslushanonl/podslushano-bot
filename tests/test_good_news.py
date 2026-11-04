"""Хорошие новости: источники, разбор, проверка по коду, дедупликация, причины, расписание, команда."""
import json
import os
import unittest
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

os.environ.setdefault("BOT_TOKEN", "123456:test")

import config  # noqa: E402
from utils import digest_core as core  # noqa: E402
from utils import good_news as gn  # noqa: E402
from utils.site_news import FeedItem  # noqa: E402

AMS = ZoneInfo("Europe/Amsterdam")
NOW = datetime(2026, 11, 2, 8, 0, tzinfo=AMS)


def _ams(hour: int, minute: int = 0, day: int = 2) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=AMS)


def _item(title, *, url=None, desc="Описание.", hours_ago=1, source="NOS", published=True):
    pub = (NOW - timedelta(hours=hours_ago)).astimezone(gn.timezone.utc) if published else None
    return FeedItem(url=url or f"https://www.nos.nl/a/{abs(hash(title)) % 10**8}",
                    title=title, description=desc, published=pub, source=source)


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append((chat_id, text, kwargs))


# --- Замоканные ответы модели: та же форма, что у anthropic.types.Message ---------------

def _text(s):
    return SimpleNamespace(type="text", text=s)


def _thinking():
    return SimpleNamespace(type="thinking", thinking="", signature="sig")


def _tool(ids=None, *, inp=None, name=None):
    return SimpleNamespace(type="tool_use", id="toolu_1", name=name or gn.SELECT_TOOL_NAME,
                           input={"ids": ids} if inp is None else inp)


def _resp(*blocks, stop="end_turn", out=20):
    return SimpleNamespace(content=list(blocks), stop_reason=stop,
                           usage=SimpleNamespace(input_tokens=8498, output_tokens=out))


def _written(*entries):
    return _text(json.dumps(list(entries), ensure_ascii=False))


@contextmanager
def _model(*responses):
    """Подменяет клиента Anthropic: messages.create отдаёт ответы по очереди."""
    create = AsyncMock(side_effect=list(responses))
    client = SimpleNamespace(messages=SimpleNamespace(create=create))
    with patch.object(gn, "_get_client", return_value=client):
        yield create


class WindowTests(unittest.TestCase):
    def test_due_from_0730_until_noon_only(self):
        self.assertFalse(gn.is_due(_ams(7, 29)))
        self.assertTrue(gn.is_due(_ams(7, 30)))
        self.assertTrue(gn.is_due(_ams(11, 59)))
        self.assertFalse(gn.is_due(_ams(12, 0)))

    def test_default_toggle_is_on(self):
        self.assertTrue(config.GOOD_NEWS_ENABLED)


class FeedSourceTests(unittest.TestCase):
    def test_feed_list_has_working_outlets_only(self):
        feeds = config.GOOD_NEWS_FEEDS
        self.assertGreaterEqual(len(feeds), 10)
        for dead in ("nhnieuws", "omroepflevoland"):
            self.assertFalse(any(dead in f for f in feeds), dead)

    def test_broadcaster_names(self):
        self.assertEqual(gn.broadcaster("https://www.rtvoost.nl/rss"), "RTV Oost")
        self.assertEqual(gn.broadcaster("https://feeds.nos.nl/nosnieuwsbinnenland"), "NOS")
        self.assertEqual(gn.broadcaster("https://www.omropfryslan.nl/rss/index.xml"), "Omrop Fryslân")

    def test_sanitize_makes_bad_feed_parse(self):
        # Похоже на NH Nieuws в проде: недопустимый управляющий символ и голый «&» в ленте.
        raw = ('<?xml version="1.0" encoding="iso-8859-1"?><rss><channel>'
               "<item><title>Tom & Jerry \x0b rescue</title><link>https://www.nhnieuws.nl/1</link>"
               "<description>Hond gered</description></item></channel></rss>").encode("utf-8")
        with self.assertRaises(ET.ParseError):
            ET.fromstring(raw)
        items = gn.parse_feed(gn.sanitize_feed(raw), "https://www.nhnieuws.nl/rss")
        self.assertEqual(len(items), 1)
        self.assertIn("Tom & Jerry", items[0].title)

    def test_url_key_ignores_utm_slash_and_host_case(self):
        a = gn.url_key("https://WWW.Omroep.nl/nieuws/1/?utm_source=x#top")
        b = gn.url_key("https://www.omroep.nl/nieuws/1")
        self.assertEqual(a, b)


class CollectTests(unittest.TestCase):
    def test_keeps_24h_dedupes_and_skips_sent_and_negatives(self):
        items = [
            _item("Собаку спасли из канала", url="https://a.nl/1"),
            _item("Соседи собрали деньги на ремонт", url="https://a.nl/2"),
            _item("Соседи собрали деньги на ремонт", url="https://b.nl/2"),  # тот же заголовок
            _item("Рекорд в Лейдене", url="https://a.nl/3", hours_ago=30),  # старше 24 ч
            _item("Пожар в доме", url="https://a.nl/4"),  # негатив
            _item("Кошка нашлась", url="https://a.nl/5"),  # уже отправлена
            _item("Без даты", url="https://a.nl/6", published=False),
        ]
        sent = {gn.url_key("https://a.nl/5")}
        got = gn.collect(NOW, sent, items)
        self.assertEqual([i.url for i in got], ["https://a.nl/1", "https://a.nl/2"])

    def test_cap_at_max_candidates(self):
        items = [_item(f"Новость номер {i} хорошая", url=f"https://a.nl/{i}", hours_ago=1) for i in range(100)]
        self.assertEqual(len(gn.collect(NOW, set(), items)), gn.MAX_CANDIDATES)


class RegexBackstopTests(unittest.TestCase):
    def test_excludes_bad_news(self):
        for title in ["Погибли двое в ДТП", "Пожар в доме", "Повышение цен на газ", "Забастовка в аэропорту",
                      "Twee doden bij ongeluk", "Drie doden bij brand", "Man overleden na val"]:
            self.assertTrue(gn.excluded(title, ""), title)

    def test_keeps_rescue_and_good_news(self):
        for title in ["Собаку спасли из канала", "Hond gered uit het kanaal",
                      "Brandweer redde kat uit boom", "Соседи собрали деньги на ремонт"]:
            self.assertFalse(gn.excluded(title, ""), title)



class VerificationTests(unittest.TestCase):
    def test_numbers_and_latin_names_must_be_in_source(self):
        src = "Omroep Brabant: 3 honden gered in Den Bosch, 12 maart."
        self.assertEqual(gn.verify_item("Три собаки 3 нашлись в Den Bosch", src), [])
        self.assertEqual(gn.verify_item("5 собак нашлись в Den Bosch", src), ["5"])
        self.assertEqual(gn.verify_item("Собаки нашлись в Eindhoven", src), ["Eindhoven"])

    def test_cyrillic_capitals_are_not_checked(self):
        self.assertEqual(gn.verify_item("Собаки нашлись", "dogs found"), [])

    def test_verify_all_drops_unsupported_and_adds_footer_fields(self):
        picked = {1: _item("Hond gevonden", url="https://www.omroepbrabant.nl/n/1",
                           desc="Hond na 3 dagen gevonden.", source="Omroep Brabant")}
        items = [{"id": 1, "emoji": "🐕", "headline": "Собака нашлась", "text": "Нашлась через 3 дня."}]
        kept, dropped = gn.verify_all(items, picked)
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["url"], "https://www.omroepbrabant.nl/n/1")
        bad = [{"id": 1, "emoji": "🐕", "headline": "Собака", "text": "Нашлась через 5 дней."}]
        kept, dropped = gn.verify_all(bad, picked)
        self.assertEqual(kept, [])
        self.assertEqual(len(dropped), 1)


class ParseTests(unittest.TestCase):
    def test_ids_from_tool_input(self):
        self.assertEqual(gn.parse_ids([3, 7]), [3, 7])
        self.assertEqual(gn.parse_ids([]), [])
        self.assertEqual(gn.parse_ids([3, 3, 9, 1, 2]), [3, 9, 1])  # уникальные, не больше 3
        self.assertIsNone(gn.parse_ids("[3, 7]"))  # строка — не список
        self.assertIsNone(gn.parse_ids([3, "x"]))
        self.assertIsNone(gn.parse_ids([True]))
        self.assertIsNone(gn.parse_ids(None))

    def test_selected_ids_read_from_tool_use_not_text(self):
        resp = _resp(_text("[9, 8]"), _tool([2]), stop="tool_use")
        self.assertEqual(gn.selected_ids(resp), [2])

    def test_selected_ids_none_without_tool_use(self):
        self.assertIsNone(gn.selected_ids(_resp(_text("[1, 2]"))))
        self.assertIsNone(gn.selected_ids(_resp(_tool([1], name="other_tool"))))
        self.assertIsNone(gn.selected_ids(_resp(_tool(inp={}))))
        self.assertIsNone(gn.selected_ids(_resp(_tool(inp={"ids": "1, 2"}))))

    def test_response_text_joins_all_text_blocks(self):
        resp = _resp(_thinking(), _text("[{\"id\": 1, "), _tool([1]), _text("\"x\": 2}]"))
        self.assertEqual(gn.response_text(resp), '[{"id": 1, "x": 2}]')
        self.assertEqual(gn.response_text(_resp(_thinking())), "")
        self.assertEqual(gn.response_text(_resp()), "")

    def test_truncated_text_is_detected_as_parse_error(self):
        truncated = '[{"id": 1, "emoji": "🐕", "headline": "Собака", "text": "Нашлась и'
        self.assertIsNone(gn.parse_json_array(truncated))
        self.assertEqual(gn.parse_json_array('[{"id": 1}]'), [{"id": 1}])


class ValidateTests(unittest.TestCase):
    def _picked(self):
        return {1: _item("A", url="https://a.nl/1"), 2: _item("B", url="https://a.nl/2")}

    def test_link_and_source_never_from_model(self):
        raw = [{"id": 1, "emoji": "🐕", "headline": "Собака", "text": "Нашлась.", "url": "https://evil.example"}]
        out = gn.validate(raw, self._picked())
        self.assertEqual(len(out), 1)
        self.assertNotIn("url", out[0])

    def test_drops_unknown_duplicate_long_and_url_text(self):
        raw = [{"id": 9, "headline": "x", "text": "y."},
               {"id": 1, "headline": "Собака", "text": "Нашлась."},
               {"id": 1, "headline": "Собака", "text": "Нашлась."},
               {"id": 2, "headline": "слово " * 11, "text": "Нашлась."},
               {"id": 2, "headline": "Собака", "text": "См. https://x.nl сейчас."}]
        self.assertEqual([i["id"] for i in gn.validate(raw, self._picked())], [1])


class RenderTests(unittest.TestCase):
    def test_empty_exact(self):
        self.assertEqual(gn.render([]), "Сегодня хороших новостей не нашлось 🙈")

    def test_footer_format_and_url_last(self):
        items = [{"emoji": "🐕", "headline": "Собака нашлась", "text": "Пёс вернулся домой.",
                  "source": "Omroep Brabant", "date": "02.11.2026", "url": "https://www.omroepbrabant.nl/n/1"}]
        expected = (
            "☀️ Хорошие новости для «Голландского перекрёстка»\n\n"
            "Доброе утро ☕️ Немного хорошего на сегодня:\n\n"
            "🐕 Собака нашлась\nПёс вернулся домой.\n"
            "Источник: Omroep Brabant · 02.11.2026\n"
            "https://www.omroepbrabant.nl/n/1\n\n"
            "Хорошего дня 🧡"
        )
        self.assertEqual(gn.render(items), expected)

    def test_date_converted_to_amsterdam(self):
        pub = datetime(2026, 11, 1, 23, 30, tzinfo=gn.timezone.utc)  # 02.11 по Амстердаму
        item = FeedItem(url="https://www.nos.nl/a", title="T", description="", published=pub, source="NOS")
        kept, _ = gn.verify_all([{"id": 1, "emoji": "🌟", "headline": "Текст", "text": "Текст."}], {1: item})
        self.assertEqual(kept[0]["date"], "02.11.2026")


class SentStoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.store = {}

        async def fake_get(key):
            return self.store.get(key)

        async def fake_set(key, value):
            self.store[key] = value

        for p in [patch.object(core, "meta_get", side_effect=fake_get),
                  patch.object(core, "meta_set", side_effect=fake_set)]:
            p.start()
            self.addCleanup(p.stop)

    async def test_sent_url_is_stored_and_reloaded(self):
        await gn._save_sent(NOW, ["https://www.nos.nl/a/1?utm_source=x"])
        loaded = await gn._load_sent(NOW)
        self.assertIn(gn.url_key("https://www.nos.nl/a/1"), loaded)

    async def test_old_entries_pruned(self):
        old = (NOW.date() - timedelta(days=gn.SENT_KEEP_DAYS + 1)).isoformat()
        self.store[gn.SENT_KEY] = json.dumps({"https://old.nl/x": old})
        self.assertEqual(await gn._load_sent(NOW), {})

    async def test_corrupt_store_is_ignored(self):
        self.store[gn.SENT_KEY] = "{не json"
        self.assertEqual(await gn._load_sent(NOW), {})


class BuildTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.store = {}

        async def fake_get(key):
            return self.store.get(key)

        async def fake_set(key, value):
            self.store[key] = value

        for p in [patch.object(core, "meta_get", side_effect=fake_get),
                  patch.object(core, "meta_set", side_effect=fake_set),
                  patch.object(gn, "_site_items", AsyncMock(return_value=[]))]:
            p.start()
            self.addCleanup(p.stop)

    def _feeds(self, items):
        return patch.object(gn, "_load_all_feeds", AsyncMock(return_value=items))

    async def test_backstop_applies_to_rss_items_before_model(self):
        bad = _item("Погибли двое в ДТП", url="https://a.nl/x")
        with self._feeds([bad]), _model() as create:
            _, reason = await gn.build(NOW)
        create.assert_not_awaited()
        self.assertEqual(reason, "no_candidates")

    async def test_two_calls_and_ok(self):
        item = _item("Собаку нашли 3 дня спустя", url="https://www.omroepbrabant.nl/n/1",
                     desc="Hond na 3 dagen teruggevonden in Tilburg.", source="Omroep Brabant")
        written = _written({"id": 1, "emoji": "🐕", "headline": "Собака нашлась", "text": "Пёс вернулся через 3 дня."})
        with self._feeds([item]), _model(_resp(_tool([1]), stop="tool_use"), _resp(written)) as create:
            items, reason = await gn.build(NOW)
        self.assertEqual(reason, "ok")
        self.assertEqual(create.await_count, 2)
        self.assertEqual(items[0]["url"], "https://www.omroepbrabant.nl/n/1")

    async def test_no_llm_without_candidates(self):
        with self._feeds([]), _model() as create:
            items, reason = await gn.build(NOW)
        self.assertEqual(reason, "no_sources")
        create.assert_not_awaited()

    async def test_model_none(self):
        item = _item("Соседи помогли", url="https://a.nl/1")
        with self._feeds([item]), _model(_resp(_tool([]), stop="tool_use")) as create:
            _, reason = await gn.build(NOW)
        self.assertEqual(reason, "model_none")
        self.assertEqual(create.await_count, 1)

    async def test_dropped_by_verification(self):
        item = _item("Собаку нашли", url="https://a.nl/1", desc="Нашли через 3 дня.")
        written = _written({"id": 1, "emoji": "🐕", "headline": "Собака", "text": "Через 9 дней."})
        with self._feeds([item]), _model(_resp(_tool([1]), stop="tool_use"), _resp(written)):
            _, reason = await gn.build(NOW)
        self.assertEqual(reason, "dropped_by_verification")


class ModelCallTests(unittest.IsolatedAsyncioTestCase):
    """Сборка с замоканным ответом модели: tool_use, пустой текст, обрезанный ответ."""

    async def asyncSetUp(self):
        for p in [patch.object(gn, "_load_sent", AsyncMock(return_value={})),
                  patch.object(gn, "_site_items", AsyncMock(return_value=[]))]:
            p.start()
            self.addCleanup(p.stop)
        self.items = [
            _item("Собаку нашли", url="https://a.nl/1", desc="Hond na 3 dagen gevonden."),
            _item("Соседи помогли", url="https://a.nl/2", desc="Buren helpen elkaar."),
        ]

    async def _build(self, *responses):
        with patch.object(gn, "_load_all_feeds", AsyncMock(return_value=self.items)), \
             _model(*responses) as create:
            items, reason = await gn.build(NOW)
        return items, reason, create

    # --- tool_use -----------------------------------------------------------------------

    async def test_select_forces_tool_without_thinking_and_bigger_limits(self):
        written = _written({"id": 1, "emoji": "🐕", "headline": "Собака нашлась", "text": "Нашлась через 3 дня."})
        _, reason, create = await self._build(_resp(_tool([1]), stop="tool_use"), _resp(written))
        self.assertEqual(reason, "ok")
        select, write = (c.kwargs for c in create.await_args_list)
        self.assertEqual(select["max_tokens"], 400)
        self.assertEqual(select["thinking"], {"type": "disabled"})
        self.assertEqual(select["tool_choice"], {"type": "tool", "name": gn.SELECT_TOOL_NAME})
        self.assertEqual([t["name"] for t in select["tools"]], [gn.SELECT_TOOL_NAME])
        schema = select["tools"][0]["input_schema"]
        self.assertEqual(schema["required"], ["ids"])
        ids = schema["properties"]["ids"]
        self.assertEqual((ids["type"], ids["items"], ids["maxItems"]), ("array", {"type": "integer"}, 3))
        self.assertEqual(write["max_tokens"], 900)
        self.assertEqual(write["thinking"], {"type": "disabled"})
        self.assertNotIn("tool_choice", write)
        self.assertNotIn("tools", write)

    async def test_ids_come_from_tool_use_block_not_text(self):
        # Текст ответа говорит [2], инструмент — [1]: верим только tool_use.
        written = _written({"id": 1, "emoji": "🐕", "headline": "Собака нашлась", "text": "Нашлась через 3 дня."})
        items, reason, create = await self._build(
            _resp(_text("Выбираю [2]"), _tool([1]), stop="tool_use"), _resp(written))
        self.assertEqual(reason, "ok")
        self.assertEqual([i["url"] for i in items], ["https://a.nl/1"])
        self.assertIn("id: 1 |", create.await_args_list[1].kwargs["messages"][0]["content"])
        self.assertNotIn("id: 2 |", create.await_args_list[1].kwargs["messages"][0]["content"])

    async def test_bad_tool_input_is_parse_error(self):
        _, reason, create = await self._build(_resp(_tool(inp={"ids": ["1"]}), stop="tool_use"))
        self.assertEqual(reason, "parse_error_select")
        self.assertEqual(create.await_count, 1)

    async def test_unknown_ids_from_tool_are_parse_error(self):
        _, reason, _ = await self._build(_resp(_tool([42]), stop="tool_use"))
        self.assertEqual(reason, "parse_error_select")

    # --- пустой текст -------------------------------------------------------------------

    async def test_prod_case_empty_select_answer_is_error_not_no_news(self):
        # Как в проде: выход=100, стоп=max_tokens, текста нет вовсе.
        _, reason, create = await self._build(_resp(_thinking(), stop="max_tokens", out=100))
        self.assertEqual(reason, "parse_error_select")
        self.assertEqual(create.await_count, 1)

    async def test_select_with_empty_text_and_no_tool_is_parse_error(self):
        _, reason, _ = await self._build(_resp(_text("")))
        self.assertEqual(reason, "parse_error_select")

    async def test_write_with_empty_text_is_parse_error(self):
        _, reason, create = await self._build(_resp(_tool([1]), stop="tool_use"), _resp(_text("")))
        self.assertEqual(reason, "parse_error_write")
        self.assertEqual(create.await_count, 2)

    async def test_write_text_assembled_from_all_blocks(self):
        entry = json.dumps([{"id": 1, "emoji": "🐕", "headline": "Собака нашлась",
                             "text": "Нашлась через 3 дня."}], ensure_ascii=False)
        cut = len(entry) // 2
        items, reason, _ = await self._build(
            _resp(_tool([1]), stop="tool_use"),
            _resp(_thinking(), _text(entry[:cut]), _text(entry[cut:])))
        self.assertEqual(reason, "ok")
        self.assertEqual(items[0]["headline"], "Собака нашлась")

    # --- обрезанный ответ ---------------------------------------------------------------

    async def test_truncated_tool_call_is_parse_error(self):
        _, reason, create = await self._build(_resp(_tool(inp={}), stop="max_tokens", out=400))
        self.assertEqual(reason, "parse_error_select")
        self.assertEqual(create.await_count, 1)

    async def test_tool_call_cut_by_max_tokens_is_not_trusted(self):
        _, reason, create = await self._build(_resp(_tool([1]), stop="max_tokens", out=400))
        self.assertEqual(reason, "parse_error_select")
        self.assertEqual(create.await_count, 1)

    async def test_truncated_write_is_parse_error(self):
        _, reason, _ = await self._build(
            _resp(_tool([1]), stop="tool_use"),
            _resp(_text('[{"id": 1, "emoji": "🐕", "headline": "Собака'), stop="max_tokens", out=900))
        self.assertEqual(reason, "parse_error_write")

    async def test_truncated_write_without_max_tokens_flag_is_parse_error(self):
        _, reason, _ = await self._build(
            _resp(_tool([1]), stop="tool_use"),
            _resp(_text('[{"id": 1, "emoji": "🐕", "headline": "Собака')))
        self.assertEqual(reason, "parse_error_write")

    async def test_run_reports_prod_case_as_error_to_admins(self):
        bot = FakeBot()
        with patch.object(gn.config, "ADMIN_IDS", [1]), \
             patch.object(gn, "_load_all_feeds", AsyncMock(return_value=self.items)), \
             _model(_resp(_thinking(), stop="max_tokens", out=100)):
            status = await gn.run(bot, NOW)
        self.assertEqual(status, "error")
        self.assertTrue(bot.sent[0][1].startswith(gn.ERROR_PREFIX))
        self.assertIn("отбор", bot.sent[0][1])


class RunTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.bot = FakeBot()
        p = patch.object(gn.config, "ADMIN_IDS", [1, 2])
        p.start()
        self.addCleanup(p.stop)

    async def test_sends_digest_to_all_admins_plain(self):
        items = [{"emoji": "🐕", "headline": "H", "text": "T.", "source": "NOS", "date": "02.11.2026", "url": "https://a.nl/1"}]
        with patch.object(gn, "build", AsyncMock(return_value=(items, "ok"))), \
             patch.object(gn, "_save_sent", AsyncMock()):
            status = await gn.run(self.bot, NOW)
        self.assertEqual(status, "sent")
        self.assertEqual([c for c, _, _ in self.bot.sent], [1, 2])
        for _, text, kwargs in self.bot.sent:
            self.assertEqual(text, gn.render(items))
            self.assertNotIn("parse_mode", kwargs)

    async def test_none_sends_empty_message(self):
        with patch.object(gn, "build", AsyncMock(return_value=([], "model_none"))):
            status = await gn.run(self.bot, NOW)
        self.assertEqual(status, "none")
        self.assertEqual(self.bot.sent[0][1], gn.EMPTY)

    async def test_parse_error_is_not_reported_as_no_news(self):
        with patch.object(gn, "build", AsyncMock(return_value=([], "parse_error_write"))):
            status = await gn.run(self.bot, NOW)
        self.assertEqual(status, "error")
        text = self.bot.sent[0][1]
        self.assertTrue(text.startswith(gn.ERROR_PREFIX))
        self.assertNotIn("не нашлось", text)

    async def test_api_error_reported_with_prefix(self):
        with patch.object(gn, "build", AsyncMock(side_effect=RuntimeError("boom"))):
            status = await gn.run(self.bot, NOW)
        self.assertEqual(status, "error")
        self.assertIn("RuntimeError: boom", self.bot.sent[0][1])
        self.assertTrue(self.bot.sent[0][1].startswith(gn.ERROR_PREFIX))

    async def test_sent_urls_recorded_only_after_send(self):
        save = AsyncMock()
        with patch.object(gn, "build", AsyncMock(return_value=([], "model_none"))), \
             patch.object(gn, "_save_sent", save):
            await gn.run(self.bot, NOW)
        save.assert_not_awaited()


class ScheduleGuardTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.store = {}

        async def fake_get(key):
            return self.store.get(key)

        async def fake_set(key, value):
            self.store[key] = value

        for p in [patch.object(core, "meta_get", side_effect=fake_get),
                  patch.object(core, "meta_set", side_effect=fake_set),
                  patch.object(gn, "enabled", return_value=True)]:
            p.start()
            self.addCleanup(p.stop)

    async def test_runs_once_per_day_within_window(self):
        run = AsyncMock(return_value="sent")
        with patch.object(gn, "run", run):
            await gn.scheduled_pass(FakeBot(), _ams(8, 0))
            await gn.scheduled_pass(FakeBot(), _ams(9, 0))
        self.assertEqual(run.await_count, 1)
        self.assertEqual(self.store[gn.LAST_DAY_KEY], "2026-11-02")

    async def test_no_catchup_after_noon(self):
        run = AsyncMock(return_value="sent")
        with patch.object(gn, "run", run):
            await gn.scheduled_pass(FakeBot(), _ams(13, 0))
        run.assert_not_awaited()

    async def test_disabled_does_nothing(self):
        run = AsyncMock(return_value="sent")
        with patch.object(gn, "enabled", return_value=False), patch.object(gn, "run", run):
            await gn.scheduled_pass(FakeBot(), _ams(8, 0))
        run.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()

