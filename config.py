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
# Ссылка на бота (для кнопки «Вернуться в Telegram» на странице оплаты)
BOT_URL: str = os.getenv("BOT_URL", "https://t.me/podslushano_nl_bot")
# Публичная ссылка на логотип (показывается на странице оплаты). Пусто = без лого.
LOGO_URL: str = os.getenv("LOGO_URL", "")

# Реквизиты компании (для юридических страниц)
COMPANY_NAME: str = os.getenv("COMPANY_NAME", "Podslushano.nl")
COMPANY_EMAIL: str = os.getenv("COMPANY_EMAIL", "podslushano.nl@gmail.com")
COMPANY_KVK: str = os.getenv("COMPANY_KVK", "98882317")
COMPANY_BTW: str = os.getenv("COMPANY_BTW", "NL005359099B74")
COMPANY_ADDRESS: str = os.getenv(
    "COMPANY_ADDRESS", "Karel Doormanstraat 63, 5342 TJ Oss, Nederland"
)

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

# --- Платное само-добавление в гайд (Mollie) --------------------------------
# Ключ Mollie (test_... или live_...). Без него платный поток выключен.
MOLLIE_API_KEY: str = os.getenv("MOLLIE_API_KEY", "")
# Тарифы размещения: месяц и год (цена строкой, как требует Mollie)
LISTING_CURRENCY: str = os.getenv("LISTING_CURRENCY", "EUR")
LISTING_PRICE_MONTH: str = os.getenv("LISTING_PRICE_MONTH", "9.99")
LISTING_PRICE_YEAR: str = os.getenv("LISTING_PRICE_YEAR", "99.00")
# Премиум-тарифы (карточка выше в выдаче + бейдж)
LISTING_PRICE_MONTH_PREMIUM: str = os.getenv("LISTING_PRICE_MONTH_PREMIUM", "19.99")
LISTING_PRICE_YEAR_PREMIUM: str = os.getenv("LISTING_PRICE_YEAR_PREMIUM", "199.00")


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


LISTING_DAYS_MONTH: int = _int_env("LISTING_DAYS_MONTH", 30)
LISTING_DAYS_YEAR: int = _int_env("LISTING_DAYS_YEAR", 365)


def plan_info(plan: str) -> dict:
    """Данные тарифа: цена, период, премиум-флаг и подпись.

    plan: 'month' | 'year' | 'month_premium' | 'year_premium'.
    """
    premium = plan.endswith("_premium")
    if plan.startswith("month"):
        price = LISTING_PRICE_MONTH_PREMIUM if premium else LISTING_PRICE_MONTH
        days, title = LISTING_DAYS_MONTH, "месяц"
    else:
        price = LISTING_PRICE_YEAR_PREMIUM if premium else LISTING_PRICE_YEAR
        days, title = LISTING_DAYS_YEAR, "год"
    if premium:
        title += " 🌟 Премиум"
    return {"plan": plan, "price": price, "days": days, "title": title, "premium": premium}
# Публичный адрес сервиса для webhook оплаты. Railway генерирует домен —
# берём его автоматически, либо можно задать WEBHOOK_BASE_URL вручную.
_railway_domain = os.getenv("RAILWAY_PUBLIC_DOMAIN", "")
WEBHOOK_BASE_URL: str = os.getenv("WEBHOOK_BASE_URL", "") or (
    f"https://{_railway_domain}" if _railway_domain else ""
)
# Порт веб-сервера (Railway задаёт PORT)
try:
    PORT: int = int(os.getenv("PORT", "8080"))
except ValueError:
    PORT = 8080


def payments_enabled() -> bool:
    """Платный поток доступен, если есть ключ Mollie и публичный адрес webhook."""
    return bool(MOLLIE_API_KEY and WEBHOOK_BASE_URL)


def privacy_url() -> str:
    return f"{WEBHOOK_BASE_URL}/privacy" if WEBHOOK_BASE_URL else SITE_URL


def terms_url() -> str:
    return f"{WEBHOOK_BASE_URL}/terms" if WEBHOOK_BASE_URL else SITE_URL


# --- Защита от спама и лимит расходов на ИИ ----------------------------------
# Антифлуд: не больше FLOOD_LIMIT сообщений за FLOOD_WINDOW секунд.
FLOOD_LIMIT: int = _int_env("FLOOD_LIMIT", 6)
FLOOD_WINDOW: int = _int_env("FLOOD_WINDOW", 8)
# Сколько ответов ИИ в день на одного пользователя (0 = без лимита).
AI_DAILY_LIMIT: int = _int_env("AI_DAILY_LIMIT", 40)

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
