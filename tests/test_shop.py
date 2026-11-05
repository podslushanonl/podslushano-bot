"""Магазин мерча: каталог, проверка заказа, оплата через Mollie и статус заказа."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from database.models import Base, ShopOrder
from utils import shop

CATALOG = {"currency": "EUR", "shipping": {"NL": "4.95", "DE": "7.95", "BE": "7.95"},
           "products": [{"id": "shopper", "title": "Шоппер", "price": "24.95", "colors": ["Чёрный"], "available": True}]}
ORDER = {"items": [{"id": "shopper", "color": "Чёрный", "qty": 2}], "country": "NL", "name": "Anna Ivanova",
         "email": "anna@example.com", "street": "Damrak", "house": "1", "postcode": "1012lg", "city": "Amsterdam"}


class ShopTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        cat = Path(self.tmp.name) / "catalog.json"
        cat.write_text(json.dumps(CATALOG, ensure_ascii=False))
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{Path(self.tmp.name) / 't.db'}")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.pay = AsyncMock(return_value={"id": "tr_1", "checkout_url": "https://mollie.test/pay"})
        self.patches = [patch.object(shop, "get_session", self.sessions), patch.object(shop, "CATALOG", cat),
                        patch.object(shop.payments, "create_payment", self.pay), patch.dict(os.environ, {"SHOP_OPEN": "1"})]
        for p in self.patches:
            p.start()
        app = web.Application()
        shop.install_routes(app)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        for p in self.patches:
            p.stop()
        await self.engine.dispose()
        self.tmp.cleanup()

    async def test_closed_without_flag(self):
        with patch.dict(os.environ, {"SHOP_OPEN": "0"}):
            d = await (await self.client.get("/api/shop/catalog")).json()
            self.assertFalse(d["open"])
            r = await self.client.post("/api/shop/order", json=ORDER)
            self.assertEqual(r.status, 403)

    def test_validation(self):
        cat = shop.load_catalog()
        ok, err = shop.validate(ORDER, cat)
        self.assertIsNone(err)
        self.assertEqual(ok["total"], "54.85")          # 2 × 24.95 + 4.95
        self.assertEqual(ok["postcode"], "1012 LG")
        _, err = shop.validate({**ORDER, "country": "FR"}, cat)
        self.assertIn("Нидерланды", err)
        _, err = shop.validate({**ORDER, "postcode": "12345"}, cat)
        self.assertIn("4 цифры и 2 буквы", err)
        _, err = shop.validate({**ORDER, "phone": "+7 900 123 45 67"}, cat)
        self.assertIn("Нидерландов, Германии или Бельгии", err)
        _, err = shop.validate({**ORDER, "items": [{"id": "shopper", "color": "Красный", "qty": 1}]}, cat)
        self.assertIn("цвет", err)
        _, err = shop.validate({**ORDER, "items": [{"id": "nope", "qty": 1}]}, cat)
        self.assertIn("нет в продаже", err)

    async def test_order_paid_flow(self):
        r = await self.client.post("/api/shop/order", json=ORDER)
        self.assertEqual(r.status, 200)
        d = await r.json()
        self.assertEqual(d["checkout_url"], "https://mollie.test/pay")
        self.assertEqual(self.pay.await_args.args[2], "54.85")   # сумму считает сервер, а не приложение
        with patch.object(shop, "_after_paid", AsyncMock()) as after:
            await shop.on_payment(None, "tr_1", {"status": "paid", "metadata": {"kind": "shop", "token": d["token"]}})
            await shop.on_payment(None, "tr_1", {"status": "paid", "metadata": {"kind": "shop", "token": d["token"]}})
            self.assertEqual(after.call_count, 1)                # повторный webhook не шлёт письмо второй раз
        page = await (await self.client.get(f"/shop/return?token={d['token']}")).text()
        self.assertIn(f"podslushano://shop/order/{d['token']}", page)
        self.assertIn(f"/app/shop/order/{d['token']}", page)   # вернуться можно и без установленного приложения
        o = await (await self.client.get(f"/api/shop/order/{d['token']}")).json()
        self.assertEqual(o["order"]["status"], "paid")
        self.assertEqual(o["order"]["items"][0]["qty"], 2)
        async with self.sessions() as s:
            row = await s.get(ShopOrder, 1)
            subject, html_body, _ = shop._email(row)
            self.assertIn(row.code, subject)
            self.assertIn("14 дней", html_body)


    async def test_admin_status_flow(self):
        r = await (await self.client.post("/api/shop/order", json=ORDER)).json()
        code = r["code"]
        o, err = await shop.set_status(code, "printing")
        self.assertIn("Нельзя", err)                       # неоплаченный заказ нельзя передать в печать
        with patch.object(shop, "_after_paid", AsyncMock()):
            await shop.on_payment(None, "tr_1", {"status": "paid", "metadata": {"token": r["token"]}})
        o, err = await shop.set_status(code.lower(), "printing")
        self.assertEqual((o.status, err), ("printing", ""))
        o, err = await shop.set_status(code, "shipped", "postnl.nl/track")
        self.assertIn("https://", err)
        o, err = await shop.set_status(code, "shipped", "https://jouw.postnl.nl/track/3S123")
        self.assertEqual(o.status, "shipped")
        subject, body, _ = shop._shipped_email(o)
        self.assertIn(code, subject)
        self.assertIn("https://jouw.postnl.nl/track/3S123", body)

    def test_waitlist_email_without_batch(self):
        from utils.email_templates import waitlist_joined
        from utils.waitlist import CAMPAIGNS
        self.assertIn("shoppers", CAMPAIGNS)
        subject, html_body, text = waitlist_joined(title="шопперы ALLO", position=3, stock=None, unsubscribe_url="https://x/u")
        self.assertIn("шопперы ALLO", subject)
        self.assertNotIn("партии", text)        # шопперы печатаются под заказ: про партию не пишем
        self.assertIn("партии 24", waitlist_joined(title="свеча", position=1, stock=24, unsubscribe_url="https://x/u")[2])

if __name__ == "__main__":
    unittest.main()
