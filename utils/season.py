"""Определение текущего сезона — чтобы раздел «Чем заняться» сам обновлялся
(«этим летом / этой осенью…») без правок в коде."""
from datetime import date

_SEASONS = {
    "summer": {"word": "лето", "phrase": "этим летом", "emoji": "☀️"},
    "autumn": {"word": "осень", "phrase": "этой осенью", "emoji": "🍂"},
    "winter": {"word": "зима", "phrase": "этой зимой", "emoji": "❄️"},
    "spring": {"word": "весна", "phrase": "этой весной", "emoji": "🌷"},
}


def current_season(today: date | None = None) -> dict:
    """Возвращает {word, phrase, emoji} для текущего месяца."""
    m = (today or date.today()).month
    if m in (6, 7, 8):
        key = "summer"
    elif m in (9, 10, 11):
        key = "autumn"
    elif m in (12, 1, 2):
        key = "winter"
    else:
        key = "spring"
    return _SEASONS[key]


# Стабильная часть подписи кнопки — по ней матчим нажатие (эмодзи меняется по сезону)
EVENTS_LABEL_CORE = "Афиша"


def events_button_label() -> str:
    """Подпись кнопки меню: «☀️ Афиша» / «🍂 Афиша» и т.д."""
    return f"{current_season()['emoji']} {EVENTS_LABEL_CORE}"
