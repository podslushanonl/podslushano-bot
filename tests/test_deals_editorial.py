import json
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from utils import deals_editorial as editorial

def fixture():
    return {"channel_id":"-1001234567890","silent":True,"posts":[{
        "id":"sample_1","html":"<b>Проверка</b><blockquote>Условия</blockquote><tg-spoiler>CODE</tg-spoiler>",
        "buttons":[{"label":"Источник","url":"https://example.com/offer"}],
        "publish_before":(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()}]}

class DealsEditorialTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # These tests mock transport claims. Persistent receipt/conflict behavior
        # is exercised against SQLite by test_deals_intake.
        for name in ("verify_existing_posts", "record_sent"):
            mock = patch.object(editorial, name, new=AsyncMock())
            mock.start()
            self.addCleanup(mock.stop)

    def test_validation(self):
        self.assertEqual(editorial.parse_batch(json.dumps(fixture()))["posts"][0]["id"],"sample_1")
        b=fixture()
        b["posts"][0]["buttons"][0]["url"]="http://example.com"
        with self.assertRaises(ValueError):
            editorial.parse_batch(json.dumps(b))
        b=fixture()
        b["posts"].append(b["posts"][0])
        with self.assertRaises(ValueError):
            editorial.parse_batch(json.dumps(b))

    async def test_target_mismatch(self):
        with patch.object(editorial,"wp_call",new=AsyncMock(return_value={"chat":"-1009999999999"})):
            bot=AsyncMock()
            with self.assertRaises(ValueError):
                await editorial.publish_batch(bot,fixture())
            bot.send_message.assert_not_awaited()

    async def test_post_and_dedup(self):
        bot=AsyncMock()
        bot.id=42
        bot.get_chat.return_value=SimpleNamespace(type="channel")
        bot.get_chat_member.return_value=SimpleNamespace(can_post_messages=True)
        bot.send_message.return_value=SimpleNamespace(message_id=1)
        with patch.object(editorial,"wp_call",new=AsyncMock(return_value={"chat":"-1001234567890"})), patch.object(editorial,"_meta_set",new=AsyncMock(side_effect=[True,False])),patch.object(editorial.asyncio,"sleep",new=AsyncMock()):
            b=fixture()
            self.assertEqual((await editorial.publish_batch(bot,b))["sent"],1)
            self.assertEqual((await editorial.publish_batch(bot,b))["skipped"],1)
            bot.send_message.assert_awaited_once()
            args=bot.send_message.call_args
            self.assertEqual(args.args[0],-1001234567890)
            self.assertTrue(args.kwargs["disable_notification"])
            self.assertEqual(args.kwargs["parse_mode"],"HTML")
            self.assertEqual(args.kwargs["reply_markup"].inline_keyboard[0][0].url,"https://example.com/offer")

    async def test_expired(self):
        bot=AsyncMock()
        bot.id=42
        bot.get_chat.return_value=SimpleNamespace(type="channel")
        bot.get_chat_member.return_value=SimpleNamespace(can_post_messages=True)
        b=fixture()
        b["posts"][0]["publish_before"]=(datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat()
        with patch.object(editorial,"wp_call",new=AsyncMock(return_value={"chat":"-1001234567890"})),patch.object(editorial,"_meta_set",new=AsyncMock()) as claim:
            self.assertEqual((await editorial.publish_batch(bot,b))["skipped"],1)
            claim.assert_not_awaited()
            bot.send_message.assert_not_awaited()
