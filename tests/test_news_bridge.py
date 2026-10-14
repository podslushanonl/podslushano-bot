import asyncio
import json
import sys
import types
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
from aiohttp.test_utils import TestClient, TestServer
from utils import news_bridge as bridge


def sample(slot='morning',day='2026-10-15'):
    clock = '09:35' if slot == 'morning' else '17:35'
    return {'date':day,'slot':slot,'checked_at':f'{day}T{clock}:00+02:00',
        'items':[{'text':f'Новость {i}: проверенный текст с достаточным количеством деталей и фактов.',
                  'url':f'https://www.knmi.nl/news/{i}'} for i in range(5)]}


def moment(hour=10,minute=0,day='2026-10-15'):
    return datetime.fromisoformat(f'{day}T{hour:02}:{minute:02}:00').replace(tzinfo=bridge.TZ)


def test_format_links_and_validation():
    p = sample()
    p['items'][0]['text'] += ' <b>текст</b> & детали'
    p['items'][0]['url'] += '?a=1&b=2'
    bridge.validate(p,moment())
    text = bridge.render(p)
    assert text.startswith('🇳🇱 Утренние новости | 15.10\n\n1. ')
    assert text.count('>тут</a>') == 5
    assert '&amp;b=2' in text and '&lt;b&gt;' in text
    assert text.endswith('Следите за новостями вместе с нами')
    evening = bridge.render(sample('evening'))
    assert '\n<a href=' in evening
    assert evening.endswith(bridge.CTAS['evening'])
    for change in [{'date':'2026-10-14'},{'items':p['items'][:4]},
                   {'checked_at':'2026-10-15T08:00:00+02:00'},
                   {'checked_at':'2026-10-15T09:35:00'},{'slot':'other'}]:
        with pytest.raises(ValueError):
            bridge.validate(dict(p,**change),moment())
    for url in ['javascript:alert(1)','https://user:pass@example.com','https://example.com/ bad']:
        bad = sample(); bad['items'][0]['url'] = url
        with pytest.raises(ValueError): bridge.validate(bad,moment())
    with pytest.raises(ValueError): bridge.validate(sample(),moment(8))
    fresh = sample(); fresh['checked_at'] = '2026-10-15T08:00:00+02:00'
    bridge.validate(fresh,moment(8),dry_run=True)


def test_dst():
    p = sample(day='2026-10-25')
    p['checked_at'] = '2026-10-25T09:35:00+01:00'
    bridge.validate(p,moment(day='2026-10-25'))
    assert moment(day='2026-10-25').utcoffset().total_seconds() == 3600


def test_send_once_pause_and_ambiguity(tmp_path,monkeypatch):
    monkeypatch.setenv('NEWS_OUTBOX_DB',str(tmp_path/'news.sqlite'))
    paused = AsyncMock(return_value=False)
    monkeypatch.setitem(sys.modules,'handlers.content',types.SimpleNamespace(_is_paused=paused))
    bot = types.SimpleNamespace(send_message=AsyncMock(return_value=types.SimpleNamespace(message_id=42)))
    with bridge.db() as conn:
        for slot in bridge.SLOTS:
            p=sample(slot)
            conn.execute('INSERT INTO news(day,slot,payload,digest,state) VALUES(?,?,?,?,?)',
                         (p['date'],slot,json.dumps(p),'test','queued'))
    async def scenario():
        with patch.object(bridge,'channel_status',AsyncMock(return_value={})):
            await bridge.publish_due(bot,moment(9,59))
            assert bot.send_message.await_count == 0
            paused.return_value = True
            await bridge.publish_due(bot,moment())
            assert bot.send_message.await_count == 0
            paused.return_value = False
            await bridge.publish_due(bot,moment())
            await bridge.publish_due(bot,moment())
            assert bot.send_message.await_count == 1
            with bridge.db() as conn:
                assert conn.execute("SELECT state FROM news WHERE slot='morning'").fetchone()[0] == 'sent'
            bot.send_message.side_effect = TimeoutError()
            await bridge.publish_due(bot,moment(18))
            await bridge.publish_due(bot,moment(18))
            assert bot.send_message.await_count == 2
            with bridge.db() as conn:
                assert conn.execute("SELECT state FROM news WHERE slot='evening'").fetchone()[0] == 'delivery_unknown'
    asyncio.run(scenario())


def test_http_dry_run_auth_and_deduplication(tmp_path,monkeypatch):
    monkeypatch.setenv('NEWS_OUTBOX_DB',str(tmp_path/'http.sqlite'))
    monkeypatch.setenv('NEWS_BRIDGE_TOKEN','test-private')
    monkeypatch.setitem(sys.modules,'handlers.content',types.SimpleNamespace(_is_paused=AsyncMock(return_value=False)))
    real_validate = bridge.validate
    def current_validate(p,**kwargs): return real_validate(p,moment(9,40),**kwargs)
    async def scenario():
        app=bridge.web.Application(); app['bot']=object()
        app.router.add_get('/api/news/status',bridge.status)
        app.router.add_post('/api/news',bridge.ingest)
        async with TestClient(TestServer(app)) as client:
            headers={'Authorization':'Bearer test-private'}
            assert (await client.get('/api/news/status')).status == 401
            assert (await client.post('/api/news',json=dict(sample(),dry_run=True),headers=headers)).status == 200
            with bridge.db() as conn: assert conn.execute('SELECT COUNT(*) FROM news').fetchone()[0] == 0
            response=await client.post('/api/news',json=sample(),headers=headers)
            assert response.status == 202
            response=await client.post('/api/news',json=sample(),headers=headers)
            assert (await response.json())['duplicate']
            changed=sample(); changed['items'][0]['text']+=' Другие сведения.'
            assert (await client.post('/api/news',json=changed,headers=headers)).status == 409
    with patch.object(bridge,'validate',current_validate),patch.object(bridge,'channel_status',AsyncMock(return_value={'can_post':True})):
        asyncio.run(scenario())
