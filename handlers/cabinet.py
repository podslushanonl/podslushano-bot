"""Личный кабинет специалиста.

Специалист видит свои карточки в гайде, управляет подпиской (продление —
переиспользуем поток из selfadd) и редактирует данные. КАЖДАЯ правка карточки
уходит на модерацию админу и применяется только после одобрения. Карточку из
старого гайда (seed) можно «привязать» к себе — тоже через одобрение админа.
"""
import html
import logging

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy import select

import config
from database.db import get_session
from database.models import Specialist, SpecialistClaim, SpecialistEdit
from keyboards.menus import BTN_CABINET, cancel_menu, main_menu
from states.forms import CabinetClaim, CabinetEdit
from utils.geo import province_of_city

log = logging.getLogger(__name__)

router = Router()
router.message.filter(F.chat.type == ChatType.PRIVATE)

ONLINE_WORDS = {"онлайн", "online", "по всей стране"}

# Поля карточки, доступные для правки: ключ → (подпись, как просить значение)
FIELDS = {
    "name": "имя/название",
    "category": "категорию",
    "city": "город",
    "description": "описание",
    "contact": "контакт",
    "photo": "фото",
}


def _is_admin(uid: int) -> bool:
    return uid in config.ADMIN_IDS


def _where(sp: Specialist) -> str:
    if sp.is_online:
        return "онлайн"
    return sp.city or sp.province or "—"


def _status_label(sp: Specialist) -> str:
    base = {
        "active": "✅ активна",
        "pending": "🕓 на проверке",
        "awaiting_payment": "💳 ждёт оплаты",
        "expired": "⛔ скрыта (срок истёк)",
        "rejected": "❌ отклонена",
    }.get(sp.status, sp.status)
    if sp.paid_until:
        base += f", оплачено до {sp.paid_until:%d.%m.%Y}"
    return base


def _card_text(sp: Specialist) -> str:
    lines = [
        f"<b>{html.escape(sp.name)}</b> — {html.escape(sp.category)}, "
        f"{html.escape(_where(sp))}"
    ]
    if sp.description:
        lines.append(html.escape(sp.description))
    if sp.contact:
        lines.append(f"📞 {html.escape(sp.contact)}")
    lines.append(f"\n<i>Статус: {_status_label(sp)}</i>")
    return "\n".join(lines)


def _card_kb(sp: Specialist) -> InlineKeyboardMarkup:
    rows = [[
        InlineKeyboardButton(text="✏️ Изменить", callback_data=f"cab:edit:{sp.id}"),
        InlineKeyboardButton(text="🔁 Продлить", callback_data=f"specrenew:{sp.id}"),
    ]]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _edit_fields_kb(sid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Имя/название", callback_data=f"cab:f:{sid}:name"),
            InlineKeyboardButton(text="Категория", callback_data=f"cab:f:{sid}:category"),
        ],
        [
            InlineKeyboardButton(text="Город", callback_data=f"cab:f:{sid}:city"),
            InlineKeyboardButton(text="Описание", callback_data=f"cab:f:{sid}:description"),
        ],
        [
            InlineKeyboardButton(text="Контакт", callback_data=f"cab:f:{sid}:contact"),
            InlineKeyboardButton(text="Фото", callback_data=f"cab:f:{sid}:photo"),
        ],
        [InlineKeyboardButton(text="⬅️ Закрыть", callback_data="cab:close")],
    ])


def _claim_start_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔗 Привязать мою карточку",
                              callback_data="cab:claimstart")]
    ])


async def _safe_send(bot, chat_id, text, reply_markup=None) -> None:
    try:
        await bot.send_message(chat_id, text, reply_markup=reply_markup)
    except Exception as e:  # noqa: BLE001
        log.warning("Кабинет: не удалось отправить %s: %s", chat_id, e)


# --- Вход в кабинет ----------------------------------------------------------

@router.message(Command("cabinet"))
@router.message(F.text == BTN_CABINET)
async def cabinet_open(message: Message, state: FSMContext) -> None:
    await state.clear()
    uid = message.from_user.id
    async with get_session() as session:
        rows = (
            await session.scalars(
                select(Specialist).where(Specialist.submitter_user_id == uid)
            )
        ).all()
        cards = [(s.id, _card_text(s), _card_kb(s)) for s in rows]

    if not cards:
        await message.answer(
            "👤 <b>Мой кабинет</b>\n\nУ тебя пока нет карточек в гайде.\n\n"
            "Если ты уже есть в нашем гайде — привяжи свою карточку к аккаунту "
            "(после подтверждения сможешь её редактировать и продлевать). "
            "Или добавь себя через меню «➕ Добавить себя в гайд».",
            reply_markup=_claim_start_kb(),
        )
        return

    await message.answer(
        f"👤 <b>Мой кабинет</b>\n\nТвои карточки в гайде ({len(cards)}). "
        "Любая правка карточки публикуется после проверки модератором.",
    )
    for _sid, text, kb in cards:
        await message.answer(text, reply_markup=kb, disable_web_page_preview=True)
    await message.answer(
        "Нет нужной карточки из гайда? Можно привязать её к себе 👇",
        reply_markup=_claim_start_kb(),
    )


@router.callback_query(F.data == "cab:close")
async def cabinet_close(callback: CallbackQuery) -> None:
    try:
        await callback.message.delete()
    except Exception:  # noqa: BLE001
        pass
    await callback.answer()


# --- Редактирование карточки (с модерацией) ---------------------------------

@router.callback_query(F.data.startswith("cab:edit:"))
async def cabinet_edit(callback: CallbackQuery) -> None:
    sid = int(callback.data.split(":")[2])
    async with get_session() as session:
        sp = await session.get(Specialist, sid)
        if sp is None or sp.submitter_user_id != callback.from_user.id:
            await callback.answer("Это не твоя карточка", show_alert=True)
            return
        name = sp.name
    await callback.message.answer(
        f"✏️ Что изменить в карточке «{html.escape(name)}»? Выбери поле 👇\n\n"
        "<i>Правка вступит в силу после проверки модератором.</i>",
        reply_markup=_edit_fields_kb(sid),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("cab:f:"))
async def cabinet_pick_field(callback: CallbackQuery, state: FSMContext) -> None:
    _, _, sid_s, field = callback.data.split(":")
    sid = int(sid_s)
    if field not in FIELDS:
        await callback.answer("Неизвестное поле", show_alert=True)
        return
    async with get_session() as session:
        sp = await session.get(Specialist, sid)
        if sp is None or sp.submitter_user_id != callback.from_user.id:
            await callback.answer("Это не твоя карточка", show_alert=True)
            return
    await state.set_state(CabinetEdit.waiting_value)
    await state.update_data(edit_sid=sid, edit_field=field)
    if field == "photo":
        prompt = "Пришли новое фото картинкой 🙂"
    elif field == "city":
        prompt = ("Напиши новый город. Или «онлайн», если работаешь по всей стране.")
    else:
        prompt = f"Напиши новое значение: {FIELDS[field]}."
    await callback.message.answer(prompt, reply_markup=cancel_menu())
    await callback.answer()


@router.message(CabinetEdit.waiting_value)
async def cabinet_save_value(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    sid = data.get("edit_sid")
    field = data.get("edit_field")
    if not sid or field not in FIELDS:
        await state.clear()
        await message.answer("Что-то пошло не так, открой кабинет заново.",
                             reply_markup=main_menu())
        return

    if field == "photo":
        if not message.photo:
            await message.answer("Пришли фото картинкой 🙂")
            return
        new_value = message.photo[-1].file_id
        shown = "новое фото"
    else:
        if not message.text or not message.text.strip():
            await message.answer("Напиши значение текстом 🙂")
            return
        new_value = message.text.strip()[:1000]
        shown = new_value

    uid = message.from_user.id
    async with get_session() as session:
        sp = await session.get(Specialist, sid)
        if sp is None or sp.submitter_user_id != uid:
            await state.clear()
            await message.answer("Это не твоя карточка.", reply_markup=main_menu())
            return
        edit = SpecialistEdit(
            specialist_id=sid, user_id=uid, field=field, new_value=new_value,
        )
        session.add(edit)
        await session.commit()
        await session.refresh(edit)
        eid, sp_name, old_val = edit.id, sp.name, getattr(sp, _column_for(field), None)

    await state.clear()
    await message.answer(
        "Готово! Отправил правку на проверку модератору. "
        "Карточка обновится после одобрения ✅",
        reply_markup=main_menu(),
    )
    await _notify_admins_edit(message.bot, eid, sp_name, field, old_val, new_value)


def _column_for(field: str) -> str:
    return "photo_file_id" if field == "photo" else field


async def _notify_admins_edit(bot, eid: int, sp_name: str, field: str,
                              old_val, new_value: str) -> None:
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Одобрить", callback_data=f"cabedit_ok:{eid}"),
        InlineKeyboardButton(text="❌ Отклонить", callback_data=f"cabedit_no:{eid}"),
    ]])
    label = FIELDS.get(field, field)
    for admin_id in config.ADMIN_IDS:
        try:
            if field == "photo":
                await bot.send_photo(
                    admin_id, new_value,
                    caption=(f"✏️ Правка карточки «{html.escape(sp_name)}»\n"
                             f"Поле: {label} (новое фото выше)"),
                    reply_markup=kb,
                )
            else:
                old_s = html.escape(str(old_val or "—"))
                new_s = html.escape(new_value)
                await bot.send_message(
                    admin_id,
                    f"✏️ <b>Правка карточки</b> «{html.escape(sp_name)}»\n\n"
                    f"Поле: <b>{label}</b>\n"
                    f"Было: {old_s}\nСтанет: {new_s}",
                    reply_markup=kb,
                )
        except Exception as e:  # noqa: BLE001
            log.warning("Не отправил правку админу %s: %s", admin_id, e)


@router.callback_query(F.data.startswith("cabedit_ok:"))
async def cabedit_approve(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Только для админов", show_alert=True)
        return
    eid = int(callback.data.split(":", 1)[1])
    async with get_session() as session:
        edit = await session.get(SpecialistEdit, eid)
        if edit is None or edit.status != "pending":
            await callback.answer("Уже обработано", show_alert=True)
            return
        sp = await session.get(Specialist, edit.specialist_id)
        if sp is None:
            edit.status = "rejected"
            await session.commit()
            await callback.answer("Карточка не найдена", show_alert=True)
            return
        _apply_edit(sp, edit.field, edit.new_value)
        edit.status = "approved"
        await session.commit()
        owner, sp_name = sp.submitter_user_id, sp.name
    await _mark_done(callback, "✅ Правка одобрена и применена.")
    if owner:
        await _safe_send(callback.bot, owner,
                         f"✅ Правка карточки «{sp_name}» одобрена и применена.")
    await callback.answer("Применено")


@router.callback_query(F.data.startswith("cabedit_no:"))
async def cabedit_reject(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Только для админов", show_alert=True)
        return
    eid = int(callback.data.split(":", 1)[1])
    async with get_session() as session:
        edit = await session.get(SpecialistEdit, eid)
        if edit is None or edit.status != "pending":
            await callback.answer("Уже обработано", show_alert=True)
            return
        edit.status = "rejected"
        await session.commit()
        sp = await session.get(Specialist, edit.specialist_id)
        owner = sp.submitter_user_id if sp else None
        sp_name = sp.name if sp else ""
    await _mark_done(callback, "❌ Правка отклонена.")
    if owner:
        await _safe_send(callback.bot, owner,
                         f"❌ Правка карточки «{sp_name}» отклонена модератором.")
    await callback.answer("Отклонено")


def _apply_edit(sp: Specialist, field: str, value: str | None) -> None:
    if field == "photo":
        sp.photo_file_id = value
    elif field == "city":
        if value and value.strip().lower() in ONLINE_WORDS:
            sp.is_online, sp.city, sp.province = True, "", ""
        else:
            sp.is_online = False
            sp.city = value or ""
            sp.province = province_of_city(value or "") or sp.province
    else:
        setattr(sp, field, value)


async def _mark_done(callback: CallbackQuery, note: str) -> None:
    """Убирает кнопки у сообщения админа и дописывает результат."""
    try:
        if callback.message.photo:
            await callback.message.edit_caption(
                caption=(callback.message.caption or "") + f"\n\n{note}")
        else:
            await callback.message.edit_text(
                (callback.message.text or "") + f"\n\n{note}")
    except Exception:  # noqa: BLE001
        pass


# --- Привязка карточки из гайда (claim, с одобрением) -----------------------

@router.callback_query(F.data == "cab:claimstart")
async def claim_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(CabinetClaim.waiting_query)
    await callback.message.answer(
        "🔗 Напиши имя или название своей карточки, как оно указано в гайде — "
        "я найду её, а модератор подтвердит, что она твоя.",
        reply_markup=cancel_menu(),
    )
    await callback.answer()


@router.message(CabinetClaim.waiting_query)
async def claim_search(message: Message, state: FSMContext) -> None:
    q = (message.text or "").strip()
    if not q:
        await message.answer("Напиши название текстом 🙂")
        return
    await state.clear()
    ql = q.casefold()
    async with get_session() as session:
        rows = (
            await session.scalars(
                select(Specialist).where(Specialist.submitter_user_id.is_(None))
            )
        ).all()
        matches = [s for s in rows if ql in (s.name or "").casefold()][:8]
        found = [(s.id, s.name, _where(s)) for s in matches]

    if not found:
        await message.answer(
            "Не нашёл свободную карточку с таким названием 🤔 Проверь написание "
            "или напиши нам через «✉️ Связаться с нами».",
            reply_markup=main_menu(),
        )
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"Это моя: {name} ({where})",
                              callback_data=f"cab:claim:{sid}")]
        for sid, name, where in found
    ])
    await message.answer(
        "Нашёл вот что. Выбери свою карточку 👇", reply_markup=kb,
    )


@router.callback_query(F.data.startswith("cab:claim:"))
async def claim_request(callback: CallbackQuery) -> None:
    sid = int(callback.data.split(":")[2])
    uid = callback.from_user.id
    async with get_session() as session:
        sp = await session.get(Specialist, sid)
        if sp is None:
            await callback.answer("Карточка не найдена", show_alert=True)
            return
        if sp.submitter_user_id is not None:
            await callback.answer("Эта карточка уже привязана", show_alert=True)
            return
        # нет ли уже висящей заявки от этого же пользователя
        dup = (await session.scalars(
            select(SpecialistClaim).where(
                SpecialistClaim.specialist_id == sid,
                SpecialistClaim.user_id == uid,
                SpecialistClaim.status == "pending",
            )
        )).first()
        if dup:
            await callback.answer("Заявка уже отправлена, ждём проверки", show_alert=True)
            return
        claim = SpecialistClaim(
            specialist_id=sid, user_id=uid,
            username=callback.from_user.username,
        )
        session.add(claim)
        await session.commit()
        await session.refresh(claim)
        cid, name, where = claim.id, sp.name, _where(sp)

    await callback.message.answer(
        f"Заявка на привязку карточки «{html.escape(name)}» отправлена 🙌 "
        "Мы проверим и подтвердим — я напишу.",
        reply_markup=main_menu(),
    )
    await callback.answer("Отправлено")
    uname = f"@{callback.from_user.username}" if callback.from_user.username else f"id {uid}"
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"cabclaim_ok:{cid}"),
        InlineKeyboardButton(text="❌ Отклонить", callback_data=f"cabclaim_no:{cid}"),
    ]])
    for admin_id in config.ADMIN_IDS:
        await _safe_send(
            callback.bot, admin_id,
            f"🔗 <b>Заявка на привязку карточки</b>\n\n"
            f"Карточка: «{html.escape(name)}» ({html.escape(where)})\n"
            f"Заявитель: {uname}",
        )
        # кнопки отдельным сообщением (чтобы _safe_send без kb остался простым)
        await _safe_send_kb(callback.bot, admin_id, "Решение по заявке 👇", kb)


async def _safe_send_kb(bot, chat_id, text, kb) -> None:
    try:
        await bot.send_message(chat_id, text, reply_markup=kb)
    except Exception as e:  # noqa: BLE001
        log.warning("Кабинет: не отправил кнопки админу %s: %s", chat_id, e)


@router.callback_query(F.data.startswith("cabclaim_ok:"))
async def claim_approve(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Только для админов", show_alert=True)
        return
    cid = int(callback.data.split(":", 1)[1])
    async with get_session() as session:
        claim = await session.get(SpecialistClaim, cid)
        if claim is None or claim.status != "pending":
            await callback.answer("Уже обработано", show_alert=True)
            return
        sp = await session.get(Specialist, claim.specialist_id)
        requester = claim.user_id
        if sp is None:
            claim.status = "rejected"
            await session.commit()
            await callback.answer("Карточка не найдена", show_alert=True)
            return
        # Карточку мог уже привязать другой одобренной заявкой — не переназначаем
        already = sp.submitter_user_id is not None and sp.submitter_user_id != requester
        if already:
            claim.status = "rejected"
            await session.commit()
            name = sp.name
        else:
            sp.submitter_user_id = requester
            # Переводим из seed в управляемую владельцем: иначе карточку удалит
            # пересев гайда и её обойдут напоминания/продление (они смотрят source=self)
            sp.source = "self"
            claim.status = "approved"
            await session.commit()
            name = sp.name
    if already:
        await _mark_done(
            callback, "⚠️ Карточка уже привязана к другому аккаунту — заявка отклонена.")
        await _safe_send(
            callback.bot, requester,
            "❌ Эту карточку уже привязал другой пользователь. "
            "Если это ошибка — напиши нам через «✉️ Связаться с нами».",
        )
        await callback.answer("Уже привязана")
        return
    await _mark_done(callback, "✅ Привязка подтверждена.")
    await _safe_send(
        callback.bot, requester,
        f"✅ Карточка «{name}» привязана к твоему аккаунту. "
        "Управляй ей в «👤 Мой кабинет специалиста».",
    )
    await callback.answer("Подтверждено")


@router.callback_query(F.data.startswith("cabclaim_no:"))
async def claim_reject(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Только для админов", show_alert=True)
        return
    cid = int(callback.data.split(":", 1)[1])
    async with get_session() as session:
        claim = await session.get(SpecialistClaim, cid)
        if claim is None or claim.status != "pending":
            await callback.answer("Уже обработано", show_alert=True)
            return
        claim.status = "rejected"
        await session.commit()
        owner = claim.user_id
    await _mark_done(callback, "❌ Заявка на привязку отклонена.")
    await _safe_send(
        callback.bot, owner,
        "❌ Заявку на привязку карточки отклонили. Если это ошибка — "
        "напиши нам через «✉️ Связаться с нами».",
    )
    await callback.answer("Отклонено")
