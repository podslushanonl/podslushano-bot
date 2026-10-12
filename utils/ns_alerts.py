"""Уведомления о сбоях NS в Telegram для подписчиков станции.

Подписка приходит с сайта ссылкой t.me/<бот>?start=ns_<код станции>.
Раз в 5 минут бот смотрит сбои NS (тот же кэш, что и у сайта) и пишет
подписчикам затронутых станций один раз на каждый сбой. Claude здесь не
используется: тексты уже переведены в utils.ns_trains.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramForbiddenError
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import delete, select

from database.db import get_session
from database.models import NsAlertSent, NsSubscription
from utils import ns_trains

log = logging.getLogger(__name__)
router = Router()

SITE_URL = "https://podslushano.nl/trains/"
CHECK_EVERY = 300
MAX_STATIONS = 3
PLANNED_AHEAD = timedelta(hours=24)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def relevant(data: dict, now: datetime | None = None) -> list[dict]:
    """Сбои, о которых стоит предупредить: текущие и ремонт, который начнётся в ближайшие сутки."""
    now = now or _now()
    out = [x for x in data.get("now") or [] if x.get("stations")]
    for x in data.get("planned") or []:
        st = ns_trains._parse_ts(x.get("start"))
        if x.get("stations") and st and st - now <= PLANNED_AHEAD:
            out.append(x)
    return out


def alert_text(x: dict, station_name: str) -> str:
    lines = [f"<b>Поезда NS · {_h(station_name)}</b>", "",
             f"<b>{_h(x.get('type_ru') or 'Изменения')}: {_h(x.get('title') or '')}</b>"]
    if x.get("situation"):
        lines.append(_h(x["situation"]))
    if x.get("text"):
        lines.append(_h(x["text"]))
    if x.get("cause"):
        lines.append(f"Причина: {_h(x['cause'])}")
    if not x.get("active", True) and x.get("start_ru"):
        lines.append(f"Когда: {_h(x['start_ru'])}{' — ' + _h(x['end_ru']) if x.get('end_ru') else ''}")
    elif x.get("expected"):
        lines.append(_h(x["expected"]))
    elif x.get("end_ru"):
        lines.append(f"Ожидаемо до: {_h(x['end_ru'])}")
    if x.get("extra_max") or x.get("extra_min"):
        lo, hi = x.get("extra_min"), x.get("extra_max")
        lines.append(f"Дорога займёт дольше: +{lo or hi}{'–' + str(hi) if lo and hi and hi != lo else ''} мин")
    if x.get("buses"):
        lines.append("Вместо поездов ходят автобусы.")
    for a in x.get("advice") or []:
        lines.append(f"Совет: {_h(a)}")
    lines += ["", f"Табло и все сбои: {SITE_URL}"]
    return "\n".join(lines)


def _now_line(n: int) -> str:
    if n == 1:
        return "Сейчас на этой станции есть сбой, подробности ниже."
    word = "сбоя" if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14) else "сбоев"
    return f"Сейчас на этой станции {n} {word}, подробности ниже."


def _h(text: str) -> str:
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _manage_kb(subs: list[NsSubscription]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=f"Отписаться: {s.station_name or s.station_code}",
                                  callback_data=f"nsun:{s.station_code}")] for s in subs]
    rows.append([InlineKeyboardButton(text="Табло и сбои на сайте", url=SITE_URL)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _subs(user_id: int) -> list[NsSubscription]:
    async with get_session() as session:
        return list((await session.execute(
            select(NsSubscription).where(NsSubscription.user_id == user_id).order_by(NsSubscription.id))).scalars())


async def _mark_sent(user_id: int, ids: list[str]) -> None:
    if not ids:
        return
    async with get_session() as session:
        have = set((await session.execute(select(NsAlertSent.disruption_id).where(
            NsAlertSent.user_id == user_id, NsAlertSent.disruption_id.in_(ids)))).scalars())
        for i in ids:
            if i not in have:
                session.add(NsAlertSent(user_id=user_id, disruption_id=i[:80]))
        await session.commit()


async def start_subscription(message: Message, code: str) -> None:
    """?start=ns_UT: подписка на станцию и то, что на ней происходит сейчас."""
    code = (code or "").upper()
    user_id = message.from_user.id
    name = await ns_trains.station_name(code) if ns_trains._STATION_RE.match(code) else None
    if not name:
        await message.answer("Не нашёл такую станцию NS. Выберите станцию на сайте ещё раз: " + SITE_URL)
        return
    subs = await _subs(user_id)
    if not any(s.station_code == code for s in subs):
        if len(subs) >= MAX_STATIONS:
            await message.answer(f"Можно следить максимум за {MAX_STATIONS} станциями. Отпишитесь от одной из них:",
                                 reply_markup=_manage_kb(subs))
            return
        async with get_session() as session:
            session.add(NsSubscription(user_id=user_id, station_code=code, station_name=name))
            await session.commit()
        subs = await _subs(user_id)
    try:
        current = [x for x in relevant(await ns_trains.get_disruptions()) if code in x.get("stations", [])]
    except Exception as e:  # noqa: BLE001
        log.warning("NS alerts: сбои не загрузились: %s", e)
        current = []
    await message.answer(
        f"Готово. Если на станции <b>{_h(name)}</b> отменят поезда, случится сбой или начнётся ремонт, "
        "я сразу напишу и подскажу, как доехать (например, автобусом вместо поезда).\n\n"
        + ("Сейчас на этой станции всё спокойно." if not current else _now_line(len(current)))
        + "\n\nУправлять подписками: /trains",
        reply_markup=_manage_kb(subs), parse_mode="HTML")
    for x in current[:3]:
        await message.answer(alert_text(x, name), parse_mode="HTML", disable_web_page_preview=True)
    # Всё текущее человек уже увидел: в фоне повторно не шлём.
    await _mark_sent(user_id, [x["id"] for x in current if x.get("id")])


@router.message(Command("trains"))
async def cmd_trains(message: Message) -> None:
    subs = await _subs(message.from_user.id)
    if not subs:
        await message.answer("Вы пока не следите ни за одной станцией. Выберите свою станцию на сайте и нажмите "
                             "«Уведомления в Telegram»: " + SITE_URL, disable_web_page_preview=True)
        return
    names = ", ".join(_h(s.station_name or s.station_code) for s in subs)
    await message.answer(f"Вы следите за станциями: {names}.\nПри отменах, сбоях и ремонте я напишу сразу.",
                         reply_markup=_manage_kb(subs))


@router.callback_query(F.data.startswith("nsun:"))
async def cb_unsubscribe(call: CallbackQuery) -> None:
    code = call.data.split(":", 1)[1]
    async with get_session() as session:
        await session.execute(delete(NsSubscription).where(
            NsSubscription.user_id == call.from_user.id, NsSubscription.station_code == code))
        await session.commit()
    subs = await _subs(call.from_user.id)
    await call.answer("Подписка отключена")
    text = ("Больше не пишу об этой станции." if not subs else
            "Готово. Остались станции: " + ", ".join(_h(s.station_name or s.station_code) for s in subs) + ".")
    await call.message.edit_text(text, reply_markup=_manage_kb(subs) if subs else None)


async def check_once(bot: Bot) -> int:
    async with get_session() as session:
        subs = list((await session.execute(select(NsSubscription))).scalars())
    if not subs:
        return 0
    items = relevant(await ns_trains.get_disruptions())
    if not items:
        return 0
    by_user: dict[int, list[NsSubscription]] = {}
    for s in subs:
        by_user.setdefault(s.user_id, []).append(s)
    async with get_session() as session:
        sent = {(u, d) for u, d in (await session.execute(select(NsAlertSent.user_id, NsAlertSent.disruption_id)))}
    count = 0
    for user_id, user_subs in by_user.items():
        new_ids = []
        for x in items:
            if not x.get("id") or (user_id, x["id"]) in sent:
                continue
            hit = next((s for s in user_subs if s.station_code in x["stations"]), None)
            if not hit:
                continue
            try:
                await bot.send_message(user_id, alert_text(x, hit.station_name or hit.station_code),
                                       parse_mode="HTML", disable_web_page_preview=True)
                count += 1
            except TelegramForbiddenError:
                async with get_session() as session:
                    await session.execute(delete(NsSubscription).where(NsSubscription.user_id == user_id))
                    await session.commit()
                break
            except Exception as e:  # noqa: BLE001 — один человек не должен ломать рассылку
                log.warning("NS alerts: не отправилось %s: %s", user_id, e)
                continue
            new_ids.append(x["id"])
            await asyncio.sleep(0.05)
        await _mark_sent(user_id, new_ids)
    return count


async def _cleanup() -> None:
    old = (_now() - timedelta(days=30)).replace(tzinfo=None)
    async with get_session() as session:
        await session.execute(delete(NsAlertSent).where(NsAlertSent.created_at < old))
        await session.commit()


async def ns_alerts_loop(bot: Bot) -> None:
    if not ns_trains._key():
        log.info("NS alerts: NS_API_KEY не задан, уведомления выключены")
        return
    await asyncio.sleep(60)
    rounds = 0
    while True:
        try:
            n = await check_once(bot)
            if n:
                log.info("NS alerts: отправлено %s", n)
            rounds += 1
            if rounds % 288 == 0:
                await _cleanup()
        except Exception as e:  # noqa: BLE001
            log.warning("NS alerts: %s", e)
        await asyncio.sleep(CHECK_EVERY)
