"""Админ-панель: управление базой специалистов прямо из бота.

Доступно только администраторам (config.ADMIN_IDS) и только в личке.
Команда /admin открывает панель: добавить специалиста, посмотреть добавленные
вручную, найти и удалить.
"""
import asyncio
import html
import json
import os
import re
import tempfile
from datetime import datetime, timedelta

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramForbiddenError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    Message,
)
from sqlalchemy import func, or_, select

import config
from database.db import get_session
from database.models import BotUser, Meta, Specialist
from keyboards.menus import cancel_menu, main_menu
from states.forms import (
    AdminAddSpecialist,
    AdminAfisha,
    AdminAnnounce,
    AdminBroadcast,
    AdminCircle,
    AdminFind,
    AdminIG,
    AdminPost,
    AdminSetPhoto,
)
from utils.ai import (
    ai_afisha_channel,
    ai_channel_post,
    ai_enabled,
    ai_instagram_carousel,
    ai_post_from_source,
    extract_specialist_query,
    pick_best_photo,
)
from utils.webpage import fetch_page_text
from utils.make import make_enabled, send_to_make
from utils.slides import make_cta_url, make_slide_url, slides_enabled
from utils.places import fetch_place_candidates, fetch_place_photo, places_enabled
from utils.video import ffmpeg_available, make_circle
from utils.season import current_season
from utils.analytics import gather_stats
from utils.reviews import recent_reviews
from utils.geo import CATEGORIES, NEIGHBORS, detect_category, detect_city, province_of_city

router = Router()
# Только админы и только в личке
router.message.filter(F.chat.type == ChatType.PRIVATE, F.from_user.id.in_(config.ADMIN_IDS))
router.callback_query.filter(F.from_user.id.in_(config.ADMIN_IDS))

ONLINE_WORDS = {"онлайн", "online", "онлайн по всей стране", "по всей стране"}


def _not_command(message: Message) -> bool:
    """True, если сообщение НЕ команда. Вешаем на диалоги админки, которые ловят
    свободный текст, чтобы они не «съедали» команды (/invoice и т.п.) — те должны
    срабатывать в любом состоянии."""
    return not (message.text or "").startswith("/")


def _admin_panel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Добавить специалиста", callback_data="admin:add")],
            [InlineKeyboardButton(text="📋 Добавленные вручную", callback_data="admin:list")],
            [InlineKeyboardButton(text="🔎 Найти и удалить", callback_data="admin:find")],
            [InlineKeyboardButton(text="📇 Весь гайд (выгрузка)", callback_data="admin:guideexport")],
            [InlineKeyboardButton(text="📣 Рассылка-анонс", callback_data="admin:broadcast")],
            [InlineKeyboardButton(text="📝 Пост в канал по теме", callback_data="admin:post")],
            [InlineKeyboardButton(text="📸 Instagram-карусель (Make)", callback_data="admin:ig")],
            [InlineKeyboardButton(text="📅 Афиша в канал", callback_data="admin:afisha")],
            [InlineKeyboardButton(text="🆕 В афишу месяца (вручную)", callback_data="admin:afishanew")],
            [InlineKeyboardButton(text="⏳ Старый гайд: дедлайн оплаты", callback_data="admin:legacydeadline")],
            [InlineKeyboardButton(text="📋 Старый гайд: список для рассылки", callback_data="admin:legacyexport")],
            [InlineKeyboardButton(text="📊 Статистика", callback_data="admin:stats")],
            [InlineKeyboardButton(text="⭐ Отзывы", callback_data="admin:reviews")],
        ]
    )


def _del_button(spec_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🗑 Удалить", callback_data=f"admindel:{spec_id}")]]
    )


def _where(sp: Specialist) -> str:
    if sp.is_online:
        return "онлайн"
    return sp.city or sp.province or "—"


@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        "🛠 <b>Админ-панель.</b> Управление базой специалистов.\nЧто делаем?",
        reply_markup=_admin_panel(),
    )


# --- Добавление специалиста (пошагово) --------------------------------------

@router.callback_query(F.data == "admin:add")
async def add_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminAddSpecialist.name)
    await callback.message.answer(
        "➕ <b>Новый специалист.</b>\n\nШаг 1/5. Имя или название?",
        reply_markup=cancel_menu(),
    )
    await callback.answer()


@router.message(AdminAddSpecialist.name, _not_command)
async def add_name(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("Напиши имя/название текстом 🙂")
        return
    await state.update_data(sp_name=message.text.strip())
    await state.set_state(AdminAddSpecialist.category)
    cats = ", ".join(CATEGORIES.keys())
    await message.answer(
        f"Шаг 2/5. Категория? Напиши одну из:\n\n{cats}",
        reply_markup=cancel_menu(),
    )


@router.message(AdminAddSpecialist.category, _not_command)
async def add_category(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    cat = detect_category(text)
    if not cat:
        cat = next((c for c in CATEGORIES if c.lower() == text.lower()), None)
    if not cat:
        await message.answer(
            "Не распознал категорию 🤔 Напиши точнее, например «юрист» или «стоматолог».",
            reply_markup=cancel_menu(),
        )
        return
    await state.update_data(sp_category=cat)
    await state.set_state(AdminAddSpecialist.location)
    await message.answer(
        f"Категория: <b>{cat}</b> ✅\n\n"
        "Шаг 3/5. Город? Или напиши <b>онлайн</b>, если работает по всей стране.",
        reply_markup=cancel_menu(),
    )


@router.message(AdminAddSpecialist.location, _not_command)
async def add_location(message: Message, state: FSMContext) -> None:
    loc = (message.text or "").strip()
    if not loc:
        await message.answer("Напиши город или «онлайн» 🙂")
        return
    if loc.lower() in ONLINE_WORDS:
        await state.update_data(sp_online=True, sp_city="", sp_province="")
    else:
        known = detect_city(loc)  # каноничное имя города + провинция
        if known:
            city, province = known
        else:
            city = loc
            extracted = await extract_specialist_query(
                loc, list(CATEGORIES.keys()), list(NEIGHBORS.keys())
            )
            province = extracted.get("province") or ""
        await state.update_data(sp_online=False, sp_city=city, sp_province=province)
    await state.set_state(AdminAddSpecialist.description)
    await message.answer(
        "Шаг 4/5. Короткое описание услуг? (или «-», чтобы пропустить)",
        reply_markup=cancel_menu(),
    )


@router.message(AdminAddSpecialist.description, _not_command)
async def add_description(message: Message, state: FSMContext) -> None:
    desc = (message.text or "").strip()
    await state.update_data(sp_description=None if desc == "-" else desc)
    await state.set_state(AdminAddSpecialist.contact)
    await message.answer(
        "Шаг 5/5. Контакты? (телефон / @username / email / сайт)",
        reply_markup=cancel_menu(),
    )


@router.message(AdminAddSpecialist.contact, _not_command)
async def add_contact(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("Напиши контакты текстом 🙂")
        return
    data = await state.get_data()
    async with get_session() as session:
        sp = Specialist(
            name=data["sp_name"],
            category=data["sp_category"],
            city=data.get("sp_city", ""),
            province=data.get("sp_province", ""),
            description=data.get("sp_description"),
            contact=message.text.strip(),
            is_online=data.get("sp_online", False),
            status="active",
            source="admin",
        )
        session.add(sp)
        await session.commit()
        await session.refresh(sp)
    await state.clear()
    await message.answer(
        f"✅ Добавлено в гайд (#{sp.id}):\n<b>{html.escape(sp.name)}</b> — "
        f"{html.escape(sp.category)}, {html.escape(_where(sp))}",
        reply_markup=main_menu(),
    )


# --- Список добавленных вручную ---------------------------------------------

@router.callback_query(F.data == "admin:list")
async def list_added(callback: CallbackQuery) -> None:
    await callback.answer()
    async with get_session() as session:
        rows = (
            await session.scalars(
                select(Specialist)
                .where(Specialist.source != "seed")
                .order_by(Specialist.id.desc())
                .limit(30)
            )
        ).all()
    if not rows:
        await callback.message.answer(
            "Пока нет специалистов, добавленных вручную или через само-добавление."
        )
        return
    await callback.message.answer(f"📋 Добавленные ({len(rows)}):")
    for sp in rows:
        await callback.message.answer(
            f"#{sp.id} <b>{html.escape(sp.name)}</b>\n"
            f"{html.escape(sp.category)} · {html.escape(_where(sp))}\n"
            f"{html.escape(sp.contact or '')}",
            reply_markup=_del_button(sp.id),
        )


# --- Поиск и удаление --------------------------------------------------------

@router.callback_query(F.data == "admin:find")
async def find_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminFind.waiting_query)
    await callback.message.answer(
        "Напиши имя или слово для поиска специалиста, которого нужно удалить:",
        reply_markup=cancel_menu(),
    )
    await callback.answer()


@router.message(AdminFind.waiting_query, _not_command)
async def find_run(message: Message, state: FSMContext) -> None:
    # Остаёмся в режиме поиска: можно искать и удалять подряд, выход — «❌ Отмена»
    query = (message.text or "").strip()
    if not query:
        await message.answer("Напиши слово для поиска 🙂", reply_markup=cancel_menu())
        return
    like = f"%{query}%"
    async with get_session() as session:
        rows = (
            await session.scalars(
                select(Specialist)
                .where(
                    or_(
                        Specialist.name.ilike(like),
                        Specialist.category.ilike(like),
                        Specialist.description.ilike(like),
                        Specialist.city.ilike(like),
                    )
                )
                .limit(20)
            )
        ).all()
    if not rows:
        await message.answer(
            "Никого не нашёл. Попробуй другое слово (имя, категория, город) "
            "или нажми «❌ Отмена».",
            reply_markup=cancel_menu(),
        )
        return
    await message.answer(
        f"Нашёл ({len(rows)}). Жми «🗑 Удалить» под нужным. "
        "Можно искать дальше или «❌ Отмена»."
    )
    for sp in rows:
        await message.answer(
            f"#{sp.id} <b>{html.escape(sp.name)}</b>\n"
            f"{html.escape(sp.category)} · {html.escape(_where(sp))}",
            reply_markup=_del_button(sp.id),
        )


@router.callback_query(F.data.startswith("admindel:"))
async def delete_spec(callback: CallbackQuery) -> None:
    spec_id = int(callback.data.split(":", 1)[1])
    async with get_session() as session:
        sp = await session.get(Specialist, spec_id)
        if sp is None:
            await callback.answer("Уже удалено", show_alert=True)
            return
        name = sp.name
        await session.delete(sp)
        await session.commit()
    await callback.message.edit_text(f"🗑 Удалено: {name}")
    await callback.answer("Удалено")


# --- Модерация платных само-добавлений --------------------------------------

@router.callback_query(F.data.startswith("specok:"))
async def spec_publish(callback: CallbackQuery) -> None:
    spec_id = int(callback.data.split(":", 1)[1])
    async with get_session() as session:
        sp = await session.get(Specialist, spec_id)
        if sp is None:
            await callback.answer("Карточка не найдена", show_alert=True)
            return
        sp.status = "active"
        # Платный срок отсчитываем с момента публикации (а не оплаты), чтобы
        # дни на проверке не «съедались». Только для платных карточек.
        if sp.source == "self" and sp.paid_until is not None:
            days = config.plan_info(sp.plan or "year")["days"]
            sp.paid_until = datetime.utcnow() + timedelta(days=days)
            sp.renewal_reminded = False
        await session.commit()
        sub, name = sp.submitter_user_id, sp.name
    await callback.message.edit_text((callback.message.text or "") + "\n\n✅ ОПУБЛИКОВАНО")
    if sub:
        try:
            await callback.bot.send_message(
                sub, f"🎉 Готово! Твоя карточка «{name}» опубликована в гайде. Спасибо!"
            )
        except Exception:  # noqa: BLE001
            pass
    await callback.answer("Опубликовано")


@router.callback_query(F.data.startswith("specno:"))
async def spec_decline(callback: CallbackQuery) -> None:
    spec_id = int(callback.data.split(":", 1)[1])
    async with get_session() as session:
        sp = await session.get(Specialist, spec_id)
        if sp is None:
            await callback.answer("Карточка не найдена", show_alert=True)
            return
        sp.status = "rejected"
        await session.commit()
        sub, name = sp.submitter_user_id, sp.name
    await callback.message.edit_text((callback.message.text or "") + "\n\n❌ ОТКЛОНЕНО")
    if sub:
        try:
            await callback.bot.send_message(
                sub,
                f"К сожалению, карточку «{name}» мы не опубликовали. "
                "Если вы оплачивали размещение — мы вернём средства 🙏\n\n"
                "Напишите нам через /contact или напрямую:\n" + config.support_block(),
                disable_web_page_preview=True,
            )
        except Exception:  # noqa: BLE001
            pass
    await callback.answer("Отклонено")


# --- Анонс в канал с кнопкой «Открыть бота» ---------------------------------

def _open_bot_kb(username: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(
            text="🤖 Открыть бота", url=f"https://t.me/{username}")]]
    )


def _announce_kb(username: str) -> InlineKeyboardMarkup:
    """Кнопки под анонсом: открыть бота + сразу разместить объявление (deep-link)."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🤖 Открыть бота", url=f"https://t.me/{username}")],
        [InlineKeyboardButton(text="📋 Разместить объявление",
                              url=f"https://t.me/{username}?start=board")],
    ])


@router.message(Command("announce"))
async def cmd_announce(message: Message, state: FSMContext) -> None:
    await state.clear()
    if not config.ANNOUNCE_CHANNEL:
        await message.answer(
            "⚠️ Не задан канал для анонса.\n\n"
            "1) Добавь бота в канал как <b>администратора</b> с правами "
            "«Публиковать сообщения» и «Закреплять сообщения».\n"
            "2) Добавь переменную <code>ANNOUNCE_CHANNEL</code> (например "
            "<code>@username_канала</code> или <code>-100…</code>) в Railway."
        )
        return
    await state.set_state(AdminAnnounce.waiting_text)
    await message.answer(
        "Пришли текст анонса (можно с форматированием и эмодзи). "
        "Я добавлю под ним кнопку «🤖 Открыть бота» и опубликую в канал.",
        reply_markup=cancel_menu(),
    )


@router.message(AdminAnnounce.waiting_text, _not_command)
async def announce_text(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("Нужен текст сообщения 🙂")
        return
    await state.update_data(ann_text=message.html_text)
    me = await message.bot.me()
    await message.answer("Вот как будет выглядеть пост 👇")
    await message.answer(
        message.html_text, reply_markup=_announce_kb(me.username),
        disable_web_page_preview=True,
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Опубликовать и закрепить", callback_data="announce:yes"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="announce:no"),
    ]])
    await message.answer(f"Опубликовать в <code>{config.ANNOUNCE_CHANNEL}</code>?", reply_markup=kb)


@router.callback_query(F.data == "announce:no")
async def announce_no(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.answer("Отменил — ничего не опубликовал.", reply_markup=main_menu())
    await callback.answer()


@router.callback_query(F.data == "announce:yes")
async def announce_yes(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await state.clear()
    text = data.get("ann_text")
    if not text:
        await callback.answer("Текст не найден, начни заново: /announce", show_alert=True)
        return
    me = await callback.bot.me()
    try:
        msg = await callback.bot.send_message(
            config.ANNOUNCE_CHANNEL, text,
            reply_markup=_announce_kb(me.username), disable_web_page_preview=True,
        )
        try:
            await callback.bot.pin_chat_message(config.ANNOUNCE_CHANNEL, msg.message_id)
            note = " и закрепил 📌"
        except Exception:  # noqa: BLE001
            note = " (но закрепить не вышло — дай боту право «Закреплять сообщения»)"
        await callback.message.answer(f"✅ Опубликовал в канал{note}", reply_markup=main_menu())
    except Exception as e:  # noqa: BLE001
        await callback.message.answer(
            f"❌ Не получилось опубликовать: {html.escape(str(e))}\n\n"
            "Проверь: бот — администратор канала с правом «Публиковать сообщения», "
            "и <code>ANNOUNCE_CHANNEL</code> указан верно.",
            reply_markup=main_menu(),
        )
    await callback.answer()


# --- Афиша «Чем заняться» в канал -------------------------------------------

AFISHA_CITIES = ["Amsterdam", "Rotterdam", "Den Haag", "Utrecht", "Eindhoven", "Groningen"]


def _afisha_cities_kb() -> InlineKeyboardMarkup:
    btns = [InlineKeyboardButton(text=c, callback_data=f"afpost|{c}") for c in AFISHA_CITIES]
    rows = [btns[i:i + 2] for i in range(0, len(btns), 2)]
    rows.append([InlineKeyboardButton(text="🌍 По всей стране", callback_data="afpost|__all__")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _clean_afisha(text: str) -> str:
    """Готовит ИИ-афишу к публикации в канал: убирает markdown-разделители (---)
    и служебную строку «🔗 Источник», чтобы пост выглядел чисто и нативно."""
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if re.fullmatch(r"[-—–*_=]{3,}", stripped):  # горизонтальная черта markdown
            continue
        if stripped.startswith("🔗 Источник") or stripped.lower().startswith("источник"):
            continue
        lines.append(line)
    out = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    # Срезаем ИИ-вступление («Вот афиша…») — оставляем сразу первое событие
    m = re.search(r"^\s*\d+\.", out, re.MULTILINE)
    if m:
        out = out[m.start():].strip()
    return out


def _afisha_cta(city: str) -> str:
    """Нативный призыв в конце поста — со стрелкой на кнопку «Открыть бота» ниже."""
    if city == "__all__":
        return (
            "🎉 А что интересного именно в твоём городе — спроси у нашего бота. "
            "Свежие события, концерты и идеи на любой день 👇🏼"
        )
    return (
        f"🎉 Больше событий в {city} и других городах — у нашего бота. "
        "Просто напиши свой город 👇🏼"
    )


# Лимит одного сообщения в Telegram — 4096 символов. Держим запас.
_TG_LIMIT = 4096


def _assemble_afisha(title: str, body: str, cta: str) -> str:
    """Склеивает пост и, если он длиннее лимита Telegram, подрезает список по
    границе ЦЕЛЫХ мероприятий (события разделены пустой строкой) — чтобы не
    оставить событие без даты/ссылки. Заголовок и призыв всегда сохраняются."""
    text = f"{title}\n\n{body}\n\n{cta}"
    if len(text) <= _TG_LIMIT:
        return text
    # Доступно под тело (минус заголовок, призыв и разделители)
    budget = _TG_LIMIT - len(title) - len(cta) - len("\n\n\n\n")
    blocks = re.split(r"\n\s*\n", body)  # одно событие = один блок
    kept: list[str] = []
    used = 0
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        add = len(block) + (2 if kept else 0)  # «\n\n» между блоками
        if used + add > budget:
            break
        kept.append(block)
        used += add
    body = "\n\n".join(kept)
    return f"{title}\n\n{body}\n\n{cta}"


@router.message(Command("afishapost"))
async def cmd_afisha_post(message: Message, state: FSMContext) -> None:
    await state.clear()
    if not config.ANNOUNCE_CHANNEL:
        await message.answer(
            "⚠️ Не задан канал для публикации.\n\n"
            "1) Добавь бота в канал как <b>администратора</b> с правами "
            "«Публиковать сообщения» и «Закреплять сообщения».\n"
            "2) Добавь переменную <code>ANNOUNCE_CHANNEL</code> (например "
            "<code>@username_канала</code> или <code>-100…</code>) в Railway."
        )
        return
    if not ai_enabled():
        await message.answer("ИИ-подбор событий сейчас недоступен 🙏 (не настроен ключ).")
        return
    await state.set_state(AdminAfisha.waiting_city)
    s = current_season()
    await message.answer(
        f"{s['emoji']} <b>Афиша в канал «Чем заняться {s['phrase']}».</b>\n\n"
        "По какому городу собрать подборку? Напиши город или выбери 👇\n"
        "Я соберу афишу через ИИ, покажу предпросмотр и спрошу подтверждение.",
        reply_markup=cancel_menu(),
    )
    await message.answer("📍 Города:", reply_markup=_afisha_cities_kb())


@router.callback_query(F.data == "admin:afisha")
async def afisha_btn(callback: CallbackQuery, state: FSMContext) -> None:
    await cmd_afisha_post(callback.message, state)
    await callback.answer()


@router.callback_query(AdminAfisha.waiting_city, F.data.startswith("afpost|"))
async def afisha_city_cb(callback: CallbackQuery, state: FSMContext) -> None:
    city = callback.data.split("|", 1)[1]
    await callback.answer()
    await _afisha_draft(callback.message, state, city)


@router.message(AdminAfisha.waiting_city, _not_command)
async def afisha_city_msg(message: Message, state: FSMContext) -> None:
    city = (message.text or "").strip()
    if not city:
        await message.answer("Напиши город текстом или выбери кнопкой 🙂")
        return
    await _afisha_draft(message, state, city)


async def _afisha_draft(message: Message, state: FSMContext, city: str) -> None:
    """Собирает афишу через ИИ, сохраняет черновик и показывает предпросмотр."""
    s = current_season()
    await message.bot.send_chat_action(message.chat.id, action="typing")
    await message.answer("⏳ Собираю афишу через ИИ, это займёт несколько секунд…")
    result = await ai_afisha_channel(city, s["phrase"])
    if not result:
        await state.clear()
        await message.answer(
            "Не получилось собрать подборку 😔 Попробуй ещё раз (/afishapost) "
            "или другой город.",
            reply_markup=main_menu(),
        )
        return
    where = "по всей стране" if city == "__all__" else city
    title = f"{s['emoji']} Чем заняться {s['phrase']} · {where}"
    text = _assemble_afisha(title, _clean_afisha(result), _afisha_cta(city))
    await state.update_data(afisha_text=text)
    await state.set_state(AdminAfisha.confirm)
    me = await message.bot.me()
    await message.answer("Вот как будет выглядеть пост 👇")
    await message.answer(
        text, reply_markup=_open_bot_kb(me.username),
        parse_mode=None, disable_web_page_preview=True,
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Опубликовать", callback_data="afpost:pub")],
        [InlineKeyboardButton(text="📌 Опубликовать и закрепить", callback_data="afpost:pin")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="afpost:no")],
    ])
    await message.answer(
        f"Опубликовать в <code>{config.ANNOUNCE_CHANNEL}</code>? "
        "Закреплять пост или нет — на твой выбор. "
        "Если событий мало или текст не нравится — жми «Отмена» и собери заново.",
        reply_markup=kb,
    )


@router.callback_query(F.data == "afpost:no")
async def afisha_no(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.answer("Отменил — ничего не опубликовал.", reply_markup=main_menu())
    await callback.answer()


@router.callback_query(F.data.in_({"afpost:pub", "afpost:pin"}))
async def afisha_publish(callback: CallbackQuery, state: FSMContext) -> None:
    pin = callback.data == "afpost:pin"
    data = await state.get_data()
    await state.clear()
    text = data.get("afisha_text")
    if not text:
        await callback.answer("Текст не найден, собери заново: /afishapost", show_alert=True)
        return
    me = await callback.bot.me()
    try:
        msg = await callback.bot.send_message(
            config.ANNOUNCE_CHANNEL, text,
            reply_markup=_open_bot_kb(me.username),
            parse_mode=None, disable_web_page_preview=True,
        )
        note = ""
        if pin:
            try:
                await callback.bot.pin_chat_message(config.ANNOUNCE_CHANNEL, msg.message_id)
                note = " и закрепил 📌"
            except Exception:  # noqa: BLE001
                note = " (но закрепить не вышло — дай боту право «Закреплять сообщения»)"
        await callback.message.answer(f"✅ Опубликовал афишу в канал{note}", reply_markup=main_menu())
    except Exception as e:  # noqa: BLE001
        await callback.message.answer(
            f"❌ Не получилось опубликовать: {html.escape(str(e))}\n\n"
            "Проверь: бот — администратор канала с правом «Публиковать сообщения», "
            "и <code>ANNOUNCE_CHANNEL</code> указан верно.",
            reply_markup=main_menu(),
        )
    await callback.answer()


# --- Пост в канал по теме (ИИ генерит структурный пост) ---------------------

CAPTION_LIMIT = 1024  # лимит подписи к фото в Telegram


async def _send_post(bot, chat_id, text: str, photo_url: str | None, reply_markup=None):
    """Публикует пост: фото + текст (подпись если ≤1024, иначе фото отдельно).

    При кривом HTML от модели падаем на чистый текст. Если фото нет/не
    отправилось — шлём пост обычным сообщением. Возвращает Message поста
    (для закрепления) или None.
    """
    plain = re.sub(r"<[^>]+>", "", text)
    # Лимит подписи Telegram считается по видимому тексту (без HTML-тегов)
    visible_len = len(plain)
    # 1) Фото + подпись одним сообщением (когда текст помещается в подпись)
    if photo_url and visible_len <= CAPTION_LIMIT:
        try:
            return await bot.send_photo(
                chat_id, photo_url, caption=text, reply_markup=reply_markup
            )
        except Exception:  # noqa: BLE001 — кривой HTML → подпись без разметки
            try:
                return await bot.send_photo(
                    chat_id, photo_url, caption=plain, reply_markup=reply_markup
                )
            except Exception:  # noqa: BLE001 — фото не отправилось → текст ниже
                photo_url = None
    # 2) Фото отдельно (длинный текст), затем текст сообщением
    if photo_url:
        try:
            await bot.send_photo(chat_id, photo_url)
        except Exception:  # noqa: BLE001 — не вышло с фото, продолжаем текстом
            pass
    # 3) Текст сообщением (с фолбэком на чистый текст)
    try:
        return await bot.send_message(
            chat_id, text, reply_markup=reply_markup, disable_web_page_preview=True
        )
    except Exception:  # noqa: BLE001
        return await bot.send_message(
            chat_id, plain, reply_markup=reply_markup, disable_web_page_preview=True
        )


_POST_BTN_DEFAULT = "🤖 Открыть бота"
_POST_BTN_OFF = {"off", "нет", "выкл", "-", "—"}


async def _post_button_kb(bot) -> InlineKeyboardMarkup | None:
    """Кнопка под постом в канале (ссылка на бота). Текст настраивается через
    /setpostbutton; «off» — без кнопки."""
    async with get_session() as session:
        m = await session.get(Meta, "post_btn")
    label = (m.value if m else _POST_BTN_DEFAULT).strip()
    if not label or label.lower() in _POST_BTN_OFF:
        return None
    me = await bot.get_me()
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=label, url=f"https://t.me/{me.username}")
    ]])


@router.message(Command("setpostbutton"))
async def set_post_button(message: Message, state: FSMContext) -> None:
    await state.clear()
    arg = (message.text or "").partition(" ")[2].strip()
    if not arg:
        async with get_session() as session:
            m = await session.get(Meta, "post_btn")
        cur = (m.value if m else _POST_BTN_DEFAULT)
        await message.answer(
            "✏️ <b>Кнопка под постом в канале.</b>\n"
            f"Сейчас: <code>{html.escape(cur)}</code>\n\n"
            "Чтобы изменить: <code>/setpostbutton Текст кнопки</code>\n"
            "Убрать кнопку: <code>/setpostbutton off</code>",
            reply_markup=main_menu(),
        )
        return
    async with get_session() as session:
        await session.merge(Meta(key="post_btn", value=arg[:60]))
        await session.commit()
    if arg.lower() in _POST_BTN_OFF:
        await message.answer("Ок, посты буду публиковать без кнопки.", reply_markup=main_menu())
    else:
        await message.answer(f"Готово. Кнопка под постом: <b>{html.escape(arg[:60])}</b>",
                             reply_markup=main_menu())


def _post_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Опубликовать", callback_data="post:pub")],
        [InlineKeyboardButton(text="📌 Опубликовать и закрепить", callback_data="post:pin")],
        [InlineKeyboardButton(text="✏️ Внести правки", callback_data="post:edit")],
        [InlineKeyboardButton(text="🔁 Переписать заново", callback_data="post:redo")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="post:no")],
    ])


@router.message(Command("post"))
async def cmd_post(message: Message, state: FSMContext) -> None:
    await state.clear()
    if not config.ANNOUNCE_CHANNEL:
        await message.answer(
            "⚠️ Не задан канал для публикации (ANNOUNCE_CHANNEL). Добавь бота в канал "
            "админом и задай переменную."
        )
        return
    if not ai_enabled():
        await message.answer("ИИ сейчас недоступен 🙏 (не настроен ключ или нет баланса).")
        return
    await state.set_state(AdminPost.waiting_topic)
    await message.answer(
        "📝 <b>Пост в канал.</b> Напиши тему — или просто пришли <b>ссылку на сайт</b>, "
        "и я сделаю пост по этой странице. Покажу предпросмотр, потом опубликуем.\n\n"
        "<i>Тема: «как получить BSN», «красивые места рядом с Утрехтом осенью», "
        "«голландская кухня: что попробовать».\n"
        "Ссылка: https://nltimes.nl/… — перескажу статью своими словами и дам "
        "ссылку на источник.</i>",
        reply_markup=cancel_menu(),
    )


@router.callback_query(F.data == "admin:post")
async def post_btn(callback: CallbackQuery, state: FSMContext) -> None:
    await cmd_post(callback.message, state)
    await callback.answer()


@router.message(AdminPost.waiting_topic, _not_command)
async def post_topic(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("Напиши тему текстом 🙂")
        return
    await _post_generate(message, state, message.text.strip())


_URL_RE = re.compile(r"https?://[^\s<>]+", re.IGNORECASE)


def _extract_url(text: str) -> str | None:
    """Достаёт первую ссылку из сообщения (или None). Срезает хвостовую пунктуацию."""
    m = _URL_RE.search(text or "")
    if not m:
        return None
    return m.group(0).rstrip(".,);:!?»\"'")


async def _post_generate(message: Message, state: FSMContext, topic: str,
                         base_text: str | None = None, instruction: str | None = None) -> None:
    await state.update_data(post_topic=topic)
    # Правки существующего поста идут по тексту, ссылку повторно не открываем.
    source_url = None if (base_text and instruction) else _extract_url(topic)
    if source_url:
        await message.answer("🔗 Открываю ссылку и читаю страницу…")
        await message.bot.send_chat_action(message.chat.id, action="typing")
        page = await fetch_page_text(source_url)
        if not page:
            await state.clear()
            await message.answer(
                "Не смог открыть эту ссылку или на странице нет текста 😔 "
                "Проверь адрес или пришли тему словами (/post).",
                reply_markup=main_menu(),
            )
            return
        await message.answer("✍️ Пишу пост по странице, это займёт несколько секунд…")
        await message.bot.send_chat_action(message.chat.id, action="typing")
        result = await ai_post_from_source(source_url, page[0], page[1])
        if not result or not result[0]:
            await state.clear()
            await message.answer(
                "Не получилось собрать пост по ссылке 😔 Попробуй ещё раз (/post).",
                reply_markup=main_menu(),
            )
            return
        await _post_preview(message, state, result, topic)
        return
    note = "✏️ Вношу правки…" if instruction else "✍️ Готовлю пост через ИИ, это займёт несколько секунд…"
    await message.answer(note)
    await message.bot.send_chat_action(message.chat.id, action="typing")
    result = await ai_channel_post(topic, base_text=base_text, instruction=instruction)
    if not result or not result[0]:
        await state.clear()
        await message.answer(
            "Не получилось сгенерировать пост 😔 Попробуй ещё раз (/post) или другую тему.",
            reply_markup=main_menu(),
        )
        return
    await _post_preview(message, state, result, topic)


async def _post_preview(message: Message, state: FSMContext,
                        result: tuple[str, str], topic: str) -> None:
    """Показывает предпросмотр поста (с фото) и кнопки публикации/правок.

    Общий финал для постов по теме и по ссылке."""
    text, img_query = result
    photo_url = None
    if places_enabled():
        photo_url = await fetch_place_photo(img_query or topic)
    await state.update_data(post_text=text, post_photo=photo_url)
    await state.set_state(AdminPost.confirm)
    await message.answer("Вот предпросмотр поста 👇")
    await _send_post(message.bot, message.chat.id, text, photo_url,
                     reply_markup=await _post_button_kb(message.bot))
    hint = ""
    if places_enabled() and not photo_url:
        hint = "\n\n⚠️ Фото по теме не нашлось — опубликую без картинки."
    elif not places_enabled():
        hint = ("\n\n💡 Чтобы к постам добавлялись реальные фото мест, задай "
                "переменную <code>GOOGLE_MAPS_API_KEY</code> (Google Places API).")
    await message.answer(
        f"Опубликовать в <code>{config.ANNOUNCE_CHANNEL}</code>? "
        f"Можно переписать заново или отменить.{hint}",
        reply_markup=_post_confirm_kb(),
    )


@router.callback_query(F.data == "post:redo")
async def post_redo(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    topic = data.get("post_topic")
    await callback.answer("Переписываю…")
    if not topic:
        await callback.message.answer("Тема потерялась, начни заново: /post",
                                      reply_markup=main_menu())
        return
    await _post_generate(callback.message, state, topic)


@router.callback_query(F.data == "post:edit")
async def post_edit(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if not data.get("post_text"):
        await callback.answer("Пост потерялся, начни заново: /post", show_alert=True)
        return
    await state.set_state(AdminPost.editing)
    await callback.message.answer(
        "✏️ Напиши, что изменить в посте — я поправлю и покажу заново.\n\n"
        "<i>Например: «сделай короче», «добавь про цены и часы работы», "
        "«убери последний абзац», «больше про детей», «смени заголовок».</i>",
        reply_markup=cancel_menu(),
    )
    await callback.answer()


@router.message(AdminPost.editing, _not_command)
async def post_edit_apply(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("Напиши правку текстом 🙂")
        return
    data = await state.get_data()
    topic = data.get("post_topic", "")
    base_text = data.get("post_text", "")
    if not base_text:
        await state.clear()
        await message.answer("Пост потерялся, начни заново: /post", reply_markup=main_menu())
        return
    await _post_generate(message, state, topic, base_text=base_text,
                         instruction=message.text.strip())


@router.callback_query(F.data == "post:no")
async def post_no(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.answer("Отменил — пост не опубликован.", reply_markup=main_menu())
    await callback.answer()


@router.callback_query(F.data.in_({"post:pub", "post:pin"}))
async def post_publish(callback: CallbackQuery, state: FSMContext) -> None:
    pin = callback.data == "post:pin"
    data = await state.get_data()
    await state.clear()
    text = data.get("post_text")
    photo_url = data.get("post_photo")
    if not text:
        await callback.answer("Текст не найден, начни заново: /post", show_alert=True)
        return
    try:
        msg = await _send_post(callback.bot, config.ANNOUNCE_CHANNEL, text, photo_url,
                               reply_markup=await _post_button_kb(callback.bot))
        note = ""
        if pin and msg:
            try:
                await callback.bot.pin_chat_message(config.ANNOUNCE_CHANNEL, msg.message_id)
                note = " и закрепил 📌"
            except Exception:  # noqa: BLE001
                note = " (но закрепить не вышло — дай боту право «Закреплять сообщения»)"
        await callback.message.answer(f"✅ Опубликовал пост в канал{note}", reply_markup=main_menu())
    except Exception as e:  # noqa: BLE001
        await callback.message.answer(
            f"❌ Не получилось опубликовать: {html.escape(str(e))}\n\n"
            "Проверь, что бот — админ канала с правом «Публиковать сообщения».",
            reply_markup=main_menu(),
        )
    await callback.answer()


# --- Видео-кружок (video note) в канал --------------------------------------

def _circle_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Опубликовать в канал", callback_data="circle:pub")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="circle:no")],
    ])


@router.message(Command("circle"))
async def cmd_circle(message: Message, state: FSMContext) -> None:
    await state.clear()
    if not config.ANNOUNCE_CHANNEL:
        await message.answer("⚠️ Не задан канал (ANNOUNCE_CHANNEL).")
        return
    if not ffmpeg_available():
        await message.answer("⚠️ ffmpeg на сервере недоступен — кружок не сделать. "
                             "Нужен передеплой образа с ffmpeg.")
        return
    await state.set_state(AdminCircle.waiting_video)
    await message.answer(
        "🎥 Пришли видео (до 60 сек и до 20 МБ). Я обрежу его в круг и опубликую "
        "кружком в канал. Можно прислать и готовый кружок — опубликую как есть.",
        reply_markup=cancel_menu(),
    )


async def _circle_preview(message: Message, state: FSMContext,
                          note_id: str | None, path: str | None) -> None:
    await state.set_state(AdminCircle.confirm)
    await state.update_data(circle_note_id=note_id, circle_path=path)
    try:
        if note_id:
            await message.bot.send_video_note(message.chat.id, note_id)
        else:
            await message.bot.send_video_note(message.chat.id, FSInputFile(path), length=480)
    except Exception as e:  # noqa: BLE001
        await state.clear()
        await message.answer(f"Не вышло показать кружок: {html.escape(str(e))}",
                             reply_markup=main_menu())
        return
    await message.answer(
        f"Опубликовать кружок в <code>{config.ANNOUNCE_CHANNEL}</code>?",
        reply_markup=_circle_kb(),
    )


@router.message(AdminCircle.waiting_video, F.video_note)
async def circle_from_note(message: Message, state: FSMContext) -> None:
    await _circle_preview(message, state, message.video_note.file_id, None)


@router.message(AdminCircle.waiting_video, F.video | F.document)
async def circle_from_video(message: Message, state: FSMContext) -> None:
    vid = message.video
    if not vid and message.document and (message.document.mime_type or "").startswith("video"):
        vid = message.document
    if not vid:
        await message.answer("Пришли именно видео 🙂")
        return
    if (vid.file_size or 0) > 20 * 1024 * 1024:
        await message.answer("Видео больше 20 МБ — бот не может его скачать. "
                             "Пришли покороче или полегче (до 20 МБ).")
        return
    await message.answer("⏳ Делаю кружок, секунду…")
    await message.bot.send_chat_action(message.chat.id, action="upload_video_note")
    tmpdir = tempfile.mkdtemp(prefix="circle_")
    in_path = os.path.join(tmpdir, "in.mp4")
    out_path = os.path.join(tmpdir, "out.mp4")
    try:
        await message.bot.download(vid, destination=in_path)
    except Exception as e:  # noqa: BLE001
        await message.answer(f"Не смог скачать видео: {html.escape(str(e))}",
                             reply_markup=main_menu())
        await state.clear()
        return
    ok = await make_circle(in_path, out_path)
    if not ok:
        await state.clear()
        await message.answer("Не получилось обработать видео 😔 Попробуй другое "
                             "(mp4, до 60 сек).", reply_markup=main_menu())
        return
    await _circle_preview(message, state, None, out_path)


@router.callback_query(F.data == "circle:no")
async def circle_no(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.answer("Отменил — кружок не опубликован.", reply_markup=main_menu())
    await callback.answer()


@router.callback_query(F.data == "circle:pub")
async def circle_pub(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await state.clear()
    note_id = data.get("circle_note_id")
    path = data.get("circle_path")
    try:
        if note_id:
            await callback.bot.send_video_note(config.ANNOUNCE_CHANNEL, note_id)
        elif path and os.path.exists(path):
            await callback.bot.send_video_note(config.ANNOUNCE_CHANNEL, FSInputFile(path), length=480)
        else:
            await callback.answer("Видео потерялось, начни заново: /circle", show_alert=True)
            return
        await callback.message.answer("✅ Опубликовал кружок в канал.", reply_markup=main_menu())
    except Exception as e:  # noqa: BLE001
        await callback.message.answer(
            f"❌ Не получилось опубликовать: {html.escape(str(e))}\n\n"
            "Проверь, что бот — админ канала с правом публикации.",
            reply_markup=main_menu(),
        )
    await callback.answer()


# --- Instagram-карусель через Make ------------------------------------------

def _ig_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Отправить в Make (опубликовать)", callback_data="ig:send")],
        [InlineKeyboardButton(text="✏️ Внести правки", callback_data="ig:edit")],
        [InlineKeyboardButton(text="🔁 Переписать заново", callback_data="ig:redo")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="ig:no")],
    ])


@router.message(Command("ig"))
async def cmd_ig(message: Message, state: FSMContext) -> None:
    await state.clear()
    if not make_enabled():
        await message.answer(
            "⚠️ Не задан вебхук Make (<code>MAKE_WEBHOOK_URL</code>). Добавь переменную "
            "с адресом своего вебхука Make — туда бот будет слать карусели для Instagram."
        )
        return
    if not ai_enabled():
        await message.answer("ИИ сейчас недоступен 🙏 (не настроен ключ или нет баланса).")
        return
    if not places_enabled():
        await message.answer(
            "⚠️ Не задан <code>GOOGLE_MAPS_API_KEY</code> (Google Places) — слайды уйдут без "
            "реальных фото. Лучше сначала задать ключ."
        )
    if not slides_enabled():
        await message.answer(
            "⚠️ Слайды уйдут как сырые фото БЕЗ текста (нет шрифтов или не задан "
            "<code>WEBHOOK_BASE_URL</code> для отдачи готовых картинок)."
        )
    await state.set_state(AdminIG.waiting_topic)
    await message.answer(
        "📸 <b>Instagram-карусель.</b> Напиши тему — я подготовлю заголовок-хук, "
        "слайды с текстом и подберу к каждому реальное фото (4:5), покажу "
        "предпросмотр, потом отправлю в Make на публикацию.\n\n"
        "<i>Например: «5 ошибок новичков с налогами в NL», «как получить BSN», "
        "«красивые осенние места рядом с Утрехтом», «голландская кухня: что попробовать».</i>",
        reply_markup=cancel_menu(),
    )


@router.callback_query(F.data == "admin:ig")
async def ig_btn(callback: CallbackQuery, state: FSMContext) -> None:
    await cmd_ig(callback.message, state)
    await callback.answer()


@router.message(AdminIG.waiting_topic, _not_command)
async def ig_topic(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("Напиши тему текстом 🙂")
        return
    await _ig_generate(message, state, message.text.strip())


def _nl_query(q: str) -> str:
    """Привязывает запрос фото к Нидерландам, чтобы сток не отдавал чужие страны
    (горы, тропики и т.п.) для абстрактных тем."""
    q = (q or "").strip()
    low = q.lower()
    if any(w in low for w in ("netherland", "holland", "dutch")):
        return q
    return f"{q} Netherlands".strip()


async def _ig_build_payload(topic: str, data: dict, avoid: set[str] | None = None) -> dict:
    """Собирает JSON для Make: подбирает реальное фото (4:5) к каждому слайду и
    рисует готовый слайд (фото + текст 1080×1350).

    image_url — ГОТОВЫЙ слайд (если рендер доступен), сырое фото — в photo_url.
    avoid — фото из прошлой версии (чтобы при правках реально подменились новыми)."""
    used: set[str] = set(avoid or set())

    async def pick(query: str, desc: str) -> str:
        """Кандидаты из всех стоков (+ вариант «с воздуха») → ИИ-vision выбирает
        самый подходящий и интересный кадр. Без повторов между слайдами."""
        if not places_enabled():
            return ""
        base = await fetch_place_candidates(_nl_query(query or topic), "portrait", 6)
        aerial = await fetch_place_candidates(
            _nl_query(f"{query or topic} aerial drone view"), "portrait", 4)
        pool, seen = [], set()
        for u in base + aerial:
            if u and u not in seen and u not in used:
                seen.add(u)
                pool.append(u)
        if not pool:
            return ""
        chosen = await pick_best_photo(desc, pool[:8]) or pool[0]
        used.add(chosen)
        return chosen

    headline = data.get("headline", "")
    cover_q = data.get("cover_img_query") or ""
    cover_photo = await pick(cover_q, f"{headline}. {topic}")
    cover_slide = await make_slide_url(cover_photo, headline, "", "cover") or cover_photo

    slides_out = [{
        "index": 1,
        "role": "cover",
        "title": headline,
        "body": "",
        "image_url": cover_slide,
        "photo_url": cover_photo,
        "img_query": cover_q,
    }]
    for i, s in enumerate(data.get("slides", []), start=2):
        q = (s.get("img_query") or "").strip()
        title = (s.get("title") or "").strip()
        body = (s.get("body") or "").strip()
        photo = await pick(q, f"{title}. {body}")
        slide = await make_slide_url(photo, title, body, "content") or photo
        slides_out.append({
            "index": i,
            "role": "content",
            "title": title,
            "body": body,
            "image_url": slide,
            "photo_url": photo,
            "img_query": q,
        })

    # Финальный слайд — фиксированный фирменный CTA с ПОСТОЯННЫМ фоном
    # (assets/cta_bg.jpg), а не случайным авто-подбором.
    cta_slide = await make_cta_url(None) or ""
    slides_out.append({
        "index": len(slides_out) + 1,
        "role": "cta",
        "title": "Фирменный CTA (подписка)",
        "body": "",
        "image_url": cta_slide,
        "photo_url": "",
        "img_query": "",
    })

    hashtag = data.get("hashtag", "")
    hashtags = [hashtag] if hashtag else []
    urls = [s["image_url"] for s in slides_out if s["image_url"]]
    return {
        "type": data.get("type", "carousel"),
        "topic": topic,
        "headline": data.get("headline", ""),
        "caption": data.get("caption", ""),
        "hashtags": hashtags,
        "hashtags_text": hashtag,
        "slides": slides_out,
        "slides_count": len(slides_out),
        "image_urls": urls,
        # Для модуля Instagram в Make (поле Files: массив объектов {image_url, media_type})
        "files": [{"image_url": u, "media_type": "IMAGE"} for u in urls],
    }


def _ig_preview_text(payload: dict) -> str:
    kind = "карусель" if payload["type"] == "carousel" else "одиночный пост"
    found = len(payload["image_urls"])
    lines = [
        f"📸 <b>Instagram — {kind}</b> ({payload['slides_count']} слайд., фото найдено: {found})",
        "",
        f"<b>Слайд 1 (обложка):</b> {html.escape(payload['headline'])}",
    ]
    for s in payload["slides"][1:]:
        title = html.escape(s["title"]) if s["title"] else ""
        body = html.escape(s["body"]) if s["body"] else ""
        label = "CTA" if s.get("role") == "cta" else f"Слайд {s['index']}"
        piece = f"<b>{label}:</b>"
        if title:
            piece += f" {title}"
        if body:
            piece += f"\n{body}"
        lines.append(piece)
    lines.append("")
    lines.append("<b>Подпись:</b>")
    lines.append(html.escape(payload.get("caption", "")))
    if payload.get("hashtags_text"):
        lines.append("")
        lines.append(html.escape(payload["hashtags_text"]))
    return "\n".join(lines)


async def _ig_generate(message: Message, state: FSMContext, topic: str,
                       instruction: str | None = None) -> None:
    await state.update_data(ig_topic=topic)
    base_json = (await state.get_data()).get("ig_data") if instruction else None
    note = "✏️ Вношу правки и пересобираю карусель…" if instruction else \
        "✍️ Готовлю карусель: текст, подбор и ИИ-проверка фото — займёт минуту-полторы…"
    await message.answer(note)
    await message.bot.send_chat_action(message.chat.id, action="typing")
    data = await ai_instagram_carousel(topic, base_json=base_json, instruction=instruction)
    if not data:
        await state.clear()
        await message.answer(
            "Не получилось сгенерировать карусель 😔 Попробуй ещё раз (/ig) или другую тему.",
            reply_markup=main_menu(),
        )
        return
    # при правках исключаем фото прошлой версии, чтобы они реально сменились
    avoid = set((await state.get_data()).get("ig_used_photos") or []) if instruction else None
    payload = await _ig_build_payload(topic, data, avoid=avoid)
    photos_now = [s.get("photo_url") for s in payload["slides"] if s.get("photo_url")]
    await state.update_data(ig_payload=payload, ig_data=json.dumps(data, ensure_ascii=False),
                            ig_used_photos=photos_now)
    await state.set_state(AdminIG.confirm)
    # Превью: показываем ВСЕ фото слайдов альбомом (по порядку), затем текст
    urls = payload["image_urls"][:10]  # альбом Telegram — максимум 10 фото
    preview = _ig_preview_text(payload)
    if len(urls) >= 2:
        media = [
            InputMediaPhoto(media=u, caption=("🖼 Фото слайдов по порядку" if i == 0 else None))
            for i, u in enumerate(urls)
        ]
        try:
            await message.bot.send_media_group(message.chat.id, media=media)
        except Exception:  # noqa: BLE001 — битый URL ломает весь альбом → шлём хотя бы обложку
            if urls:
                try:
                    await message.bot.send_photo(message.chat.id, urls[0], caption="🖼 Обложка")
                except Exception:  # noqa: BLE001
                    pass
    elif urls:
        try:
            await message.bot.send_photo(message.chat.id, urls[0], caption="🖼 Обложка")
        except Exception:  # noqa: BLE001
            pass
    # Текст может быть длинным — шлём отдельным сообщением (с фолбэком без HTML)
    try:
        await message.answer(preview, disable_web_page_preview=True)
    except Exception:  # noqa: BLE001
        await message.answer(re.sub(r"<[^>]+>", "", preview), disable_web_page_preview=True)
    note = ""
    if places_enabled() and len(payload["image_urls"]) < payload["slides_count"]:
        note = "\n\n⚠️ К части слайдов фото не нашлось — Make подставит свой фон/шаблон."
    await message.answer(
        "Отправить в Make на публикацию в Instagram?" + note,
        reply_markup=_ig_confirm_kb(),
    )


@router.callback_query(F.data == "ig:redo")
async def ig_redo(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    topic = data.get("ig_topic")
    await callback.answer("Переписываю…")
    if not topic:
        await callback.message.answer("Тема потерялась, начни заново: /ig",
                                      reply_markup=main_menu())
        return
    await _ig_generate(callback.message, state, topic)


@router.callback_query(F.data == "ig:edit")
async def ig_edit(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if not data.get("ig_data"):
        await callback.answer("Карусель потерялась, начни заново: /ig", show_alert=True)
        return
    await state.set_state(AdminIG.editing)
    await callback.message.answer(
        "✏️ Напиши, что изменить в тексте карусели — поправлю и пересоберу.\n\n"
        "<i>Например: «исправь грамматику и убери тире», «слайд 3 перепиши проще», "
        "«заголовок короче», «добавь слайд про цены», «тон живее».</i>",
        reply_markup=cancel_menu(),
    )
    await callback.answer()


@router.message(AdminIG.editing, _not_command)
async def ig_edit_apply(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("Напиши правку текстом 🙂")
        return
    data = await state.get_data()
    topic = data.get("ig_topic", "")
    if not data.get("ig_data"):
        await state.clear()
        await message.answer("Карусель потерялась, начни заново: /ig", reply_markup=main_menu())
        return
    await _ig_generate(message, state, topic, instruction=message.text.strip())


@router.callback_query(F.data == "ig:no")
async def ig_no(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.answer("Отменил — в Instagram ничего не ушло.", reply_markup=main_menu())
    await callback.answer()


def _ig_sent_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔁 Отправить ещё раз", callback_data="ig:send")],
        [InlineKeyboardButton(text="✅ Готово", callback_data="ig:done")],
    ])


@router.callback_query(F.data == "ig:done")
async def ig_done(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.answer("Готово 👍", reply_markup=main_menu())
    await callback.answer()


@router.callback_query(F.data == "ig:send")
async def ig_send(callback: CallbackQuery, state: FSMContext) -> None:
    # НЕ очищаем состояние: если Make/Instagram не опубликовал — можно отправить ещё раз
    data = await state.get_data()
    payload = data.get("ig_payload")
    if not payload:
        await callback.answer("Данные не найдены, начни заново: /ig", show_alert=True)
        return
    if not payload.get("image_urls"):
        await callback.answer("Нет готовых картинок — нечего публиковать. Перегенерируй /ig",
                              show_alert=True)
        return
    await callback.answer("Отправляю в Make…")
    ok, detail = await send_to_make(payload)
    if ok:
        await callback.message.answer(
            "✅ Отправил карусель в Make — он соберёт слайды и опубликует в Instagram.\n"
            "<i>Если пост не появился в Instagram через пару минут — нажми «Отправить ещё раз».</i>",
            reply_markup=_ig_sent_kb(),
        )
    else:
        await callback.message.answer(
            "❌ Не получилось отправить в Make.\n"
            f"<b>Причина:</b> {html.escape(detail or 'неизвестно')}\n\n"
            "Проверь, что <code>MAKE_WEBHOOK_URL</code> задан верно и сценарий включён, "
            "потом нажми «Отправить ещё раз».",
            reply_markup=_ig_sent_kb(),
        )


# --- Статистика -------------------------------------------------------------

@router.message(Command("stats"))
async def cmd_stats(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(await gather_stats(), reply_markup=main_menu())


@router.callback_query(F.data == "admin:stats")
async def stats_btn(callback: CallbackQuery) -> None:
    await callback.message.answer(await gather_stats())
    await callback.answer()


@router.message(Command("findspec"))
async def cmd_findspec(message: Message, state: FSMContext) -> None:
    """/findspec <имя> — показать данные специалиста(ов): контакт, фото, дубликаты."""
    await state.clear()
    q = (message.text or "").partition(" ")[2].strip()
    if not q:
        await message.answer("Использование: <code>/findspec имя</code>")
        return
    ql = q.casefold()
    async with get_session() as session:
        rows = (await session.scalars(select(Specialist))).all()
    found = [s for s in rows if ql in (s.name or "").casefold()][:10]
    if not found:
        await message.answer(f"Не нашёл специалиста по «{html.escape(q)}».")
        return
    blocks = [f"🔎 Найдено: <b>{len(found)}</b>"
              + (" ⚠️ есть дубликаты" if len(found) > 1 else "")]
    for s in found:
        where = "онлайн" if s.is_online else (s.city or s.province or "—")
        paid = f"\n• оплачено до: {s.paid_until:%d.%m.%Y}" if s.paid_until else ""
        blocks.append(
            f"\n<b>#{s.id} {html.escape(s.name)}</b>"
            f"\n• категория: {html.escape(s.category)}"
            f"\n• где: {html.escape(where)}"
            f"\n• контакт: {html.escape(s.contact or '—')}"
            f"\n• статус: {s.status} · источник: {s.source} · "
            f"премиум: {'да' if s.is_premium else 'нет'}"
            f"\n• фото: {'есть' if s.photo_file_id else 'нет'}" + paid
        )
    await message.answer("\n".join(blocks), disable_web_page_preview=True)


# --- Отзывы: кто и что оставил ----------------------------------------------

def _fmt_review(r: dict) -> str:
    stars = "⭐" * r["rating"]
    name = html.escape(r.get("first_name") or "—")
    who = f"@{r['username']}" if r.get("username") else f"id <code>{r['user_id']}</code>"
    when = r["created_at"].strftime("%d.%m.%Y") if r.get("created_at") else ""
    head = f"{stars} <b>{html.escape(r['spec_name'])}</b>"
    meta = f"\n👤 {name} ({who})" + (f" · {when}" if when else "")
    text = r.get("text")
    body = f"\n<i>«{html.escape(text[:300])}»</i>" if text else "\n<i>(без текста, только оценка)</i>"
    return head + meta + body


async def _reviews_text() -> str:
    items = await recent_reviews(12)
    if not items:
        return "⭐ Отзывов пока нет."
    return (
        "⭐ <b>Последние отзывы</b> (до 12)\n\n"
        + "\n\n".join(_fmt_review(r) for r in items)
    )


@router.message(Command("reviews"))
async def cmd_reviews(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        await _reviews_text(), reply_markup=main_menu(), disable_web_page_preview=True
    )


@router.callback_query(F.data == "admin:reviews")
async def reviews_btn(callback: CallbackQuery) -> None:
    await callback.message.answer(await _reviews_text(), disable_web_page_preview=True)
    await callback.answer()


@router.message(Command("invoice"))
async def cmd_invoice(message: Message, state: FSMContext) -> None:
    """/invoice <id> [email] — (пере)отправить счёт по специалисту."""
    await state.clear()
    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        # Покажем кандидатов с сохранённым e-mail, чтобы было откуда взять ID
        async with get_session() as session:
            rows = (await session.execute(
                select(Specialist)
                .where(Specialist.invoice_email.isnot(None))
                .order_by(Specialist.id.desc()).limit(10)
            )).scalars().all()
        if rows:
            lines = [f"#{s.id} — {html.escape(s.name)} — {html.escape(s.invoice_email)}"
                     for s in rows]
            await message.answer(
                "Кому дослать счёт? Скопируй нужный номер и отправь, напр. "
                f"<code>/invoice {rows[0].id}</code>\n\n" + "\n".join(lines)
            )
        else:
            await message.answer("Пока нет специалистов с сохранённым e-mail для счёта.\n"
                                 "Использование: <code>/invoice ID [email]</code>")
        return
    if not config.invoice_enabled():
        await message.answer("⚠️ Resend не настроен: задай RESEND_API_KEY и "
                             "INVOICE_FROM_EMAIL в переменных окружения.")
        return
    spec_id = int(parts[1])
    async with get_session() as session:
        sp = await session.get(Specialist, spec_id)
        if sp is None:
            await message.answer(f"Специалист #{spec_id} не найден.")
            return
        to_email = parts[2] if len(parts) > 2 else (sp.invoice_email or "")
        name, plan = sp.name, sp.plan or "year"
    if not to_email:
        await message.answer("У этого специалиста не сохранён e-mail. "
                             "Укажи вручную: <code>/invoice ID email</code>")
        return
    info = config.plan_info(plan)
    from utils.invoices import send_invoice
    desc = f"Vermelding in Podslushano-gids: {name} ({info['title']})"
    ok, detail = await send_invoice(to_email, name, desc, info["price"])
    if ok:
        await message.answer(f"🧾 Счёт отправлен на {to_email}.")
    else:
        await message.answer(f"❌ Не удалось отправить счёт.\nПричина: {html.escape(detail)}")


# --- Рассылка-анонс ---------------------------------------------------------

async def _users_count() -> int:
    async with get_session() as session:
        return await session.scalar(
            select(func.count()).select_from(BotUser).where(BotUser.is_blocked.is_(False))
        ) or 0


@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message, state: FSMContext) -> None:
    await _broadcast_start(message, state)


@router.callback_query(F.data == "admin:broadcast")
async def broadcast_btn(callback: CallbackQuery, state: FSMContext) -> None:
    await _broadcast_start(callback.message, state)
    await callback.answer()


async def _broadcast_start(message: Message, state: FSMContext) -> None:
    await state.set_state(AdminBroadcast.waiting_message)
    count = await _users_count()
    await message.answer(
        f"📣 <b>Рассылка-анонс</b> для {count} пользователей.\n\n"
        "Пришли сообщение, которое нужно разослать — текст, фото, видео или с кнопкой-ссылкой. "
        "Я покажу предпросмотр и спрошу подтверждение.",
        reply_markup=cancel_menu(),
    )


@router.message(AdminBroadcast.waiting_message, _not_command)
async def broadcast_preview(message: Message, state: FSMContext) -> None:
    await state.update_data(bc_chat=message.chat.id, bc_msg=message.message_id)
    count = await _users_count()
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"✅ Отправить всем ({count})", callback_data="bcast:yes")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="bcast:no")],
        ]
    )
    await message.answer(
        "👆 Вот так выглядит сообщение. Разослать его всем "
        f"{count} пользователям?",
        reply_markup=kb,
    )


@router.callback_query(F.data == "bcast:no")
async def broadcast_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("Рассылка отменена 👌", reply_markup=main_menu())
    await callback.answer()


@router.callback_query(F.data == "bcast:yes")
async def broadcast_send(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await state.clear()
    src_chat, src_msg = data.get("bc_chat"), data.get("bc_msg")
    if not src_chat or not src_msg:
        await callback.answer("Сообщение потерялось, начни заново", show_alert=True)
        return
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        "🚀 Рассылка запущена! Пришлю итог, когда закончу.", reply_markup=main_menu()
    )
    asyncio.create_task(
        _do_broadcast(callback.bot, src_chat, src_msg, callback.from_user.id)
    )
    await callback.answer()


async def _do_broadcast(bot, src_chat: int, src_msg: int, admin_id: int) -> None:
    async with get_session() as session:
        user_ids = (
            await session.scalars(select(BotUser.user_id).where(BotUser.is_blocked.is_(False)))
        ).all()
    sent = 0
    failed = 0
    for uid in user_ids:
        try:
            await bot.copy_message(uid, src_chat, src_msg)
            sent += 1
        except TelegramForbiddenError:
            failed += 1
            async with get_session() as session:  # бот заблокирован — помечаем
                u = await session.get(BotUser, uid)
                if u:
                    u.is_blocked = True
                    await session.commit()
        except Exception:  # noqa: BLE001
            failed += 1
        await asyncio.sleep(0.05)  # ~20 сообщений/сек — в пределах лимитов Telegram
    try:
        await bot.send_message(
            admin_id,
            f"✅ Рассылка завершена.\nДоставлено: {sent}\nНе доставлено: {failed}",
        )
    except Exception:  # noqa: BLE001
        pass


# --- Старый бессрочный гайд: дедлайн оплаты и выгрузка для рассылки ----------

@router.message(Command("legacy_deadline"))
async def cmd_legacy_deadline(message: Message) -> None:
    await _legacy_set_deadline(message)


@router.message(Command("setcontact"))
async def cmd_setcontact(message: Message) -> None:
    """Сменить контакты карточки без удаления (отзывы и оплата сохраняются).
    /setcontact ID  — показать текущий контакт.
    /setcontact ID новый контакт  — заменить."""
    from database.models import Review
    from utils.contact_links import parse_contact_links
    from utils.reviews import specialist_key

    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer(
            "Использование:\n"
            "<code>/setcontact ID</code> — показать текущий контакт\n"
            "<code>/setcontact ID новый контакт</code> — заменить\n\n"
            "Пример: <code>/setcontact 220 https://site.com · instagram: @user · +31 6 12345678</code>\n"
            "Контакты разделяй « · ». ID — из CSV (/legacy_export) или ссылки claim_&lt;ID&gt;.",
            reply_markup=main_menu(),
        )
        return
    sid = int(parts[1])
    async with get_session() as session:
        sp = await session.get(Specialist, sid)
        if sp is None:
            await message.answer(f"Карточка #{sid} не найдена 🤔")
            return
        if len(parts) < 3:
            await message.answer(
                f"Карточка «{html.escape(sp.name)}» (#{sid}).\n\nТекущий контакт:\n"
                f"<code>{html.escape(sp.contact or '—')}</code>\n\n"
                f"Чтобы заменить — пришли:\n<code>/setcontact {sid} новый контакт</code>"
            )
            return
        new_contact = parts[2].strip()
        old, name = sp.contact, sp.name
        # Переносим отзывы на новый ключ (он завязан на имя+контакт)
        old_key, new_key = specialist_key(name, old), specialist_key(name, new_contact)
        if old_key != new_key:
            revs = (await session.scalars(select(Review).where(Review.spec_key == old_key))).all()
            for r in revs:
                r.spec_key = new_key
        sp.contact = new_contact
        await session.commit()
    links = parse_contact_links(new_contact)
    link_lines = "\n".join(f"• {l['label']} → {l['url']}" for l in links) or "— ссылки не распознаны (проверь формат)"
    await message.answer(
        f"✅ Контакт карточки «{html.escape(name)}» (#{sid}) обновлён.\n\n"
        f"Было: <code>{html.escape(old or '—')}</code>\n"
        f"Стало: <code>{html.escape(new_contact)}</code>\n\n"
        f"Кнопки будут такие:\n{link_lines}",
        reply_markup=main_menu(),
    )


@router.message(Command("premium"))
async def cmd_premium(message: Message) -> None:
    """Включить/выключить премиум-размещение карточки (выше в выдаче + значок 🌟).
    Использование: /premium ID on|off"""
    parts = (message.text or "").split()
    flag = parts[2].lower() if len(parts) >= 3 else ""
    if len(parts) < 3 or not parts[1].isdigit() or flag not in ("on", "off", "вкл", "выкл"):
        await message.answer(
            "Использование: <code>/premium ID on|off</code>\n"
            "Например: <code>/premium 220 on</code> — карточка показывается выше "
            "остальных и со значком 🌟 (в боте и на сайте).",
            reply_markup=main_menu(),
        )
        return
    sid = int(parts[1])
    on = flag in ("on", "вкл")
    async with get_session() as session:
        sp = await session.get(Specialist, sid)
        if sp is None:
            await message.answer(f"Карточка #{sid} не найдена 🤔")
            return
        sp.is_premium = on
        name = sp.name
        await session.commit()
    await message.answer(
        f"{'🌟 Премиум включён' if on else 'Премиум выключен'} для «{html.escape(name)}» (#{sid}).",
        reply_markup=main_menu(),
    )


@router.message(Command("card"))
async def cmd_card(message: Message) -> None:
    """Показать карточку целиком. /card ID"""
    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer("Использование: <code>/card ID</code> — показать карточку.",
                             reply_markup=main_menu())
        return
    sid = int(parts[1])
    async with get_session() as session:
        sp = await session.get(Specialist, sid)
    if sp is None:
        await message.answer(f"Карточка #{sid} не найдена 🤔")
        return
    where = "онлайн" if sp.is_online else (sp.city or sp.province or "—")
    paid = sp.paid_until.strftime("%d.%m.%Y") if sp.paid_until else "бессрочно"
    info = (
        f"🪪 <b>Карточка #{sp.id}</b>\n"
        f"Имя: {html.escape(sp.name)}\n"
        f"Категория: {html.escape(sp.category)} · {html.escape(where)}\n"
        f"{'🌟 Премиум' if sp.is_premium else 'Обычная'} · статус: {sp.status} · источник: {sp.source}\n"
        f"Оплачено до: {paid} · Фото: {'есть' if sp.photo_file_id else 'нет'}\n\n"
        f"Описание: {html.escape(sp.description or '—')}\n"
        f"Контакт: {html.escape(sp.contact or '—')}"
    )
    if sp.photo_file_id:
        try:
            await message.answer_photo(sp.photo_file_id, caption=info, reply_markup=main_menu())
            return
        except Exception:  # noqa: BLE001
            pass
    await message.answer(info, reply_markup=main_menu())


@router.message(Command("setcity"))
async def cmd_setcity(message: Message) -> None:
    """Сменить город карточки (или сделать онлайн). /setcity ID Город"""
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 3 or not parts[1].isdigit():
        await message.answer(
            "Использование: <code>/setcity ID Город</code> (или «онлайн»)\n"
            "Например: <code>/setcity 12 Utrecht</code>",
            reply_markup=main_menu(),
        )
        return
    sid, loc = int(parts[1]), parts[2].strip()
    online = loc.lower() in ONLINE_WORDS
    async with get_session() as session:
        sp = await session.get(Specialist, sid)
        if sp is None:
            await message.answer(f"Карточка #{sid} не найдена 🤔")
            return
        if online:
            sp.is_online, sp.city, sp.province = True, "", ""
        else:
            known = detect_city(loc)
            if known:
                city, province = known
            else:  # незнакомый город — провинцию не теряем, если не определилась
                city, province = loc, (province_of_city(loc) or sp.province or "")
            sp.is_online, sp.city, sp.province = False, city, province
        name, city_now, prov_now, onl = sp.name, sp.city, sp.province, sp.is_online
        await session.commit()
    where = "онлайн (вся страна)" if onl else (city_now + (f", {prov_now}" if prov_now else ""))
    await message.answer(
        f"✅ Локация карточки «{html.escape(name)}» (#{sid}): {where}.",
        reply_markup=main_menu(),
    )


@router.message(Command("preview"))
async def cmd_preview(message: Message) -> None:
    """Ссылка на живой гайд (для предпросмотра перед вставкой на сайт)."""
    base = config.WEBHOOK_BASE_URL
    if not base:
        await message.answer(
            "Публичный адрес не задан (WEBHOOK_BASE_URL / RAILWAY_PUBLIC_DOMAIN) — "
            "предпросмотр недоступен.",
            reply_markup=main_menu(),
        )
        return
    await message.answer(
        "🔌 <b>Подключение каталога на сайте к боту.</b>\n"
        "Дизайн вашей страницы НЕ меняется — меняется только источник данных.\n\n"
        "1. Проверь, что фид отдаётся (откроется список текстом):\n"
        f"{base}/api/guide.json\n\n"
        "2. На странице каталога WordPress, в блоке «Произвольный HTML», найди "
        "строку <code>var KG_DATA_URL='';</code> и замени на:\n"
        f"<code>var KG_DATA_URL='{base}/api/guide.json';</code>\n\n"
        "3. Нажми «Предпросмотр» — увидишь свой каталог с данными из бота, не "
        "публикуя. Откат — верни пустые кавычки <code>''</code>.",
        reply_markup=main_menu(),
        disable_web_page_preview=True,
    )


@router.message(Command("listcat"))
async def cmd_listcat(message: Message) -> None:
    """Список карточек по категории (для проверки правильности категорий).
    /listcat — категории со счётчиком; /listcat <категория> — карточки в ней."""
    parts = (message.text or "").split(maxsplit=1)
    async with get_session() as session:
        if len(parts) < 2:
            rows = (
                await session.execute(
                    select(Specialist.category, func.count())
                    .where(Specialist.status == "active")
                    .group_by(Specialist.category)
                    .order_by(func.count().desc())
                )
            ).all()
            txt = (
                "📂 Категории (проверить: <code>/listcat категория</code>):\n\n"
                + "\n".join(f"  • {c}: {n}" for c, n in rows)
            )
            await message.answer(txt, reply_markup=main_menu())
            return
        raw = parts[1].strip()
        cat = (
            detect_category(raw)
            or next((c for c in CATEGORIES if c.lower() == raw.lower()), None)
            or raw
        )
        specs = (
            await session.scalars(
                select(Specialist)
                .where(Specialist.status == "active", Specialist.category == cat)
                .order_by(Specialist.is_online, Specialist.city, Specialist.name)
            )
        ).all()
    if not specs:
        await message.answer(
            f"В «{cat}» активных карточек нет (или категория названа иначе). "
            "Список категорий — /listcat без аргумента.",
            reply_markup=main_menu(),
        )
        return
    buf = (
        f"📂 <b>{html.escape(cat)}</b> — {len(specs)} карточек.\n"
        "Не та категория? <code>/setcategory ID нужная</code>\n\n"
    )
    for sp in specs:
        where = "онлайн" if sp.is_online else (sp.city or sp.province or "—")
        line = f"#{sp.id} {html.escape(sp.name[:45])} · {html.escape(where)}\n"
        if len(buf) + len(line) > 3500:  # не упираемся в лимит сообщения
            await message.answer(buf)
            buf = ""
        buf += line
    if buf:
        await message.answer(buf, reply_markup=main_menu())


@router.message(Command("fillcities"))
async def cmd_fillcities(message: Message) -> None:
    """Массово проставить город карточкам без него — только из названия (надёжно)."""
    scanned = filled = 0
    changes: list[str] = []
    async with get_session() as session:
        rows = (
            await session.scalars(
                select(Specialist).where(
                    Specialist.is_online.is_(False),
                    Specialist.status == "active",
                    or_(Specialist.city.is_(None), Specialist.city == ""),
                )
            )
        ).all()
        scanned = len(rows)
        for sp in rows:
            d = detect_city(sp.name or "")  # только из названия — без угадывания по описанию
            if d:
                city, prov = d
                sp.city = city
                if not sp.province:
                    sp.province = prov
                filled += 1
                if len(changes) < 25:
                    changes.append(f"#{sp.id} {sp.name[:30]} → {city}")
        await session.commit()
    txt = (
        f"🗺 Карточек без города: {scanned}. Проставил город из названия: {filled}.\n"
        "Остальные находятся по провинции — поиск это уже показывает корректно. "
        "Точечно можно добить командой /setcity."
    )
    if changes:
        txt += "\n\n" + "\n".join(changes)
    await message.answer(txt, reply_markup=main_menu())


@router.message(Command("setcategory"))
async def cmd_setcategory(message: Message) -> None:
    """Сменить категорию карточки. /setcategory ID категория"""
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 3 or not parts[1].isdigit():
        await message.answer(
            "Использование: <code>/setcategory ID категория</code>\n"
            "Например: <code>/setcategory 257 мастер маникюра</code>\n\n"
            "Категории: " + ", ".join(CATEGORIES.keys()),
            reply_markup=main_menu(),
        )
        return
    sid, raw = int(parts[1]), parts[2].strip()
    cat = detect_category(raw) or next((c for c in CATEGORIES if c.lower() == raw.lower()), None)
    if not cat:
        await message.answer(
            "Не распознал категорию 🤔 Доступные: " + ", ".join(CATEGORIES.keys())
        )
        return
    async with get_session() as session:
        sp = await session.get(Specialist, sid)
        if sp is None:
            await message.answer(f"Карточка #{sid} не найдена 🤔")
            return
        old, name = sp.category, sp.name
        sp.category = cat
        await session.commit()
    await message.answer(
        f"✅ Категория карточки «{html.escape(name)}» (#{sid}): <b>{cat}</b> (было «{old}»).",
        reply_markup=main_menu(),
    )


@router.message(Command("setname"))
async def cmd_setname(message: Message) -> None:
    """Сменить имя/название карточки. /setname ID Новое имя"""
    from database.models import Review
    from utils.reviews import specialist_key

    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 3 or not parts[1].isdigit():
        await message.answer(
            "Использование: <code>/setname ID Новое имя</code>", reply_markup=main_menu()
        )
        return
    sid, new = int(parts[1]), parts[2].strip()
    async with get_session() as session:
        sp = await session.get(Specialist, sid)
        if sp is None:
            await message.answer(f"Карточка #{sid} не найдена 🤔")
            return
        old = sp.name
        old_key, new_key = specialist_key(old, sp.contact), specialist_key(new, sp.contact)
        if old_key != new_key:  # переносим отзывы на новый ключ
            revs = (await session.scalars(select(Review).where(Review.spec_key == old_key))).all()
            for r in revs:
                r.spec_key = new_key
        sp.name = new
        await session.commit()
    await message.answer(
        f"✅ Имя карточки #{sid}: «{html.escape(new)}» (было «{html.escape(old)}»).",
        reply_markup=main_menu(),
    )


@router.message(Command("setdesc"))
async def cmd_setdesc(message: Message) -> None:
    """Сменить описание карточки. /setdesc ID текст (или «-» чтобы убрать)"""
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer(
            "Использование: <code>/setdesc ID Новое описание</code> "
            "(или <code>/setdesc ID -</code> чтобы убрать).",
            reply_markup=main_menu(),
        )
        return
    sid = int(parts[1])
    new = parts[2].strip() if len(parts) >= 3 else ""
    async with get_session() as session:
        sp = await session.get(Specialist, sid)
        if sp is None:
            await message.answer(f"Карточка #{sid} не найдена 🤔")
            return
        sp.description = None if new in ("", "-") else new
        name = sp.name
        await session.commit()
    await message.answer(
        f"✅ Описание карточки «{html.escape(name)}» (#{sid}) обновлено.",
        reply_markup=main_menu(),
    )


@router.message(Command("setphoto"))
async def cmd_setphoto(message: Message, state: FSMContext) -> None:
    """Добавить/сменить фото карточки. /setphoto ID — затем прислать фото."""
    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer(
            "Использование: <code>/setphoto ID</code> — затем пришли фото "
            "(или «-», чтобы убрать).",
            reply_markup=main_menu(),
        )
        return
    sid = int(parts[1])
    async with get_session() as session:
        sp = await session.get(Specialist, sid)
        if sp is None:
            await message.answer(f"Карточка #{sid} не найдена 🤔")
            return
        name = sp.name
    await state.set_state(AdminSetPhoto.waiting_photo)
    await state.update_data(photo_sid=sid)
    await message.answer(
        f"Пришли фото для карточки «{html.escape(name)}» (#{sid}) одним сообщением.\n"
        "Или отправь «-», чтобы убрать фото.",
        reply_markup=cancel_menu(),
    )


@router.message(AdminSetPhoto.waiting_photo)
async def setphoto_receive(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    sid = data.get("photo_sid")
    if message.photo:
        file_id = message.photo[-1].file_id  # самое крупное превью
    elif message.text and message.text.strip() == "-":
        file_id = None
    else:
        await message.answer("Пришли именно фото (картинкой) или «-», чтобы убрать.")
        return
    await state.clear()
    async with get_session() as session:
        sp = await session.get(Specialist, sid)
        if sp is None:
            await message.answer(f"Карточка #{sid} не найдена 🤔", reply_markup=main_menu())
            return
        sp.photo_file_id = file_id
        name = sp.name
        await session.commit()
    done = "добавлено" if file_id else "убрано"
    await message.answer(
        f"✅ Фото {done} для карточки «{html.escape(name)}» (#{sid}).",
        reply_markup=main_menu(),
    )


@router.message(Command("grant"))
async def cmd_grant(message: Message) -> None:
    """Бесплатно продлить карточку до даты — например, тем, кто недавно оплатил.
    Использование: /grant ID ГГГГ-ММ-ДД"""
    parts = (message.text or "").split()
    if len(parts) < 3 or not parts[1].isdigit():
        await message.answer(
            "Использование: <code>/grant ID ДАТА</code>\n"
            "Например: <code>/grant 204 2027-01-31</code> — оставить карточку #204 "
            "активной бесплатно до 31.01.2027 (для тех, кто оплатил недавно).\n\n"
            "ID карточки — из CSV выгрузки (/legacy_export) или из ссылки claim_<ID>.",
            reply_markup=main_menu(),
        )
        return
    sid = int(parts[1])
    try:
        until = datetime.strptime(parts[2], "%Y-%m-%d").replace(hour=23, minute=59, second=59)
    except ValueError:
        await message.answer("Дата должна быть в формате ГГГГ-ММ-ДД, например 2027-01-31.")
        return
    async with get_session() as session:
        sp = await session.get(Specialist, sid)
        if sp is None:
            await message.answer(f"Карточка #{sid} не найдена 🤔")
            return
        sp.paid_until = until
        sp.status = "active"
        sp.renewal_reminded = False
        name = sp.name
        await session.commit()
    await message.answer(
        f"✅ Карточка «{name}» (#{sid}) активна и оплачена до <b>{until:%d.%m.%Y}</b> — бесплатно.\n"
        "Деньги не списываются, авто-скрытие её не тронет.",
        reply_markup=main_menu(),
    )


@router.callback_query(F.data == "admin:legacydeadline")
async def legacy_deadline_btn(callback: CallbackQuery) -> None:
    await _legacy_set_deadline(callback.message)
    await callback.answer()


async def _legacy_set_deadline(message: Message) -> None:
    """Проставляет всем бессрочным карточкам из старого гайда дедлайн оплаты.
    После него фильтр видимости автоматически убирает их из поиска."""
    deadline = config.grandfather_deadline()
    async with get_session() as session:
        rows = (
            await session.scalars(
                select(Specialist).where(
                    Specialist.source == "seed",
                    Specialist.status == "active",
                    Specialist.paid_until.is_(None),
                )
            )
        ).all()
        n = 0
        for s in rows:
            s.paid_until = deadline
            n += 1
        await session.commit()
    await message.answer(
        f"⏳ Дедлайн оплаты <b>{deadline:%d.%m.%Y}</b> проставлен для <b>{n}</b> "
        "карточек из старого гайда.\n\n"
        "До этой даты они видны как обычно, после — автоматически скроются из поиска "
        "(не удаляются: оплата вернёт карточку).\n\n"
        "Дальше выгрузи список со ссылками для рассылки: /legacy_export",
        reply_markup=main_menu(),
    )


@router.message(Command("guide_export"))
async def cmd_guide_export(message: Message) -> None:
    await _guide_export(message)


@router.callback_query(F.data == "admin:guideexport")
async def guide_export_btn(callback: CallbackQuery) -> None:
    await _guide_export(callback.message)
    await callback.answer()


# --- Массовая переразметка категорий (новая таксономия) ---------------------

def _suggest_category(sp: Specialist) -> str | None:
    """Подбирает категорию по новой таксономии: сначала по имени (надёжно),
    затем по имени+описанию. None — если не распознали (оставим как есть)."""
    return (
        detect_category(sp.name or "")
        or detect_category(f"{sp.name or ''} {sp.description or ''}")
        or None
    )


async def _recat_rows() -> list[tuple[int, str, str, str]]:
    """Список (id, имя, было, станет) для карточек, где категория поменяется."""
    async with get_session() as session:
        specs = (
            await session.scalars(
                select(Specialist).where(Specialist.status != "rejected").order_by(Specialist.id)
            )
        ).all()
    rows = []
    for sp in specs:
        sug = _suggest_category(sp)
        if sug and sug in CATEGORIES and sug != sp.category:
            rows.append((sp.id, sp.name, sp.category, sug))
    return rows


@router.message(Command("recategorize"))
async def cmd_recategorize(message: Message, state: FSMContext) -> None:
    """Предпросмотр массовой переразметки (CSV «было→станет»), без изменений."""
    await state.clear()
    import csv
    import io

    from aiogram.types import BufferedInputFile

    rows = await _recat_rows()
    if not rows:
        await message.answer(
            "Все категории уже соответствуют новой таксономии — менять нечего ✅",
            reply_markup=main_menu(),
        )
        return
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["id", "Имя", "Было", "Станет"])
    for rid, name, old, new in rows:
        writer.writerow([rid, name, old, new])
    data = buf.getvalue().encode("utf-8-sig")
    doc = BufferedInputFile(data, filename="recategorize_preview.csv")
    await message.answer_document(
        doc,
        caption=(
            f"🔁 Предпросмотр переразметки: изменится <b>{len(rows)}</b> карточек.\n\n"
            "Проверь CSV. Если ок — применить всё: /recategorize_apply\n"
            "Отдельные карточки потом можно поправить: /setcategory ID категория"
        ),
    )


@router.message(Command("recategorize_apply"))
async def cmd_recategorize_apply(message: Message, state: FSMContext) -> None:
    """Применяет переразметку (детерминированно, тот же расчёт, что в предпросмотре)."""
    await state.clear()
    rows = await _recat_rows()
    if not rows:
        await message.answer("Менять нечего ✅", reply_markup=main_menu())
        return
    ids = {rid: new for rid, _, _, new in rows}
    applied = 0
    async with get_session() as session:
        for rid, new in ids.items():
            sp = await session.get(Specialist, rid)
            if sp and new in CATEGORIES and sp.category != new:
                sp.category = new
                applied += 1
        await session.commit()
    await message.answer(
        f"✅ Переразметка применена: обновлено <b>{applied}</b> карточек.\n"
        "Отзывы и рейтинги сохранены. Точечно правь: /setcategory ID категория",
        reply_markup=main_menu(),
    )


async def _guide_export(message: Message) -> None:
    """CSV со ВСЕМИ специалистами в гайде — чтобы свериться перед рассылкой
    приглашений (кому уже не надо писать)."""
    import csv
    import io

    from aiogram.types import BufferedInputFile

    async with get_session() as session:
        rows = (
            await session.scalars(
                select(Specialist)
                .where(Specialist.status != "rejected")
                .order_by(Specialist.name)
            )
        ).all()
    if not rows:
        await message.answer("В гайде пока пусто.", reply_markup=main_menu())
        return
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Имя", "Категория", "Город", "Контакт", "Источник", "Статус"])
    for s in rows:
        where = "онлайн" if s.is_online else (s.city or s.province or "")
        src = {"seed": "старый гайд", "admin": "добавлен вручную", "self": "сам(а)"}.get(
            s.source, s.source or ""
        )
        writer.writerow([s.name, s.category, where, s.contact or "", src, s.status])
    data = buf.getvalue().encode("utf-8-sig")  # BOM — чтобы Excel открыл кириллицу
    doc = BufferedInputFile(data, filename="guide_all.csv")
    await message.answer_document(
        doc,
        caption=(
            f"📇 Весь гайд: {len(rows)} специалистов.\n"
            "Сверь со списком рассылки, чтобы не написать тем, кто уже есть.\n\n"
            "Быстрая проверка одного человека: /admin → «🔎 Найти и удалить» → "
            "введи имя (просто посмотри, удалять не нужно)."
        ),
    )


@router.message(Command("legacy_export"))
async def cmd_legacy_export(message: Message) -> None:
    await _legacy_export(message)


@router.callback_query(F.data == "admin:legacyexport")
async def legacy_export_btn(callback: CallbackQuery) -> None:
    await _legacy_export(callback.message)
    await callback.answer()


async def _legacy_export(message: Message) -> None:
    """Отдаёт CSV со старыми карточками и персональной ссылкой оплаты для каждой,
    плюс готовый шаблон сообщения для рассылки."""
    import csv
    import io

    from aiogram.types import BufferedInputFile

    me = await message.bot.me()
    async with get_session() as session:
        rows = (
            await session.scalars(
                select(Specialist)
                .where(Specialist.source == "seed", Specialist.status == "active")
                .order_by(Specialist.category, Specialist.name)
            )
        ).all()
    if not rows:
        await message.answer(
            "Активных карточек из старого гайда не найдено 🤔", reply_markup=main_menu()
        )
        return
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["id", "Имя", "Категория", "Город", "Контакт", "Ссылка для оплаты", "Оплачено до"])
    for s in rows:
        link = f"https://t.me/{me.username}?start=claim_{s.id}"
        writer.writerow([
            s.id, s.name, s.category, s.city or s.province or "",
            s.contact or "", link,
            s.paid_until.strftime("%Y-%m-%d") if s.paid_until else "",
        ])
    data = buf.getvalue().encode("utf-8-sig")  # BOM — чтобы Excel открыл кириллицу
    doc = BufferedInputFile(data, filename="legacy_specialists.csv")
    await message.answer_document(
        doc,
        caption=(
            f"📋 {len(rows)} карточек из старого гайда.\n"
            "В колонке «Ссылка для оплаты» — персональная ссылка для каждого: "
            "по ней человек платит сам по лояльной цене, и карточка остаётся."
        ),
    )
    cur = config.LISTING_CURRENCY
    y = config.plan_info("year_legacy")
    norm_y = config.plan_info("year")
    deadline = config.grandfather_deadline()
    # Убираем лишние нули у цены: "29.00" → "29", "4.99" → "4.99"
    def _money(p: str) -> str:
        return p.rstrip("0").rstrip(".") if "." in p else p
    y_price, norm_price = _money(y["price"]), _money(norm_y["price"])
    await message.answer(
        "✉️ <b>Шаблон сообщения для рассылки</b> (скопируй, подставь имя и ссылку из CSV):\n\n"
        "<code>Здравствуйте! 🧡 Пишем вам от команды «Подслушано в Нидерландах».\n\n"
        "Вы — один из специалистов нашего гайда (он есть и на сайте, и в нашем "
        "Telegram-боте). Спасибо, что доверились нам одними из первых!\n\n"
        "Когда вы размещались, оплата была разовой. Но с тех пор гайд заметно "
        "вырос: мы перенесли его в бота, добавили удобный "
        "поиск, отзывы и продвижение. Чтобы всё это поддерживать и приводить вам "
        f"клиентов, с {deadline:%d.%m.%Y} мы переходим на ежегодное размещение.\n\n"
        "Понимаем, что менять условия — всегда неприятно, поэтому для вас, кто был с "
        f"нами с самого начала, мы сделали особую цену: {y_price} {cur} в год вместо "
        f"обычных {norm_price} {cur}. Это наша благодарность за доверие.\n\n"
        "Чтобы карточка осталась в гайде, продлите по личной ссылке до "
        f"{deadline:%d.%m.%Y}:\nССЫЛКА\n\n"
        "Если сейчас неактуально — ничего делать не нужно, карточка просто перестанет "
        "показываться. А если есть вопросы или сомнения — просто ответьте на это "
        "сообщение, мы на связи 🧡</code>",
        reply_markup=main_menu(),
    )
