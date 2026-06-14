"""Раздел «Чем заняться» — афиша и сезонные идеи по городу.

Опирается на живой веб-поиск ИИ: реальные события на ближайшие дни + сезонные
идеи. Сезон определяется по дате автоматически («этим летом / этой осенью…»).
"""
import logging

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from keyboards.menus import ANSWER_FOOTER, cancel_menu, main_menu, share_button
from states.forms import EventsSearch
from utils.ai import ai_enabled, ai_events
from utils.analytics import log_event
from utils.limits import allow_ai
from utils.season import EVENTS_LABEL_CORE, current_season

log = logging.getLogger(__name__)

router = Router()
router.message.filter(F.chat.type == ChatType.PRIVATE)

POPULAR_CITIES = ["Amsterdam", "Rotterdam", "Den Haag", "Utrecht", "Eindhoven", "Groningen"]


def _cities_kb() -> InlineKeyboardMarkup:
    btns = [InlineKeyboardButton(text=c, callback_data=f"ev|{c}") for c in POPULAR_CITIES]
    rows = [btns[i:i + 2] for i in range(0, len(btns), 2)]
    rows.append([InlineKeyboardButton(text="🌍 По всей стране", callback_data="ev|__all__")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _is_events_button(message: Message) -> bool:
    """Кнопка меню «☀️/🍂/❄️/🌷 Чем заняться» — эмодзи меняется по сезону."""
    return bool(message.text) and message.text.endswith(EVENTS_LABEL_CORE)


@router.message(Command("afisha", "events"))
@router.message(_is_events_button)
async def events_start(message: Message, state: FSMContext) -> None:
    if not ai_enabled():
        await message.answer("Раздел пока недоступен 🙏", reply_markup=main_menu())
        return
    s = current_season()
    await state.set_state(EventsSearch.waiting_city)
    await message.answer(
        f"{s['emoji']} Покажу, чем заняться {s['phrase']} 🎉\n\n"
        "В каком городе? Напиши или выбери 👇",
        reply_markup=cancel_menu(),
    )
    await message.answer("📍 Города:", reply_markup=_cities_kb())


@router.callback_query(F.data.startswith("ev|"))
async def events_city_cb(callback: CallbackQuery, state: FSMContext) -> None:
    city = callback.data.split("|", 1)[1]
    await callback.answer()
    await _show_events(callback.message, state, city, uid=callback.from_user.id)


@router.message(EventsSearch.waiting_city)
async def events_city_msg(message: Message, state: FSMContext) -> None:
    city = (message.text or "").strip()
    if not city:
        await message.answer("Напиши город текстом 🙂")
        return
    await _show_events(message, state, city, uid=message.from_user.id)


async def _show_events(message: Message, state: FSMContext, city: str, uid: int) -> None:
    await state.clear()
    if not allow_ai(uid):
        await message.answer(
            "На сегодня уже много запросов 🙏 Загляни попозже.", reply_markup=main_menu()
        )
        return
    s = current_season()
    where = "по всей стране" if city == "__all__" else city
    where_in = "по всей стране" if city == "__all__" else f"в городе {city}"
    # Явно сообщаем, что уже ищем — поиск идёт до минуты, иначе кажется, что бот
    # «завис» и хочется жать кнопку города ещё раз.
    await message.answer(f"🔎 Уже ищу мероприятия {where_in}… Это займёт до минуты ⏳")
    await message.bot.send_chat_action(message.chat.id, action="typing")
    result = await ai_events(city, s["phrase"])
    if not result:
        await message.answer(
            "Не получилось собрать подборку 😔 Попробуй позже или другой город.",
            reply_markup=main_menu(),
        )
        return
    await log_event("events", "__all__" if city == "__all__" else city)
    title = f"{s['emoji']} Чем заняться {s['phrase']} · {where}"
    await message.answer(
        title + "\n\n" + result + ANSWER_FOOTER,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[share_button(uid)]]),
        parse_mode=None,
        disable_web_page_preview=True,
    )
