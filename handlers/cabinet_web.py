"""/start cabinet_web: a sign-in link to the business cabinet on the website."""
from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import func, select

from database.db import get_session
from database.models import Specialist
from utils.site_api import telegram_login_link

router = Router()


@router.message(CommandStart(deep_link=True), F.text.endswith(" cabinet_web"))
async def cabinet_web_link(message: Message) -> None:
    uid = message.from_user.id
    async with get_session() as session:
        count = await session.scalar(select(func.count(Specialist.id)).where(
            Specialist.submitter_user_id == uid, Specialist.status != "deleted"))
    if not count:
        await message.answer(
            "К вашему Telegram не привязано ни одной карточки. "
            "Если карточка оформлялась на сайте, войдите по почте, указанной для счёта.")
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Открыть кабинет на сайте", url=telegram_login_link(uid))]])
    await message.answer("Ссылка для входа в кабинет бизнеса. Она действует один час.", reply_markup=kb)
