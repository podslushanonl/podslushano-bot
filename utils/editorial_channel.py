"""Редакционная линия Telegram-канала с обязательным предпросмотром."""
from __future__ import annotations
import asyncio, html, logging, re
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select
import config
from database.db import get_session
from database.models import ContentPost, Meta
from utils.ai import _create_with_server_tool_continuation, _extract_text_and_sources, _get_client, _web_search_errors, _web_search_tool, ai_enabled

log = logging.getLogger(__name__)
router = Router()
AMSTERDAM = ZoneInfo("Europe/Amsterdam")
RECENT_SLOTS = 8
DRAFT_CHUNK = 95
MORNING_SOURCES = ["knmi.nl", "ns.nl", "prorail.nl", "rijkswaterstaat.nl", "vananaarbeter.nl", "9292.nl"]
EVENT_SOURCES = ["evenementen.nl", "iamsterdam.com", "uitagendautrecht.nl", "rotterdamfestivals.nl", "denhaag.com", "thisiseindhoven.com", "visitbrabant.com", "holland.com"]
FACT_SOURCES = ["canonvannederland.nl", "rijksmuseum.nl", "openluchtmuseum.nl", "cultureelerfgoed.nl", "stadsarchief.amsterdam.nl", "archieven.nl", "holland.com"]

def _now(): return datetime.now(AMSTERDAM).replace(tzinfo=None)

async def _meta_get(key):
    async with get_session() as s:
        row = await s.get(Meta, key); return row.value if row else ""

async def _meta_set(key, value):
    async with get_session() as s:
        row = await s.get(Meta, key)
        if row is None: s.add(Meta(key=key, value=str(value)[:100]))
        else: row.value = str(value)[:100]
        await s.commit()

async def _attempt_allowed(key, now, cooldown=20):
    raw = await _meta_get(key)
    if raw:
        try:
            if now - datetime.fromisoformat(raw) < timedelta(minutes=cooldown): return False
        except ValueError: pass
    await _meta_set(key, now.isoformat(timespec="minutes")); return True

async def _recent_topics():
    out=[]
    for i in range(RECENT_SLOTS):
        v=await _meta_get(f"editorial_recent_{i}")
        if v: out.append(v)
    return out

async def _remember_topic(text):
    first=next((x.strip() for x in text.splitlines() if x.strip()), "")
    first=re.sub(r"^[^\wА-Яа-яЁё]+", "", first)[:90]
    if not first: return
    recent=await _recent_topics(); vals=[first]+[x for x in recent if x.lower()!=first.lower()]
    for i,v in enumerate(vals[:RECENT_SLOTS]): await _meta_set(f"editorial_recent_{i}",v)

def _clean_text(text):
    text=re.sub(r"^```(?:text)?\s*|\s*```$", "", (text or "").strip()).replace("**","").replace("__","")
    return re.sub(r"<[^>]+>", "", text).strip()

async def _generate(system,user,domains,max_tokens=900):
    if not ai_enabled() or not config.AI_WEB_SEARCH: return None
    tools=_web_search_tool(domains,max_uses=6)
    if not tools: return None
    try:
        r=await _create_with_server_tool_continuation(_get_client(),model=config.AI_POST_MODEL,max_tokens=max_tokens,system=system,messages=[{"role":"user","content":user}],tools=tools)
    except Exception as exc:
        log.warning("Editorial web generation failed: %s",exc); return None
    if _web_search_errors(r): return None
    text,sources=_extract_text_and_sources(r); text=_clean_text(text)
    return (text,sources) if text and sources else None

async def _morning_brief():
    system=("Ты выпускающий редактор утреннего Telegram-брифа для русскоязычных жителей Нидерландов. Обязательно проверь свежие данные поиском. Используй KNMI для погоды, NS/ProRail/9292 для транспорта, Rijkswaterstaat/VanAnaarBeter для дорог. Ничего не выдумывай. Это ОДИН пост, не три отдельных. За 20 секунд читатель должен понять погоду на день, существенные сбои транспорта и крупные пробки, аварии или перекрытия. Мелкие локальные задержки не перечисляй. Если серьёзных проблем нет, скажи коротко. 450-750 знаков. Первая строка живой заголовок, затем три компактных блока ☁️, 🚆, 🚗. Без markdown и HTML.")
    r=await _generate(system,f"Сегодня {_now():%d.%m.%Y}, Europe/Amsterdam. Бриф только на сегодня.",MORNING_SOURCES,700)
    return r[0] if r else None

async def _event_spotlight():
    recent=await _recent_topics()
    system=("Ты редактор русскоязычного Telegram-медиа о Нидерландах. Найди ОДНО сильное реальное мероприятие на ближайшие 14 дней. В приоритете evenementen.nl, затем официальный сайт события или городская афиша. Проверь дату, место, цену и актуальный статус. Никаких списков. Выбирай событие с историей или визуальным/культурным поводом, а не первое в поиске. Начни с конкретного хука, затем 2-3 детали, почему туда стоит пойти, затем дата, город/адрес, цена и официальный источник. Без рекламных клише. 650-1000 знаков.")
    r=await _generate(system,f"Сегодня {_now():%d.%m.%Y}. Не повторяй: {', '.join(recent) or 'нет'}.",EVENT_SOURCES,900)
    if not r:return None
    text,sources=r
    if "http://" not in text and "https://" not in text:text+=f"\n\nИсточник: {sources[0]}"
    return text

async def _curiosity_post():
    recent=await _recent_topics()
    system=("Ты редактор Telegram-медиа для людей, которые уже живут в Нидерландах. Найди один небанальный проверяемый сюжет: странную деталь истории, происхождение повседневной вещи или правила, инженерное решение, малоизвестную традицию, архитектурный след прошлого, музейный объект или языковую деталь с историей. Проверяй факты по надёжным нидерландским источникам. Без нового сильного угла запрещены темы: ниже уровня моря, велосипеды, тюльпаны, кофешопы, красные фонари, деревянные башмаки, мельницы, прямолинейность голландцев. Не начинай с «А вы знали?». Сначала информационный разрыв, потом объяснение и связь с сегодняшними Нидерландами. 650-1000 знаков.")
    r=await _generate(system,f"Сегодня {_now():%d.%m.%Y}. Не повторяй: {', '.join(recent) or 'нет'}.",FACT_SOURCES,900)
    return r[0] if r else None

async def _store_draft(did,kind,text,button):
    await _meta_set(f"ed_{did}_kind",kind); await _meta_set(f"ed_{did}_button","1" if button else "0"); await _meta_set(f"ed_{did}_status","pending")
    chunks=[text[i:i+DRAFT_CHUNK] for i in range(0,len(text),DRAFT_CHUNK)]; await _meta_set(f"ed_{did}_n",len(chunks))
    for i,c in enumerate(chunks): await _meta_set(f"ed_{did}_{i}",c)

async def _load_draft(did):
    if await _meta_get(f"ed_{did}_status")!="pending":return None
    try:n=int(await _meta_get(f"ed_{did}_n"))
    except ValueError:return None
    text="".join([await _meta_get(f"ed_{did}_{i}") for i in range(n)])
    return await _meta_get(f"ed_{did}_kind"),text,await _meta_get(f"ed_{did}_button")=="1"

def _approval_kb(did):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Опубликовать",callback_data=f"edpub:{did}"),InlineKeyboardButton(text="❌ Пропустить",callback_data=f"edskip:{did}")]])

async def _send_for_approval(bot,kind,text,button=False):
    did=f"{int(_now().timestamp())%100000000:08d}"; await _store_draft(did,kind,text,button)
    labels={"morning":"Утренний бриф","event":"Мероприятие","curiosity":"Познавательный пост"}; sent=False
    for aid in config.ADMIN_IDS:
        try:
            await bot.send_message(aid,f"👀 <b>{labels.get(kind,kind)}. Предпросмотр</b>\n\n{html.escape(text)}\n\nВ канал ничего не уйдёт, пока вы не подтвердите публикацию.",reply_markup=_approval_kb(did),disable_web_page_preview=True); sent=True
        except Exception as exc:log.warning("Cannot send preview: %s",exc)
    return sent

def _channel_kb():return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🎭 Открыть афишу в боте",url=config.BOT_URL)]])

async def _publish_editorial(bot,kind,text,button):
    try:
        await bot.send_message(config.ANNOUNCE_CHANNEL,text,parse_mode=None,reply_markup=_channel_kb() if button else None,disable_web_page_preview=True)
        if kind in {"event","curiosity"}:await _remember_topic(text)
        return True
    except Exception as exc:log.warning("Editorial publish failed: %s",exc); return False

@router.callback_query(F.data.startswith("edpub:"),F.from_user.id.in_(config.ADMIN_IDS))
async def editorial_publish_callback(cb:CallbackQuery):
    did=cb.data.split(":",1)[1]; draft=await _load_draft(did)
    if not draft:await cb.answer("Этот черновик уже обработан",show_alert=True);return
    kind,text,button=draft
    if await _publish_editorial(cb.bot,kind,text,button):
        await _meta_set(f"ed_{did}_status","published");await cb.answer("Опубликовано");await cb.message.edit_reply_markup(reply_markup=None)
    else:await cb.answer("Не удалось опубликовать",show_alert=True)

@router.callback_query(F.data.startswith("edskip:"),F.from_user.id.in_(config.ADMIN_IDS))
async def editorial_skip_callback(cb:CallbackQuery):
    did=cb.data.split(":",1)[1]
    if not await _load_draft(did):await cb.answer("Этот черновик уже обработан",show_alert=True);return
    await _meta_set(f"ed_{did}_status","skipped");await cb.answer("Пропущено");await cb.message.edit_reply_markup(reply_markup=None)

async def _run_generated(bot,now,kind,datekey,generator,button=False):
    if await _meta_get(datekey)==now.date().isoformat():return
    if not await _attempt_allowed(f"{datekey}_try",now,30):return
    text=await generator()
    if text and await _send_for_approval(bot,kind,text,button):await _meta_set(datekey,now.date().isoformat())

async def _run_morning(bot,now):
    if time(6,45)<=now.time()<time(8,0):await _run_generated(bot,now,"morning","editorial_morning_date",_morning_brief)
async def _run_event(bot,now):
    if now.weekday()==4 and time(13,0)<=now.time()<time(15,0):await _run_generated(bot,now,"event","editorial_event_date",_event_spotlight,True)
async def _run_curiosity(bot,now):
    if now.weekday()==5 and time(14,0)<=now.time()<time(16,0):await _run_generated(bot,now,"curiosity","editorial_fact_date",_curiosity_post)

async def _queue_due_content_post(bot,now):
    from handlers.content import MISSED_GRACE, _post_kb, render_post, seed_content_calendar
    await seed_content_calendar()
    async with get_session() as s:
        due=(await s.scalars(select(ContentPost).where(ContentPost.status=="scheduled",ContentPost.scheduled_at<=now).order_by(ContentPost.scheduled_at))).all()
        for row in due:
            if now-row.scheduled_at>MISSED_GRACE:row.status="skipped";row.error_text="missed before admin preview"
        await s.commit();ready=[row for row in due if now-row.scheduled_at<=MISSED_GRACE]
    if not ready:return
    post=ready[0];key=f"content_preview_{post.id}"
    if await _meta_get(key)=="1":return
    text,_=await render_post(post)
    kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Опубликовать",callback_data=f"cpub:{post.id}"),InlineKeyboardButton(text="❌ Пропустить",callback_data=f"cskip:{post.id}")]])
    for aid in config.ADMIN_IDS:
        try:
            await bot.send_message(aid,f"👀 <b>Пост бота. Предпросмотр</b>\nСлот: {post.scheduled_at:%d.%m · %H:%M}\n\n{text}",reply_markup=kb,disable_web_page_preview=True)
            await bot.send_message(aid,"Кнопка под постом будет такой:",reply_markup=_post_kb(post))
        except Exception as exc:log.warning("Cannot send content preview: %s",exc)
    await _meta_set(key,"1")

@router.callback_query(F.data.startswith("cpub:"),F.from_user.id.in_(config.ADMIN_IDS))
async def content_publish_callback(cb:CallbackQuery):
    from handlers.content import publish_content_post
    pid=int(cb.data.split(":",1)[1])
    async with get_session() as s:post=await s.get(ContentPost,pid)
    if not post or post.status not in {"scheduled","failed"}:await cb.answer("Этот пост уже обработан",show_alert=True);return
    ok=await publish_content_post(cb.bot,pid,early=True);await cb.answer("Опубликовано" if ok else "Ошибка публикации",show_alert=not ok)
    if ok:await cb.message.edit_reply_markup(reply_markup=None)

@router.callback_query(F.data.startswith("cskip:"),F.from_user.id.in_(config.ADMIN_IDS))
async def content_skip_callback(cb:CallbackQuery):
    pid=int(cb.data.split(":",1)[1])
    async with get_session() as s:
        post=await s.get(ContentPost,pid)
        if not post or post.status not in {"scheduled","failed"}:await cb.answer("Этот пост уже обработан",show_alert=True);return
        post.status="skipped";post.error_text="skipped by admin from preview";await s.commit()
    await cb.answer("Пропущено");await cb.message.edit_reply_markup(reply_markup=None)

async def editorial_channel_loop(bot):
    await asyncio.sleep(35)
    while True:
        try:
            now=_now();await _run_morning(bot,now);await _run_event(bot,now);await _run_curiosity(bot,now);await _queue_due_content_post(bot,now)
        except Exception as exc:log.exception("Editorial channel loop failed: %s",exc)
        await asyncio.sleep(60)
