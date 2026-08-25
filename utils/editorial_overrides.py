"""Focused evening editorial themes + on-demand admin previews."""
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import config
from utils import editorial_channel as editorial

router = Router()


async def _focused_evening_post() -> str | None:
    recent = await editorial._recent_topics()
    system = (
        "Ты вечерний редактор Telegram-канала для русскоязычных людей, которые уже живут в Нидерландах. "
        "В 21:00 выходит один живой пост. Разрешены ТОЛЬКО две рубрики, их нужно чередовать по смыслу: "
        "1) «История одного места/предмета» — выбери конкретное место, здание, улицу, сооружение, предмет, "
        "знак, элемент городской среды или повседневную вещь в Нидерландах и расскажи неожиданную, проверяемую историю; "
        "2) «Почему здесь так?» — возьми конкретную деталь повседневной жизни в Нидерландах, которую люди замечают, "
        "но редко понимают, и объясни, почему она устроена именно так. Это НЕ новости и НЕ подборка. "
        "Не используй банальности про уровень моря, велосипеды, тюльпаны, кофешопы, красные фонари, мельницы, "
        "деревянные башмаки и прямолинейность голландцев. Не начинай с «А вы знали?». "
        "Сначала сильная конкретная деталь или вопрос, затем история/объяснение. Факты обязательно проверяй веб-поиском. "
        "500-850 знаков. Человеческий русский язык, без маркетингового CTA, markdown и HTML."
    )
    result = await editorial._generate(
        system,
        f"Сегодня {editorial._now():%d.%m.%Y}. Не повторяй последние темы: {', '.join(recent) or 'нет'}.",
        editorial.EVENING_SOURCES,
        800,
    )
    return result[0] if result else None


def install() -> None:
    # The scheduler resolves editorial._evening_post at runtime, so replacing it here
    # narrows the 21:00 slot without duplicating the scheduler.
    editorial._evening_post = _focused_evening_post


def _preview_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌦 Утренний бриф", callback_data="edtest:morning")],
        [InlineKeyboardButton(text="🎭 Мероприятие", callback_data="edtest:event")],
        [InlineKeyboardButton(text="💡 Познавательный пост", callback_data="edtest:curiosity")],
        [InlineKeyboardButton(text="🌙 Вечерний пост 21:00", callback_data="edtest:evening")],
    ])


@router.message(Command("editorialpreview"))
async def editorial_preview_command(message: Message) -> None:
    if message.from_user.id not in config.ADMIN_IDS:
        return
    await message.answer(
        "👀 <b>Предпросмотр следующих редакционных постов</b>\n\n"
        "Выберите формат. Бот сделает свежий веб-поиск и пришлёт реальный черновик. "
        "Сам по себе тест ничего в канал не публикует.",
        reply_markup=_preview_menu(),
    )


@router.callback_query(F.data.startswith("edtest:"), F.from_user.id.in_(config.ADMIN_IDS))
async def editorial_preview_callback(callback: CallbackQuery) -> None:
    kind = callback.data.split(":", 1)[1]
    generators = {
        "morning": (editorial._morning_brief, False),
        "event": (editorial._event_spotlight, True),
        "curiosity": (editorial._curiosity_post, False),
        "evening": (_focused_evening_post, False),
    }
    selected = generators.get(kind)
    if not selected:
        await callback.answer("Неизвестный формат", show_alert=True)
        return
    await callback.answer("Готовлю свежий черновик…")
    generator, button = selected
    text = await generator()
    if not text:
        await callback.message.answer("Не удалось получить проверенный материал. Ничего не опубликовано.")
        return
    await editorial._send_for_approval(callback.bot, kind, text, button)
