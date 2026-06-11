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
