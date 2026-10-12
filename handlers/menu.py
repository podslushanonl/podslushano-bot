"""Главное меню — одна карточка с кнопками, разделы открываются в ней же.

Внизу экрана остаётся одна кнопка «☰ Меню» (и /menu): она присылает карточку
заново. Разделы ведут в уже существующие сценарии — их функции вызываются от имени
пользователя (в колбэке callback.message.from_user — это бот, поэтому подставляем
настоящего пользователя).
"""
from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import config
from keyboards.menus import BTN_MENU, main_menu

router = Router()
router.message.filter(F.chat.type == ChatType.PRIVATE)

CARD_TEXT = (
    "<b>podslushano.nl</b> · жизнь в Нидерландах в одном месте\n\n"
    "Выберите раздел или просто напишите вопрос: BSN, DigiD, налоги, жильё, врачи. Отвечу по делу."
)
SECTION_TEXT = {
    "services": "<b>🛠 Сервисы</b>\n\nРазберу письмо по фото и посчитаю зарплату на руки.",
    "biz": "<b>💼 Для бизнеса</b>\n\nКарточка в гайде специалистов, событие в афише, реклама у нас.",
    "more": "<b>☰ Ещё</b>\n\nСвязаться с командой, поделиться ботом, сайт и документы.",
}


def _b(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def card_kb(section: str = "main") -> InlineKeyboardMarkup:
    back = [_b("⬅️ Назад", "m:main")]
    if section == "services":
        rows = [[_b("📩 Разобрать письмо", "m:go:letter")], [_b("🧮 Калькулятор зарплаты", "m:go:salary")]]
        if config.STICKER_PACK_URL:
            rows.append([InlineKeyboardButton(text="🎨 Наши стикеры", url=config.STICKER_PACK_URL)])
        return InlineKeyboardMarkup(inline_keyboard=rows + [back])
    if section == "biz":
        rows = []
        if config.payments_enabled():
            rows += [[_b("➕ Добавить себя в гайд", "m:go:selfadd")], [_b("📅 Добавить событие в афишу", "m:go:afisha_add")]]
        rows += [[_b("👤 Кабинет специалиста", "m:go:cabinet")], [_b("📢 Реклама и сотрудничество", "m:go:ad")]]
        return InlineKeyboardMarkup(inline_keyboard=rows + [back])
    if section == "more":
        rows = [[_b("✉️ Связаться с нами", "m:go:contact")], [_b("📣 Поделиться ботом", "m:go:share")],
                [InlineKeyboardButton(text="🌐 Сайт podslushano.nl", url=config.SITE_URL)],
                [InlineKeyboardButton(text="📄 Конфиденциальность", url=config.privacy_url()),
                 InlineKeyboardButton(text="📄 Условия", url=config.terms_url())]]
        return InlineKeyboardMarkup(inline_keyboard=rows + [back])
    return InlineKeyboardMarkup(inline_keyboard=[
        [_b("🔍 Найти специалиста", "m:go:contacts"), _b("📅 Афиша", "m:go:events")],
        [_b("📋 Объявления", "m:go:board"), _b("📚 Жизнь в Нидерландах", "m:go:guide")],
        [_b("✍️ Предложка", "m:go:submit"), _b("🚆 Поезда NS", "m:go:trains")],
        [_b("👤 Мой podslushano.nl", "m:go:home")],
        [_b("🛠 Сервисы", "m:services"), _b("💼 Для бизнеса", "m:biz"), _b("☰ Ещё", "m:more")],
    ])


async def send_card(message: Message, section: str = "main", refresh_keyboard: bool = False) -> None:
    """Присылает карточку меню. refresh_keyboard — заодно заменить старую большую клавиатуру."""
    if refresh_keyboard:
        await message.answer("Меню теперь в одной карточке 👇", reply_markup=main_menu())
    await message.answer(SECTION_TEXT.get(section, CARD_TEXT), reply_markup=card_kb(section),
                         disable_web_page_preview=True)


@router.message(F.text == BTN_MENU)
async def menu_button(message: Message, state: FSMContext) -> None:
    await state.clear()
    await send_card(message)


@router.callback_query(F.data.in_({"m:main", "m:services", "m:biz", "m:more"}))
async def switch_section(callback: CallbackQuery) -> None:
    section = callback.data.split(":", 1)[1]
    try:
        await callback.message.edit_text(SECTION_TEXT.get(section, CARD_TEXT), reply_markup=card_kb(section),
                                         disable_web_page_preview=True)
    except Exception:  # noqa: BLE001 — старое сообщение нельзя изменить: пришлём новое
        await send_card(callback.message, section)
    await callback.answer()


def _entries() -> dict:
    """Ключ кнопки → функция раздела (message, state). Импорт здесь, чтобы не было циклов."""
    from handlers import board, cabinet, contacts, events, guides, home, letters, salary, selfadd, share, submissions, support
    from handlers.afisha import afisha_add_start
    from utils.ns_alerts import cmd_trains

    async def trains(message, state):
        await state.clear()
        await cmd_trains(message)

    return {
        "contacts": contacts.ask_query, "events": events.events_start, "board": board.board_open,
        "guide": guides.show_menu, "submit": submissions.submit_menu, "trains": trains, "home": home.home_open,
        "letter": letters.letter_start, "salary": salary.salary_start, "selfadd": selfadd.self_start,
        "afisha_add": afisha_add_start, "cabinet": cabinet.cabinet_open, "ad": submissions.ask_ad,
        "contact": support.contact_start, "share": share.share,
    }


@router.callback_query(F.data.startswith("m:go:"))
async def open_entry(callback: CallbackQuery, state: FSMContext) -> None:
    fn = _entries().get(callback.data[5:])
    await callback.answer()
    if not fn:
        await send_card(callback.message)
        return
    # Сообщение карточки отправил бот: подставляем пользователя, чтобы разделы видели его id
    as_user = callback.message.model_copy(update={"from_user": callback.from_user, "text": None})
    await fn(as_user, state)
