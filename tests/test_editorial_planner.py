from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, MagicMock, patch

from aiogram.filters import CommandObject

from handlers import editorial_planner as handlers
from utils import editorial_planner as bridge
from utils.nav_guard import is_navigation


def message(user_id=7, chat_type="private"):
    return SimpleNamespace(
        from_user=SimpleNamespace(id=user_id, full_name="Ксюша <test>"),
        chat=SimpleNamespace(type=chat_type), answer=AsyncMock(),
    )


class PlannerConfigTests(TestCase):
    def test_disabled_without_both_settings(self):
        for env in ({}, {"EDITORIAL_PLANNER_TOKEN": "secret"},
                    {"EDITORIAL_PLANNER_URL": bridge.DEFAULT_PLANNER_URL}):
            with patch.dict("os.environ", env, clear=True):
                self.assertFalse(bridge.bridge_enabled())

    def test_links_never_follow_api_to_another_origin(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(bridge.safe_record_url("https://evil.example/?secret=1"), bridge.DEFAULT_PLANNER_URL)
            self.assertEqual(bridge.safe_record_url("https://user:pass@podslushano-editorial.alex-podslushano.chatgpt.site/"), bridge.DEFAULT_PLANNER_URL)
            self.assertEqual(bridge.open_keyboard().inline_keyboard[0][0].url, bridge.DEFAULT_PLANNER_URL)

    def test_invalid_configuration_is_not_used_for_requests(self):
        with patch.dict("os.environ", {
            "EDITORIAL_PLANNER_URL": "http://example.com/?token=bad",
            "EDITORIAL_PLANNER_TOKEN": "secret",
        }, clear=True):
            self.assertFalse(bridge.bridge_enabled())

    def test_commands_escape_unfinished_forms(self):
        for value in ("/task Снять рынок", "/idea@podslushano_nl_bot История", "/planner_link abc", "/planner_post", "/direction Видео"):
            self.assertTrue(is_navigation(value))


class PlannerHandlersTests(IsolatedAsyncioTestCase):
    async def test_post_is_admin_only_and_does_not_choose_other_chat(self):
        m = message()
        with patch.object(handlers.config, "ADMIN_IDS", [42]):
            await handlers.planner_post(m)
            m.answer.assert_not_awaited()
            m = message(42)
            await handlers.planner_post(m)
            self.assertEqual(m.answer.await_count, 1)
            self.assertEqual(m.answer.call_args.kwargs["reply_markup"].inline_keyboard[0][0].url, bridge.planner_url())

    async def test_binding_code_is_not_transmitted_from_a_group(self):
        m = message(chat_type="supergroup")
        with patch.object(handlers, "planner_request", new_callable=AsyncMock) as request:
            await handlers.planner_link(m, CommandObject(command="planner_link", args="abcd"))
            request.assert_not_awaited()
            self.assertIn("личные", m.answer.call_args.args[0])

    async def test_create_uses_telegram_identity_and_separate_description(self):
        m = message()
        with patch.object(handlers, "planner_request", new_callable=AsyncMock,
                          return_value={"record": {"id": "t", "title": "Рынок"}, "url": bridge.planner_url()+"/?task=t"}) as request:
            await handlers.planner_task(m, CommandObject(command="task", args="Рынок\nСнять общий план"))
            request.assert_awaited_once_with("create", telegramId=7, kind="task", title="Рынок", description="Снять общий план")
            self.assertNotIn("authorId", request.call_args.kwargs)

    async def test_empty_command_does_not_create_a_task(self):
        m = message()
        with patch.object(handlers, "planner_request", new_callable=AsyncMock) as request:
            await handlers.planner_idea(m, CommandObject(command="idea"))
            request.assert_not_awaited()
            self.assertIn("/idea", m.answer.call_args.args[0])

    async def test_api_denial_is_shown_without_success_message(self):
        m = message()
        with patch.object(handlers, "planner_request", new_callable=AsyncMock,
                          side_effect=bridge.PlannerError("Сначала подключите профиль")):
            await handlers.planner_task(m, CommandObject(command="task", args="Рынок"))
            self.assertIn("подключите", m.answer.call_args.args[0])
            self.assertNotIn("добавлена", m.answer.call_args.args[0])


class PlannerQueueTests(IsolatedAsyncioTestCase):
    async def test_unconfigured_bridge_makes_no_network_requests(self):
        with patch.dict("os.environ", {}, clear=True), patch.object(bridge, "planner_request", new_callable=AsyncMock) as request:
            self.assertEqual(await bridge.process_planner_reminders(SimpleNamespace(send_message=AsyncMock())), 0)
            request.assert_not_awaited()

    async def test_delivery_precedes_ack_and_failed_delivery_is_not_acked(self):
        items = [
            {"id": "one", "telegramId": 7, "text": "Срок сегодня", "url": bridge.planner_url()},
            {"id": "two", "telegramId": 8, "text": "Вторая задача", "url": bridge.planner_url()},
        ]
        request = AsyncMock(side_effect=[{"items": items}, {"ok": True}])
        bot = SimpleNamespace(send_message=AsyncMock(side_effect=[None, RuntimeError("blocked")]))
        with patch.object(bridge, "bridge_enabled", return_value=True), patch.object(bridge, "planner_request", request), \
             patch.object(bridge, "_already_delivered", AsyncMock(return_value=False)), \
             patch.object(bridge, "_mark_delivered", AsyncMock()) as remembered:
            self.assertEqual(await bridge.process_planner_reminders(bot), 1)
            remembered.assert_awaited_once_with("one")
            self.assertEqual(request.await_args_list[-1].kwargs, {"id": "one"})
            self.assertEqual(request.await_count, 2)
            self.assertIsNone(bot.send_message.call_args_list[0].kwargs["parse_mode"])

    async def test_delivered_marker_retries_ack_without_sending_again(self):
        item = {"id": "one", "telegramId": 7, "text": "Срок сегодня"}
        bot = SimpleNamespace(send_message=AsyncMock())
        request = AsyncMock(side_effect=[{"items": [item]}, {"ok": True}])
        with patch.object(bridge, "bridge_enabled", return_value=True), patch.object(bridge, "planner_request", request), \
             patch.object(bridge, "_already_delivered", AsyncMock(return_value=True)):
            self.assertEqual(await bridge.process_planner_reminders(bot), 0)
            bot.send_message.assert_not_awaited()
            request.assert_awaited_with("ack", id="one")


class PlannerHttpTests(IsolatedAsyncioTestCase):
    async def test_auth_errors_explain_bridge_and_profile_failures_separately(self):
        cases = (
            (401, "bind", "EDITORIAL_PLANNER_TOKEN"),
            (401, "create", "EDITORIAL_PLANNER_TOKEN"),
            (403, "bind", "Доступ к профилю"),
            (403, "create", "Получить код подключения"),
        )
        for status, action, expected in cases:
            with self.subTest(status=status, action=action):
                response = MagicMock(status=status)
                response.json = AsyncMock(return_value={"error": "untrusted test-secret"})
                response_context = MagicMock()
                response_context.__aenter__ = AsyncMock(return_value=response)
                response_context.__aexit__ = AsyncMock(return_value=False)
                session = MagicMock()
                session.post.return_value = response_context
                session_context = MagicMock()
                session_context.__aenter__ = AsyncMock(return_value=session)
                session_context.__aexit__ = AsyncMock(return_value=False)
                with patch.dict("os.environ", {
                    "EDITORIAL_PLANNER_URL": bridge.DEFAULT_PLANNER_URL,
                    "EDITORIAL_PLANNER_TOKEN": "test-secret",
                }, clear=True), patch.object(bridge.aiohttp, "ClientSession", return_value=session_context):
                    with self.assertRaises(bridge.PlannerError) as error:
                        await bridge.planner_request(action)
                    self.assertIn(expected, str(error.exception))
                    self.assertNotIn("test-secret", str(error.exception))
                    response.json.assert_not_awaited()

    async def test_secret_is_in_header_and_redirects_are_disabled(self):
        response = MagicMock(status=200)
        response.json = AsyncMock(return_value={"ok": True})
        response_context = MagicMock()
        response_context.__aenter__ = AsyncMock(return_value=response)
        response_context.__aexit__ = AsyncMock(return_value=False)
        session = MagicMock()
        session.post.return_value = response_context
        session_context = MagicMock()
        session_context.__aenter__ = AsyncMock(return_value=session)
        session_context.__aexit__ = AsyncMock(return_value=False)
        with patch.dict("os.environ", {"EDITORIAL_PLANNER_URL": bridge.DEFAULT_PLANNER_URL, "EDITORIAL_PLANNER_TOKEN": "test-secret"}, clear=True), \
             patch.object(bridge.aiohttp, "ClientSession", return_value=session_context):
            self.assertEqual(await bridge.planner_request("ack", id="one"), {"ok": True})
            args, kwargs = session.post.call_args
            self.assertNotIn("test-secret", args[0])
            self.assertEqual(kwargs["headers"]["Authorization"], "Bearer test-secret")
            self.assertFalse(kwargs["allow_redirects"])
