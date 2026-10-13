"""Барахолка в приложении: общая с ботом доска объявлений, подача с фото, модерация, жильё с оплатой."""
import base64
import io
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from PIL import Image
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from database.models import AppUser, Base, Listing, Meta
from handlers import board
from utils import app_api, community, market
from utils.site_api import make_token


def jpeg_b64(w=2400, h=1200) -> str:
    buf = io.BytesIO()
    img = Image.new("RGB", (w, h), (200, 90, 30))
    exif = Image.Exif()
    exif[0x8825] = {1: "N"}  # GPS
    img.save(buf, "JPEG", exif=exif)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


class FakeBot:
    def __init__(self):
        self.photos, self.messages, self.deleted = [], [], []
        self.uploads = 0

    async def send_photo(self, chat_id, photo, caption=None, reply_markup=None, **kw):
        self.photos.append((chat_id, photo, caption, reply_markup))
        fid = "FILE1"
        if not isinstance(photo, str):  # загрузка нового фото — каждому свой file_id
            self.uploads += 1
            fid = "FILE1" if self.uploads == 1 else f"FILE{self.uploads}"
        return SimpleNamespace(photo=[SimpleNamespace(file_id="small"), SimpleNamespace(file_id=fid)],
                               chat=SimpleNamespace(id=-100), message_id=len(self.photos))

    async def send_message(self, chat_id, text, reply_markup=None, **kw):
        self.messages.append((chat_id, text, reply_markup))

    async def delete_message(self, chat_id, message_id):
        self.deleted.append((chat_id, message_id))

    async def get_file(self, file_id):
        return SimpleNamespace(file_path=f"photos/{file_id}.jpg")

    async def download_file(self, path, dest):
        dest.write(b"JPEGDATA")


GOODS = {"category": "goods", "intent": "offer", "title": "Детская коляска Bugaboo",
         "description": "Коляска в хорошем состоянии, забирать в Utrecht, есть дождевик.",
         "price": "€120", "city": "Utrecht", "contacts": {"telegram": "@anna_nl", "phone": "0612345678"}}


class MarketTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{Path(self.tmp.name) / 't.db'}")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.pay = AsyncMock(return_value={"id": "tr_1", "checkout_url": "https://pay.example/tr_1"})
        self.patches = [patch.object(m, "get_session", self.sessions) for m in (app_api, community, market)] + [
            patch.object(market.config, "ADMIN_IDS", [999]),
            patch.object(market.config, "WEBHOOK_BASE_URL", "https://bot.example"),
            patch.object(market, "create_payment", self.pay),
            patch.object(board, "_housing_paid", lambda: True),
        ]
        for p in self.patches:
            p.start()
        community._hits.clear()
        market._photo_cache.clear()
        old = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=10)
        async with self.sessions() as s:
            s.add_all([AppUser(id=1, email="a@x.nl", name="Анна", tg_id=555, created_at=old, rules_at=old),
                       AppUser(id=2, email="b@x.nl", name="Борис", created_at=old, rules_at=old),
                       AppUser(id=3, email="c@x.nl", name="Вера", created_at=old)])
            await s.commit()
        self.bot = FakeBot()
        app = web.Application(client_max_size=20 * 1024 * 1024)
        app["bot"] = self.bot
        market.install_routes(app)
        self.c = TestClient(TestServer(app))
        await self.c.start_server()

    async def asyncTearDown(self):
        await self.c.close()
        for p in self.patches:
            p.stop()
        await self.engine.dispose()
        self.tmp.cleanup()

    def h(self, uid):
        return {"Authorization": "Bearer " + make_token({"k": "app", "u": uid}, 3600)} if uid else {}

    async def post(self, path, uid, body=None):
        return await self.c.post(path, json=body or {}, headers=self.h(uid))

    async def get(self, path, uid=None):
        return await self.c.get(path, headers=self.h(uid))

    async def approve(self, lid):
        async with self.sessions() as s:
            l = await s.get(Listing, lid)
            l.status, l.expires_at = "approved", datetime.utcnow() + timedelta(days=30)
            await s.commit()

    async def test_submit_with_photo_goes_to_moderation(self):
        self.assertEqual((await self.post("/api/app/market", None, GOODS)).status, 401)
        self.assertEqual((await self.post("/api/app/market", 3, GOODS)).status, 428)   # правила не приняты
        r = await self.post("/api/app/market", 1, GOODS | {"photo": jpeg_b64()})
        d = await r.json()
        self.assertEqual(r.status, 200, d)
        self.assertEqual(d["status"], "pending")
        async with self.sessions() as s:
            l = await s.get(Listing, d["id"])
        self.assertEqual((l.photo_file_id, l.app_user_id, l.submitter_user_id), ("FILE1", 1, 555))
        self.assertIn("Telegram: @anna_nl", l.contact)
        self.assertIn("+31612345678", l.contact)
        # служебное сообщение с загрузкой убрано, модератору ушла карточка с кнопками бота
        self.assertEqual(len(self.bot.deleted), 1)
        upload, card = self.bot.photos
        self.assertEqual(card[1], "FILE1")
        self.assertIn("из приложения", card[2])
        self.assertEqual(card[3].inline_keyboard[0][0].callback_data, f"lstok:{d['id']}")
        # фото уменьшено и без геопозиции
        img = Image.open(io.BytesIO(upload[1].data))
        self.assertEqual(max(img.size), market.PHOTO_SIDE)
        self.assertNotIn(0x8825, img.getexif())
        # пока на проверке: не в общем списке, чужим не видно, автору видно
        self.assertEqual((await (await self.get("/api/app/market")).json())["items"], [])
        self.assertEqual((await self.get(f"/api/app/market/{d['id']}", 2)).status, 404)
        mine = await (await self.get(f"/api/app/market/{d['id']}", 1)).json()
        self.assertEqual(mine["item"]["status_title"], "На проверке")
        self.assertEqual(mine["item"]["form"]["contacts"]["telegram"], "@anna_nl")
        my = await (await self.get("/api/app/market/my", 1)).json()
        self.assertEqual([x["id"] for x in my["items"]], [d["id"]])
        # фото до публикации: по прямой ссылке не отдаётся, автору — по подписанной
        self.assertEqual((await self.get(f"/api/app/market/{d['id']}/photo")).status, 404)
        self.assertIn("?k=", mine["item"]["photo"])
        self.assertEqual((await self.get(mine["item"]["photo"])).status, 200)
        other = await self.get(mine["item"]["photo"].replace(f"/{d['id']}/", "/999/"))
        self.assertEqual(other.status, 404)

    async def test_browse_filters_and_photo(self):
        ids = []
        for body in (GOODS, GOODS | {"category": "free", "intent": "", "title": "Отдам книги на русском",
                                     "city": "", "nationwide": True}):
            ids.append((await (await self.post("/api/app/market", 1, body)).json())["id"])
        async with self.sessions() as s:  # объявление из бота с фото из Telegram
            s.add(Listing(category="goods", intent="seek", title="Ищу велосипед", city="Amsterdam",
                          description="Нужен городской велосипед", contact="Telegram: @boris_nl",
                          photo_file_id="TGFILE", submitter_user_id=777, status="pending"))
            await s.commit()
        for lid in ids + [3]:
            await self.approve(lid)
        all_ = await (await self.get("/api/app/market")).json()
        self.assertEqual(len(all_["items"]), 3)
        self.assertIn("goods", [c["key"] for c in all_["categories"]])
        utrecht = await (await self.get("/api/app/market?city=Utrecht")).json()
        self.assertEqual(sorted(x["id"] for x in utrecht["items"]), sorted(ids))   # + вся страна
        goods = await (await self.get("/api/app/market?cat=goods&q=велосипед")).json()
        self.assertEqual([x["id"] for x in goods["items"]], [3])
        card = (await (await self.get("/api/app/market/3")).json())["item"]
        self.assertEqual(card["contacts"], [{"type": "telegram", "title": "Telegram", "url": "https://t.me/boris_nl"}])
        self.assertFalse(card["mine"])
        r = await self.get(card["photo"])
        self.assertEqual((r.status, await r.read()), (200, b"JPEGDATA"))
        # снятое не видно
        self.assertEqual((await self.post(f"/api/app/market/{ids[0]}/close", 2)).status, 404)
        self.assertEqual((await self.post(f"/api/app/market/{ids[0]}/close", 1)).status, 200)
        self.assertEqual((await self.get(f"/api/app/market/{ids[0]}", 2)).status, 404)

    async def test_several_photos_keep_and_reorder(self):
        d = await (await self.post("/api/app/market", 1, GOODS | {"photos": [jpeg_b64(800, 600), jpeg_b64(600, 800)]})).json()
        await self.approve(d["id"])
        item = (await (await self.get(f"/api/app/market/{d['id']}", 2)).json())["item"]
        self.assertEqual(item["photos"], [f"/api/app/market/{d['id']}/photo", f"/api/app/market/{d['id']}/photo?i=1"])
        self.assertEqual((await self.get(item["photos"][1])).status, 200)
        self.assertEqual((await self.get(f"/api/app/market/{d['id']}/photo?i=5")).status, 404)
        # правка: второе фото становится обложкой, первое убираем, добавляем новое
        await self.post("/api/app/market", 1, GOODS | {"id": d["id"], "photos": ["keep:1", jpeg_b64(500, 500)]})
        async with self.sessions() as s:
            l = await s.get(Listing, d["id"])
        self.assertEqual((l.photo_file_id, market.all_photos(l)), ("FILE2", ["FILE2", "FILE3"]))
        mine = (await (await self.get(f"/api/app/market/{d['id']}", 1)).json())["item"]
        self.assertEqual(len(mine["photos"]), 2)
        self.assertTrue(all("k=" in u for u in mine["photos"]))   # снова на проверке — ссылки только автору
        self.assertEqual((await self.get(mine["photos"][1])).status, 200)
        # «photo»: "" от старого клиента убирает все фото
        await self.post("/api/app/market", 1, GOODS | {"id": d["id"], "photo": ""})
        async with self.sessions() as s:
            self.assertEqual(market.all_photos(await s.get(Listing, d["id"])), [])

    async def test_validation(self):
        cases = [
            (GOODS | {"contacts": {}}, "контакт"),
            (GOODS | {"contacts": {"phone": "12"}}, "Телефон"),
            (GOODS | {"intent": ""}, "предлагаете"),
            (GOODS | {"title": "Да"}, "Заголовок"),
            (GOODS | {"description": "Коляска, пиздец какая хорошая, забирайте скорее"}, "мата"),
            (GOODS | {"city": ""}, "город"),
            (GOODS | {"photo": "bm90IGFuIGltYWdl"}, "фото"),
        ]
        for body, word in cases:
            r = await self.post("/api/app/market", 2, body)
            self.assertEqual(r.status, 400, body)
            self.assertIn(word, (await r.json())["error"])

    async def test_housing_needs_payment_first(self):
        body = {"category": "housing", "intent": "offer", "title": "Комната в Rotterdam",
                "description": "Сдаю комнату с 1 ноября, 18 м², рядом метро, можно с регистрацией.",
                "price": "€750", "city": "Rotterdam", "contacts": {"email": "anna@x.nl"}}
        d = await (await self.post("/api/app/market", 1, body)).json()
        self.assertEqual((d["status"], d["pay_url"]), ("awaiting_payment", "https://pay.example/tr_1"))
        self.assertEqual(self.bot.messages, [])   # модераторам — только после оплаты
        meta = self.pay.call_args
        self.assertEqual(meta.args[1], {"listing_id": d["id"], "kind": "listing"})
        self.assertEqual(meta.kwargs["redirect_url"], "https://bot.example/app/market/my")
        again = await (await self.post(f"/api/app/market/{d['id']}/pay", 1)).json()
        self.assertTrue(again["ok"])
        # правка до оплаты не отправляет объявление на проверку бесплатно
        edited = await (await self.post("/api/app/market", 1, body | {"id": d["id"], "price": "€700"})).json()
        self.assertEqual(edited["status"], "awaiting_payment")
        self.assertEqual(self.bot.messages, [])
        # снять неоплаченное и снова подать — всё равно нужна оплата
        await self.post(f"/api/app/market/{d['id']}/close", 1)
        again2 = await (await self.post("/api/app/market", 1, body | {"id": d["id"]})).json()
        self.assertEqual(again2["status"], "awaiting_payment")
        self.assertEqual(self.bot.messages, [])
        # после успешной оплаты (отметка вебхука) правка не требует новой оплаты
        async with self.sessions() as s:
            l = await s.get(Listing, d["id"])
            l.status = "approved"
            s.add(Meta(key=f"pay:{l.payment_id}", value="done"))
            await s.commit()
        paid = await (await self.post("/api/app/market", 1, body | {"id": d["id"], "price": "€690"})).json()
        self.assertEqual(paid["status"], "pending")

    async def test_limit_and_report(self):
        with patch.object(market.config, "BOARD_MAX_ACTIVE", 1):
            first = await (await self.post("/api/app/market", 1, GOODS)).json()
            self.assertEqual((await self.post("/api/app/market", 1, GOODS)).status, 429)
            # исправить своё можно и при лимите
            r = await self.post("/api/app/market", 1, GOODS | {"id": first["id"], "price": "€100"})
            self.assertEqual(r.status, 200)
        self.assertEqual((await self.post("/api/app/market", 2, GOODS | {"id": first["id"]})).status, 404)
        self.assertEqual((await self.post(f"/api/app/market/{first['id']}/report", 2, {"reason": "scam"})).status, 404)
        await self.approve(first["id"])
        before = len(self.bot.messages)
        self.assertEqual((await self.post(f"/api/app/market/{first['id']}/report", 2, {"reason": "scam"})).status, 200)
        await self.post(f"/api/app/market/{first['id']}/report", 2, {"reason": "scam"})   # повтор не дублируется
        self.assertEqual(len(self.bot.messages), before + 1)
        self.assertIn("мошенничество", self.bot.messages[-1][1])


if __name__ == "__main__":
    unittest.main()
