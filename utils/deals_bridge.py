"""Vygodno NL: authenticated WordPress relay, existing bot and Mollie credentials.
No webhook changes, new service, token transfer, or agent usage.
"""
from __future__ import annotations
import hmac
import logging
import re
from urllib.parse import urlsplit

import aiohttp
from aiohttp import web
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message

import config
from utils.site_api import _mollie

log = logging.getLogger(__name__)
router = Router(name="deals_bridge")
SITE = "https://www.podslushano.nl"
WP = SITE + "/wp-json/pn/v1/deals/"
TG_METHODS = {
    "getMe", "getChat", "getChatMember", "createChatInviteLink",
    "revokeChatInviteLink", "approveChatJoinRequest", "declineChatJoinRequest",
    "banChatMember", "unbanChatMember", "sendMessage",
}
ID = r"[A-Za-z0-9]+"
PAY_PATH = re.compile(r"/v2/payments(?:/tr_"+ID+r")?")
CUSTOMER_PATH = re.compile(r"/v2/customers(?:/(cst_"+ID+r")(?:/subscriptions(?:/sub_"+ID+r")?(?:\?limit=250)?)?)?")
AMOUNTS = {"3.99", "39.99"}

async def wp_call(path, body=None):
    if not config.WP_USER or not config.WP_APP_PASSWORD:
        return None
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=12),
                                         auth=aiohttp.BasicAuth(config.WP_USER, config.WP_APP_PASSWORD)) as s:
            async with s.request("GET" if body is None else "POST", WP+path, json=body,
                                 allow_redirects=False) as r:
                if r.status != 200:
                    return None
                result = await r.json(content_type=None)
                return result if isinstance(result, dict) else None
    except Exception:
        log.warning("Vygodno NL: WordPress bridge unavailable")
        return None

def message_payload(message: Message):
    # Telegram wire aliases: WordPress expects "from", not aiogram from_user.
    return message.model_dump(mode="json", by_alias=True, exclude_none=True)

async def forward(update):
    result = await wp_call("bridge-update", update)
    return bool(result and result.get("ok") is True)

@router.message(F.chat.type == "private", F.text.regexp(r"^/start(?:@\w+)?\s+bind_[a-f0-9]{48}$"))
async def bind(message: Message):
    if not await forward({"message":message_payload(message)}):
        await message.answer("Не удалось подтвердить Telegram. Вернитесь на сайт и повторите подключение.", parse_mode=None)

@router.message(F.chat.type == "private", Command("deals_access"))
async def access(message: Message):
    payload = message_payload(message)
    payload["text"] = "/access"
    if not await forward({"message":payload}):
        await message.answer("Не удалось проверить подписку. Попробуйте чуть позже.", parse_mode=None)

async def forward_join(handler, event, data):
    # Only send minimal join request data, only for links from this bot.
    inv = event.invite_link
    bot = data.get("bot")
    if inv and bot and inv.creator.id == bot.id and event.chat.type == 'channel':
        cfg=await wp_call('bridge-secret')
        if not cfg or str(event.chat.id)!=str(cfg.get('chat') or ''):
            return await handler(event, data)
        payload = {"chat_join_request":{
            "chat":{"id":event.chat.id,"type":event.chat.type},
            "from":{"id":event.from_user.id},
            "invite_link":{"invite_link":inv.invite_link}}}
        await forward(payload)
    return await handler(event, data)

async def forward_channel(handler, event, data):
    if event.chat.type == "channel" and (event.text or "").strip() == "/deals_channel":
        await forward({"channel_post":{"chat":{"id":event.chat.id,"title":event.chat.title,"type":"channel"}}})
    return await handler(event, data)

def own(obj):
    return isinstance(obj, dict) and (obj.get("metadata") or {}).get("source") == "deals_wp"

def amount_ok(body):
    a=body.get("amount") or {}
    return a.get("currency")=="EUR" and a.get("value") in AMOUNTS

async def mollie_rpc(method, path, body, key):
    if not isinstance(path,str) or not isinstance(body,dict) or method not in ("GET","POST","DELETE"):
        return None
    if key and not re.fullmatch(r"[a-f0-9]{64}",key):
        return None
    if path=="/v2/customers" and method=="POST":
        if not re.fullmatch(r"Telegram @[a-z0-9_]{5,32}",str(body.get("name",""))):
            return None
        return await _mollie("POST","/customers",{"name":body["name"],"metadata":{"source":"deals_wp"}})
    if PAY_PATH.fullmatch(path):
        if method=="GET" and path!="/v2/payments":
            p=await _mollie("GET",path[3:])
            return p if own(p) else None
        if path!="/v2/payments" or method!="POST" or not amount_ok(body) or not own(body):
            return None
        meta=body["metadata"]
        plan=meta.get("plan")
        if meta.get("kind")!="deals_first" or plan not in ("month","year") or body["amount"]["value"]!=("3.99" if plan=="month" else "39.99") or body.get("sequenceType")!=("first" if plan=="month" else "oneoff"):
            return None
        if body.get("webhookUrl")!=WP+"webhook" or not str(body.get("redirectUrl","")).startswith(SITE+"/?pn_deals=1"):
            return None
        cid=body.get("customerId","")
        if not re.fullmatch(r"cst_"+ID,cid) or not own(await _mollie("GET","/customers/"+cid)):
            return None
        return await _mollie("POST","/payments",body)
    m=CUSTOMER_PATH.fullmatch(path)
    if not m or not m.group(1) or "/subscriptions" not in path:
        return None
    if not own(await _mollie("GET","/customers/"+m.group(1))):
        return None
    if method=="POST":
        if not path.endswith("/subscriptions") or not amount_ok(body) or not own(body):
            return None
        if body.get("interval")!="1 month" or body["amount"]["value"]!="3.99" or body.get("webhookUrl")!=WP+"webhook":
            return None
        if (body.get("metadata") or {}).get("kind")!="deals_renewal":
            return None
    if method=="DELETE" and not re.search(r"/sub_"+ID+r"$",path):
        return None
    return await _mollie(method,path[3:],body if method=="POST" else None,idempotency_key=key or None)

async def rpc(request):
    # The secret is created by WordPress admin and read with existing WP app credentials.
    # No credentials, API keys, or raw responses are written to logs.
    supplied=request.headers.get("X-PN-Deals-Bridge","")
    if not re.fullmatch(r"[a-f0-9]{64}",supplied):
        return web.json_response({"ok":False},status=403)
    cfg=await wp_call("bridge-secret")
    if not cfg or not hmac.compare_digest(supplied,str(cfg.get("secret",""))):
        return web.json_response({"ok":False},status=403)
    try:
        b=await request.json()
        if not isinstance(b,dict): raise ValueError()
        op=b.get("op")
        if op=="health":
            me=await request.app["bot"].get_me()
            result={"id":me.id,"username":me.username,"mollie":bool(config.MOLLIE_API_KEY and config.MOLLIE_API_KEY.startswith("live_"))}
        elif op=="mollie":
            result=await mollie_rpc(b.get("method"),b.get("path"),b.get("body") or {},b.get("key") or "")
        elif op=="telegram":
            method=b.get("method")
            body=b.get("body") or {}
            if method not in TG_METHODS or not isinstance(body,dict):
                raise ValueError()
            # Channel operations can only target the confirmed channel or explicit setup candidate.
            if method not in ("getMe","sendMessage"):
                chat=str(body.get("chat_id",""))
                if chat not in {str(cfg.get("chat") or ""),str(cfg.get("candidate") or "")} or not re.fullmatch(r"-100\d+",chat):
                    raise ValueError()
            if method=="sendMessage" and not re.fullmatch(r"\d+",str(body.get("chat_id",""))):
                raise ValueError()
            # Telegram API uses the running bot token. No webhook operations are allowed.
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=12)) as session:
                async with session.post("https://api.telegram.org/bot"+config.BOT_TOKEN+"/"+method,
                                        json=body,allow_redirects=False) as response:
                    j=await response.json(content_type=None)
                    result=j.get("result") if j.get("ok") else None
        else: raise ValueError()
        if result is None:
            return web.json_response({"ok":False},status=502)
        return web.json_response({"ok":True,"result":result})
    except Exception:
        log.warning("Vygodno NL bridge operation failed")
        return web.json_response({"ok":False},status=502)

def install_routes(app):
    app.router.add_post("/api/deals/bridge",rpc)
