"""Authenticated, persistent Telegram news outbox; no paid AI generation."""
import asyncio
import hashlib
import hmac
import html
import json
import logging
import os
import sqlite3
from datetime import datetime, time
from pathlib import Path
from urllib.parse import urlsplit

from aiohttp import web
import config
from utils.morning_bridge import TZ, channel_status

log = logging.getLogger(__name__)
LOCK = asyncio.Lock()
SLOTS = {'morning': 10, 'evening': 18}
CTAS = {'morning': 'Следите за новостями вместе с нами',
        'evening': 'Подписывайтесь, чтобы не пропускать главные новости Нидерландов каждый день'}


def db():
    path = Path(os.getenv('NEWS_OUTBOX_DB', '/app/data/news_outbox.sqlite3'))
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute('CREATE TABLE IF NOT EXISTS news (day TEXT NOT NULL, slot TEXT NOT NULL, payload TEXT NOT NULL, digest TEXT NOT NULL, state TEXT NOT NULL, message_id INTEGER, error TEXT, PRIMARY KEY(day,slot))')
    return conn


def validate(payload, now=None, *, dry_run=False):
    now = now or datetime.now(TZ)
    if not isinstance(payload, dict) or payload.get('slot') not in SLOTS:
        raise ValueError('slot must be morning or evening')
    checked = datetime.fromisoformat(payload.get('checked_at', ''))
    if checked.tzinfo is None:
        raise ValueError('checked_at must include timezone')
    checked = checked.astimezone(TZ)
    if payload.get('date') != now.date().isoformat() or checked.date() != now.date():
        raise ValueError('Only current Amsterdam date accepted')
    if not -60 <= (now.timestamp() - checked.timestamp()) <= 3600:
        raise ValueError('Research must be no older than 60 minutes')
    hour = SLOTS[payload['slot']]
    if not dry_run and not time(hour-1) <= now.time().replace(tzinfo=None) < time(hour,45):
        raise ValueError(f'Intake window is {hour-1:02}:00-{hour:02}:45 Amsterdam')
    items = payload.get('items')
    if not isinstance(items, list) or len(items) != 5:
        raise ValueError('Exactly five news items required')
    urls = set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError('Each item requires text and url')
        text, url = item.get('text'), item.get('url')
        if not isinstance(text,str) or not 40 <= len(text.strip()) <= 650:
            raise ValueError('News text must contain 40-650 characters')
        if any(s in text for s in ('https://', 'http://', '')):
            raise ValueError('Keep source URL separate from text')
        if not isinstance(url,str) or len(url) > 2000:
            raise ValueError('Invalid source URL')
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or any(c.isspace() for c in url):
            raise ValueError('Source must be a valid HTTPS URL')
        if url in urls:
            raise ValueError('Duplicate source URL')
        urls.add(url)
    plain = '\n\n'.join(item['text'] for item in items)
    if len(plain.encode('utf-16-le')) // 2 + 220 > 4096:
        raise ValueError('Text too long for one Telegram post')
    return checked


def render(payload):
    label = 'Утренние' if payload['slot'] == 'morning' else 'Вечерние'
    date = datetime.fromisoformat(payload['date']).strftime('%d.%m')
    blocks = [f'🇳🇱 {label} новости | {date}']
    for number, item in enumerate(payload['items'],1):
        link = f'<a href="{html.escape(item["url"],quote=True)}">тут</a>'
        separator = ' ' if payload['slot'] == 'morning' else '\n'
        blocks.append(f'{number}. {html.escape(item["text"].strip())}{separator}{link}')
    blocks.append(CTAS[payload['slot']])
    return '\n\n'.join(blocks)


def authorize(request):
    token = os.getenv('NEWS_BRIDGE_TOKEN','')
    if not token or not hmac.compare_digest(request.headers.get('Authorization',''),'Bearer '+token):
        raise web.HTTPUnauthorized()


async def status(request):
    authorize(request)
    channel = await channel_status(request.app['bot'])
    from handlers.content import _is_paused
    with db() as conn:
        rows = conn.execute('SELECT day,slot,state,message_id,error FROM news ORDER BY day DESC,slot LIMIT 14').fetchall()
    return web.json_response({'ok':True,'channel':channel,'paused':await _is_paused(),
        'timezone':'Europe/Amsterdam','publish_at':{'morning':'10:00','evening':'18:00'},'recent':[dict(row) for row in rows]})


async def ingest(request):
    authorize(request)
    if request.content_length and request.content_length > 24000:
        raise web.HTTPRequestEntityTooLarge(max_size=24000,actual_size=request.content_length)
    try:
        payload = await request.json()
        dry_run = payload.pop('dry_run',False) if isinstance(payload,dict) else False
        if not isinstance(dry_run,bool):
            raise ValueError('dry_run must be boolean')
        validate(payload,dry_run=dry_run)
    except (ValueError,TypeError,KeyError) as exc:
        return web.json_response({'ok':False,'error':str(exc)},status=400)
    await channel_status(request.app['bot'])
    if dry_run:
        return web.json_response({'ok':True,'state':'validated_not_queued','html':render(payload)})
    from handlers.content import _is_paused
    if await _is_paused():
        return web.json_response({'ok':False,'error':'Content publication paused'},status=409)
    serialized = json.dumps(payload,ensure_ascii=False,sort_keys=True)
    digest = hashlib.sha256(serialized.encode()).hexdigest()
    async with LOCK:
        with db() as conn:
            row = conn.execute('SELECT state,digest,message_id FROM news WHERE day=? AND slot=?',(payload['date'],payload['slot'])).fetchone()
            if row:
                if row['digest'] != digest:
                    return web.json_response({'ok':False,'error':'Slot already has a different post','state':row['state']},status=409)
                return web.json_response({'ok':True,'state':row['state'],'message_id':row['message_id'],'duplicate':True})
            conn.execute('INSERT INTO news(day,slot,payload,digest,state) VALUES(?,?,?,?,?)',
                (payload['date'],payload['slot'],serialized,digest,'queued'))
    return web.json_response({'ok':True,'state':'queued','publish_at':f'{payload["date"]}T{SLOTS[payload["slot"]]:02}:00:00 Europe/Amsterdam'},status=202)


async def publish_due(bot,now=None):
    now = now or datetime.now(TZ)
    from handlers.content import _is_paused
    if await _is_paused():
        return
    async with LOCK:
        with db() as conn:
            rows = conn.execute("SELECT * FROM news WHERE day=? AND state='queued'",(now.date().isoformat(),)).fetchall()
        for row in rows:
            if now.time().replace(tzinfo=None) < time(SLOTS[row['slot']]):
                continue
            payload = json.loads(row['payload'])
            key = (row['day'],row['slot'])
            try:
                validate(payload,now)
                await channel_status(bot)
            except (ValueError,RuntimeError) as exc:
                with db() as conn:
                    conn.execute("UPDATE news SET state='rejected',error=? WHERE day=? AND slot=?",(str(exc)[:200],*key))
                continue
            with db() as conn:
                claimed = conn.execute("UPDATE news SET state='sending' WHERE day=? AND slot=? AND state='queued'",key).rowcount
            if not claimed:
                continue
            try:
                message = await bot.send_message(config.ANNOUNCE_CHANNEL,render(payload),parse_mode='HTML',disable_web_page_preview=True)
            except Exception:
                with db() as conn:
                    conn.execute("UPDATE news SET state='delivery_unknown',error='Check channel before retry' WHERE day=? AND slot=?",key)
                log.exception('News delivery uncertain; automatic retry disabled')
                continue
            with db() as conn:
                conn.execute("UPDATE news SET state='sent',message_id=? WHERE day=? AND slot=?",(message.message_id,*key))
            log.info('News published day=%s slot=%s message_id=%s',*key,message.message_id)


async def lifecycle(app):
    async def loop():
        while True:
            try:
                if os.getenv('NEWS_BRIDGE_TOKEN'):
                    await publish_due(app['bot'])
            except Exception:
                log.exception('News bridge scheduler error')
            await asyncio.sleep(5)
    task = asyncio.create_task(loop())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


def install_routes(app):
    app.router.add_get('/api/news/status',status)
    app.router.add_post('/api/news',ingest)
    app.cleanup_ctx.append(lifecycle)
