import os
os.environ.setdefault("BOT_TOKEN", "123456:test")
os.environ.setdefault("ADMIN_IDS", "1")

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from aiogram.enums import ChatType, ChatMemberStatus
import config
from handlers import content
from utils import editorial_channel as ed
from utils import morning_autopublish as morning


class MorningTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.meta = {}
        self.now = datetime(2026, 10, 5, 5, 50)
        self.generated = 0
        self.sent = []
        self.paused = False
        self.can_post = True
        self.fail_send = False
        self.invalid = False
        self.username = "podslushanovnl"

        async def get(key):
            return self.meta.get(key, "")

        async def put(key, value):
            self.meta[key] = str(value)[:100]

        async def generate():
            self.generated += 1
            if self.invalid:
                return None
            return ("Доброе утро! Проверенный тестовый текст.\n\n🌦️ Погода\n\nПогода."
                    "\n\n🚇 Транспорт\n\nТранспорт.\n\n🚗 Дороги\n\nДороги.\n\n" + ed.MORNING_FOOTER)

        async def paused():
            return self.paused

        async def chat(channel):
            return SimpleNamespace(id=-100, username=self.username, type=ChatType.CHANNEL)

        async def me():
            return SimpleNamespace(id=99)

        async def member(channel, user):
            return SimpleNamespace(status=ChatMemberStatus.ADMINISTRATOR, can_post_messages=self.can_post)

        async def send(channel, text, **kwargs):
            if channel == "@podslushanovnl":
                self.sent.append((text, kwargs))
                if self.fail_send:
                    raise TimeoutError("ambiguous response")
            return SimpleNamespace(message_id=123)

        self.bot = SimpleNamespace(get_chat=chat, get_me=me, get_chat_member=member, send_message=send)
        self.patches = [patch.object(ed, "_meta_get", get), patch.object(ed, "_meta_set", put),
                        patch.object(ed, "_now", lambda: self.now), patch.object(ed, "_morning_brief", generate),
                        patch.object(content, "_is_paused", paused),
                        patch.object(config, "ANNOUNCE_CHANNEL", "@podslushanovnl")]
        for item in self.patches:
            item.start()

    async def asyncTearDown(self):
        for item in reversed(self.patches):
            item.stop()

    async def tick(self, hour, minute):
        self.now = self.now.replace(hour=hour, minute=minute)
        await morning.run_morning(self.bot, self.now)

    async def test_prepare_wait_send_once_with_real_footer(self):
        await self.tick(5, 49)
        self.assertEqual(self.generated, 0)
        await self.tick(5, 50)
        self.assertEqual(self.generated, 1)
        self.assertFalse(self.sent)
        await self.tick(5, 59)
        self.assertFalse(self.sent)
        await self.tick(6, 0)
        await self.tick(6, 1)
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.generated, 1)
        text, kwargs = self.sent[0]
        self.assertTrue(text.startswith("<i>Доброе утро!"))
        self.assertIn("<b>🌦️ Погода</b>", text)
        self.assertIn("<blockquote><i>Информация актуальна на 05:50, 05.10.2026.", text)
        self.assertNotIn("{checked_at}", text)
        self.assertEqual(kwargs["parse_mode"], "HTML")

    async def test_restart_reuses_persisted_draft(self):
        await self.tick(5, 50)
        # Only persistent Meta/draft chunks survive; no in-memory draft cache.
        await self.tick(6, 0)
        self.assertEqual(self.generated, 1)
        self.assertEqual(self.meta["editorial_morning_date"], "2026-10-05")

    async def test_expired_draft_is_researched_again(self):
        await self.tick(5, 50)
        await self.tick(6, 25)
        self.assertEqual(self.generated, 2)
        self.assertIn("06:25, 05.10.2026", self.sent[0][0])

    async def test_pause_and_wrong_channel_and_missing_rights_block(self):
        self.paused = True
        await self.tick(6, 0)
        self.paused = False
        self.can_post = False
        await self.tick(6, 5)
        self.can_post = True
        self.username = "anotherchannel"
        await self.tick(6, 10)
        self.assertEqual(self.generated, 0)
        self.assertFalse(self.sent)

    async def test_no_unverified_post_and_bounded_attempts(self):
        self.invalid = True
        for minute in (0, 5, 10, 15, 20):
            await self.tick(6, minute)
        self.assertEqual(self.generated, 3)
        self.assertFalse(self.sent)

    async def test_ambiguous_send_never_duplicates(self):
        self.fail_send = True
        await self.tick(6, 0)
        self.fail_send = False
        await self.tick(6, 10)
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.meta["morning_auto_2026-10-05"], "uncertain")
        self.assertNotIn("editorial_morning_date", self.meta)

    async def test_no_send_after_window_or_previous_success(self):
        await self.tick(7, 0)
        self.meta["editorial_morning_date"] = "2026-10-05"
        await self.tick(6, 0)
        self.assertFalse(self.sent)

    async def test_amsterdam_clock_in_brazil_and_after_dst(self):
        for date, utc_hour in ((datetime(2026, 10, 24, 6), 4), (datetime(2026, 10, 25, 6), 5)):
            self.meta.clear()
            self.sent.clear()
            self.now = date
            brazil = date.replace(hour=utc_hour, tzinfo=timezone.utc).astimezone(ZoneInfo("America/Sao_Paulo"))
            await morning.run_morning(self.bot, brazil)
            self.assertEqual(len(self.sent), 1)


if __name__ == "__main__":
    unittest.main()
