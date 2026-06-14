"""«Поделиться ботом» + реферальные ссылки (рост).

Каждый пользователь получает личную ссылку t.me/<bot>?start=ref_<id>. Кто
пришёл по ней — запоминается (referred_by), и реферер видит счётчик приглашённых.
"""
from urllib.parse import quote

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import func, select

from database.db import get_session
from database.models import BotUser
from keyboards.menus import BTN_SHARE, SHARE_TEXT, main_menu

router = Router()
router.message.filter(F.chat.type == ChatType.PRIVATE)


async def _invited_count(user_id: int) -> int:
    async with get_session() as session:
        return await session.scalar(
            select(func.count()).select_from(BotUser).where(BotUser.referred_by == user_id)
        ) or 0


@router.message(Command("share", "podelitsya"))
@router.message(F.text == BTN_SHARE)
async def share(message: Message, state: FSMContext) -> None:
    await state.clear()
    me = await message.bot.me()
    uid = message.from_user.id
    ref_link = f"https://t.me/{me.username}?start=ref_{uid}"
    share_url = f"https://t.me/share/url?url={quote(ref_link)}&text={quote(SHARE_TEXT)}"
    invited = await _invited_count(uid)
    tail = (
        f"\n\nПо твоей ссылке уже пришло друзей: <b>{invited}</b> 🙌 Спасибо!"
        if invited else "\n\nПоделись — и помоги друзьям освоиться в NL 💛"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📣 Отправить друзьям", url=share_url)],
    ])
    await message.answer(
        "📣 <b>Поделиться ботом</b>\n\n"
        "Твоя личная ссылка (по ней друзья сразу откроют бота):\n"
        f"{ref_link}{tail}",
        reply_markup=kb,
        disable_web_page_preview=True,
    )
    # вернём обычное меню отдельным касанием, чтобы инлайн-кнопка осталась видимой
    await message.answer("Спасибо, что помогаешь нам расти! 🌱", reply_markup=main_menu())
