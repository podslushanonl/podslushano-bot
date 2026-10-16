"""Местоположение по GPS (Google Geocoding — подменяется в тестах), лента «Рядом» в радиусе 50 км,
приоритет подтверждённых в ленте «Все» и «Премиум верификация» (проверочный режим и подписка Mollie).

На SQLite всегда; с TEST_DATABASE_URL — ещё и на PostgreSQL.
"""
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from database.models import AppUser
from tests.test_feed import PG_URL, FeedHarness
from utils import app_api, app_geo, billing, feed

# Ответы Google Geocoding: деревня в Utrecht (Bunnik), Брюссель и Париж (вне трёх стран)
def _result(name, code, lat, lng, kind="locality", partial=False):
    return {"types": [kind, "political"], **({"partial_match": True} if partial else {}), "geometry": {"location": {"lat": lat, "lng": lng}},
            "address_components": [{"long_name": name, "short_name": name, "types": [kind, "political"]},
                                   {"long_name": "X", "short_name": code, "types": ["country", "political"]}]}


async def fake_geocode(params):
    if "latlng" in params:
        lat = float(params["latlng"].split(",")[0])
        if lat > 52.0:
            return [_result("Bunnik", "NL", 52.067, 5.198)]
        if lat > 50.7:
            name = "Brussel" if params.get("language") == "nl" else "Bruxelles"
            return [_result(name, "BE", 50.85, 4.35)]
        return [_result("Paris", "FR", 48.85, 2.35)]
    cc = params.get("components", "")[-2:]
    if params.get("address", "").lower().startswith("bunn") and cc == "NL":
        return [_result("Bunnik", "NL", 52.067, 5.198)]
    if params.get("address", "") == "Liège":
        if cc == "DE":
            return [_result("Thiendorf", "DE", 51.29, 13.74)]   # чужое место, которое Google отдаёт как точное совпадение
        if cc == "BE":
            fr = params.get("language") == "fr"
            return [_result("Liège" if fr else "Luik", "BE", 50.63, 5.57), _result("Gent" if not fr else "Gand", "BE", 51.05, 3.72, partial=True)]
    if params.get("address", "") == "Ghent" and cc == "BE":   # название на другом языке — точное совпадение
        return [_result("Gent" if params.get("language") == "nl" else "Gand", "BE", 51.05, 3.72)]
    if params.get("address", "") == "Eupen" and cc == "BE":
        return [_result("Eupen", "BE", 50.63, 6.03)]
    return []


class GeoBase(FeedHarness):
    mods = FeedHarness.mods + (app_geo, billing)

    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.geo = [patch.object(app_geo, "_geocode", fake_geocode),
                    patch.object(app_geo.config, "GOOGLE_MAPS_API_KEY", "test")]
        for p in self.geo:
            p.start()

    async def asyncTearDown(self):
        for p in self.geo:
            p.stop()
        await super().asyncTearDown()

    async def where(self, uid):
        async with self.sessions() as s:
            u = await s.get(AppUser, uid)
            return u.city, u.country.value, u.lat, u.lng

    # ------------------------------------------------------------ местоположение

    async def test_location_any_village(self):
        st, d = await self.post("/api/app/me/location", 1, {"lat": 52.0671234, "lng": 5.1981234})
        self.assertEqual((st, d["place"]), (200, {"name": "Bunnik", "country": "Нидерланды"}))
        self.assertEqual(d["user"]["city"], "Bunnik")
        self.assertEqual(await self.where(1), ("Bunnik", "Нидерланды", 52.067, 5.198))   # координаты округлены до ~100 м
        # Бельгия: название на языке местности, страна меняется
        st, d = await self.post("/api/app/me/location", 2, {"lat": 50.85, "lng": 4.35})
        self.assertEqual(d["place"], {"name": "Brussel", "country": "Бельгия"})
        # Вне трёх стран и без координат — понятный отказ, профиль не меняется
        self.assertEqual((await self.post("/api/app/me/location", 3, {"lat": 48.85, "lng": 2.35}))[0], 422)
        self.assertEqual((await self.post("/api/app/me/location", 3, {"lat": "x"}))[0], 400)
        self.assertEqual((await self.post("/api/app/me/location", 0, {"lat": 52, "lng": 5}))[0], 401)
        self.assertEqual((await self.where(3))[0], "Amsterdam")
        st, d = await self.get("/api/app/geo/search?q=Bunn&country=Нидерланды")
        self.assertEqual([p["name"] for p in d["places"]], ["Bunnik"])
        self.assertEqual((await self.get("/api/app/geo/search?q=Bunn&country=France"))[0], 400)
        # Бельгия: название на языке региона (Liège — по-французски, Gent — по-нидерландски), «похожее» Thiendorf отброшено
        st, d = await self.get("/api/app/geo/search?q=Liège")
        self.assertEqual([(p["name"], p["country"]) for p in d["places"]], [("Liège", "Бельгия")])
        self.assertEqual([p["name"] for p in (await self.get("/api/app/geo/search?q=Ghent"))[1]["places"]], ["Gent"])
        self.assertEqual([p["name"] for p in (await self.get("/api/app/geo/search?q=Eupen"))[1]["places"]], ["Eupen"])
        self.assertEqual(app_geo._language("BE", 50.63, 6.03), "de")    # Eupen — немецкоязычная община
        self.assertEqual(app_geo._language("BE", 50.43, 6.03), "fr")    # Malmedy рядом — франкоязычный
        self.assertTrue(app_geo._similar("Den Haag", "the hague"))
        self.assertTrue(app_geo._similar("Amsterdam", "Амстердам"))   # запрос кириллицей не фильтруем

    async def test_near_by_radius(self):
        # Анна в Bunnik (рядом с Utrecht), Гена — в Utrecht (8 км), Вера — в Amsterdam (≈40 км), Борис — в Berlin
        async with self.sessions() as s:
            for uid, lat, lng in ((1, 52.067, 5.198), (4, 52.09, 5.12), (3, 52.37, 4.9), (2, 52.52, 13.4)):
                u = await s.get(AppUser, uid)
                u.lat, u.lng = lat, lng
            await s.commit()
        a = await self.publish(1, "Анна")
        g = await self.publish(4, "Гена")
        v = await self.publish(3, "Вера")
        b = await self.publish(2, "Борис")
        ids = lambda d: [x["id"] for x in d["posts"]]  # noqa: E731
        self.assertEqual(ids((await self.get("/api/app/posts?scope=near", 1))[1]), [v["id"], g["id"], a["id"]])
        async with self.sessions() as s:   # Вера переехала в Groningen (≈150 км) — уже не рядом
            await s.execute(feed.UserPost.__table__.update().where(feed.UserPost.id == v["id"]).values(lat=53.22, lng=6.57))
            await s.commit()
        self.assertEqual(ids((await self.get("/api/app/posts?scope=near", 1))[1]), [g["id"], a["id"]])
        self.assertEqual(ids((await self.get("/api/app/posts?scope=near", 2))[1]), [b["id"]])
        # «Все» — посты всех трёх стран
        self.assertEqual(set(ids((await self.get("/api/app/posts?scope=all", 1))[1])), {a["id"], g["id"], v["id"], b["id"]})

    async def test_verified_posts_first_in_all(self):
        a = await self.publish(1, "Анна, с галочкой")
        g = await self.publish(4, "Гена")
        async with self.sessions() as s:
            (await s.get(AppUser, 1)).is_verified = True
            await s.commit()
        d = (await self.get("/api/app/posts?scope=all", 2))[1]
        self.assertEqual([x["id"] for x in d["posts"]], [a["id"], g["id"]])
        d = (await self.get(f"/api/app/posts?scope=all&before={g['id'] + 1}", 2))[1]   # следующие страницы — по дате
        self.assertEqual([x["id"] for x in d["posts"]], [g["id"], a["id"]])

    # ------------------------------------------------------------ премиум верификация

    async def test_billing_off_without_mollie(self):
        with patch.dict(os.environ, {"BILLING_MOCK": ""}), patch.object(billing, "mollie_ready", lambda: False):
            st, d = await self.get("/api/app/billing/verify", 1)
            self.assertEqual((st, d["verified"], d["price"], d["available"]), (200, False, 3.99, False))
            self.assertEqual((await self.post("/api/app/billing/verify", 1))[0], 503)   # бесплатно галочку не получить
        self.assertFalse((await self.get("/api/app/me", 1))[1]["user"]["verified"])

    async def test_billing_mock_grants_and_expires(self):
        with patch.dict(os.environ, {"BILLING_MOCK": "1"}), patch.object(billing, "mollie_ready", lambda: False):
            st, d = await self.post("/api/app/billing/verify", 1)
            self.assertEqual((st, d["paid"], d["user"]["verified"]), (200, True, True))
            self.assertTrue(d["until"])
            p = await self.publish(1, "Теперь с галочкой")
            self.assertTrue(p["author"]["verified"])
            async with self.sessions() as s:   # срок истёк — галочка снимается при следующей проверке
                (await s.get(AppUser, 1)).verified_until = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)
                await s.commit()
            # Экран оплаты не открывают — галочку снимает любой запрос вошедшего (лента, профиль), не реже раза в 5 минут
            app_api._expired_at = None
            self.assertFalse((await self.get("/api/app/me", 1))[1]["user"]["verified"])
            self.assertFalse((await self.get("/api/app/billing/verify", 1))[1]["verified"])

    async def test_admin_badge_is_lifetime(self):
        async with self.sessions() as s:
            (await s.get(AppUser, 1)).is_verified = True
            await s.commit()
        with patch.dict(os.environ, {"BILLING_MOCK": "1"}), patch.object(billing, "mollie_ready", lambda: False):
            d = (await self.get("/api/app/billing/verify", 1))[1]
            self.assertEqual((d["verified"], d["lifetime"]), (True, True))
            self.assertEqual((await self.post("/api/app/billing/verify", 1))[0], 409)

    async def test_mollie_subscription(self):
        calls = []

        async def fake_mollie(method, path, body=None):
            calls.append((method, path, body))
            if path == "/customers":
                return {"id": "cst_1"}
            if path == "/payments":
                return {"id": "tr_1", "_links": {"checkout": {"href": "https://www.mollie.com/checkout/tr_1"}}}
            if path.endswith("/subscriptions"):
                return {"id": "sub_1"}
            return {}
        with patch.object(billing, "mollie_ready", lambda: True), patch.object(billing, "_mollie", fake_mollie), \
                patch.object(billing.config, "WEBHOOK_BASE_URL", "https://api.example"):
            st, d = await self.post("/api/app/billing/verify", 2)
            self.assertEqual((st, d["url"]), (200, "https://www.mollie.com/checkout/tr_1"))
            first = calls[1][2]
            self.assertEqual((first["sequenceType"], first["amount"], first["webhookUrl"], first["customerId"]),
                             ("first", {"currency": "EUR", "value": "3.99"}, "https://api.example/mollie-webhook", "cst_1"))
            self.assertFalse((await self.get("/api/app/me", 2))[1]["user"]["verified"])   # до оплаты — без галочки
            # Вебхук: первый платёж оплачен → галочка и подписка «каждый месяц»
            paid = {"status": "paid", "metadata": first["metadata"]}
            await billing.on_mollie_payment("tr_1", paid)
            await billing.on_mollie_payment("tr_1", paid)   # повтор уведомления — без второй подписки
            self.assertTrue((await self.get("/api/app/me", 2))[1]["user"]["verified"])
            subs = [c for c in calls if c[1].endswith("/subscriptions")]
            self.assertEqual((len(subs), subs[0][1], subs[0][2]["interval"]), (1, "/customers/cst_1/subscriptions", "1 month"))
            d = (await self.get("/api/app/billing/verify", 2))[1]
            self.assertTrue(d["subscribed"])
            self.assertEqual((await self.post("/api/app/billing/verify", 2))[0], 409)   # подписка уже есть
            async with self.sessions() as s:
                until1 = (await s.get(AppUser, 2)).verified_until
            # Списание по подписке → срок ещё на месяц; повтор того же платежа — не продлевает
            renew = {"status": "paid", "metadata": {"kind": "app_verify_sub", "user_id": 2}}
            await billing.on_mollie_payment("tr_2", renew)
            await billing.on_mollie_payment("tr_2", renew)
            await billing.on_mollie_payment("tr_3", {"status": "failed", "metadata": renew["metadata"]})
            async with self.sessions() as s:
                self.assertEqual((await s.get(AppUser, 2)).verified_until - until1, billing.PERIOD)
            # Отмена: подписка удаляется в Mollie, галочка остаётся до конца срока
            st, d = await self.post("/api/app/billing/verify/cancel", 2)
            self.assertEqual((st, d["subscribed"], d["verified"]), (200, False, True))
            self.assertEqual(calls[-1][:2], ("DELETE", "/customers/cst_1/subscriptions/sub_1"))
            self.assertEqual((await self.post("/api/app/billing/verify/cancel", 2))[0], 404)


class GeoSqliteTests(GeoBase, unittest.IsolatedAsyncioTestCase):
    pass


@unittest.skipUnless(PG_URL, "TEST_DATABASE_URL не задан")
class GeoPostgresTests(GeoBase, unittest.IsolatedAsyncioTestCase):
    url = PG_URL


if __name__ == "__main__":
    unittest.main()
