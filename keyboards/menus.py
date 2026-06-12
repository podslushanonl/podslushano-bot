"""Кнопки и меню бота."""
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

# Тексты пунктов главного меню (используются и для кнопок, и для распознавания)
BTN_STORY = "📰 Прислать историю / сплетню"
BTN_QUESTION = "❓ Задать вопрос (предложка)"
BTN_VIDEO = "🎬 Прислать видео"
BTN_AD = "📢 Реклама / сотрудничество"
BTN_CONTACTS = "🔍 Найти специалиста"
BTN_CANCEL = "❌ Отмена"


def main_menu() -> ReplyKeyboardMarkup:
    """Главное меню с кнопками внизу экрана."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_STORY)],
            [KeyboardButton(text=BTN_QUESTION), KeyboardButton(text=BTN_VIDEO)],
            [KeyboardButton(text=BTN_AD)],
            [KeyboardButton(text=BTN_CONTACTS)],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выбери пункт меню 👇",
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
