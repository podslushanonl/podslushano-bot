"""Opt-in, fixed-fixture live delivery verification; separate from daily slots."""
import asyncio
import json
import logging
import re
from datetime import datetime

from aiohttp import web
from utils import morning_bridge, news_bridge

LOCK = asyncio.Lock()
log = logging.getLogger(__name__)
KINDS = ('briefing','morning','evening')


def db():
    conn = news_bridge.db()
    conn.execute('CREATE TABLE IF NOT EXISTS publication_tests (run_id TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL, due_at REAL NOT NULL, state TEXT NOT NULL, message_id INTEGER, telegram_date TEXT, links INTEGER, error TEXT, PRIMARY KEY(run_id,kind))')
    return conn


def fixtures(now):
    common = {'date':now.date().isoformat(),'checked_at':now.isoformat()}
    briefing = dict(common,intro='Доброе утро! Это служебная проверка автопубликации, а не актуальная утренняя сводка.',
        weather='Этот блок проверяет оформление прогноза погоды. Метеорологические данные в тесте не публикуются.',
        transport='Этот блок проверяет оформление транспортной информации. Это не сообщение об ограничениях движения.',
        roads='Этот блок проверяет оформление дорожной информации. Это не сообщение о перекрытиях или задержках.',
        sources=['https://www.knmi.nl','https://www.ns.nl','https://www.rijkswaterstaat.nl'])
    result = {'briefing':briefing}
    for slot in ('morning','evening'):
        result[slot] = dict(common,slot=slot,items=[
            {'text':f'Служебная проверка {i+1}: тестируем пункт новостной подборки и кликабельное слово «тут». Это не настоящая новость.',
             'url':url} for i,url in enumerate([
                 'https://www.knmi.nl/nederland-nu/weer/verwachtingen',
                 'https://www.ns.nl/reisinformatie/actuele-situatie-op-het-spoor/',
                 'https://9292.nl/',
                 'https://www.rijkswaterstaat.nl/',
                 'https://nos.nl/'])])
    return result


def validate(payload,kind,now):
    if kind == 'briefing':
        morning_bridge.validate(payload,now,dry_run=True)
    else:
        news_bridge.validate(payload,now,dry_run=True)


def render(payload,kind):
    body = morning_bridge.render(payload) if kind == 'briefing' else news_bridge.render(payload)
    return 'ТЕСТ АВТОПУБЛИКАЦИИ — служебное сообщение\n\n'+body


async def start(request):
    news_bridge.authorize(request)
    if request.content_length and request.content_length > 1024:
        raise web.HTTPRequestEntityTooLarge(max_size=1024,actual_size=request.content_length)
    try:
        data=await request.json()
        run_id=data.get('run_id') if isinstance(data,dict) else None
        if not isinstance(run_id,str) or not re.fullmatch(r'[a-zA-Z0-9_-]{8,80}',run_id):
            raise ValueError('run_id must contain 8-80 letters/digits/_/-')
    except (ValueError,TypeError) as exc:
        return web.json_response({'ok':False,'error':str(exc)},status=400)
    await morning_bridge.channel_status(request.app['bot'])
    from handlers.content import _is_paused
    if await _is_paused():
        return web.json_response({'ok':False,'error':'Content publication paused'},status=409)
    now=datetime.now(morning_bridge.TZ)
    async with LOCK:
        with db() as conn:
            rows=conn.execute('SELECT kind FROM publication_tests WHERE run_id=?',(run_id,)).fetchall()
            if rows:
                return web.json_response({'ok':True,'run_id':run_id,'duplicate':True})
            for kind,payload in fixtures(now).items():
                validate(payload,kind,now)
                conn.execute('INSERT INTO publication_tests(run_id,kind,payload,due_at,state) VALUES(?,?,?,?,?)',
                    (run_id,kind,json.dumps(payload,ensure_ascii=False),now.timestamp()+15,'queued'))
    return web.json_response({'ok':True,'run_id':run_id,'state':'queued','delay_seconds':15},status=202)


async def status(request):
    news_bridge.authorize(request)
    with db() as conn:
        rows=conn.execute('SELECT run_id,kind,due_at,state,message_id,telegram_date,links,error FROM publication_tests WHERE run_id=?',(request.match_info['run_id'],)).fetchall()
    return web.json_response({'ok':True,'results':[dict(row) for row in rows]})


async def publish_due(bot,now=None):
    now=now or datetime.now(morning_bridge.TZ)
    from handlers.content import _is_paused
    if await _is_paused():
        return
    async with LOCK:
        with db() as conn:
            rows=conn.execute("SELECT * FROM publication_tests WHERE state='queued' AND due_at<=?",(now.timestamp(),)).fetchall()
        for row in rows:
            key=(row['run_id'],row['kind'])
            payload=json.loads(row['payload'])
            try:
                validate(payload,row['kind'],now)
                await morning_bridge.channel_status(bot)
            except (ValueError,RuntimeError) as exc:
                with db() as conn:
                    conn.execute("UPDATE publication_tests SET state='rejected',error=? WHERE run_id=? AND kind=?",(str(exc)[:200],*key))
                continue
            with db() as conn:
                claimed=conn.execute("UPDATE publication_tests SET state='sending' WHERE run_id=? AND kind=? AND state='queued'",key).rowcount
            if not claimed:
                continue
            try:
                message=await morning_bridge.deliver(bot,render(payload,row['kind']),silent=True)
            except Exception:
                with db() as conn:
                    conn.execute("UPDATE publication_tests SET state='delivery_unknown',error='Check channel before retry' WHERE run_id=? AND kind=?",key)
                log.exception('Test delivery uncertain; retry disabled')
                continue
            links=sum(getattr(e.type,'value',e.type)=='text_link' for e in (getattr(message,'entities',None) or []))
            with db() as conn:
                conn.execute("UPDATE publication_tests SET state='sent',message_id=?,telegram_date=?,links=? WHERE run_id=? AND kind=?",
                    (message.message_id,message.date.isoformat(),links,*key))


def install_routes(app):
    app.router.add_post('/api/publication-test',start)
    app.router.add_get('/api/publication-test/{run_id}',status)
