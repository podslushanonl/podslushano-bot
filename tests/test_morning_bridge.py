import asyncio
import json
import sys
import types
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
from utils import morning_bridge as bridge


def sample(day='2026-10-13', clock='05:50:00+02:00'):
    return dict(date=day, checked_at=f'{day}T{clock}', intro='Доброе утро! Сегодня проверяем публикацию утреннего поста.', weather='Утром и днём ожидается погода из проверенного прогноза.', transport='Проверенные ограничения движения поездов и автобусов.', roads='Проверенные ограничения на дорогах и ожидаемые задержки.', sources=['https://www.knmi.nl', 'https://www.ns.nl', 'https://www.rijkswaterstaat.nl'])


def moment(hour=6, minute=0, day='2026-10-13'):
    return datetime.fromisoformat(f'{day}T{hour:02}:{minute:02}:00').replace(tzinfo=bridge.TZ)


def test_validation_and_escaping():
    p=sample()
    p['weather'] += ' <b>не HTML</b> & текст'
    bridge.validate(p, moment())
    result=bridge.render(p)
    assert '&lt;b&gt;не HTML&lt;/b&gt;' in result
    assert '\n\n🌦️ Погода\n\n' in result
    assert '05:50, 13 октября' in result
    assert result.endswith(bridge.CTA)
    for invalid in [dict(p,date='2026-10-12'),dict(p,checked_at='2026-10-13T04:00:00+02:00'),dict(p,checked_at='2026-10-13T05:50:00'),dict(p,sources=[])]:
        with pytest.raises(ValueError): bridge.validate(invalid,moment())


def test_dst_uses_amsterdam():
    p=sample(day='2026-10-25',clock='05:50:00+01:00')
    bridge.validate(p,moment(day='2026-10-25'))
    assert moment(day='2026-10-25').utcoffset().total_seconds()==3600


def test_authorization(monkeypatch):
    monkeypatch.setenv('MORNING_BRIDGE_TOKEN','private')
    with pytest.raises(bridge.web.HTTPUnauthorized):
        bridge.authorize(types.SimpleNamespace(headers={}))
    bridge.authorize(types.SimpleNamespace(headers={'Authorization':'Bearer private'}))


def test_outbox_send_once_and_ambiguous_delivery(tmp_path,monkeypatch):
    monkeypatch.setenv('MORNING_OUTBOX_DB',str(tmp_path/'queue.sqlite'))
    paused=AsyncMock(return_value=False)
    get=AsyncMock(return_value='')
    put=AsyncMock()
    monkeypatch.setitem(sys.modules,'handlers.content',types.SimpleNamespace(_is_paused=paused))
    monkeypatch.setitem(sys.modules,'utils.editorial_channel',types.SimpleNamespace(_meta_get=get,_meta_set=put))
    bot=types.SimpleNamespace(send_message=AsyncMock(return_value=types.SimpleNamespace(message_id=42)))
    with bridge.db() as conn:
        conn.execute('INSERT INTO morning(day,payload,digest,state) VALUES(?,?,?,?)',('2026-10-13',json.dumps(sample()),'test','queued'))
    async def scenario():
        with patch.object(bridge,'channel_status',AsyncMock(return_value={})):
            await bridge.publish_due(bot,moment(5,59))
            assert bot.send_message.await_count==0
            await bridge.publish_due(bot,moment())
            await bridge.publish_due(bot,moment())
            assert bot.send_message.await_count==1
            with bridge.db() as conn:
                assert conn.execute('SELECT state FROM morning').fetchone()[0]=='sent'
                conn.execute("UPDATE morning SET state='queued'")
            bot.send_message.side_effect=TimeoutError()
            await bridge.publish_due(bot,moment())
            await bridge.publish_due(bot,moment())
            assert bot.send_message.await_count==2
            with bridge.db() as conn:
                assert conn.execute('SELECT state FROM morning').fetchone()[0]=='delivery_unknown'
    asyncio.run(scenario())
