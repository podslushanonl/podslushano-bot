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

    def test_optional_photo_and_manual_buttons(self):
        b=fixture()
        b["posts"][0]["photo_url"]="https://example.com/product.jpg"
        self.assertEqual(editorial.parse_batch(json.dumps(b))["posts"][0]["photo_url"],"https://example.com/product.jpg")
        b["posts"][0]["html"]="x"*1001
        with self.assertRaises(ValueError):
            editorial.parse_batch(json.dumps(b))
        self.assertEqual(editorial.manual_buttons("Магазин | https://example.com/a"),
                         [{"label":"Магазин","url":"https://example.com/a"}])
        with self.assertRaises(ValueError):
            editorial.manual_buttons("Магазин | http://example.com")
        self.assertIsNone(editorial.markup([]))

    async def test_photo_delivery(self):
        bot=AsyncMock()
        bot.id=42
        bot.get_chat.return_value=SimpleNamespace(type="channel")
        bot.get_chat_member.return_value=SimpleNamespace(can_post_messages=True)
        bot.send_photo.return_value=SimpleNamespace(message_id=1)
        b=fixture()
        b["posts"][0]["photo_url"]="https://example.com/product.jpg"
        with patch.object(editorial,"wp_call",new=AsyncMock(return_value={"chat":"-1001234567890"})),patch.object(editorial,"_meta_set",new=AsyncMock(return_value=True)),patch.object(editorial.asyncio,"sleep",new=AsyncMock()):
            self.assertEqual((await editorial.publish_batch(bot,b))["sent"],1)
            bot.send_message.assert_not_awaited()
            self.assertEqual(bot.send_photo.call_args.kwargs["photo"],"https://example.com/product.jpg")
            self.assertEqual(bot.send_photo.call_args.kwargs["caption"],b["posts"][0]["html"])

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
