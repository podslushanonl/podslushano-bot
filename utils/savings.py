"""Раздел «💶 Сэкономить»: редакционные разборы + ссылки на сравнение и оформление.

Темы: медстраховка (zorgverzekering, сменить можно до 31 декабря) и eSIM для поездок.
Бот объясняет и даёт общие подсказки (не персональный финансовый совет), а сравнение
и оформление происходят у сравнителя или поставщика по ссылке.

Ссылки идут через /go/<ключ>?s=<источник>: так считаем переходы из бота, с сайта и
из Instagram. Партнёрские ссылки задаются переменной SAVINGS_LINKS (JSON
{"ключ": "url"}); пока её нет, ведём на обычные сайты. Если ключ задан там,
ссылка считается партнёрской и показывается пометка об этом.

Deep links: ?start=save, ?start=save_zorg, ?start=save_esim.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import date, datetime, timedelta, timezone

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramForbiddenError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiohttp import web
from sqlalchemy import func, select

import config
from database.db import get_session
from database.models import LinkClick, SavingsReminder

log = logging.getLogger(__name__)
router = Router()

SITE_PAGE = "https://podslushano.nl/save/"
REMIND_MONTH, REMIND_DAY = 12, 12      # напоминание о медстраховке приходит 12 декабря
EIGEN_RISICO = 400                       # обязательный eigen risico 2027
# Пороги дохода для zorgtoeslag 2027 (предварительные, по бюджету; окончательные — в ноябре)
TOESLAG_SINGLE, TOESLAG_PAIR = 43000, 54000

DEFAULT_LINKS = {
    "zorg_compare": ("Сравнить медстраховки", "https://www.zorgwijzer.nl/"),
    "zorg_toeslag": ("Zorgtoeslag: проверить", "https://www.belastingdienst.nl/wps/wcm/connect/nl/zorgtoeslag/zorgtoeslag"),
    "esim_holafly": ("Holafly", "https://esim.holafly.com/"),
    "esim_saily": ("Saily", "https://saily.com/"),
    "esim_airalo": ("Airalo", "https://www.airalo.com/"),
}


def _overrides() -> dict[str, str]:
    try:
        raw = json.loads(os.getenv("SAVINGS_LINKS", "") or "{}")
    except ValueError:
        log.warning("SAVINGS_LINKS: не JSON, используем обычные ссылки")
        return {}
    return {k: v for k, v in raw.items() if k in DEFAULT_LINKS and str(v).startswith("https://")}


def target(key: str) -> str | None:
    if key not in DEFAULT_LINKS:
        return None
    return _overrides().get(key) or DEFAULT_LINKS[key][1]


def is_partner(key: str) -> bool:
    return key in _overrides()


def go_url(key: str, source: str = "bot") -> str:
    """Ссылка со счётчиком переходов (или прямая, если веб-сервер бота не настроен)."""
    base = (config.WEBHOOK_BASE_URL or "").rstrip("/")
    return f"{base}/go/{key}?s={source}" if base else (target(key) or SITE_PAGE)


PARTNER_NOTE = "\n\n<i>Часть ссылок партнёрские: если вы что-то оформите, мы можем получить вознаграждение. Для вас цена та же.</i>"


def _note(keys: list[str]) -> str:
    return PARTNER_NOTE if any(is_partner(k) for k in keys) else ""


# ---------------------------------------------------------------- тексты

MENU_TEXT = (
    "<b>💶 Сэкономить</b>\n\n"
    "Разбираем по-русски, где в Нидерландах переплачивают, и как выбрать выгоднее. "
    "Сравнение и оформление — на сайте сравнителя или поставщика, мы подсказываем, на что смотреть."
)

ZORG_TEXT = (
    "<b>🏥 Медстраховка 2027: как не переплатить</b>\n\n"
    "Сменить страховку на следующий год можно <b>до 31 декабря</b>. Новый страховщик сам расторгнет старый договор.\n\n"
    "<b>Главное за минуту</b>\n"
    "• Базовый пакет (basisverzekering) по закону <b>одинаковый у всех</b>. Сравнивайте цену, тип полиса и допстраховку.\n"
    f"• Eigen risico в 2027 году — <b>€{EIGEN_RISICO}</b>. Его вы платите сами, прежде чем страховка начнёт платить. "
    "Не касается семейного врача (huisarts) и детей до 18.\n"
    "• Дети до 18 застрахованы <b>бесплатно</b> в полисе родителя.\n"
    "• Стоматолог для взрослых и почти вся физиотерапия <b>не входят</b> в базовый пакет: это aanvullende verzekering.\n"
    "• Новые цены страховщики объявляют до 12 ноября, сравнивать лучше после этой даты.\n\n"
    "<b>Типы полиса</b>\n"
    "• <b>Naturapolis</b> — только врачи и больницы с договором, обычно дешевле.\n"
    "• <b>Restitutiepolis</b> — любой врач, дороже.\n"
    "• <b>Budgetpolis</b> — самый дешёвый, но выбор клиник меньше.\n\n"
    "Ответьте на 6 коротких вопросов, и я подскажу, на что смотреть именно вам."
)

ESIM_TEXT = (
    "<b>📶 Интернет в поездке: eSIM</b>\n\n"
    "eSIM — это сим-карта, которую устанавливают в телефон по QR-коду. Без пластика и без похода в магазин, "
    "за 5 минут до вылета.\n\n"
    "<b>Что важно знать</b>\n"
    "• <b>По ЕС она не нужна:</b> ваша голландская сим-карта работает в странах ЕС по домашнему тарифу.\n"
    "• Пригодится за пределами ЕС: Турция, Египет, ОАЭ, Великобритания, США, Грузия, Украина и другие.\n"
    "• Проверьте, что телефон поддерживает eSIM и не привязан к оператору (simlock).\n"
    "• Обычно это только интернет, без номера. Звонить можно через WhatsApp и Telegram.\n"
    "• Устанавливайте дома по Wi-Fi, а включайте по прилёте.\n\n"
    "<b>Сравните цены на свою страну</b> у нескольких сервисов: тарифы на одно направление часто отличаются в разы."
)

QUESTIONS = [
    ("Есть дети до 18 лет?", ("Да", "Нет")),
    ("Нужен стоматолог для взрослых?", ("Да", "Нет")),
    ("Часто ходите к врачам или постоянно принимаете лекарства?", ("Часто", "Редко")),
    ("Важно лечиться у конкретного врача или в конкретной клинике?", ("Да, важно", "Не важно")),
    ("Нужны физиотерапия, очки или линзы?", ("Да", "Нет")),
    (f"Ваш годовой доход (брутто) примерно до €{TOESLAG_SINGLE:,} на одного или до €{TOESLAG_PAIR:,} "
     "вместе с партнёром?".replace(",", " "), ("Да, до", "Больше")),
]


def quiz_hints(answers: str) -> list[str]:
    """answers — строка из 6 символов '1' (первый вариант) / '0' (второй)."""
    kids, dentist, often, own_doctor, extras, low_income = (answers + "000000")[:6]
    out = []
    if kids == "1":
        out.append("Детей до 18 добавьте в свой полис: они застрахованы бесплатно, стоматолог для них уже в базовом пакете.")
    if dentist == "1":
        out.append("Смотрите aanvullende tandartsverzekering. Сравнивайте не только цену, но и лимит в год и процент возмещения.")
    if extras == "1":
        out.append("Физиотерапия, очки и линзы почти не входят в базовый пакет: смотрите aanvullende verzekering "
                   "и сравнивайте, сколько сеансов и какую сумму в год она покрывает.")
    if dentist != "1" and extras != "1":
        out.append("Стоматолог, физиотерапия и очки не нужны — допстраховка, скорее всего, лишняя: базового пакета достаточно.")
    if often == "1":
        out.append(f"Не берите добровольный eigen risico: обязательные €{EIGEN_RISICO}, скорее всего, и так уйдут за год.")
    else:
        out.append(f"Болеете редко и есть запас денег — добровольный eigen risico (до €500 сверху) снижает взнос. "
                   f"Но в плохой год заплатите до €{EIGEN_RISICO + 500} сами.")
    if own_doctor == "1":
        out.append("Нужна свобода выбора — смотрите restitutiepolis или проверьте, есть ли у вашей клиники договор "
                   "со страховщиком (gecontracteerde zorg).")
    else:
        out.append("Если не важно, где лечиться, naturapolis или budgetpolis обычно дешевле. Проверьте, что ближайшая "
                   "больница есть в списке договорных.")
    if low_income == "1":
        out.append("Вам, скорее всего, положена <b>zorgtoeslag</b>: государство возвращает часть взноса каждый месяц. "
                   "Если ещё не получаете, проверьте и подайте заявку на сайте Belastingdienst (кнопка ниже). "
                   "Учитываются и сбережения.")
    out.append("Спросите на работе про коллективную скидку (collectiviteit): многие работодатели её дают.")
    return out


def _kb(rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _url(text: str, key: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, url=go_url(key))


def _cb(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def menu_kb() -> InlineKeyboardMarkup:
    return _kb([[_cb("🏥 Медстраховка 2027", "sv:zorg")], [_cb("📶 eSIM для поездок", "sv:esim")],
                [InlineKeyboardButton(text="🌐 Раздел на сайте", url=SITE_PAGE)], [_cb("☰ Меню", "m:main")]])


def zorg_kb() -> InlineKeyboardMarkup:
    return _kb([[_cb("📝 Ответить на 6 вопросов", "sv:q:")], [_url("🔍 Сравнить цены", "zorg_compare")],
                [_cb("🔔 Напомнить до 31 декабря", "sv:remind")], [_cb("⬅️ Назад", "sv:menu")]])


def esim_kb() -> InlineKeyboardMarkup:
    keys = ["esim_holafly", "esim_saily", "esim_airalo"]
    return _kb([[_url(DEFAULT_LINKS[k][0], k) for k in keys], [_cb("⬅️ Назад", "sv:menu")]])


def question(answers: str) -> tuple[str, InlineKeyboardMarkup]:
    i = len(answers)
    q, (a, b) = QUESTIONS[i]
    return (f"<b>Вопрос {i + 1} из {len(QUESTIONS)}</b>\n\n{q}",
            _kb([[_cb(a, f"sv:q:{answers}1"), _cb(b, f"sv:q:{answers}0")], [_cb("⬅️ Назад", "sv:zorg")]]))


def result(answers: str) -> tuple[str, InlineKeyboardMarkup]:
    hints = "\n".join(f"• {h}" for h in quiz_hints(answers))
    text = (f"<b>На что смотреть вам</b>\n\n{hints}\n\n"
            "Теперь сравните цены на 2027 год и оформите новую страховку до 31 декабря.\n\n"
            "<i>Это общая информация, а не персональный финансовый совет.</i>" + _note(["zorg_compare", "zorg_toeslag"]))
    return text, _kb([[_url("🔍 Сравнить цены", "zorg_compare")], [_url("💶 Проверить zorgtoeslag", "zorg_toeslag")],
                      [_cb("🔔 Напомнить до 31 декабря", "sv:remind")], [_cb("⬅️ Назад", "sv:zorg")]])


def remind_date(today: date) -> date:
    return date(today.year, REMIND_MONTH, REMIND_DAY)


# ---------------------------------------------------------------- бот

async def open_menu(message: Message, state: FSMContext | None = None) -> None:
    if state:
        await state.clear()
    await message.answer(MENU_TEXT, reply_markup=menu_kb(), disable_web_page_preview=True)


async def open_topic(message: Message, topic: str) -> None:
    if topic == "esim":
        await message.answer(ESIM_TEXT + _note(list(k for k in DEFAULT_LINKS if k.startswith("esim"))),
                             reply_markup=esim_kb(), disable_web_page_preview=True)
    else:
        await message.answer(ZORG_TEXT, reply_markup=zorg_kb(), disable_web_page_preview=True)


async def _edit(callback: CallbackQuery, text: str, kb: InlineKeyboardMarkup) -> None:
    try:
        await callback.message.edit_text(text, reply_markup=kb, disable_web_page_preview=True)
    except Exception:  # noqa: BLE001 — старое сообщение не изменить: пришлём новое
        await callback.message.answer(text, reply_markup=kb, disable_web_page_preview=True)


@router.callback_query(F.data == "sv:menu")
async def cb_menu(callback: CallbackQuery) -> None:
    await _edit(callback, MENU_TEXT, menu_kb())
    await callback.answer()


@router.callback_query(F.data == "sv:zorg")
async def cb_zorg(callback: CallbackQuery) -> None:
    await _edit(callback, ZORG_TEXT, zorg_kb())
    await callback.answer()


@router.callback_query(F.data == "sv:esim")
async def cb_esim(callback: CallbackQuery) -> None:
    await _edit(callback, ESIM_TEXT + _note([k for k in DEFAULT_LINKS if k.startswith("esim")]), esim_kb())
    await callback.answer()


@router.callback_query(F.data.regexp(r"^sv:q:[01]{0,6}$"))
async def cb_quiz(callback: CallbackQuery) -> None:
    answers = callback.data[5:]
    text, kb = result(answers) if len(answers) >= len(QUESTIONS) else question(answers)
    await _edit(callback, text, kb)
    await callback.answer()


async def add_reminder(user_id: int, today: date | None = None) -> str:
    today = today or datetime.now(timezone.utc).date()
    when = remind_date(today)
    if today >= when:
        left = (date(today.year, 12, 31) - today).days
        return (f"До 31 декабря осталось {left} дн. Напоминать уже поздно: лучше сравните цены сейчас."
                if left > 0 else "Сегодня последний день, чтобы сменить страховку на следующий год.")
    async with get_session() as session:
        exists = await session.scalar(select(SavingsReminder.id).where(
            SavingsReminder.user_id == user_id, SavingsReminder.topic == "zorg", SavingsReminder.year == today.year))
        if not exists:
            session.add(SavingsReminder(user_id=user_id, topic="zorg", year=today.year))
            await session.commit()
    return f"Готово! Напомню {when.day} декабря, чтобы вы успели сменить страховку до 31 декабря."


@router.callback_query(F.data == "sv:remind")
async def cb_remind(callback: CallbackQuery) -> None:
    await callback.answer(await add_reminder(callback.from_user.id), show_alert=True)


REMINDER_TEXT = (
    "<b>🔔 Медстраховка: осталось меньше трёх недель</b>\n\n"
    "Сменить страховку на 2027 год можно до 31 декабря. Сравните цены и проверьте, "
    "не переплачиваете ли вы. Новый страховщик сам расторгнет старый договор."
)


async def send_due(bot: Bot, today: date | None = None) -> int:
    today = today or datetime.now(timezone.utc).date()
    if today < remind_date(today):
        return 0
    async with get_session() as session:
        rows = list((await session.execute(select(SavingsReminder).where(
            SavingsReminder.year == today.year, SavingsReminder.sent_at.is_(None)).limit(500))).scalars())
        sent = 0
        for r in rows:
            try:
                await bot.send_message(r.user_id, REMINDER_TEXT + _note(["zorg_compare"]), reply_markup=_kb([
                    [_url("🔍 Сравнить цены", "zorg_compare")], [_cb("🏥 Что выбрать: 6 вопросов", "sv:q:")]]),
                    disable_web_page_preview=True)
                sent += 1
            except TelegramForbiddenError:
                pass
            except Exception as e:  # noqa: BLE001 — не застревать на одном пользователе
                log.warning("Сэкономить: напоминание %s не отправлено: %s", r.user_id, e)
            r.sent_at = datetime.now(timezone.utc).replace(tzinfo=None)
            await asyncio.sleep(0.05)
        await session.commit()
    return sent


async def savings_loop(bot: Bot) -> None:
    await asyncio.sleep(120)
    while True:
        try:
            n = await send_due(bot)
            if n:
                log.info("Сэкономить: отправлено напоминаний %s", n)
        except Exception as e:  # noqa: BLE001
            log.warning("Сэкономить: %s", e)
        await asyncio.sleep(3600)


# ---------------------------------------------------------------- переходы

_SRC = re.compile(r"[^a-z0-9_]")


async def go(request: web.Request) -> web.Response:
    key = request.match_info.get("key", "")
    url = target(key)
    if not url:
        raise web.HTTPFound(SITE_PAGE)
    source = _SRC.sub("", (request.query.get("s") or "").lower())[:20] or "direct"
    try:
        async with get_session() as session:
            session.add(LinkClick(key=key, source=source))
            await session.commit()
    except Exception as e:  # noqa: BLE001 — счётчик не должен ломать переход
        log.warning("Сэкономить: клик не записан: %s", e)
    raise web.HTTPFound(url)


async def stats_text(days: int = 30) -> str:
    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
    async with get_session() as session:
        rows = (await session.execute(select(LinkClick.key, LinkClick.source, func.count()).where(
            LinkClick.created_at >= since).group_by(LinkClick.key, LinkClick.source))).all()
        rem = await session.scalar(select(func.count()).select_from(SavingsReminder).where(
            SavingsReminder.year == datetime.now(timezone.utc).year)) or 0
    by_key: dict[str, dict[str, int]] = {}
    for key, source, n in rows:
        by_key.setdefault(key, {})[source] = n
    lines = [f"💶 <b>Сэкономить</b> · переходы за {days} дн.\n"]
    for key, (label, _) in DEFAULT_LINKS.items():
        src = by_key.get(key, {})
        detail = ", ".join(f"{s} {n}" for s, n in sorted(src.items(), key=lambda x: -x[1]))
        mark = " · партнёр" if is_partner(key) else ""
        lines.append(f"• {label}{mark}: <b>{sum(src.values())}</b>" + (f" ({detail})" if detail else ""))
    lines.append(f"\nНапоминаний о медстраховке в этом году: <b>{rem}</b>")
    lines.append("\nСсылки для Instagram и ChatPlace:\n"
                 f"<code>{go_url('zorg_compare', 'ig')}</code>\n"
                 "<code>https://t.me/podslushano_nl_bot?start=save_zorg</code>\n"
                 "<code>https://t.me/podslushano_nl_bot?start=save_esim</code>")
    return "\n".join(lines)


def install_routes(app: web.Application) -> None:
    app.router.add_get("/go/{key}", go)
