"""Загрузка настроек из файла .env."""
import os
from datetime import datetime
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

# Контакты поддержки для пользователей (вопросы, проблемы, возвраты).
SUPPORT_EMAIL: str = os.getenv("SUPPORT_EMAIL", "") or COMPANY_EMAIL
# Необязательно: публичный Telegram для прямой связи (напр. @username или ссылка).
SUPPORT_TELEGRAM: str = os.getenv("SUPPORT_TELEGRAM", "")

# Канал для анонсов через команду /announce (напр. @mychannel или -100123...).
ANNOUNCE_CHANNEL: str = os.getenv("ANNOUNCE_CHANNEL", "")


def support_block() -> str:
    """Готовый блок с контактами поддержки для вставки в сообщения."""
    lines = [f"✉️ E-mail: {SUPPORT_EMAIL}"]
    if SUPPORT_TELEGRAM:
        lines.append(f"💬 Telegram: {SUPPORT_TELEGRAM}")
    return "\n".join(lines)


def bot_username() -> str:
    """@username бота без «@» — из BOT_URL (для реферальных ссылок и подписи)."""
    return BOT_URL.rstrip("/").rsplit("/", 1)[-1] if BOT_URL else ""


def bot_handle() -> str:
    """@username бота — для подписи под ответами."""
    u = bot_username()
    return f"@{u}" if u else ""

# --- Искусственный интеллект (Claude) ---------------------------------------
# Ключ берётся в консоли Anthropic: https://console.anthropic.com/ → API Keys.
# Если ключа нет — бот продолжит работать на правилах, просто без «живого» ИИ.
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
# Модель: Haiku — быстрая и дешёвая. Используется для служебной классификации
# запросов (какой специалист/город), где важна не грамотность, а скорость/цена.
AI_MODEL: str = os.getenv("AI_MODEL", "claude-haiku-4-5-20251001")
# Модель для ОТВЕТОВ пользователям (свободный чат, калькулятор зарплаты,
# события/афиша): Haiku 4.5 — дёшево и достаточно для комьюнити-помощника.
# Можно переопределить через .env.
AI_CHAT_MODEL: str = os.getenv("AI_CHAT_MODEL", "claude-haiku-4-5-20251001")
# Модель для разбора писем по фото (vision) — тут важнее качество, держим Sonnet.
AI_VISION_MODEL: str = os.getenv("AI_VISION_MODEL", "claude-sonnet-4-6")
# Модель для генерации постов в канал (/post) — качество важнее цены, постов мало.
AI_POST_MODEL: str = os.getenv("AI_POST_MODEL", "claude-sonnet-4-6")
# Фотосток для картинок к постам: достаточно одного ключа (Pexels проще). Пусто = без фото.
PEXELS_API_KEY: str = os.getenv("PEXELS_API_KEY", "")
UNSPLASH_ACCESS_KEY: str = os.getenv("UNSPLASH_ACCESS_KEY", "")
# Вебхук Make для авто-публикации Instagram-каруселей (бот шлёт туда JSON со
# слайдами и подписью, Make рисует слайды и публикует). Пусто = функция выключена.
MAKE_WEBHOOK_URL: str = os.getenv("MAKE_WEBHOOK_URL", "")

# Веб-поиск для ИИ — даёт свежую информацию (актуальные цифры, правила, новости).
# 1/true — включён (по умолчанию). 0/false — выключить.
AI_WEB_SEARCH: bool = os.getenv("AI_WEB_SEARCH", "1").strip().lower() in (
    "1", "true", "yes", "on", "да",
)
# Сколько поисков максимум за один ответ (защита от лишних расходов).
try:
    AI_WEB_MAX_USES: int = int(os.getenv("AI_WEB_MAX_USES", "2"))
except ValueError:
    AI_WEB_MAX_USES = 2

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
# Лояльный тариф для «старожилов» — карточек из старого бессрочного контакт-гайда
LISTING_PRICE_MONTH_LEGACY: str = os.getenv("LISTING_PRICE_MONTH_LEGACY", "4.99")
LISTING_PRICE_YEAR_LEGACY: str = os.getenv("LISTING_PRICE_YEAR_LEGACY", "29.00")
# Цена размещения одного мероприятия в афише месяца (строкой, как требует Mollie)
AFISHA_PRICE: str = os.getenv("AFISHA_PRICE", "25.00")
# Доска объявлений: цена «поднять наверх» (строкой, как требует Mollie)
BOARD_BUMP_PRICE: str = os.getenv("BOARD_BUMP_PRICE", "4.99")
# Доска: символическая плата за размещение жилья (анти-скам). "" / "0" = бесплатно.
BOARD_HOUSING_PRICE: str = os.getenv("BOARD_HOUSING_PRICE", "2.99")
# Дедлайн оплаты для бессрочных карточек из старого гайда (после — скрываем из поиска)
GRANDFATHER_DEADLINE: str = os.getenv("GRANDFATHER_DEADLINE", "2026-06-30")


def grandfather_deadline() -> "datetime":
    """Момент, до которого старым карточкам нужно оплатить размещение (конец дня)."""
    from datetime import datetime as _dt
    try:
        d = _dt.strptime(GRANDFATHER_DEADLINE, "%Y-%m-%d")
    except ValueError:
        d = _dt(2026, 6, 30)
    return d.replace(hour=23, minute=59, second=59)


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


LISTING_DAYS_MONTH: int = _int_env("LISTING_DAYS_MONTH", 30)
LISTING_DAYS_YEAR: int = _int_env("LISTING_DAYS_YEAR", 365)

# Доска объявлений: срок жизни объявления и лимит активных у одного пользователя
BOARD_LISTING_DAYS: int = _int_env("BOARD_LISTING_DAYS", 30)
BOARD_MAX_ACTIVE: int = _int_env("BOARD_MAX_ACTIVE", 5)


def plan_info(plan: str) -> dict:
    """Данные тарифа: цена, период, премиум-флаг и подпись.

    plan: 'month' | 'year' | 'month_premium' | 'year_premium'.
    """
    premium = plan.endswith("_premium")
    legacy = plan.endswith("_legacy")
    if plan.startswith("month"):
        if legacy:
            price = LISTING_PRICE_MONTH_LEGACY
        else:
            price = LISTING_PRICE_MONTH_PREMIUM if premium else LISTING_PRICE_MONTH
        days, title = LISTING_DAYS_MONTH, "месяц"
    else:
        if legacy:
            price = LISTING_PRICE_YEAR_LEGACY
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


# --- Счета на e-mail (Resend) -----------------------------------------------
RESEND_API_KEY: str = os.getenv("RESEND_API_KEY", "")
# Отправитель письма со счётом. Для боевого — адрес на verified-домене в Resend,
# например "Podslushano <facturen@podslushano.nl>". Для теста — onboarding@resend.dev.
INVOICE_FROM_EMAIL: str = os.getenv("INVOICE_FROM_EMAIL", "")
# Ставка BTW (НДС), % — цена считается ВКЛЮЧАЮЩЕЙ этот процент.
try:
    BTW_PERCENT: float = float(os.getenv("BTW_PERCENT", "21"))
except ValueError:
    BTW_PERCENT = 21.0

# Отправка счёта через Gmail (SMTP) — без DNS. Нужен App Password Google.
GMAIL_ADDRESS: str = os.getenv("GMAIL_ADDRESS", "") or COMPANY_EMAIL
GMAIL_APP_PASSWORD: str = os.getenv("GMAIL_APP_PASSWORD", "")


def invoice_enabled() -> bool:
    gmail = bool(GMAIL_ADDRESS and GMAIL_APP_PASSWORD)
    resend = bool(RESEND_API_KEY and INVOICE_FROM_EMAIL)
    return gmail or resend


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
