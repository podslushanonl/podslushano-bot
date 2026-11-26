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

    async def test_only_cancel_unpaid_deals_checkout(self):
        original={"id":"tr_test","metadata":{"source":"deals_wp","kind":"deals_first"},"status":"open","isCancelable":True}
        cancelled={**original,"status":"canceled"}
        with patch.object(bridge,"_mollie",new_callable=AsyncMock) as api:
            api.side_effect=[original,cancelled]
            self.assertEqual(await bridge.mollie_rpc("DELETE","/v2/payments/tr_test",{},""),cancelled)
            self.assertEqual(api.await_count,2)
        for payment in ({**original,"status":"paid"},{**original,"isCancelable":False},{**original,"metadata":{"source":"donation"}},{**original,"metadata":{"source":"deals_wp","kind":"deals_renewal"}}):
            with patch.object(bridge,"_mollie",new_callable=AsyncMock) as api:
                api.return_value=payment
                self.assertIsNone(await bridge.mollie_rpc("DELETE","/v2/payments/tr_test",{},""))
                self.assertEqual(api.await_count,1)


class DealsContactTests(unittest.IsolatedAsyncioTestCase):
    async def test_feedback_deep_link_opens_review_form(self):
        from types import SimpleNamespace
        from handlers import support
        from states.forms import SupportContact
        message = SimpleNamespace(text="/start deals_feedback", answer=AsyncMock())
        state = AsyncMock()
        await bridge.deals_start(message, state)
        state.clear.assert_awaited_once()
        state.set_state.assert_awaited_once_with(SupportContact.waiting_message)
        state.update_data.assert_awaited_once_with(kind="deals_review")
        self.assertIn("Отзыв", message.answer.call_args.args[0])

    async def test_access_deep_link_keeps_existing_access_flow(self):
        from types import SimpleNamespace
        message = SimpleNamespace(text="/start deals_access")
        with patch.object(bridge, "access", new_callable=AsyncMock) as access:
            await bridge.deals_start(message, AsyncMock())
            access.assert_awaited_once_with(message)

    async def test_review_delivered_privately_and_acknowledged_only_on_success(self):
        from types import SimpleNamespace
        from handlers import support
        user = SimpleNamespace(full_name="Reader", username="reader", id=123)
        message = SimpleNamespace(from_user=user, bot=SimpleNamespace(send_message=AsyncMock()),
            copy_to=AsyncMock(), answer=AsyncMock())
        state = AsyncMock()
        state.get_data.return_value = {"kind":"deals_review"}
        with patch.object(support.config, "ADMIN_IDS", [456]):
            await support.contact_relay(message, state)
        self.assertIn("Отзыв", message.bot.send_message.call_args.args[1])
        message.copy_to.assert_awaited_once_with(456)
        self.assertIn("отзыв передан", message.answer.call_args.args[0])
        message.copy_to.side_effect = RuntimeError("delivery failed")
        with patch.object(support.config, "ADMIN_IDS", [456]):
            await support.contact_relay(message, state)
        self.assertIn("Не получилось", message.answer.call_args.args[0])
