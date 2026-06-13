"""Кнопки и меню бота."""
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

import config

# Тексты пунктов главного меню (используются и для кнопок, и для распознавания)
BTN_STORY = "📰 Прислать историю / сплетню"
BTN_QUESTION = "❓ Задать вопрос (предложка)"
BTN_VIDEO = "🎬 Прислать видео"
BTN_AD = "📢 Реклама / сотрудничество"
BTN_CONTACTS = "🔍 Найти специалиста"
BTN_GUIDE = "📚 Полезное о жизни в NL"
BTN_LETTER = "📩 Разобрать письмо"
BTN_SALARY = "🧮 Калькулятор зарплаты"
BTN_SELF_ADD = "➕ Добавить себя в гайд"
BTN_STICKERS = "🎨 Наши стикеры"
BTN_CONTACT = "✉️ Связаться с нами"
BTN_SHARE = "📣 Поделиться ботом"
BTN_CANCEL = "❌ Отмена"


def main_menu() -> ReplyKeyboardMarkup:
    """Главное меню с кнопками внизу экрана."""
    keyboard = [
        [KeyboardButton(text=BTN_STORY)],
        [KeyboardButton(text=BTN_QUESTION), KeyboardButton(text=BTN_VIDEO)],
        [KeyboardButton(text=BTN_AD)],
        [KeyboardButton(text=BTN_CONTACTS)],
        [KeyboardButton(text=BTN_GUIDE)],
        [KeyboardButton(text=BTN_LETTER), KeyboardButton(text=BTN_SALARY)],
    ]
    # Кнопка платного само-добавления — только если подключена оплата
    if config.payments_enabled():
        keyboard.append([KeyboardButton(text=BTN_SELF_ADD)])
    # Кнопка стикерпака — только если задана ссылка в настройках
    if config.STICKER_PACK_URL:
        keyboard.append([KeyboardButton(text=BTN_STICKERS)])
    keyboard.append([KeyboardButton(text=BTN_CONTACT), KeyboardButton(text=BTN_SHARE)])
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
        input_field_placeholder="Выбери пункт меню 👇",
    )


def stickers_button() -> InlineKeyboardMarkup:
    """Inline-кнопка-ссылка на стикерпак (добавляется в один тап)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎨 Добавить стикерпак", url=config.STICKER_PACK_URL)]
        ]
    )


def cancel_menu() -> ReplyKeyboardMarkup:
    """Клавиатура с одной кнопкой «Отмена» во время заполнения заявки."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BTN_CANCEL)]],
        resize_keyboard=True,
    )


# Варианты формата для анкеты рекламы (текст кнопок = ответ пользователя)
AD_FORMATS = [
    "📰 Пост в ленте",
    "📲 Сторис",
    "🎬 Видео / Reels",
    "🧩 Несколько форматов",
    "🤔 Пока не уверен(а)",
]


def ad_format_menu() -> ReplyKeyboardMarkup:
    """Кнопки выбора формата размещения в анкете рекламы."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=AD_FORMATS[0]), KeyboardButton(text=AD_FORMATS[1])],
            [KeyboardButton(text=AD_FORMATS[2]), KeyboardButton(text=AD_FORMATS[3])],
            [KeyboardButton(text=AD_FORMATS[4])],
            [KeyboardButton(text=BTN_CANCEL)],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выбери формат или напиши свой 👇",
    )


def moderation_buttons(submission_id: int) -> InlineKeyboardMarkup:
    """Кнопки «Одобрить / Отклонить» под заявкой в личке у админа."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Одобрить", callback_data=f"approve:{submission_id}"
                ),
                InlineKeyboardButton(
                    text="❌ Отклонить", callback_data=f"reject:{submission_id}"
                ),
            ]
        ]
    )
