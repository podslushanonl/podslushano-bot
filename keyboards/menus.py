"""Кнопки и меню бота."""
from urllib.parse import quote

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

import config
from utils.season import events_button_label

# Тексты пунктов главного меню (используются и для кнопок, и для распознавания)
BTN_STORY = "📰 Прислать историю / сплетню"
BTN_QUESTION = "❓ Задать вопрос (предложка)"
BTN_VIDEO = "🎬 Прислать видео"
BTN_SUBMIT = "✍️ Спросить / поделиться"
BTN_AD = "📢 Реклама / сотрудничество"
BTN_CONTACTS = "🔍 Найти специалиста"
BTN_BOARD = "📋 Объявления"
BTN_GUIDE = "📚 Полезное о жизни в NL"
BTN_LETTER = "📩 Разобрать письмо"
BTN_SALARY = "🧮 Калькулятор зарплаты"
BTN_SELF_ADD = "➕ Добавить себя в гайд"
BTN_CABINET = "👤 Личный кабинет"
BTN_STICKERS = "🎨 Наши стикеры"
BTN_CONTACT = "✉️ Связаться с нами"
BTN_SHARE = "📣 Поделиться ботом"
BTN_CANCEL = "❌ Отмена"


def main_menu() -> ReplyKeyboardMarkup:
    """Главное меню с кнопками внизу экрана."""
    keyboard = [
        [KeyboardButton(text=BTN_SUBMIT)],
        [KeyboardButton(text=BTN_AD)],
        [KeyboardButton(text=BTN_CONTACTS)],
        [KeyboardButton(text=BTN_BOARD)],
        [KeyboardButton(text=BTN_GUIDE)],
        [KeyboardButton(text=events_button_label())],  # ☀️/🍂/❄️/🌷 Чем заняться
        [KeyboardButton(text=BTN_LETTER), KeyboardButton(text=BTN_SALARY)],
    ]
    # Кнопка платного само-добавления — только если подключена оплата
    if config.payments_enabled():
        keyboard.append([KeyboardButton(text=BTN_SELF_ADD)])
        keyboard.append([KeyboardButton(text=BTN_CABINET)])
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


def feedback_button() -> InlineKeyboardButton:
    """Кнопка «пожаловаться на неверный ответ».

    Низкий порог сообщить об ошибке, когда бот ответил не по теме или не помог,
    но никакого сбоя (исключения) не было — поэтому авто-краш-репорт молчит.
    """
    return InlineKeyboardButton(
        text="🤔 Бот ответил не по теме?", callback_data="report_wrong"
    )


def feedback_kb() -> InlineKeyboardMarkup:
    """Inline-клавиатура с одной кнопкой жалобы на ответ бота."""
    return InlineKeyboardMarkup(inline_keyboard=[[feedback_button()]])


# Текст-приглашение при шеринге бота (используется и в /share, и в кнопках под ответами)
SHARE_TEXT = (
    "Нашёл бота-помощника для русскоязычных в Нидерландах 🇳🇱 "
    "Отвечает на вопросы о жизни тут, объясняет письма по фото, считает зарплату "
    "и ищет специалистов — бесплатно. Советую 👇"
)

# Подпись под содержательными ответами: сохраняет ссылку на бота в пересланном
# или заскриненном сообщении (виральность) — работает и в HTML, и в обычном тексте.
ANSWER_FOOTER = f"\n\n— {config.bot_handle()} · помощник по жизни в Нидерландах 🇳🇱"


def share_button(user_id: int) -> InlineKeyboardButton:
    """Кнопка «Поделиться»: открывает диалог пересылки с ЛИЧНОЙ реферальной
    ссылкой пользователя — так шеринг ещё и растит реферальную петлю."""
    ref = f"https://t.me/{config.bot_username()}?start=ref_{user_id}"
    url = f"https://t.me/share/url?url={quote(ref)}&text={quote(SHARE_TEXT)}"
    return InlineKeyboardButton(text="📣 Поделиться ботом", url=url)


def answer_kb(user_id: int) -> InlineKeyboardMarkup:
    """Под ответом ИИ: «Поделиться» (реферальная ссылка) + «ответил не по теме»."""
    return InlineKeyboardMarkup(
        inline_keyboard=[[share_button(user_id)], [feedback_button()]]
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
    """Кнопки «Одобрить / Отклонить / Ответить» под заявкой в личке у админа."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Одобрить", callback_data=f"approve:{submission_id}"
                ),
                InlineKeyboardButton(
                    text="❌ Отклонить", callback_data=f"reject:{submission_id}"
                ),
            ],
            [InlineKeyboardButton(
                text="✍️ Ответить автору", callback_data=f"subreply:{submission_id}")],
        ]
    )
