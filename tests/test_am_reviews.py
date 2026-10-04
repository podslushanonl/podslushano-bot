"""Isolated tests: temporary SQLite, no real Telegram calls."""
import asyncio
import importlib
import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

import am_reviews as reviews


class ReviewFlow(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.url = 'sqlite+aiosqlite:///' + self.temp.name + '/reviews.db'
        self.engine = create_async_engine(self.url)
        async with self.engine.begin() as conn:
            await conn.run_sync(reviews.AMReview.__table__.create)
        self.session = async_sessionmaker(self.engine, expire_on_commit=False)
        self.patch_session = patch.object(reviews, 'get_session', self.session)
        self.patch_session.start()
        self.patch_admin = patch.object(reviews.config, 'ADMIN_IDS', [123])
        self.patch_admin.start()
        self.patch_env = patch.dict(os.environ, {'AM_REVIEWS_SECRET': 'test-secret', 'AM_REVIEWS_CHAT_ID': '123'})
        self.patch_env.start()
        self.bot = SimpleNamespace(send_message=AsyncMock())
        app = web.Application()
        app['bot'] = self.bot
        reviews.install_routes(app)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()
        self.data = dict(name='Test author', text='A real-looking test review <script>', rating=4,
                         project='Website', contact='PRIVATE', consent=True, submissionId='a'*64)

    async def asyncTearDown(self):
        await self.client.close()
        self.patch_session.stop(); self.patch_admin.stop(); self.patch_env.stop()
        await self.engine.dispose()
        self.temp.cleanup()

    async def post(self, data=None):
        return await self.client.post('/api/am-reviews', json=self.data if data is None else data,
                                      headers={'Authorization': 'Bearer test-secret'})

    async def feed(self):
        return await (await self.client.get('/api/am-reviews')).json()

    def query(self, action, user=123):
        return SimpleNamespace(from_user=SimpleNamespace(id=user), data=f'amr:{action}:1',
            answer=AsyncMock(), message=SimpleNamespace(edit_text=AsyncMock(), edit_reply_markup=AsyncMock()))

    async def test_full_lifecycle_and_authorization(self):
        bad = await self.client.post('/api/am-reviews', json=self.data)
        self.assertEqual(bad.status, 401)
        for change in ({'rating': True}, {'rating': 6}, {'consent': False}, {'text': 'short'}):
            self.assertEqual((await self.post({**self.data, **change})).status, 400)
        results = await asyncio.gather(self.post(), self.post())
        self.assertEqual([r.status for r in results], [200, 200])
        self.assertEqual(self.bot.send_message.await_count, 1)
        self.assertIn('&lt;script&gt;', self.bot.send_message.call_args.args[1])
        self.assertEqual((await self.feed())['reviews'], [])
        await reviews.moderate(self.query('publish', user=999))
        self.assertEqual((await self.feed())['reviews'], [])
        await reviews.moderate(self.query('publish'))
        feed = await self.feed()
        self.assertEqual(feed['reviews'][0]['rating'], 4)
        self.assertNotIn('PRIVATE', json.dumps(feed))
        # Data survives engine restart.
        await self.engine.dispose()
        self.assertEqual(len((await self.feed())['reviews']), 1)
        await reviews.moderate(self.query('askdelete'))
        self.assertEqual(len((await self.feed())['reviews']), 1)
        await reviews.moderate(self.query('cancel'))
        self.assertEqual(len((await self.feed())['reviews']), 1)
        await reviews.moderate(self.query('delete'))
        self.assertEqual((await self.feed())['reviews'], [])
        await reviews.moderate(self.query('publish'))
        self.assertEqual((await self.feed())['reviews'], [])
        await self.post()
        self.assertEqual(self.bot.send_message.await_count, 1)
        async with self.session() as session:
            row = await session.get(reviews.AMReview, 1)
            self.assertEqual(row.contact, '')
            self.assertEqual(row.text, '')

    async def test_delivery_failure_keeps_pending_for_retry(self):
        self.bot.send_message.side_effect = RuntimeError('offline')
        self.assertEqual((await self.post()).status, 502)
        self.assertEqual((await self.feed())['reviews'], [])
        self.bot.send_message.side_effect = None
        self.assertEqual((await self.post()).status, 200)
        async with self.session() as session:
            row = await session.get(reviews.AMReview, 1)
            self.assertTrue(row.notified)

    async def test_legacy_parser(self):
        old = ('Новый отзыв — AM Projects\nСтатус: ожидает проверки. На сайте ещё не опубликован.\n\n'
               'Имя: Maria\nОценка: 5 / 5\nПроект: Website\nКонтакт (не публиковать): Не указан\n\n'
               'Текст:\nThank you very much!\n\nАвтор согласился на публикацию имени, оценки и текста.')
        data = reviews.parse_legacy(old)
        self.assertEqual(data['rating'], 5)
        self.assertEqual(data['contact'], '')
        self.assertIsNone(reviews.parse_legacy('untrusted arbitrary text'))


if __name__ == '__main__':
    unittest.main()
