"""Спотлайт «Специалист месяца»: публикация премиум/годовых специалистов в канал.

Админ вызывает /spotlight → бот берёт специалиста (премиум или с годовой оплатой),
показывает предпросмотр поста для канала → по подтверждению публикует. Честная
ротация: пока не показали всех, один и тот же не повторяется.
"""
import asyncio
import html
import logging
import random

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramForbiddenError
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy import and_, func, or_, select

import config
from database.db import get_session
from database.models import BotUser, Meta, Specialist

log = logging.getLogger(__name__)

router = Router()
router.message.filter(F.chat.type == ChatType.PRIVATE)

_DONE_KEY = "spotlight_done"
_YEAR_PLANS = ("year", "year_premium", "year_legacy")


def _is_admin(uid: int) -> bool:
    return uid in config.ADMIN_IDS


def _where(sp: Specialist) -> str:
    if sp.is_online:
        return "онлайн"
    return sp.city or sp.province or ""


def _spotlight_text(sp: Specialist) -> str:
    where = _where(sp)
    head = f"⭐ <b>Специалист месяца</b>\n\n<b>{html.escape(sp.name)}</b> — {html.escape(sp.category)}"
    if where:
        head += f", {html.escape(where)}"
    lines = [head]
    if sp.description:
        lines.append(html.escape(sp.description))
    if sp.contact:
        lines.append(f"📞 {html.escape(sp.contact)}")
    lines.append(
        f"\nИщете проверенного специалиста? Все наши — в боте 👉 {config.BOT_URL}\n"
        "(раздел «🔍 Найти специалиста»)"
    )
    return "\n".join(lines)


async def _eligible() -> list[Specialist]:
    """Активные премиум-специалисты и реально оплатившие год (не бесплатный гайд)."""
    async with get_session() as session:
        return list(
            (await session.scalars(
                select(Specialist).where(
                    Specialist.status == "active",
                    or_(
                        Specialist.is_premium.is_(True),
                        and_(
                            Specialist.source == "self",
                            Specialist.plan.in_(_YEAR_PLANS),
                            Specialist.paid_until.is_not(None),
                        ),
                    ),
                )
            )).all()
        )


async def _done_ids() -> set[str]:
    async with get_session() as session:
        m = await session.get(Meta, _DONE_KEY)
    return set(m.value.split(",")) if m and m.value else set()


def _pick(elig: list[Specialist], done: set[str]) -> Specialist:
    pool = [s for s in elig if str(s.id) not in done] or elig
    return random.choice(pool)


def _confirm_kb(sp_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Разослать подписчикам бота",
                              callback_data=f"sp:pub:{sp_id}")],
        [InlineKeyboardButton(text="🔁 Показать другого", callback_data="sp:next")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="sp:no")],
    ])


async def _show(bot, chat_id) -> None:
    elig = await _eligible()
    if not elig:
        await bot.send_message(
            chat_id, "Пока нет премиум-специалистов или оплативших год — спотлайт пуст.")
        return
    done = await _done_ids()
    sp = _pick(elig, done)
    async with get_session() as session:
        users = await session.scalar(
            select(func.count()).select_from(BotUser).where(BotUser.is_blocked.is_(False))
        ) or 0
    from handlers.admin import _send_post  # переиспользуем отрисовку поста
    await bot.send_message(chat_id, "Предпросмотр «Специалист месяца» 👇")
    await _send_post(bot, chat_id, _spotlight_text(sp), sp.photo_file_id)
    left = len([s for s in elig if str(s.id) not in done])
    await bot.send_message(
        chat_id,
        f"Разослать <b>{users}</b> подписчикам бота? "
        f"(в очереди этого цикла ещё ~{max(left - 1, 0)})",
        reply_markup=_confirm_kb(sp.id),
    )


@router.message(Command("spotlight"))
async def cmd_spotlight(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        return
    await _show(message.bot, message.chat.id)


@router.callback_query(F.data == "sp:next")
async def sp_next(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        return
    await callback.message.edit_reply_markup(reply_markup=None)
    await _show(callback.bot, callback.message.chat.id)
    await callback.answer()


@router.callback_query(F.data == "sp:no")
async def sp_no(callback: CallbackQuery) -> None:
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("Отменил — в канал ничего не отправил.")
    await callback.answer()


@router.callback_query(F.data.startswith("sp:pub:"))
async def sp_pub(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Только для админов", show_alert=True)
        return
    sid = int(callback.data.split(":")[2])
    async with get_session() as session:
        sp = await session.get(Specialist, sid)
    if sp is None:
        await callback.answer("Карточка не найдена", show_alert=True)
        return
    await callback.message.edit_reply_markup(reply_markup=None)
    text, photo = _spotlight_text(sp), sp.photo_file_id
    await _mark_done(sid)
    await callback.message.answer(
        f"🚀 Рассылаю «{html.escape(sp.name)}» подписчикам бота — пришлю итог в конце.")
    asyncio.create_task(_broadcast(callback.bot, text, photo, callback.from_user.id))
    await callback.answer("Рассылка запущена")


async def _broadcast(bot, text: str, photo_id, admin_id: int) -> None:
    """Шлёт спотлайт всем подписчикам бота (не заблокировавшим)."""
    from handlers.admin import _send_post
    async with get_session() as session:
        uids = (await session.scalars(
            select(BotUser.user_id).where(BotUser.is_blocked.is_(False)))).all()
    sent = failed = 0
    for uid in uids:
        try:
            await _send_post(bot, uid, text, photo_id)
            sent += 1
        except TelegramForbiddenError:
            failed += 1
            async with get_session() as session:
                u = await session.get(BotUser, uid)
                if u:
                    u.is_blocked = True
                    await session.commit()
        except Exception:  # noqa: BLE001
            failed += 1
        await asyncio.sleep(0.05)  # ~20 сообщений/сек — в пределах лимитов Telegram
    try:
        await bot.send_message(
            admin_id, f"✅ Спотлайт разослан.\nДоставлено: {sent}\nНе доставлено: {failed}")
    except Exception:  # noqa: BLE001
        pass


async def _mark_done(sp_id: int) -> None:
    """Отмечает специалиста показанным; когда цикл пройден — начинает заново."""
    elig_ids = {str(s.id) for s in await _eligible()}
    async with get_session() as session:
        m = await session.get(Meta, _DONE_KEY)
        done = set(m.value.split(",")) if m and m.value else set()
        # если остался только текущий (или меньше) — цикл завершён, сбрасываем
        if elig_ids - done <= {str(sp_id)}:
            done = set()
        done.add(str(sp_id))
        await session.merge(Meta(key=_DONE_KEY, value=",".join(done)))
        await session.commit()
