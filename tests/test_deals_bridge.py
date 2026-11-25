import unittest
from unittest.mock import AsyncMock, patch
from utils import deals_bridge as bridge

class DealsBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def test_customer_is_tagged(self):
        with patch.object(bridge, "_mollie", new_callable=AsyncMock) as api:
            api.return_value={"id":"cst_test"}
            result=await bridge.mollie_rpc("POST","/v2/customers",{"name":"Telegram @testuser"},"")
            self.assertEqual(result, {"id":"cst_test"})
            api.assert_awaited_once_with("POST","/customers",{"name":"Telegram @testuser","metadata":{"source":"deals_wp"}})
    async def test_foreign_customer_cannot_cancel(self):
        with patch.object(bridge, "_mollie", new_callable=AsyncMock) as api:
            api.return_value={"id":"cst_test"}
            self.assertIsNone(await bridge.mollie_rpc("DELETE","/v2/customers/cst_test/subscriptions/sub_test",{},""))
            api.assert_awaited_once_with("GET","/customers/cst_test")
    async def test_foreign_payment_hidden(self):
        with patch.object(bridge, "_mollie", new_callable=AsyncMock) as api:
            api.return_value={"id":"tr_test","metadata":{"source":"donation"}}
            self.assertIsNone(await bridge.mollie_rpc("GET","/v2/payments/tr_test",{},""))
    async def test_external_paths_denied(self):
        with patch.object(bridge, "_mollie", new_callable=AsyncMock) as api:
            for path in ("/v2/organizations","https://example.com","/v2/customers/cst_a/payments","/v2/payments/tr_a?x=1"):
                self.assertIsNone(await bridge.mollie_rpc("GET",path,{},""))
            api.assert_not_awaited()
    async def test_annual_is_not_recurring(self):
        body={"amount":{"currency":"EUR","value":"39.99"},"metadata":{"kind":"deals_first","source":"deals_wp","plan":"year"},"sequenceType":"first"}
        with patch.object(bridge,"_mollie",new_callable=AsyncMock) as api:
            self.assertIsNone(await bridge.mollie_rpc("POST","/v2/payments",body,""))
            api.assert_not_awaited()
    def test_amounts(self):
        self.assertTrue(bridge.amount_ok({"amount":{"currency":"EUR","value":"3.99"}}))
        self.assertFalse(bridge.amount_ok({"amount":{"currency":"EUR","value":"1.00"}}))

    def test_message_payload_telegram_wire_alias(self):
        from aiogram.types import Message
        msg=Message.model_validate({"message_id":1,"date":1760000000,"chat":{"id":123,"type":"private"},"from":{"id":123,"is_bot":False,"first_name":"Test","username":"testuser"},"text":"/start bind_"+"a"*48})
        p=bridge.message_payload(msg)
        self.assertEqual(p["from"]["id"],123)
        self.assertEqual(p["from"]["username"],"testuser")
        self.assertNotIn("from_user",p)
        self.assertEqual(p["chat"]["type"],"private")
