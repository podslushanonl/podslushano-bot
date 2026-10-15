"""Pulse (вертикальные видео) и истории: загрузка файлов на диск, лента, лайки, закладки, комментарии, реакции.

На SQLite всегда; с TEST_DATABASE_URL — ещё и на PostgreSQL.
"""
import io
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from aiohttp import FormData, web
from aiohttp.test_utils import TestClient, TestServer
from PIL import Image
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from database.models import AppUser, Base, Friendship, FriendStatus, Story
from utils import app_api, app_market, community, feed, media, pulse, realtime, social, stories
from utils.site_api import make_token

PG_URL = os.getenv("TEST_DATABASE_URL", "")
MODS = (app_api, app_market, community, feed, media, pulse, realtime, social, stories)
MP4 = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom" + b"\x00" * 2000


def jpeg(w=1200, h=1600) -> bytes:
    b = io.BytesIO()
    Image.new("RGB", (w, h), (30, 120, 200)).save(b, "JPEG")
    return b.getvalue()


class Base6:
    url = ""

    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_async_engine(self.url or f"sqlite+aiosqlite:///{Path(self.tmp.name) / 't.db'}")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.patches = [patch.object(m, "get_session", self.sessions) for m in MODS] + [
            patch.object(media, "MEDIA_DIR", Path(self.tmp.name) / "media")]
        for p in self.patches:
            p.start()
        community._hits.clear()
        old = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=10)
        async with self.sessions() as s:
            s.add_all([
                AppUser(id=1, email="a@x.nl", name="Анна", created_at=old, rules_at=old),
                AppUser(id=2, email="b@x.nl", name="Борис", created_at=old, rules_at=old),
                AppUser(id=3, email="v@x.nl", name="Вера", created_at=old, rules_at=old, is_private=True),
                AppUser(id=4, email="g@x.nl", name="Гена", country="Германия", created_at=old, rules_at=old),
            ])
            await s.flush()
            s.add(Friendship(user_id=1, friend_id=3, status=FriendStatus.ACCEPTED))
            await s.commit()
        app = web.Application()
        for m in MODS:
            m.install_routes(app)
        self.c = TestClient(TestServer(app))
        await self.c.start_server()

    async def asyncTearDown(self):
        await self.c.close()
        for p in self.patches:
            p.stop()
        if self.url:
            async with self.engine.begin() as conn:
                await conn.run_sync(Base.metadata.drop_all)
        await self.engine.dispose()
        self.tmp.cleanup()

    def h(self, uid):
        return {"Authorization": "Bearer " + make_token({"k": "app", "u": uid}, 3600)} if uid else {}

    async def post(self, path, uid, body=None):
        r = await self.c.post(path, json=body or {}, headers=self.h(uid))
        return r.status, await r.json()

    async def get(self, path, uid=None):
        r = await self.c.get(path, headers=self.h(uid))
        return r.status, await r.json()

    async def upload(self, path, uid, data: bytes, name="clip.mp4", **fields):
        form = FormData()
        for k, v in fields.items():
            form.add_field(k, v)
        form.add_field("file", data, filename=name)
        r = await self.c.post(path, data=form, headers=self.h(uid))
        return r.status, await r.json()

    # ------------------------------------------------------------ Pulse

    async def test_pulse_upload_feed_like_save_comment(self):
        st, d = await self.upload("/api/app/pulse", 1, MP4, text="Закат в Utrecht")
        self.assertEqual(st, 200, d)
        clip = d["clip"]
        r = await self.c.get(clip["url"])
        self.assertEqual((r.status, await r.read()), (200, MP4))
        self.assertEqual((await self.get("/api/app/pulse", 2))[1]["clips"][0]["text"], "Закат в Utrecht")
        st, d = await self.post(f"/api/app/pulse/{clip['id']}/like", 2, {"on": True})
        self.assertEqual((st, d["count"]), (200, 1))
        await self.post(f"/api/app/pulse/{clip['id']}/save", 2, {"on": True})
        await self.post(f"/api/app/pulse/{clip['id']}/comments", 2, {"text": "Красиво!"})
        c = (await self.get("/api/app/pulse", 2))[1]["clips"][0]
        self.assertEqual((c["likes"], c["liked"], c["saved"], c["comments"]), (1, True, True, 1))
        self.assertEqual([x["id"] for x in (await self.get("/api/app/pulse/saved", 2))[1]["clips"]], [clip["id"]])
        self.assertEqual((await self.get(f"/api/app/pulse/{clip['id']}/comments", 1))[1]["comments"][0]["text"], "Красиво!")
        # жалоба и удаление — общими /api/app/report и /api/app/delete
        self.assertEqual((await self.post("/api/app/report", 2, {"kind": "clip", "id": clip["id"]}))[0], 200)
        self.assertEqual((await self.post("/api/app/delete", 1, {"kind": "clip", "id": clip["id"]}))[0], 200)
        self.assertEqual((await self.get("/api/app/pulse", 2))[1]["clips"], [])
        self.assertEqual((await self.c.get(clip["url"])).status, 404)            # удалённое видео больше не отдаётся
        self.assertEqual(await media.cleanup(force=True), 1)                      # и файл убран с диска
        self.assertEqual(list((Path(self.tmp.name) / "media" / "pulse").glob("*")), [])

    async def test_pulse_rejects_bad_files(self):
        st, d = await self.upload("/api/app/pulse", 1, b"not a video at all", name="x.txt")
        self.assertEqual(st, 400)
        self.assertIn("формат", d["error"])
        self.assertEqual((await self.upload("/api/app/pulse", 1, jpeg(), name="p.jpg"))[0], 400)   # фото в Pulse нельзя
        self.assertEqual((await self.upload("/api/app/pulse", None, MP4))[0], 401)
        with patch.object(media, "VIDEO_MAX", 1000):
            st, d = await self.upload("/api/app/pulse", 1, MP4)
        self.assertEqual(st, 400)
        self.assertEqual(list((Path(self.tmp.name) / "media" / "pulse").glob("*")), [])   # обрезок не остался
        self.assertEqual((await self.c.get("/media/pulse/../../t.db")).status, 404)

    async def test_pulse_hides_private_author_from_strangers(self):
        await self.upload("/api/app/pulse", 3, MP4, text="Только для друзей")
        self.assertEqual((await self.get("/api/app/pulse", 2))[1]["clips"], [])
        self.assertEqual(len((await self.get("/api/app/pulse", 1))[1]["clips"]), 1)   # друг видит

    # ------------------------------------------------------------ истории

    async def test_stories_upload_feed_react(self):
        st, d = await self.upload("/api/app/stories", 2, jpeg(), name="s.jpg")
        self.assertEqual((st, d["story"]["kind"]), (200, "photo"))
        saved = Image.open(media.path("stories", d["story"]["url"].rsplit("/", 1)[1]))
        self.assertLessEqual(max(saved.size), media.PHOTO_SIDE)            # уменьшено, без метаданных
        await self.upload("/api/app/stories", 1, MP4)
        groups = (await self.get("/api/app/stories", 1))[1]["groups"]
        self.assertEqual([(g["user"]["name"], g["mine"]) for g in groups], [("Анна", True), ("Борис", False)])
        self.assertEqual((await self.get("/api/app/stories", 4))[1]["groups"], [])   # другая страна, не друзья
        sid = groups[1]["items"][0]["id"]
        sent = []
        with patch.object(stories.realtime, "push_user", side_effect=lambda uid, ev: sent.append((uid, ev)) or _done()):
            self.assertEqual((await self.post(f"/api/app/stories/{sid}/react", 1, {"emoji": "🔥"}))[0], 200)
        self.assertEqual((sent[0][0], sent[0][1]["emoji"]), (2, "🔥"))
        self.assertEqual((await self.post(f"/api/app/stories/{sid}/react", 1, {"emoji": "💩"}))[0], 400)
        await self.post(f"/api/app/stories/{sid}/react", 1, {"emoji": "❤️"})        # смена реакции
        self.assertEqual((await self.get("/api/app/stories", 1))[1]["groups"][1]["items"][0]["my_reaction"], "❤️")
        st, d = await self.get(f"/api/app/stories/{sid}/reactions", 2)
        self.assertEqual([(r["emoji"], r["user"]["name"]) for r in d["reactions"]], [("❤️", "Анна")])
        self.assertEqual((await self.get(f"/api/app/stories/{sid}/reactions", 1))[0], 404)   # чужие реакции не видно
        self.assertEqual((await self.post(f"/api/app/stories/{sid}/delete", 2))[0], 200)
        self.assertEqual(len((await self.get("/api/app/stories", 1))[1]["groups"]), 1)

    async def test_expired_story_file_not_served_and_cleaned(self):
        st, d = await self.upload("/api/app/stories", 2, jpeg(), name="s.jpg")
        url = d["story"]["url"]
        self.assertEqual((await self.c.get(url)).status, 200)
        async with self.sessions() as s:
            (await s.get(Story, d["story"]["id"])).expires_at = datetime.utcnow() - timedelta(minutes=1)
            await s.commit()
        self.assertEqual((await self.c.get(url)).status, 404)
        self.assertEqual(await media.cleanup(force=True), 1)
        self.assertFalse(media.path("stories", url.rsplit("/", 1)[1]).exists())

    async def test_stories_expire_and_privacy(self):
        async with self.sessions() as s:
            s.add(Story(user_id=2, file="a" * 32 + ".jpg", expires_at=datetime.utcnow() - timedelta(minutes=1)))
            await s.commit()
        await self.upload("/api/app/stories", 3, jpeg(), name="s.jpg")              # закрытый аккаунт Веры
        names = lambda gs: [g["user"]["name"] for g in gs]  # noqa: E731
        self.assertEqual(names((await self.get("/api/app/stories", 2))[1]["groups"]), [])        # чужим не видно, старая истекла
        self.assertEqual(names((await self.get("/api/app/stories", 1))[1]["groups"]), ["Вера"])  # другу видно


class Extra:
    """Репост поста в историю, подпись, обложка профиля, видео и товары человека."""

    async def test_share_post_to_story(self):
        import base64
        st, d = await self.post("/api/app/posts", 2, {"text": "Ищу компанию на выходные", "photos": [
            "data:image/jpeg;base64," + base64.b64encode(jpeg(1080, 1350)).decode()]})
        pid = d["post"]["id"]
        st, d = await self.post("/api/app/stories/share", 1, {"post_id": pid, "bg": "ocean", "caption": "Кто со мной?"})
        self.assertEqual(st, 200, d)
        it = d["story"]
        self.assertEqual((it["kind"], it["bg"], it["caption"], it["post"]["id"], it["post"]["ratio"]), ("post", "ocean", "Кто со мной?", pid, 0.8))
        self.assertTrue(it["post"]["photo"])
        groups = (await self.get("/api/app/stories", 2))[1]["groups"]
        self.assertEqual(groups[0]["items"][0]["post"]["author"]["name"], "Борис")   # у Бориса своих историй нет
        self.assertEqual((await self.post("/api/app/stories/share", 1, {"post_id": pid, "bg": "rainbow"}))[0], 400)
        self.assertEqual((await self.post("/api/app/stories/share", 1, {"post_id": 999}))[0], 404)
        # пост закрытого аккаунта не-друг поделиться не может, а удалённый пост на наклейке пропадает
        community._hits.clear()
        vid = (await self.post("/api/app/posts", 3, {"text": "Для друзей"}))[1]["post"]["id"]
        self.assertEqual((await self.post("/api/app/stories/share", 2, {"post_id": vid}))[0], 404)
        await self.post("/api/app/delete", 2, {"kind": "post", "id": pid})
        self.assertIsNone((await self.get("/api/app/stories", 1))[1]["groups"][0]["items"][0]["post"])
        # удаление истории-репоста (без файла) не падает
        self.assertEqual((await self.post(f"/api/app/stories/{it['id']}/delete", 1))[0], 200)

    async def test_story_caption_on_upload(self):
        st, d = await self.upload("/api/app/stories", 1, jpeg(), name="s.jpg", caption="  Закат  над каналом ")
        self.assertEqual(d["story"]["caption"], "Закат над каналом")

    async def test_cover_and_profile_tabs(self):
        import base64
        st, d = await self.post("/api/app/me/cover", 1, {"photo": base64.b64encode(jpeg(2000, 2000)).decode()})
        self.assertEqual(st, 200)
        url = d["user"]["cover"]
        r = await self.c.get(url)
        self.assertEqual(Image.open(io.BytesIO(await r.read())).size, (1500, 500))
        self.assertEqual((await self.get("/api/app/user/1", 2))[1]["user"]["cover"], url)
        self.assertEqual((await self.post("/api/app/me/cover", 1, {"photo": ""}))[1]["user"]["cover"], "")
        await self.upload("/api/app/pulse", 2, MP4, text="Моё видео")
        self.assertEqual([c["text"] for c in (await self.get("/api/app/user/2/pulse", 1))[1]["clips"]], ["Моё видео"])
        await self.upload("/api/app/pulse", 3, MP4)                                   # закрытый аккаунт
        self.assertEqual((await self.get("/api/app/user/3/pulse", 2))[1]["clips"], [])
        await self.post("/api/app/market", 2, {"category": "tech", "title": "iPad", "description": "Почти новый, с чехлом", "price": "300", "city": "Amsterdam"})
        self.assertEqual([x["title"] for x in (await self.get("/api/app/market?user=2"))[1]["items"]], ["iPad"])
        self.assertEqual((await self.get("/api/app/market?user=1"))[1]["items"], [])


async def _done():
    return None


class SqliteTests(Base6, Extra, unittest.IsolatedAsyncioTestCase):
    pass


@unittest.skipUnless(PG_URL, "TEST_DATABASE_URL не задан")
class PostgresTests(Base6, Extra, unittest.IsolatedAsyncioTestCase):
    url = PG_URL
