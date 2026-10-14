import asyncio
import sys
import types
from datetime import datetime, timedelta
from unittest.mock import AsyncMock,patch

from aiohttp.test_utils import TestClient,TestServer
from utils import publication_test as test


def test_live_queue_is_delayed_idempotent_and_uses_shared_delivery(tmp_path,monkeypatch):
    monkeypatch.setenv('NEWS_OUTBOX_DB',str(tmp_path/'test.sqlite'))
    monkeypatch.setenv('NEWS_BRIDGE_TOKEN','private-test')
    paused=AsyncMock(return_value=False)
    monkeypatch.setitem(sys.modules,'handlers.content',types.SimpleNamespace(_is_paused=paused))
    now=datetime.now(test.morning_bridge.TZ)
    bot=types.SimpleNamespace(send_message=AsyncMock(return_value=types.SimpleNamespace(
        message_id=57,date=now,entities=[types.SimpleNamespace(type='text_link')]*5)))
    async def scenario():
        app=test.web.Application();app['bot']=bot
        test.install_routes(app)
        async with TestClient(TestServer(app)) as client:
            url='/api/publication-test'
            headers={'Authorization':'Bearer private-test'}
            assert (await client.post(url,json={'run_id':'test-run-001'})).status==401
            assert (await client.post(url,json={'run_id':'x'},headers=headers)).status==400
            response=await client.post(url,json={'run_id':'test-run-001'},headers=headers)
            assert response.status==202
            response=await client.post(url,json={'run_id':'test-run-001'},headers=headers)
            assert (await response.json())['duplicate']
            await test.publish_due(bot,now)
            assert bot.send_message.await_count==0
            paused.return_value=True
            await test.publish_due(bot,now+timedelta(seconds=30))
            assert bot.send_message.await_count==0
            paused.return_value=False
            await test.publish_due(bot,now+timedelta(seconds=30))
            await test.publish_due(bot,now+timedelta(seconds=30))
            assert bot.send_message.await_count==3
            for call in bot.send_message.await_args_list:
                assert call.kwargs['disable_notification'] is True
                assert call.args[1].startswith('ТЕСТ АВТОПУБЛИКАЦИИ')
            rows=(await (await client.get(url+'/test-run-001',headers=headers)).json())['results']
            assert len(rows)==3 and all(r['state']=='sent' and r['message_id']==57 for r in rows)
            with test.db() as conn:
                assert conn.execute('SELECT COUNT(*) FROM news').fetchone()[0]==0
    with patch.object(test.morning_bridge,'channel_status',AsyncMock(return_value={'can_post':True})):
        asyncio.run(scenario())


def test_ambiguous_test_delivery_is_not_retried(tmp_path,monkeypatch):
    monkeypatch.setenv('NEWS_OUTBOX_DB',str(tmp_path/'unknown.sqlite'))
    monkeypatch.setitem(sys.modules,'handlers.content',types.SimpleNamespace(_is_paused=AsyncMock(return_value=False)))
    now=datetime.now(test.morning_bridge.TZ)
    import json
    with test.db() as conn:
        conn.execute('INSERT INTO publication_tests(run_id,kind,payload,due_at,state) VALUES(?,?,?,?,?)',
                     ('ambiguous-001','morning',json.dumps(test.fixtures(now)['morning']),now.timestamp(),'queued'))
    bot=types.SimpleNamespace(send_message=AsyncMock(side_effect=TimeoutError()))
    async def scenario():
        await test.publish_due(bot,now)
        await test.publish_due(bot,now)
        assert bot.send_message.await_count==1
        with test.db() as conn:
            assert conn.execute('SELECT state FROM publication_tests').fetchone()[0]=='delivery_unknown'
    with patch.object(test.morning_bridge,'channel_status',AsyncMock(return_value={'can_post':True})):
        asyncio.run(scenario())
