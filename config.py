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
# Публикация на сайт (WordPress REST API). WP_URL пусто = берём SITE_URL.
# WP_APP_PASSWORD — «пароль приложения» из WordPress (Профиль → Пароли приложений).
WP_URL: str = os.getenv("WP_URL", "")
WP_USER: str = os.getenv("WP_USER", "")
WP_APP_PASSWORD: str = os.getenv("WP_APP_PASSWORD", "")
# Проверять SSL-сертификат сайта. Поставь 0, если у сайта самоподписанный/
# непроверяемый сертификат и бот не может подключиться (ошибка CERTIFICATE_VERIFY_FAILED).
WP_VERIFY_SSL: bool = os.getenv("WP_VERIFY_SSL", "1").strip().lower() not in (
    "0", "false", "no", "off",
)
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
COMPANY_PHONE: str = os.getenv("COMPANY_PHONE", "+31642484316")
COMPANY_IBAN: str = os.getenv("COMPANY_IBAN", "NL03 MLLE 0090 9700 04")
COMPANY_BIC: str = os.getenv("COMPANY_BIC", "MLLENL2A")

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
# Google Places API (New) — реальные фото КОНКРЕТНЫХ мест для постов (/post) и
# каруселей (/ig). Нужен ключ с включённым Places API и биллингом. Пусто = без фото.
GOOGLE_MAPS_API_KEY: str = os.getenv("GOOGLE_MAPS_API_KEY", "")
# Вебхук Make для авто-публикации Instagram-каруселей (бот шлёт туда JSON с
# готовыми слайдами и подписью, Make публикует). Пусто = функция выключена.
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
# --- Allo Walks (прогулки: разовая или абонемент на 3) -----------------------
# Цены строкой, как требует Mollie. С BTW 21% внутри.
ALLO_PRICE_SINGLE: str = os.getenv("ALLO_PRICE_SINGLE", "35.00")
ALLO_PRICE_PASS: str = os.getenv("ALLO_PRICE_PASS", "90.00")
# Абонемент: сколько прогулок и сколько дней он действует (прогулки на выбор).
ALLO_PASS_CREDITS: int = 3
try:
    ALLO_PASS_VALID_DAYS: int = int(os.getenv("ALLO_PASS_VALID_DAYS", "62"))
except ValueError:
    ALLO_PASS_VALID_DAYS = 62
# Реферальный бонус: сколько € получает приводящий за каждого оплатившего друга,
# и минимальный остаток к оплате после скидки (Mollie не примет 0).
ALLO_REFERRAL_BONUS: int = 10
ALLO_MIN_CHARGE: float = 5.0
try:
    ALLO_WALK_CAPACITY: int = int(os.getenv("ALLO_WALK_CAPACITY", "7"))
except ValueError:
    ALLO_WALK_CAPACITY = 7
# Закрытый чат участников — ссылку шлём каждому после оплаты.
ALLO_CHAT_URL: str = os.getenv("ALLO_CHAT_URL", "https://t.me/+peVFBZ4hOdY1ZDg6")
# Расписание прогулок. key — устойчивый идентификатор (дата), по нему считаем места.
ALLO_WALKS: list[dict] = [
    {
        "key": "2026-07-25",
        "date": "25 июля · суббота",
        "title": "Nijmegen + Ooijpolder",
        "meet": "Nijmegen Centraal · 11:00",
        "finish": "центр Nijmegen / Waalkade",
        "dur": "≈4–5 часов",
        "desc": ("Wandelroute Ooijpolder (7,5 км): река Waal, uiterwaarden, коники, "
                 "старые кирпичные заводы и виды. Природный маршрут, часть — по "
                 "грунтовым тропам. Собаки — на поводке."),
    },
    {
        "key": "2026-08-08",
        "date": "8 августа · суббота",
        "title": "Utrecht — каналы и werven",
        "meet": "Utrecht Centraal · 11:00",
        "finish": "центр Utrecht / Oudegracht",
        "dur": "≈3 часа + кофе",
        "desc": ("Wandelroute «Grachten en Werven» (2,6 км): каналы Oudegracht, werven "
                 "и werfkelders, Dom, Stadhuis. Лёгкая городская прогулка + кофе у воды."),
    },
]


def allo_walk(key: str) -> dict | None:
    """Прогулка по ключу-дате, или None."""
    return next((w for w in ALLO_WALKS if w["key"] == key), None)


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


# --- Реферальная программа в гайде ------------------------------------------
# Скидка приглашённому специалисту на ГОДОВОЕ размещение (Стандарт/Премиум).
REFERRAL_DISCOUNT: float = 0.20
# Награда пригласившему: бонусный Премиум на столько дней.
REFERRAL_PREMIUM_DAYS: int = _int_env("REFERRAL_PREMIUM_DAYS", 90)


def discounted_price(price: str, discount: float = REFERRAL_DISCOUNT) -> str:
    """Цена со скидкой строкой '12.34' (как требует Mollie)."""
    try:
        return f"{float(price) * (1 - discount):.2f}"
    except ValueError:
        return price


# --- Рекламные форматы (страница брони /ads с календарём и оплатой) ----------
# key -> название, бейдж, краткое описание (lead), состав (details), для кого
# (who) и варианты длительности с ценами (options, цены вкл. BTW, строкой).
AD_FORMATS: dict[str, dict] = {
    "expert": {
        "name": "Эксперт месяца", "badge": "⭐ Рекомендуем",
        "lead": "Постоянное присутствие и поток клиентов из поиска в боте. Абонемент.",
        "details": [
            "топ выдачи в боте с пометкой «⭐ Рекомендуем» — когда человек ищет специалиста в вашей категории, он видит вас первым весь срок",
            "нативный экспертный пост (проблема → решение) в Instagram + дубль в Telegram",
            "сторис-поддержка",
            "«вопрос эксперту» — отвечаете на реальный вопрос аудитории",
            "статус «Эксперт месяца»",
        ],
        "who": "юристам, бухгалтерам, риелторам, психологам, страховым, мастерам, локальным сервисам и экспертам",
        "options": [
            {"key": "1m", "label": "1 месяц", "price": "99.00"},
            {"key": "3m", "label": "3 месяца — выгоднее", "price": "249.00"},
        ],
    },
    "promo": {
        "name": "Продвижение", "badge": "Популярное",
        "lead": "Кампания на 2 месяца: 4 нативных касания в Instagram и Telegram.",
        "details": [
            "4 публикации в Instagram (нативная подача: проблема → решение)",
            "вы выбираете 4 даты выхода (минимум 14 дней между ними)",
            "2 сторис к каждой публикации",
            "Telegram-пост и присутствие в канале 2 месяца",
            "адаптация подачи под аудиторию",
        ],
        "who": "услугам, экспертам, локальным бизнесам и проектам",
        "options": [{"key": "std", "label": "4 выхода / 2 месяца", "price": "180.00"}],
        "dates": 4,   # требуется выбрать 4 даты
    },
    "tg": {
        "name": "Telegram-пост", "badge": "",
        "lead": "Рекламный пост в Telegram-канале с закрепом на 7 дней.",
        "details": [
            "1 рекламный пост в Telegram-канале",
            "закрепление поста на 7 дней",
            "адаптация текста под аудиторию",
            "ссылка, контакт или CTA",
        ],
        "who": "услугам, мероприятиям, срочным анонсам, акциям и локальным предложениям",
        "options": [{"key": "std", "label": "1 пост + закреп 7 дней", "price": "75.00"}],
        "addon": {"key": "repeat",
                  "label": "Повторная публикация через 14 дней (тот же пост)",
                  "price": "25.00"},
    },
    "afisha": {
        "name": "Афиша", "badge": "",
        "lead": "Анонс события в Instagram (пост-анонс).",
        "details": [
            "пост-анонс события в Instagram",
            "сторис-поддержка",
            "краткое описание, дата, город и стоимость",
        ],
        "who": "мероприятиям, концертам, экскурсиям, мастер-классам, лекциям, вечеринкам",
        "options": [{"key": "std", "label": "Instagram", "price": "35.00"}],
    },
    "afisha_plus": {
        "name": "Афиша+", "badge": "Расширенный",
        "lead": "Анонс в Instagram + размещение в «Афише месяца» в Telegram-боте.",
        "details": [
            "всё из «Афиши»",
            "размещение в подборке «Афиша месяца» в Telegram-боте",
            "дополнительная сторис-поддержка",
            "ссылка на билеты или регистрацию",
        ],
        "who": "событиям, где важны продажи билетов и регистрация",
        "options": [{"key": "std", "label": "Instagram + Telegram-бот", "price": "65.00"}],
    },
}


def ad_option(fmt: str, opt: str) -> dict | None:
    """Вариант формата (длительность) по ключам, или None."""
    f = AD_FORMATS.get(fmt)
    if not f:
        return None
    return next((o for o in f["options"] if o["key"] == opt), None)


def ad_addon(fmt: str) -> dict | None:
    """Опциональная доп-услуга формата (напр. повторная публикация) или None."""
    return (AD_FORMATS.get(fmt) or {}).get("addon")


# Условия сотрудничества (показываются на странице /ads). (заголовок, текст).
AD_TERMS: list[tuple[str, str]] = [
    ("1. Общие положения", "Каждое размещение является отдельным соглашением между сторонами. Предыдущие договорённости и условия не применяются автоматически к новым размещениям."),
    ("2. Принятие условий", "Оплата инвойса или платёжной ссылки означает полное согласие с данными условиями. Переписка (Instagram Direct, Telegram, Email) имеет юридическую силу и фиксирует договорённости сторон."),
    ("3. Оплата и бронирование", "100% предоплата обязательна. Слот (дата публикации) фиксируется только после оплаты. Без оплаты дата не резервируется."),
    ("4. Формат размещения", "Формат, объём и состав размещения согласовываются отдельно и фиксируются в переписке или инвойсе."),
    ("5. Срок размещения", "Срок размещения определяется текущим форматом. Если срок не зафиксирован отдельно, услуга считается выполненной с момента публикации."),
    ("6. Публикация и график", "Дата и время публикации могут корректироваться редакцией при необходимости."),
    ("7. Материалы и контент", "Материалы предоставляются не позднее чем за 48 часов до публикации. Рекламодатель несёт ответственность за достоверность информации. Редакция вправе адаптировать материалы под формат площадки."),
    ("8. Согласование", "Если рекламодатель не предоставил правки до публикации, материал считается согласованным. После публикации правки не принимаются."),
    ("9. Удаление и изменение публикаций", "Публикации могут быть изменены, архивированы или удалены по усмотрению редакции или в связи с особенностями платформ. Это не является основанием для возврата средств."),
    ("10. Результаты и KPI", "Мы не гарантируем: количество подписчиков, продажи, заявки. Охваты зависят от алгоритмов платформ."),
    ("11. Отказ от сотрудничества", "В случае отказа рекламодателя после оплаты возврат средств не производится."),
    ("12. Досрочное прекращение", "Перерасчёт возможен только за неоказанную часть услуг. Фактически выполненные публикации подлежат полной оплате."),
    ("13. Возвраты", "Возврат средств возможен только за неоказанные услуги. Комиссии платёжных систем не возвращаются."),
    ("14. Ответственность сторон", "Рекламодатель несёт ответственность за содержание рекламы. Редакция вправе отказать в размещении без объяснения причин."),
    ("15. Платформы и алгоритмы", "Редакция не несёт ответственность за изменения алгоритмов, охватов или технические ограничения сторонних платформ."),
    ("16. Использование материалов", "Редакция вправе использовать рекламные материалы в портфолио и маркетинговых целях."),
    ("17. Юридическая информация", "Все цены указаны с учётом НДС 21%. К отношениям сторон применяется законодательство Нидерландов."),
    ("18. Потребители (физические лица)", "Для физических лиц действует право на отзыв договора в течение 14 дней. Выбирая дату публикации и оформляя оплату, вы соглашаетесь на немедленное начало оказания услуги. Если на момент отзыва публикация ещё не вышла — возвращаем уплаченное за неоказанную часть; после полной или частичной публикации возврат за опубликованную часть не производится."),
]


def ad_company_block_html() -> str:
    """Реквизиты исполнителя для условий на странице рекламы."""
    return (
        f"<b>{COMPANY_NAME}</b><br>{COMPANY_ADDRESS}<br>"
        f"KVK: {COMPANY_KVK} · BTW: {COMPANY_BTW}<br>"
        f"{COMPANY_EMAIL} · {COMPANY_PHONE}<br>{SITE_URL}"
    )


# Минимальный интервал между датами в формате с несколькими выходами (дней)
AD_MULTI_MIN_GAP_DAYS: int = 14

# Аудитория в цифрах для страницы рекламы (обновлять ~раз в квартал). (число, подпись).
AD_STATS_UPDATED: str = "июнь 2026"
AD_STATS: list[tuple[str, str]] = [
    ("76 900", "подписчиков в Instagram"),
    ("3 870", "подписчиков в Telegram"),
    ("3,7 млн", "просмотров в месяц"),
    ("209 тыс.", "взаимодействий в месяц"),
    ("64% / 36%", "женщины / мужчины"),
    ("🇳🇱 NL", "русскоязычная аудитория"),
]

# Частые вопросы на странице рекламы. (вопрос, ответ).
AD_FAQ: list[tuple[str, str]] = [
    ("Как происходит оплата?",
     "Через Mollie (iDEAL, карты). Оплата — 100% предоплата; дата выхода фиксируется только после оплаты."),
    ("Как выбрать дату?",
     "В календаре доступны только свободные даты. В «Продвижении» нужно выбрать 4 даты с интервалом минимум 14 дней."),
    ("Кто готовит материал?",
     "Зависит от формата: мы помогаем с подачей и адаптируем текст под аудиторию. Материалы предоставляются не позднее чем за 48 часов до публикации."),
    ("Можно ли вернуть деньги?",
     "За уже опубликованную (полностью или частично) рекламу возврата нет. Для физлиц действует 14-дневное право на отзыв до публикации — возвращаем за неоказанную часть."),
    ("Даёте ли вы статистику охватов?",
     "Да, по запросу пришлём актуальную статистику аудитории и охватов перед размещением."),
    ("На каком языке вводить данные для счёта?",
     "Латиницей, как в документах (например, Alex Mair) — иначе фактура будет некорректной."),
]


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
