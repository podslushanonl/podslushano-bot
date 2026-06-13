"""Админ-панель: управление базой специалистов прямо из бота.

Доступно только администраторам (config.ADMIN_IDS) и только в личке.
Команда /admin открывает панель: добавить специалиста, посмотреть добавленные
вручную, найти и удалить.
"""
import asyncio
import html
from datetime import datetime, timedelta

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramForbiddenError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy import func, or_, select

import config
from database.db import get_session
from database.models import BotUser, Specialist
from keyboards.menus import cancel_menu, main_menu
from states.forms import AdminAddSpecialist, AdminAnnounce, AdminBroadcast, AdminFind
from utils.ai import extract_specialist_query
from utils.analytics import gather_stats
from utils.geo import CATEGORIES, NEIGHBORS, detect_category, detect_city, province_of_city

router = Router()
# Только админы и только в личке
router.message.filter(F.chat.type == ChatType.PRIVATE, F.from_user.id.in_(config.ADMIN_IDS))
router.callback_query.filter(F.from_user.id.in_(config.ADMIN_IDS))

ONLINE_WORDS = {"онлайн", "online", "онлайн по всей стране", "по всей стране"}


def _admin_panel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Добавить специалиста", callback_data="admin:add")],
            [InlineKeyboardButton(text="📋 Добавленные вручную", callback_data="admin:list")],
            [InlineKeyboardButton(text="🔎 Найти и удалить", callback_data="admin:find")],
            [InlineKeyboardButton(text="📣 Рассылка-анонс", callback_data="admin:broadcast")],
            [InlineKeyboardButton(text="📊 Статистика", callback_data="admin:stats")],
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


@router.message(AdminAddSpecialist.name)
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


@router.message(AdminAddSpecialist.category)
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


@router.message(AdminAddSpecialist.location)
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


@router.message(AdminAddSpecialist.description)
async def add_description(message: Message, state: FSMContext) -> None:
    desc = (message.text or "").strip()
    await state.update_data(sp_description=None if desc == "-" else desc)
    await state.set_state(AdminAddSpecialist.contact)
    await message.answer(
        "Шаг 5/5. Контакты? (телефон / @username / email / сайт)",
        reply_markup=cancel_menu(),
    )


@router.message(AdminAddSpecialist.contact)
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


@router.message(AdminFind.waiting_query)
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


@router.message(AdminAnnounce.waiting_text)
async def announce_text(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("Нужен текст сообщения 🙂")
        return
    await state.update_data(ann_text=message.html_text)
    me = await message.bot.me()
    await message.answer("Вот как будет выглядеть пост 👇")
    await message.answer(
        message.html_text, reply_markup=_open_bot_kb(me.username),
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
    await callback.message.answer("Отменил — ничего не опубликовал.")
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
            reply_markup=_open_bot_kb(me.username), disable_web_page_preview=True,
        )
        try:
            await callback.bot.pin_chat_message(config.ANNOUNCE_CHANNEL, msg.message_id)
            note = " и закрепил 📌"
        except Exception:  # noqa: BLE001
            note = " (но закрепить не вышло — дай боту право «Закреплять сообщения»)"
        await callback.message.answer(f"✅ Опубликовал в канал{note}")
    except Exception as e:  # noqa: BLE001
        await callback.message.answer(
            f"❌ Не получилось опубликовать: {html.escape(str(e))}\n\n"
            "Проверь: бот — администратор канала с правом «Публиковать сообщения», "
            "и <code>ANNOUNCE_CHANNEL</code> указан верно."
        )
    await callback.answer()


# --- Статистика -------------------------------------------------------------

@router.message(Command("stats"))
async def cmd_stats(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(await gather_stats(), reply_markup=main_menu())


@router.callback_query(F.data == "admin:stats")
async def stats_btn(callback: CallbackQuery) -> None:
    await callback.message.answer(await gather_stats())
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


@router.message(AdminBroadcast.waiting_message)
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
    await callback.message.answer("🚀 Рассылка запущена! Пришлю итог, когда закончу.")
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
