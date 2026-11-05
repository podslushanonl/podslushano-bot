"""Перенос новостей из подрубрик в одну рубрику «Новости» (тема — меткой)."""
import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("BOT_TOKEN", "123456:test")

from utils import wp_rubrics as rub  # noqa: E402

# Как на сайте сейчас: «новости» (строчными) с подрубриками, «Справочник» отдельно
CATS = [
    {"id": 10, "name": "новости", "slug": "dutch-news", "parent": 0, "count": 1},
    {"id": 11, "name": "Безопасность", "slug": "bez", "parent": 10, "count": 2},
    {"id": 12, "name": "Транспорт", "slug": "tr", "parent": 10, "count": 1},
    {"id": 20, "name": "Справочник", "slug": "spr", "parent": 0, "count": 1},
    {"id": 30, "name": "посты", "slug": "posts", "parent": 0, "count": 0},
    {"id": 1, "name": "Без рубрики", "slug": "uncategorized", "parent": 0, "count": 1},
]
POSTS = [
    {"id": 101, "categories": [11], "tags": []},
    {"id": 102, "categories": [11], "tags": [7]},
    {"id": 103, "categories": [12], "tags": []},
    {"id": 104, "categories": [10], "tags": []},       # уже в «Новостях»
    {"id": 105, "categories": [20], "tags": []},       # справка — не трогаем
    {"id": 106, "categories": [12, 20], "tags": []},   # новость и справка разом: справка остаётся
    {"id": 107, "categories": [1], "tags": []},        # без рубрики — только в отчёт
]


class PlanTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        for p in [patch.object(rub.wp, "all_categories", AsyncMock(return_value=CATS)),
                  patch.object(rub.wp, "all_posts", AsyncMock(return_value=POSTS))]:
            p.start()
            self.addCleanup(p.stop)

    async def test_plan_moves_only_subrubric_posts(self):
        plan = await rub.build_plan()
        moves = {m["id"]: m for m in plan["moves"]}
        self.assertEqual(sorted(moves), [101, 102, 103, 106])
        self.assertEqual(moves[101]["categories"], [10])
        self.assertEqual(moves[101]["topics"], ["Безопасность"])
        self.assertEqual(moves[106]["categories"], [20, 10])  # «Справочник» сохранён
        self.assertEqual(plan["by_topic"], {"Безопасность": 2, "Транспорт": 2})
        self.assertEqual(plan["unsorted"], 1)
        self.assertEqual(plan["total"], 7)
        self.assertTrue(plan["rename"])  # «новости» → «Новости»

    async def test_report_text(self):
        text = rub.plan_text(await rub.build_plan())
        self.assertIn("Переедут в рубрику «Новости»: <b>4</b>", text)
        self.assertIn("• Безопасность — 2", text)
        self.assertIn("переименована в «Новости»", text)
        self.assertIn("Без рубрики: 1", text)
        self.assertIn("Адреса самих записей не меняются", text)

    async def test_site_down_gives_none(self):
        with patch.object(rub.wp, "all_posts", AsyncMock(return_value=None)):
            self.assertIsNone(await rub.build_plan())

    async def test_no_news_rubric(self):
        with patch.object(rub.wp, "all_categories", AsyncMock(return_value=[CATS[3]])):
            plan = await rub.build_plan()
        self.assertEqual(plan["moves"], [])
        self.assertIn("нет рубрики «Новости»", rub.plan_text(plan))


class ApplyTests(unittest.IsolatedAsyncioTestCase):
    async def test_apply_sets_rubric_and_topic_tag_keeping_old_tags(self):
        with patch.object(rub.wp, "all_categories", AsyncMock(return_value=CATS)), \
             patch.object(rub.wp, "all_posts", AsyncMock(return_value=POSTS)):
            plan = await rub.build_plan()
        tags = {"Безопасность": 51, "Транспорт": 52}
        set_terms = AsyncMock(return_value=True)
        rename = AsyncMock(return_value=True)
        with patch.object(rub, "PAUSE_SECONDS", 0), \
             patch.object(rub.wp, "ensure_tag", AsyncMock(side_effect=lambda n: tags[n])), \
             patch.object(rub.wp, "set_post_terms", set_terms), \
             patch.object(rub.wp, "rename_category", rename), \
             patch.object(rub.wp, "refresh_site", AsyncMock(return_value=True)) as refresh:
            ok, failed = await rub.apply_plan(plan)
        self.assertEqual((ok, failed), (4, 0))
        calls = {c.args[0]: c.args[1:] for c in set_terms.await_args_list}
        self.assertEqual(calls[101], ([10], [51]))
        self.assertEqual(calls[102], ([10], [7, 51]))  # старая метка 7 не потерялась
        self.assertEqual(calls[106], ([20, 10], [52]))
        rename.assert_awaited_once_with(10, "Новости")
        refresh.assert_awaited_once()

    async def test_failures_are_counted(self):
        plan = {"news": {"id": 10, "name": "Новости"}, "rename": False, "by_topic": {"Транспорт": 1},
                "moves": [{"id": 1, "categories": [10], "topics": ["Транспорт"], "tags": []}]}
        with patch.object(rub, "PAUSE_SECONDS", 0), \
             patch.object(rub.wp, "ensure_tag", AsyncMock(return_value=5)), \
             patch.object(rub.wp, "set_post_terms", AsyncMock(return_value=False)), \
             patch.object(rub.wp, "refresh_site", AsyncMock()) as refresh:
            self.assertEqual(await rub.apply_plan(plan), (0, 1))
        refresh.assert_not_awaited()

    async def test_second_run_has_nothing_to_move(self):
        moved = [{"id": 101, "categories": [10], "tags": [51]}, {"id": 105, "categories": [20], "tags": []}]
        cats = [dict(c, name="Новости") if c["id"] == 10 else c for c in CATS]
        with patch.object(rub.wp, "all_categories", AsyncMock(return_value=cats)), \
             patch.object(rub.wp, "all_posts", AsyncMock(return_value=moved)):
            plan = await rub.build_plan()
        self.assertEqual(plan["moves"], [])
        self.assertFalse(plan["rename"])
        self.assertIn("переносить нечего", rub.plan_text(plan))


if __name__ == "__main__":
    unittest.main()
