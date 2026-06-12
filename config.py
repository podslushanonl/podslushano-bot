"""Загрузка настроек из файла .env."""
import os
from dotenv import load_dotenv

load_dotenv()


def _parse_admin_ids(raw: str) -> list[int]:
    """Превращает строку "111,222" в список чисел [111, 222]."""
    ids: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            ids.append(int(part))
    return ids


BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
ADMIN_IDS: list[int] = _parse_admin_ids(os.getenv("ADMIN_IDS", ""))
GUIDE_URL: str = os.getenv("GUIDE_URL", "")
# Главный сайт сообщества (показываем на стартовом экране и в приветствии)
SITE_URL: str = os.getenv("SITE_URL", "https://www.podslushano.nl")

# --- Искусственный интеллект (Claude) ---------------------------------------
# Ключ берётся в консоли Anthropic: https://console.anthropic.com/ → API Keys.
# Если ключа нет — бот продолжит работать на правилах, просто без «живого» ИИ.
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
# Модель: Haiku — быстрая и дешёвая, хорошо подходит для чата сообщества.
AI_MODEL: str = os.getenv("AI_MODEL", "claude-haiku-4-5-20251001")

# Веб-поиск для ИИ — даёт свежую информацию (актуальные цифры, правила, новости).
# 1/true — включён (по умолчанию). 0/false — выключить.
AI_WEB_SEARCH: bool = os.getenv("AI_WEB_SEARCH", "1").strip().lower() in (
    "1", "true", "yes", "on", "да",
)
# Сколько поисков максимум за один ответ (защита от лишних расходов).
try:
    AI_WEB_MAX_USES: int = int(os.getenv("AI_WEB_MAX_USES", "4"))
except ValueError:
    AI_WEB_MAX_USES = 4

# --- Стикеры ----------------------------------------------------------------
# Ссылка на ваш стикерпак, например https://t.me/addstickers/ВашПак
# Если задана — в меню появляется кнопка «🎨 Наши стикеры» с этой ссылкой.
# Если пусто — кнопки просто нет, всё остальное работает.
STICKER_PACK_URL: str = os.getenv("STICKER_PACK_URL", "")

# Путь к файлу базы данных SQLite (лежит рядом с проектом)
DB_PATH = os.path.join(os.path.dirname(__file__), "data", "bot.db")
DB_URL = f"sqlite+aiosqlite:///{DB_PATH}"


def validate() -> None:
    """Проверяет, что обязательные настройки заданы. Вызывается при старте."""
    if not BOT_TOKEN or BOT_TOKEN.startswith("123456:"):
        raise RuntimeError(
            "Не задан BOT_TOKEN. Создай файл .env (по образцу .env.example) "
            "и впиши токен от @BotFather."
        )
    if not ADMIN_IDS:
        raise RuntimeError(
            "Не задан ни один ADMIN_IDS. Впиши в .env свой Telegram ID "
            "(узнать можно у @userinfobot)."
        )
