"""Authenticated ChatGPT -> durable 06:00 Amsterdam Telegram outbox.

No AI API calls. One fixed channel, one slot per local date, no retry after
ambiguous delivery. The token only grants access to this morning outbox.
"""
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
from zoneinfo import ZoneInfo

from aiohttp import web
import config

log = logging.getLogger(__name__)
TZ = ZoneInfo('Europe/Amsterdam')
CTA = 'Нравится разбор с утра? Ставьте 🔥'
LOCK = asyncio.Lock()


def db():
    path = Path(os.getenv('MORNING_OUTBOX_DB', '/app/data/morning_outbox.sqlite3'))
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute('CREATE TABLE IF NOT EXISTS morning (day TEXT PRIMARY KEY, payload TEXT NOT NULL, digest TEXT NOT NULL, state TEXT NOT NULL, message_id INTEGER, error TEXT)')
    return conn


def validate(payload, now=None):
    now = now or datetime.now(TZ)
    if not isinstance(payload, dict):
        raise ValueError('JSON object required')
    checked = datetime.fromisoformat(payload.get('checked_at', ''))
    if checked.tzinfo is None:
        raise ValueError('checked_at must include timezone')
    checked = checked.astimezone(TZ)
    if payload.get('date') != now.date().isoformat() or checked.date() != now.date():
        raise ValueError('Only current Amsterdam date accepted')
    age = (now - checked).total_seconds()
    if not -60 <= age <= 2700:
        raise ValueError('Research must be no older than 45 minutes')
    if not time(5, 20) <= now.time().replace(tzinfo=None) < time(6, 45):
        raise ValueError('Intake window is 05:20-06:45 Amsterdam')
    for key in ('intro', 'weather', 'transport', 'roads'):
        value = payload.get(key)
        if not isinstance(value, str) or len(value.strip()) < 25:
            raise ValueError(f'Missing or too short: {key}')
        if any(x in value for x in ('http://', 'https://', '', '{checked_at}')):
            raise ValueError('Keep links and citation markup in sources only')
    if not payload['intro'].startswith('Доброе утро!'):
        raise ValueError('Intro must begin with Доброе утро!')
    sources = payload.get('sources')
    if not isinstance(sources, list) or len(sources) < 3 or not all(isinstance(s,str) and s.startswith('https://') for s in sources):
        raise ValueError('At least three research source URLs required')
    important = payload.get('important', '')
    if not isinstance(important, str) or len(important) > 600:
        raise ValueError('Invalid important block')
    if len(''.join(payload[k] for k in ('intro', 'weather', 'transport', 'roads')) + important) > 3300:
        raise ValueError('Text too long for one Telegram post')
    return checked


def render(payload):
    esc = html.escape
    checked = datetime.fromisoformat(payload['checked_at']).astimezone(TZ)
    blocks = [f"<i>{esc(payload['intro'])}</i>", '<b>🌦️ Погода</b>', esc(payload['weather']), '<b>🚇 Транспорт</b>', esc(payload['transport'])]
    if payload.get('important'):
        blocks.append(f"<blockquote><i><b>Важно:</b> {esc(payload['important'])}</i></blockquote>")
    blocks += ['<b>🚗 Дороги</b>', esc(payload['roads']), f'<blockquote><i>Информация актуальна на {checked:%H:%M}, {checked:%d.%m.%Y}. Следите за обновлениями в KNMI, NS, 9292 и Rijkswaterstaat.</i></blockquote>', f'<b>{CTA}</b>']
    return '\n\n'.join(blocks)


def authorize(request):
    token = os.getenv('MORNING_BRIDGE_TOKEN', '')
    if not token or not hmac.compare_digest(request.headers.get('Authorization', ''), 'Bearer ' + token):
        raise web.HTTPUnauthorized()


async def channel_status(bot):
    chat = await bot.get_chat(config.ANNOUNCE_CHANNEL)
    me = await bot.get_me()
    member = await bot.get_chat_member(chat.id, me.id)
    allowed = member.status == 'creator' or bool(getattr(member, 'can_post_messages', False))
    if chat.type != 'channel' or chat.username != 'podslushanovnl' or not allowed:
        raise RuntimeError('Configured channel or publishing permission mismatch')
    return {'id': chat.id, 'username': chat.username, 'title': chat.title, 'can_post': allowed}


async def status(request):
    authorize(request)
    channel = await channel_status(request.app['bot'])
    from handlers.content import _is_paused
    with db() as conn:
        row = conn.execute('SELECT day, state, message_id, error FROM morning ORDER BY day DESC LIMIT 1').fetchone()
    return web.json_response({'ok': True, 'channel': channel, 'paused': await _is_paused(), 'timezone': 'Europe/Amsterdam', 'publish_at': '06:00', 'last': dict(row) if row else None})


async def ingest(request):
    authorize(request)
    if request.content_length and request.content_length > 24000:
        raise web.HTTPRequestEntityTooLarge(max_size=24000, actual_size=request.content_length)
    try:
        payload = await request.json()
        validate(payload)
    except (ValueError, TypeError, KeyError) as exc:
        return web.json_response({'ok': False, 'error': str(exc)}, status=400)
    await channel_status(request.app['bot'])
    if payload.pop('dry_run', False):
        return web.json_response({'ok': True, 'state': 'validated_not_queued', 'html': render(payload)})
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    digest = hashlib.sha256(serialized.encode()).hexdigest()
    async with LOCK:
        with db() as conn:
            row = conn.execute('SELECT state, digest, message_id FROM morning WHERE day=?', (payload['date'],)).fetchone()
            if row:
                if row['digest'] != digest:
                    return web.json_response({'ok': False, 'error': 'Date already has a different post', 'state': row['state']}, status=409)
                return web.json_response({'ok': True, 'state': row['state'], 'message_id': row['message_id'], 'duplicate': True})
            conn.execute('INSERT INTO morning(day,payload,digest,state) VALUES(?,?,?,?)', (payload['date'], serialized, digest, 'queued'))
    return web.json_response({'ok': True, 'state': 'queued', 'publish_at': payload['date'] + 'T06:00:00 Europe/Amsterdam'}, status=202)


async def publish_due(bot, now=None):
    now = now or datetime.now(TZ)
    if now.time().replace(tzinfo=None) < time(6):
        return
    from handlers.content import _is_paused
    from utils.editorial_channel import _meta_get, _meta_set
    if await _is_paused():
        return
    day = now.date().isoformat()
    async with LOCK:
        with db() as conn:
            row = conn.execute('SELECT * FROM morning WHERE day=?', (day,)).fetchone()
        if not row or row['state'] != 'queued':
            return
        payload = json.loads(row['payload'])
        if await _meta_get('editorial_morning_date') == day:
            with db() as conn:
                conn.execute("UPDATE morning SET state='duplicate_suppressed' WHERE day=?", (day,))
            return
        try:
            validate(payload, now)
            await channel_status(bot)
        except (ValueError, RuntimeError) as exc:
            with db() as conn:
                conn.execute("UPDATE morning SET state='rejected', error=? WHERE day=?", (str(exc)[:200], day))
            return
        with db() as conn:
            conn.execute("UPDATE morning SET state='sending' WHERE day=? AND state='queued'", (day,))
        try:
            message = await bot.send_message(config.ANNOUNCE_CHANNEL, render(payload), parse_mode='HTML', disable_web_page_preview=True)
        except Exception:
            with db() as conn:
                conn.execute("UPDATE morning SET state='delivery_unknown', error='Check channel before retry' WHERE day=?", (day,))
            log.exception('Morning bridge delivery uncertain; automatic retry disabled')
            return
        with db() as conn:
            conn.execute("UPDATE morning SET state='sent', message_id=? WHERE day=?", (message.message_id, day))
        await _meta_set('editorial_morning_date', day)
        log.info('Morning bridge published day=%s message_id=%s', day, message.message_id)


async def lifecycle(app):
    async def loop():
        while True:
            try:
                if os.getenv('MORNING_BRIDGE_TOKEN'):
                    await publish_due(app['bot'])
            except Exception:
                log.exception('Morning bridge scheduler error')
            await asyncio.sleep(5)
    task = asyncio.create_task(loop())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


def install_routes(app):
    app.router.add_get('/api/morning/status', status)
    app.router.add_post('/api/morning', ingest)
    app.cleanup_ctx.append(lifecycle)
