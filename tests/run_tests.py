"""Быстрые проверки критичных инвариантов бота (запуск: python tests/run_tests.py).

Ловят регрессии в том, что уже ломалось: импорт, категории специалистов,
авто-переопределение категории, премиум-приоритет, сохранение премиума/фото
при пересеве. Падает с ненулевым кодом — удобно вешать на хук/CI.
"""
import asyncio
import os
import sys
import tempfile
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# корень проекта в путь (скрипт лежит в tests/)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("BOT_TOKEN", "123456:test")
os.environ.setdefault("ADMIN_IDS", "1")

import config  # noqa: E402

# изолированная временная БД, чтобы не трогать рабочую
config.DB_PATH = os.path.join(tempfile.mkdtemp(), "bot.db")
config.DB_URL = f"sqlite+aiosqlite:///{config.DB_PATH}"

import importlib  # noqa: E402
import database.db as db  # noqa: E402
importlib.reload(db)

from sqlalchemy import select  # noqa: E402
from database.models import (  # noqa: E402
    AnnouncementDelivery,
    AdBooking,
    BotUser,
    ContentClick,
    ContentPost,
    DiscoveredEvent,
    DigestDeliveryLog,
    DigestPreference,
    EventListing,
    Listing,
    Meta,
    NotificationDelivery,
    NotificationPreference,
    NotificationState,
    ProductEvent,
    SavedItem,
    Specialist,
    SpecialistReminderLog,
)

_fails: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    mark = "OK  " if cond else "FAIL"
    print(f"[{mark}] {name}" + (f" — {detail}" if (detail and not cond) else ""))
    if not cond:
        _fails.append(name)


def test_import_bot() -> None:
    import bot  # noqa: F401
    check("импорт bot без ошибок", True)
    check("прямая ссылка открывает добавление специалиста",
          config.specialist_add_url().endswith("?start=selfadd"))
    from keyboards.menus import BTN_HOME, main_menu
    labels = [button.text for row in main_menu().keyboard for button in row]
    check("Мой Podslushano — первый пункт главного меню",
          labels[0] == BTN_HOME)
    from handlers.home import home_digest, home_profile
    check("профиль и подборка используют разные обработчики",
          home_profile is not home_digest)


def test_specialist_premium_six_month_plan() -> None:
    info = config.plan_info("6m_premium")
    check("Премиум на полгода стоит €109", info["price"] == "109.00")
    check("Премиум на полгода действует 182 дня", info["days"] == 182)
    check("тариф на полгода остаётся Премиумом",
          info["premium"] is True and info["title"] == "6 месяцев 🌟 Премиум")

    from handlers.selfadd import _plan_duration_kb
    callbacks = [
        button.callback_data
        for row in _plan_duration_kb("premium").inline_keyboard
        for button in row
    ]
    check("вариант на полгода показан при выборе тарифа",
          "selfplan:6m_premium" in callbacks)

    monthly_total = float(config.LISTING_PRICE_MONTH_PREMIUM) * 6
    six_month = float(info["price"])
    annual_monthly = float(config.LISTING_PRICE_YEAR_PREMIUM) / 12
    check("полугодовой тариф выгоднее шести помесячных оплат",
          six_month < monthly_total)
    check("годовой тариф остаётся самым выгодным в пересчёте на месяц",
          annual_monthly < six_month / 6)


def test_specialist_onboarding_ux() -> None:
    from handlers.selfadd import (
        _build_public_contacts,
        _category_options_kb,
        _contact_hub_kb,
        _normalize_public_contact,
        _plan_duration_kb,
        _preview_text,
        _valid_contact,
        _valid_description,
        _valid_email,
        _valid_name,
    )
    from states.forms import SelfAddSpecialist
    from utils.geo import THEMES

    check("анкета принимает нормальное имя", _valid_name("Anna Nails"))
    check("анкета отклоняет пустое имя", not _valid_name("-"))
    check(
        "анкета принимает содержательное описание",
        _valid_description("Маникюр, педикюр и наращивание. Работаю по записи."),
    )
    check("анкета отклоняет случайный ответ", not _valid_description("выпвпкнл"))
    check("анкета принимает телефон и Telegram", _valid_contact("+31 6 12345678, @username"))
    check("анкета отклоняет текст вместо контакта", not _valid_contact("выпвпкнл"))
    check("анкета принимает корректный e-mail", _valid_email("mail@example.com"))
    check("анкета отклоняет неполный e-mail", not _valid_email("mail@example"))

    contact_data = {
        "sp_contact_instagram": _normalize_public_contact(
            "instagram", "https://instagram.com/anna.nails/"
        ),
        "sp_contact_telegram": _normalize_public_contact("telegram", "@anna_nails"),
        "sp_contact_email": _normalize_public_contact("email", "HELLO@EXAMPLE.COM"),
        "sp_contact_website": _normalize_public_contact("website", "www.example.nl/book"),
        "sp_contact_phone": _normalize_public_contact("phone", "06 12345678"),
    }
    check("Instagram нормализуется в username",
          contact_data["sp_contact_instagram"] == "@anna.nails")
    check("Telegram проверяется отдельно от Instagram",
          contact_data["sp_contact_telegram"] == "@anna_nails")
    check("публичная почта нормализуется",
          contact_data["sp_contact_email"] == "hello@example.com")
    check("сайт получает безопасный https URL",
          contact_data["sp_contact_website"] == "https://example.nl/book")
    check("нидерландский номер получает код страны",
          contact_data["sp_contact_phone"] == "+31612345678")
    check("неверные контакты не принимаются",
          _normalize_public_contact("telegram", "просто текст") is None
          and _normalize_public_contact("website", "не сайт") is None)

    empty_contact_callbacks = [
        button.callback_data
        for row in _contact_hub_kb({}).inline_keyboard
        for button in row
    ]
    filled_contact_buttons = [
        button
        for row in _contact_hub_kb(contact_data).inline_keyboard
        for button in row
    ]
    check("анкета предлагает пять отдельных типов контактов",
          set(empty_contact_callbacks[:5]) == {
              "selfcontact:add:instagram", "selfcontact:add:telegram",
              "selfcontact:add:email", "selfcontact:add:website",
              "selfcontact:add:phone",
          })
    check("без контакта нельзя продолжить",
          "selfcontact:done" not in empty_contact_callbacks)
    check("заполненные контакты отмечены и разрешают продолжить",
          sum(button.text.startswith("✅") for button in filled_contact_buttons) == 5
          and any(button.callback_data == "selfcontact:done" for button in filled_contact_buttons))

    public_contacts = _build_public_contacts(contact_data)
    from utils.contact_links import parse_contact_links
    parsed = parse_contact_links(public_contacts)
    check("все пять контактов превращаются в кликабельные ссылки",
          {item["type"] for item in parsed} == {
              "instagram", "telegram", "email", "website", "phone"
          })
    check("телефон не создаёт неподтверждённую кнопку WhatsApp",
          all(item["type"] != "whatsapp" for item in parsed))

    from database.models import Specialist
    from handlers.contacts import _spec_card_kb, _spec_text
    old_webhook_base = config.WEBHOOK_BASE_URL
    config.WEBHOOK_BASE_URL = "https://bot.example"
    try:
        specialist = Specialist(
            id=321, name="Anna", category="маникюр", city="Amsterdam",
            province="Noord-Holland", contact=public_contacts,
        )
        card_buttons = [
            button
            for row in _spec_card_kb(specialist, 0, 1).inline_keyboard
            for button in row
        ]
        contact_buttons = {button.text: button.url for button in card_buttons if button.url}
        check("в Telegram-карточке есть все пять контактных кнопок",
              {"📷 Instagram", "✈️ Telegram", "✉️ Почта", "🌐 Сайт", "📞 Телефон"}
              <= set(contact_buttons))
        check("почта и телефон открываются через безопасные HTTPS-кнопки",
              contact_buttons["✉️ Почта"].endswith("/contact-action/321/email")
              and contact_buttons["📞 Телефон"].endswith("/contact-action/321/phone"))
        check("контакты не дублируются текстом рядом с кнопками",
              public_contacts not in _spec_text(specialist))
    finally:
        config.WEBHOOK_BASE_URL = old_webhook_base

    callbacks = [
        button.callback_data
        for index in range(len(THEMES))
        for row in _category_options_kb(index).inline_keyboard
        for button in row
        if button.callback_data
    ]
    check("все кнопки категорий помещаются в лимит Telegram",
          max(len(value.encode()) for value in callbacks) <= 64)

    standard = [
        button.callback_data
        for row in _plan_duration_kb("standard").inline_keyboard
        for button in row
    ]
    premium = [
        button.callback_data
        for row in _plan_duration_kb("premium").inline_keyboard
        for button in row
    ]
    check("Стандарт предлагает месяц и год",
          standard[:2] == ["selfplan:month", "selfplan:year"])
    check("Премиум предлагает месяц, полгода и год", premium[:3] == [
        "selfplan:month_premium", "selfplan:6m_premium", "selfplan:year_premium"
    ])
    referral_labels = [
        button.text
        for row in _plan_duration_kb("premium", referral=True).inline_keyboard
        for button in row
    ]
    check("реферальная скидка видна до оплаты",
          any("€159,20" in label and "скидка 20%" in label for label in referral_labels))

    preview = _preview_text({
        "sp_name": "<Anna>", "sp_category": "фитнес", "sp_online": True,
        "sp_description": "Персональные тренировки онлайн для начинающих.",
        **contact_data, "sp_contact": public_contacts, "sp_email": "mail@example.com",
    })
    check("предпросмотр экранирует пользовательский HTML",
          "&lt;Anna&gt;" in preview and "<Anna>" not in preview)
    check("предпросмотр показывает контакты раздельно",
          "<b>Instagram:</b> @anna.nails" in preview
          and "<b>Телефон:</b> +31612345678" in preview)
    check("у анкеты есть предпросмотр и подтверждение оплаты",
          bool(SelfAddSpecialist.review) and bool(SelfAddSpecialist.confirm))


def test_board_ux() -> None:
    from handlers.board import (
        INTENTS,
        REPORT_REASONS,
        _browse_city_kb,
        _build_contacts,
        _contact_hub_kb,
        _listing_contact_rows,
        _my_kb,
        _normalize_contact,
        _status,
        _valid_city,
        _valid_description,
        _valid_title,
    )
    from states.forms import ListingForm
    from utils.contact_links import parse_contact_links

    check("жильё, работа, вещи и попутчики уточняют тип объявления",
          set(INTENTS) == {"housing", "jobs", "goods", "rides"})
    check("заголовок объявления проверяется",
          _valid_title("Продам городской велосипед") and not _valid_title("впв"))
    check("описание объявления проверяется",
          _valid_description("Велосипед в хорошем состоянии, недавно заменены тормоза.")
          and not _valid_description("ываыва"))
    check("город проверяется до сохранения",
          _valid_city("'s-Hertogenbosch") and not _valid_city("1"))

    contacts = {
        "l_contact_instagram": _normalize_contact("instagram", "instagram.com/board.user"),
        "l_contact_telegram": _normalize_contact("telegram", "@board_user"),
        "l_contact_whatsapp": _normalize_contact("whatsapp", "06 12345678"),
        "l_contact_email": _normalize_contact("email", "BOARD@EXAMPLE.COM"),
        "l_contact_phone": _normalize_contact("phone", "+31 20 123 45 67"),
    }
    check("пять контактов объявления нормализуются отдельно",
          contacts == {
              "l_contact_instagram": "@board.user",
              "l_contact_telegram": "@board_user",
              "l_contact_whatsapp": "+31612345678",
              "l_contact_email": "board@example.com",
              "l_contact_phone": "+31201234567",
          })
    public_contacts = _build_contacts(contacts)
    parsed = parse_contact_links(public_contacts)
    check("WhatsApp и телефон не смешиваются",
          next(x["url"] for x in parsed if x["type"] == "whatsapp").endswith("31612345678")
          and next(x["url"] for x in parsed if x["type"] == "phone").endswith("31201234567"))
    empty_callbacks = [
        button.callback_data
        for row in _contact_hub_kb({}).inline_keyboard for button in row
    ]
    check("без контакта нельзя завершить контактный экран",
          "lcontact:done" not in empty_callbacks)
    check("анкета доски имеет отдельный предпросмотр",
          bool(ListingForm.review) and bool(ListingForm.intent))

    old_base = config.WEBHOOK_BASE_URL
    config.WEBHOOK_BASE_URL = "https://bot.example"
    try:
        listing = Listing(
            id=751, category="goods", intent="offer", title="Продам велосипед",
            description="Велосипед в хорошем состоянии, недавно заменены тормоза.",
            city="Utrecht", contact=public_contacts, status="approved",
            expires_at=datetime.utcnow() + timedelta(days=10),
        )
        urls = {
            button.text: button.url
            for row in _listing_contact_rows(listing) for button in row
        }
        check("в карточке объявления есть пять кликабельных контактов",
              {"📷 Instagram", "✈️ Telegram", "💬 WhatsApp", "✉️ Почта", "📞 Телефон"}
              <= set(urls))
        check("почта и телефон используют безопасный HTTPS-мост",
              urls["✉️ Почта"].endswith("/listing-contact/751/email")
              and urls["📞 Телефон"].endswith("/listing-contact/751/phone"))
    finally:
        config.WEBHOOK_BASE_URL = old_base

    browse_callbacks = [
        button.callback_data
        for row in _browse_city_kb("goods", "Amersfoort").inline_keyboard
        for button in row
    ]
    check("просмотр доски действительно предлагает город пользователя",
          "bcity:goods:saved" in browse_callbacks and "bcity:goods:__all__" in browse_callbacks)
    awaiting = Listing(id=752, category="housing", title="Комната", status="awaiting_payment")
    awaiting_actions = [
        button.callback_data for row in _my_kb(awaiting, 0, 1).inline_keyboard for button in row
    ]
    closed = Listing(id=753, category="goods", title="Стол", status="closed")
    closed_actions = [
        button.callback_data for row in _my_kb(closed, 0, 1).inline_keyboard for button in row
    ]
    check("неоплаченное жильё можно оплатить и изменить",
          "lpay:752" in awaiting_actions and "leditlisting:752" in awaiting_actions)
    check("закрытое объявление можно опубликовать снова",
          "lrepublish:753" in closed_actions)
    expired = Listing(
        category="goods", title="Истёкшее", status="approved",
        expires_at=datetime.utcnow() - timedelta(minutes=1),
    )
    check("истёкшая карточка не считается активной", _status(expired) == "expired")
    check("жалоба предлагает причины", len(REPORT_REASONS) >= 5)


async def test_board_payment_retry_and_expiry_reminder() -> None:
    import handlers.board as board

    class FakeMessage:
        def __init__(self):
            self.answers = []

        async def answer(self, text, **kwargs):
            self.answers.append((text, kwargs))
            return type("Sent", (), {"message_id": 410})()

    class FakeBot:
        def __init__(self):
            self.messages = []

        async def send_message(self, chat_id, text, **kwargs):
            self.messages.append((chat_id, text, kwargs))
            return type("Sent", (), {"message_id": 411})()

    async with db.get_session() as session:
        unpaid = Listing(
            category="housing", intent="seek", title="Ищу комнату",
            description="Ищу комнату в Utrecht на длительный срок.",
            city="Utrecht", contact="Telegram: @board_retry", status="awaiting_payment",
            submitter_user_id=99301,
        )
        session.add(unpaid)
        await session.commit()
        await session.refresh(unpaid)
        listing_id = unpaid.id

    real_create_payment = board.create_payment

    async def failed_payment(*_args, **_kwargs):
        return None

    async def successful_payment(*_args, **_kwargs):
        return {"id": "tr_board_retry", "checkout_url": "https://pay.example/board"}

    message = FakeMessage()
    try:
        board.create_payment = failed_payment
        result = await board._request_listing_payment(message, 99301, listing_id)
        retry_callbacks = [
            button.callback_data
            for row in message.answers[-1][1]["reply_markup"].inline_keyboard
            for button in row
        ]
        check("ошибка Mollie сохраняет объявление и даёт повторить оплату",
              result is False and f"lpay:{listing_id}" in retry_callbacks)

        board.create_payment = successful_payment
        result = await board._request_listing_payment(message, 99301, listing_id)
        async with db.get_session() as session:
            saved = await session.get(Listing, listing_id)
        check("повтор оплаты не создаёт второе объявление",
              result is True and saved.payment_id == "tr_board_retry")
    finally:
        board.create_payment = real_create_payment

    bot = FakeBot()
    await board.on_listing_paid(bot, "tr_board_retry", {
        "status": "paid", "metadata": {"listing_id": listing_id, "kind": "listing"},
    })
    async with db.get_session() as session:
        paid = await session.get(Listing, listing_id)
    check("оплаченное жильё переходит на модерацию", paid.status == "pending")

    current = datetime(2026, 8, 3, 10, 0)
    async with db.get_session() as session:
        reminder = Listing(
            category="goods", intent="offer", title="Стол к продаже",
            description="Деревянный стол в хорошем состоянии, самовывоз.",
            city="Groningen", contact="Telegram: @board_remind", status="approved",
            submitter_user_id=99302, expires_at=current + timedelta(days=3),
            created_at=current - timedelta(days=60),
        )
        session.add(reminder)
        await session.commit()
    first = await board.send_listing_expiry_reminders(bot, now=current)
    second = await board.send_listing_expiry_reminders(bot, now=current)
    check("напоминание об окончании приходит один раз",
          first == 1 and second == 0
          and any("закончится" in text for _chat, text, _kwargs in bot.messages))


def test_ad_promotion_deadline() -> None:
    amsterdam = ZoneInfo("Europe/Amsterdam")
    countdown = config.ad_promotion_countdown_label(
        datetime(2026, 7, 24, 12, 0, tzinfo=amsterdam)
    )
    penultimate = config.ad_promotion_countdown_label(
        datetime(2026, 7, 29, 12, 0, tzinfo=amsterdam)
    )
    final_day = config.ad_promotion_countdown_label(
        datetime(2026, 7, 30, 12, 0, tzinfo=amsterdam)
    )
    during = config.ad_option(
        "promo", "std", datetime(2026, 7, 30, 12, 0, tzinfo=amsterdam)
    )
    after = config.ad_option(
        "promo", "std", datetime(2026, 7, 31, 0, 0, tzinfo=amsterdam)
    )
    check("акционная цена действует в пределах семи дней",
          during and during["price"] == "150.00")
    check("24 июля интерфейс показывает остаток 6 дней",
          countdown == "Осталось 6 дней")
    check("за день до финала используется верная форма слова",
          penultimate == "Остался 1 день")
    check("30 июля интерфейс показывает последний день",
          final_day == "Последний день")
    check("после дедлайна сервер возвращает цену €180",
          after and after["price"] == "180.00")
    expired_formats = config.ad_formats(
        datetime(2026, 7, 31, 0, 0, tzinfo=amsterdam)
    )
    check("после дедлайна интерфейс больше не получает акционный бейдж",
          expired_formats["promo"]["badge"] == "")
    active_formats = config.ad_formats(
        datetime(2026, 7, 24, 12, 0, tzinfo=amsterdam)
    )
    check("акционный бейдж получает автоматический обратный отсчёт",
          active_formats["promo"]["badge"] == "−€30 · осталось 6 дней")
    from utils import webserver
    expired_bundle = webserver._ads_promo_bundle_source(
        datetime(2026, 7, 31, 0, 0, tzinfo=amsterdam)
    )
    check("после дедлайна React получает обычную цену €180",
          'price:180' in expired_bundle and 'originalPrice:180' not in expired_bundle)
    check("после дедлайна React не получает акционный бейдж",
          'badge:"−€30 · 7 дней"' not in expired_bundle)


def test_numr_campaign_page() -> None:
    """The private offer stays fixed at €299 and does not leak onto /ads."""
    from utils import webserver
    offer = config.ad_option("numr_campaign", "std")
    check("NUMR package costs exactly €299",
          offer is not None and offer["price"] == "299.00")
    check("NUMR package requires four publication dates",
          config.AD_FORMATS["numr_campaign"]["dates"] == 4)
    page = webserver._numr_campaign_html(set())
    check("NUMR page has one fixed package and Mollie checkout",
          "Campagne van 2 maanden" in page
          and "4 Reels · 12 Stories" in page
          and "één van de vier Reels wordt 3 dagen" in page
          and "Benodigde materialen" in page
          and "links naar de App Store en Google Play" in page
          and "toegang tot een testaccount (indien nodig)" in page
          and 'action="/ads/numr/book?lang=nl"' in page
          and "Betaal €299 via Mollie" in page)
    regular_page = webserver._ads_html(set())
    check("private NUMR offer is absent from the regular ads page",
          "numr_campaign" not in regular_page and "NUMR" not in regular_page)


async def test_saved_items() -> None:
    async with db.get_session() as session:
        specialist = (await session.scalars(select(Specialist).limit(1))).first()
        session.add(SavedItem(
            user_id=4242, item_type="specialist", item_id=specialist.id
        ))
        await session.commit()
    async with db.get_session() as session:
        saved = (await session.scalars(select(SavedItem).where(
            SavedItem.user_id == 4242,
            SavedItem.item_type == "specialist",
        ))).first()
    check("избранное сохраняется за конкретным пользователем",
          saved is not None and saved.item_id == specialist.id)


async def test_personal_home_snapshot() -> None:
    from handlers.home import _home_kb, _home_snapshot

    now = datetime(2026, 7, 23, 12, 0)
    pref = DigestPreference(
        user_id=4243, city="Utrecht", province="Utrecht", radius_km=25,
        topics_csv="events,board", enabled=True,
    )
    async with db.get_session() as session:
        session.add(pref)
        session.add_all([
            EventListing(
                title="Home nearby event", description="test",
                city="Amersfoort", is_nationwide=False,
                event_date="26.07.2026", month_key="2026-07",
                status="approved", link="https://example.nl/home-event",
                created_at=now,
            ),
            EventListing(
                title="Home past event", description="test",
                city="Amersfoort", is_nationwide=False,
                event_date="20.07.2026", month_key="2026-07",
                status="approved", link="https://example.nl/past-home-event",
                created_at=now,
            ),
            Listing(
                category="goods", title="Home nearby listing",
                city="Amersfoort", is_nationwide=False, status="approved",
                created_at=now - timedelta(days=2),
            ),
            Listing(
                category="goods", title="Home old listing",
                city="Amersfoort", is_nationwide=False, status="approved",
                created_at=now - timedelta(days=8),
            ),
        ])
        await session.commit()

    snapshot = await _home_snapshot(4243, pref, now=now)
    check("персональная главная показывает ближайшее актуальное событие",
          [item.title for item in snapshot.events] == ["Home nearby event"],
          str([item.title for item in snapshot.events]))
    check("персональная главная показывает только новые объявления рядом",
          [item.title for item in snapshot.new_listings] == ["Home nearby listing"],
          str([item.title for item in snapshot.new_listings]))
    callbacks = [
        button.callback_data
        for row in _home_kb(True, snapshot).inline_keyboard
        for button in row
    ]
    check("живая главная открывает события и новые объявления",
          callbacks[:2] == ["home:events", "home:new"], str(callbacks))
    check("из личной главной открывается отдельный центр уведомлений",
          "home:notifications" in callbacks)
    check("событие можно сохранить для напоминания",
          snapshot.events[0].item_type == "event"
          and snapshot.events[0].item_id > 0)
    empty = await _home_snapshot(4244, None, now=now)
    check("без профиля главная не угадывает рекомендации",
          not empty.events and not empty.new_listings)


async def test_product_analytics() -> None:
    from utils.analytics import gather_product_stats, log_product_event

    now = datetime(2026, 7, 23, 12, 0)
    async with db.get_session() as session:
        session.add_all([
            ProductEvent(
                user_id=8101, name="home_open",
                created_at=datetime(2026, 7, 16, 10, 0),
            ),
            ProductEvent(
                user_id=8101, name="saved_add", entity_type="specialist",
                entity_id=12, created_at=datetime(2026, 7, 17, 10, 0),
            ),
            ProductEvent(
                user_id=8101, name="specialist_open", entity_type="specialist",
                entity_id=12, source="saved",
                created_at=datetime(2026, 7, 23, 10, 0),
            ),
            ProductEvent(
                user_id=8102, name="home_open",
                created_at=datetime(2026, 7, 16, 11, 0),
            ),
        ])
        await session.commit()
    await log_product_event(
        8103,
        "submission_created",
        entity_type="question",
        entity_id=44,
    )
    report = await gather_product_stats(now)
    check("продуктовая аналитика считает D1 по уникальным пользователям",
          "D1: <b>1/2 (50%)</b>" in report)
    check("продуктовая аналитика строит воронку",
          "открыли специалиста: <b>1</b>" in report)
    async with db.get_session() as session:
        event = (await session.scalars(select(ProductEvent).where(
            ProductEvent.user_id == 8103,
        ))).first()
    check("продуктовое событие хранит действие без текста и контактов",
          bool(event) and event.name == "submission_created"
          and not hasattr(event, "text") and not hasattr(event, "username"))


async def test_notification_center() -> None:
    from handlers.notifications import _sync_action_states, run_notification_cycle

    now = datetime(2026, 7, 23, 10, 5, tzinfo=ZoneInfo("Europe/Amsterdam"))
    naive_now = now.replace(tzinfo=None)
    async with db.get_session() as session:
        session.add(DigestPreference(
            user_id=9201, city="Amersfoort", province="Utrecht",
            radius_km=25, topics_csv="events,board", enabled=True,
        ))
        session.add(NotificationPreference(
            user_id=9201, event_reminders=True, new_listings=True,
            action_updates=True, frequency="daily",
        ))
        event = EventListing(
            title="Saved tomorrow event", city="Amersfoort",
            event_date="24.07.2026", month_key="2026-07",
            status="approved", link="https://example.nl/tomorrow",
            created_at=naive_now,
        )
        listing = Listing(
            category="goods", title="Notification listing",
            city="Amersfoort", status="approved",
            created_at=naive_now,
        )
        action_listing = Listing(
            category="services", title="My status listing",
            city="Amersfoort", status="pending",
            submitter_user_id=9201, created_at=naive_now,
        )
        session.add_all([event, listing, action_listing])
        await session.flush()
        session.add(SavedItem(
            user_id=9201, item_type="event", item_id=event.id
        ))
        await session.commit()
        listing_id = action_listing.id

    await _sync_action_states(9201)
    async with db.get_session() as session:
        listing = await session.get(Listing, listing_id)
        listing.status = "closed"
        await session.commit()

    class FakeBot:
        def __init__(self):
            self.messages = []

        async def send_message(self, chat_id, text, **kwargs):
            self.messages.append((chat_id, text))
            return type("Sent", (), {"message_id": 812})()

    bot = FakeBot()
    sent, failed = await run_notification_cycle(bot, now=now)
    check("центр уведомлений собирает события, объявления и статусы одним пакетом",
          sent == 1 and failed == 0 and len(bot.messages) == 1
          and "Saved tomorrow event" in bot.messages[0][1]
          and "Notification listing" in bot.messages[0][1]
          and "закрыто" in bot.messages[0][1])
    sent_again, _ = await run_notification_cycle(bot, now=now)
    check("персональные уведомления не дублируются при повторном цикле",
          sent_again == 0 and len(bot.messages) == 1)
    async with db.get_session() as session:
        deliveries = (await session.scalars(select(NotificationDelivery).where(
            NotificationDelivery.user_id == 9201
        ))).all()
        state = (await session.scalars(select(NotificationState).where(
            NotificationState.user_id == 9201,
            NotificationState.entity_type == "listing",
            NotificationState.entity_id == listing_id,
        ))).first()
    check("доставки уведомлений записываются по отдельным элементам",
          len(deliveries) == 3, str(len(deliveries)))
    check("статус действия обновляется только после успешной доставки",
          bool(state) and state.last_status == "closed")


async def _category_of(session, name: str):
    return (await session.scalars(
        select(Specialist).where(Specialist.name == name))).first()


async def test_db_and_categories() -> None:
    await db.init_db()
    # Категории, которые мы чинили вручную — не должны «уезжать»
    expect = {
        "Fancy Beauty Space": "мастер маникюра",
        "Парикмахер-стилист": "парикмахер",
        "Стилист": "стилист",
        "Массаж (Flex Massage)": "массаж",
        "Тату мастер": "тату и пирсинг",
        "Ламимейкер / Бровист": "брови и ресницы",
    }
    async with db.get_session() as s:
        for name, cat in expect.items():
            sp = await _category_of(s, name)
            check(f"категория «{name}» = {cat}",
                  bool(sp) and sp.category == cat,
                  f"в базе: {sp.category if sp else 'нет карточки'}")


async def test_specialist_payment_retry_keeps_form() -> None:
    import handlers.selfadd as selfadd

    class FakeState:
        def __init__(self) -> None:
            self.data = {
                "sp_name": "Retry Studio",
                "sp_category": "фитнес",
                "sp_city": "Amsterdam",
                "sp_province": "Noord-Holland",
                "sp_description": "Персональные тренировки для начинающих в Amsterdam.",
                "sp_contact": "@retry_studio",
                "sp_online": False,
                "sp_email": "retry@example.com",
                "sp_plan": "month",
            }
            self.current_state = None
            self.cleared = False

        async def get_data(self):
            return dict(self.data)

        async def update_data(self, **values):
            self.data.update(values)

        async def set_state(self, value):
            self.current_state = value

        async def clear(self):
            self.cleared = True
            self.data.clear()

    class FakeMessage:
        def __init__(self) -> None:
            self.answers = []

        async def answer(self, text, **kwargs):
            self.answers.append((text, kwargs))

    state, message = FakeState(), FakeMessage()
    real_create_payment = selfadd.create_payment

    async def failed_payment(*_args, **_kwargs):
        return None

    async def successful_payment(*_args, **_kwargs):
        return {"id": "tr_retry", "checkout_url": "https://pay.example/retry"}

    try:
        selfadd.create_payment = failed_payment
        await selfadd._create_listing_and_pay(message, state, "month", None, 99001)
        first_id = state.data.get("sp_listing_id")
        check("ошибка Mollie не стирает заполненную анкету",
              bool(first_id) and not state.cleared and state.data.get("sp_name") == "Retry Studio")
        check("после ошибки оплаты можно повторить попытку",
              state.current_state == selfadd.SelfAddSpecialist.confirm)

        selfadd.create_payment = successful_payment
        await selfadd._create_listing_and_pay(message, state, "month", None, 99001)
        async with db.get_session() as session:
            rows = list((await session.scalars(
                select(Specialist).where(Specialist.submitter_user_id == 99001)
            )).all())
        check("повтор оплаты не создаёт дубликат карточки",
              len(rows) == 1 and rows[0].id == first_id and rows[0].payment_id == "tr_retry")
        check("анкета очищается только после создания ссылки", state.cleared)
    finally:
        selfadd.create_payment = real_create_payment


async def test_repair_luxar_category() -> None:
    """Детейлинг не должен теряться в домашнем клининге."""
    async with db.get_session() as s:
        s.add(Specialist(
            name="@luxar_auto_detailing",
            category="клининг",
            city="Amsterdam",
            province="Noord-Holland",
            description=(
                "Детейлинг, защита кузова плёнками PPF, химчистка салона, "
                "полировка кузова и реставрация фар."
            ),
            contact="+31643620017",
            source="self",
            status="active",
        ))
        s.add(Specialist(
            name="Фея Чистоты",
            category="клининг",
            city="Amsterdam",
            province="Noord-Holland",
            description="Уборка домов и мойка окон.",
            contact="@home_cleaning",
            source="self",
            status="active",
        ))
        await s.commit()

    await db._repair_misclassified_specialists()

    async with db.get_session() as s:
        luxar = await _category_of(s, "@luxar_auto_detailing")
        home = await _category_of(s, "Фея Чистоты")
    check("Luxar Detail исправлен на автосервис",
          bool(luxar) and luxar.category == "автосервис")
    check("домашний клининг не переклассифицирован",
          bool(home) and home.category == "клининг")


def test_fix_category_no_override() -> None:
    # Курируемая категория главнее имени; дополнительно не ловим короткое spa
    # внутри названия Space.
    from utils.geo import _keyword_matches, detect_category
    item = {"name": "Fancy Beauty Space", "category": "мастер маникюра"}
    result = item.get("category") or detect_category(item["name"])
    check("категория из данных, а не по имени", result == "мастер маникюра",
          f"получили {result}")
    check("Space не содержит отдельное слово spa",
          not _keyword_matches("Fancy Beauty Space", "spa"))


def test_taxonomy_and_seed_categories() -> None:
    """Все карточки и интерфейсы используют одну актуальную таксономию."""
    from seeds.specialists_seed import SEED_SPECIALISTS
    from utils.geo import CATEGORIES, THEMES
    from utils.webserver import _SITE_GROUP

    used = {row["category"] for row in SEED_SPECIALISTS}
    check("в исходных карточках нет устаревших категорий",
          used <= set(CATEGORIES), f"лишние: {sorted(used - set(CATEGORIES))}")

    themed = [category for categories in THEMES.values() for category in categories]
    check("каждая категория показана в теме",
          set(themed) == set(CATEGORIES),
          f"разница: {sorted(set(themed) ^ set(CATEGORIES))}")
    check("категория не дублируется между темами",
          len(themed) == len(set(themed)))
    check("каждая категория привязана к разделу сайта",
          set(CATEGORIES) <= set(_SITE_GROUP),
          f"не привязаны: {sorted(set(CATEGORIES) - set(_SITE_GROUP))}")

    expected = {
        "Онлайн-школа разговорного английского языка Speak Up Online": "языковые курсы",
        "Преподаватель вокала": "музыкальные занятия",
        "Event United Agency": "организация мероприятий",
        "Диджей / DJ HAMMER": "музыкант и диджей",
        "Икорная лавка": "продукты и магазины",
        "Amulet Huis": "ремонт",
        "WEB-разработчик/ Digital-Promo": "it и веб",
    }
    by_name = {row["name"]: row["category"] for row in SEED_SPECIALISTS}
    for name, category in expected.items():
        check(f"аудит категории «{name}»",
              by_name.get(name) == category,
              f"в данных: {by_name.get(name)}")


def test_multi_category_discovery() -> None:
    """Карточка находится по дополнительной услуге без создания дубля."""
    from types import SimpleNamespace
    from utils.geo import specialist_matches_category

    photo_video = SimpleNamespace(
        name="Фотограф / видеограф",
        category="фотограф",
        description="Фото и видеосъёмка мероприятий.",
    )
    psych_career = SimpleNamespace(
        name="Психолог / Карьерный коуч",
        category="психолог",
        description="Помогаю искать работу и готовиться к собеседованию.",
    )
    check("фотограф-видеограф находится как фотограф",
          specialist_matches_category(photo_video, "фотограф"))
    check("фотограф-видеограф находится как видеограф",
          specialist_matches_category(photo_video, "видеограф"))
    check("психолог-карьерный коуч находится как карьерный консультант",
          specialist_matches_category(psych_career, "карьерный консультант"))


async def test_reseed_preserves_premium() -> None:
    async with db.get_session() as s:
        sp = await _category_of(s, "Fancy Beauty Space")
        sp.is_premium = True
        sp.photo_file_id = "PHOTO_TEST"
        old_id = sp.id  # запоминаем id — он НЕ должен меняться (ссылки claim_<id>)
        await s.commit()
    # имитируем смену версии сидов → пересев
    async with db.get_session() as s:
        await s.merge(Meta(key="seed_version", value="0"))
        await s.commit()
    await db._seed_if_needed()
    async with db.get_session() as s:
        sp = await _category_of(s, "Fancy Beauty Space")
    check("пересев сохранил премиум", bool(sp) and sp.is_premium is True)
    check("пересев сохранил фото", bool(sp) and sp.photo_file_id == "PHOTO_TEST")
    check("пересев обновил категорию из файла",
          bool(sp) and sp.category == "мастер маникюра")
    # Главное: id карточки не изменился → ссылки claim_<id> не протухают
    check("пересев сохранил id карточки (ссылки не ломаются)",
          bool(sp) and sp.id == old_id,
          f"было #{old_id}, стало #{sp.id if sp else '—'}")


async def test_reseed_ids_stable_all() -> None:
    """id ВСЕХ seed-карточек не меняются после смены версии засева."""
    async with db.get_session() as s:
        rows = (await s.scalars(
            select(Specialist).where(Specialist.source == "seed"))).all()
        before = {db._seed_key(r.name, r.contact, r.city, r.province): r.id
                  for r in rows}
    async with db.get_session() as s:
        await s.merge(Meta(key="seed_version", value="0"))
        await s.commit()
    await db._seed_if_needed()
    async with db.get_session() as s:
        rows = (await s.scalars(
            select(Specialist).where(Specialist.source == "seed"))).all()
        after = {db._seed_key(r.name, r.contact, r.city, r.province): r.id
                 for r in rows}
    changed = [k for k, i in before.items() if after.get(k) != i]
    check("id всех seed-карточек стабильны после пересева",
          not changed, f"сменились id у {len(changed)} карточек")


async def test_reseed_keeps_edited_premium_card() -> None:
    """Если у премиум-карточки отредактировали контакт (ключ разошёлся с файлом),
    пересев НЕ должен её удалить/затереть и не должен создать дубликат."""
    async with db.get_session() as s:
        sp = await _category_of(s, "Fancy Beauty Space")
        sp.is_premium = True
        sp.photo_file_id = "PHOTO_EDIT"
        sp.contact = "instagram: @fancy_beauty_space · +31 6 19 52 06 60"  # правка
        old_id = sp.id
        await s.commit()
    async with db.get_session() as s:
        await s.merge(Meta(key="seed_version", value="0"))
        await s.commit()
    await db._seed_if_needed()
    async with db.get_session() as s:
        rows = (await s.scalars(select(Specialist).where(
            Specialist.name == "Fancy Beauty Space"))).all()
    check("нет дубля Fancy после пересева с правкой", len(rows) == 1,
          f"карточек Fancy: {len(rows)}")
    sp = rows[0] if rows else None
    check("правленый премиум сохранён", bool(sp) and sp.is_premium is True)
    check("правленое фото сохранено", bool(sp) and sp.photo_file_id == "PHOTO_EDIT")
    check("правленый контакт не откатился к файлу",
          bool(sp) and "fancy_beauty_space" in (sp.contact or ""),
          f"контакт: {sp.contact if sp else '—'}")
    check("id правленой карточки сохранён", bool(sp) and sp.id == old_id)


async def test_specialist_reminder_delivery_log() -> None:
    """Флаг ставится только после доставки; успех и ошибка видны в журнале."""
    import handlers.selfadd as S
    from datetime import datetime, timedelta

    now = datetime.utcnow()
    async with db.get_session() as session:
        ok = Specialist(
            name="Reminder OK", category="еда", city="", province="Gelderland",
            source="self", status="active", submitter_user_id=8801,
            paid_until=now + timedelta(days=3), plan="month",
            renewal_reminded=False,
        )
        fail = Specialist(
            name="Reminder FAIL", category="еда", city="", province="Gelderland",
            source="self", status="active", submitter_user_id=8802,
            paid_until=now + timedelta(days=3), plan="month",
            renewal_reminded=False,
        )
        expired = Specialist(
            name="Reminder EXPIRED", category="еда", city="", province="Gelderland",
            source="self", status="active", submitter_user_id=8803,
            paid_until=now - timedelta(hours=1), plan="month",
            renewal_reminded=True,
        )
        historical = Specialist(
            name="Reminder HISTORICAL", category="еда", city="", province="Gelderland",
            source="self", status="expired", submitter_user_id=8804,
            paid_until=now - timedelta(hours=1), plan="month",
            renewal_reminded=True,
        )
        session.add_all([ok, fail, expired, historical])
        await session.commit()
        await session.refresh(ok); await session.refresh(fail); await session.refresh(expired)
        await session.refresh(historical)
        ok_id, fail_id, expired_id, historical_id = (
            ok.id, fail.id, expired.id, historical.id,
        )

    class _Msg:
        message_id = 4321

    class _Bot:
        def __init__(self):
            self.user_calls = []

        async def send_message(self, chat_id, *args, **kwargs):
            if chat_id in (8801, 8802, 8803, 8804):
                self.user_calls.append(chat_id)
            if chat_id == 8802:
                raise RuntimeError("bot was blocked")
            return _Msg()

    bot = _Bot()
    await S._send_renewal_reminders(bot)
    async with db.get_session() as session:
        ok = await session.get(Specialist, ok_id)
        fail = await session.get(Specialist, fail_id)
        ok_log = (await session.scalars(select(SpecialistReminderLog).where(
            SpecialistReminderLog.specialist_id == ok_id,
            SpecialistReminderLog.kind == "renewal"))).first()
        fail_log = (await session.scalars(select(SpecialistReminderLog).where(
            SpecialistReminderLog.specialist_id == fail_id,
            SpecialistReminderLog.kind == "renewal"))).first()
    check("успешное напоминание отмечено только после доставки",
          ok.renewal_reminded is True and ok_log.status == "sent"
          and ok_log.telegram_message_id == 4321)
    check("ошибка доставки оставляет напоминание неотправленным",
          fail.renewal_reminded is False and fail_log.status == "failed"
          and "bot was blocked" in (fail_log.error_text or ""))

    # Повторный 12-часовой цикл не должен долбить пользователя: после ошибки
    # повторяем не чаще раза в сутки.
    before = bot.user_calls.count(8802)
    await S._send_renewal_reminders(bot)
    check("ошибка не повторяется чаще раза в сутки",
          bot.user_calls.count(8802) == before)

    await S._send_expiry_notices(bot)
    async with db.get_session() as session:
        expired = await session.get(Specialist, expired_id)
        expiry_log = (await session.scalars(select(SpecialistReminderLog).where(
            SpecialistReminderLog.specialist_id == expired_id,
            SpecialistReminderLog.kind == "expiry"))).first()
        historical_log = (await session.scalars(select(SpecialistReminderLog).where(
            SpecialistReminderLog.specialist_id == historical_id,
            SpecialistReminderLog.kind == "expiry"))).first()
    check("истёкшая карточка скрыта", expired.status == "expired")
    check("доставка уведомления об окончании записана",
          bool(expiry_log) and expiry_log.status == "sent")
    check("старым истёкшим карточкам не шлём задним числом",
          historical_log is None and 8804 not in bot.user_calls)

    import handlers.admin as Admin
    dashboard = await Admin._renewals_dashboard_text()
    check("админ видит подтверждённые и неудачные отправки",
          "Reminder OK" in dashboard and "Reminder FAIL" in dashboard
          and "msg 4321" in dashboard and "ошибка" in dashboard)
    check("панель напоминаний помещается в сообщение Telegram",
          len(dashboard) < 4096, f"символов: {len(dashboard)}")


async def test_allo_capacity() -> None:
    """Места и абонемент-кредиты Allo Walks считаются верно."""
    import handlers.allo as A
    from datetime import datetime, timedelta
    from database.models import AlloBooking
    keys = [w["key"] for w in config.ALLO_WALKS]
    async with db.get_session() as s:
        b0 = await A._taken(s, keys[0])
        # покупка абонемента НЕ занимает места на прогулках (куплен вчера)
        s.add(AlloBooking(walk_key="pass", plan="pass", user_id=901, status="paid",
                          paid_at=datetime.utcnow() - timedelta(days=1)))
        s.add(AlloBooking(walk_key=keys[0], plan="single", user_id=902, status="paid"))
        s.add(AlloBooking(walk_key=keys[0], plan="use", user_id=901, status="paid"))
        await s.commit()
    async with db.get_session() as s:
        check("разовая+списание заняли 2 места", await A._taken(s, keys[0]) == b0 + 2)
        check("покупка абонемента не занимает место на других датах",
              await A._taken(s, "2099-12-30") == 0)
        # абонемент активен, 1 списание → осталось credits-1
        _p, rem, _vu = await A._active_pass(s, 901)
        check("у абонемента списалась 1 прогулка",
              rem == config.ALLO_PASS_CREDITS - 1, f"осталось {rem}")
    # просроченная неоплата не держит место (отдельный служебный ключ-дата)
    other = "2099-12-31"
    async with db.get_session() as s:
        before = await A._taken(s, other)
        old = AlloBooking(walk_key=other, plan="single", user_id=903, status="pending")
        s.add(old)
        await s.commit()
        old.created_at = datetime.utcnow() - timedelta(hours=3)
        await s.commit()
    async with db.get_session() as s:
        check("просроченная неоплата не занимает место",
              await A._taken(s, other) == before)
        check("просроченная неоплата не блокирует пользователя",
              other not in await A._user_booked_dates(s, 903))
        check("протухшая бронь переведена в expired",
              await A._expire_stale_holds(s, 903) == 1)
    # Свежая неоплата держит место, но не выдаётся за подтверждённую запись.
    pending_key = "2099-12-28"
    async with db.get_session() as s:
        pending = AlloBooking(walk_key=pending_key, plan="single", user_id=904,
                              status="pending", payment_id="tr_open")
        s.add(pending)
        await s.commit()
        await s.refresh(pending)
        pending_id = pending.id
    async with db.get_session() as s:
        check("свежая неоплата временно держит место",
              await A._taken(s, pending_key) == 1)
        check("неоплата не помечает пользователя записанным",
              pending_key not in await A._user_booked_dates(s, 904))
        pending_rows = await A._user_pending_bookings(s, 904)
        check("незавершённую оплату можно продолжить",
              pending_rows.get(pending_key) is not None)
        check("повторная попытка освобождает прежнее место",
              await A._cancel_pending(s, 904, pending_key) == 1)
    async with db.get_session() as s:
        check("отменённая попытка больше не держит место",
              await A._taken(s, pending_key) == 0)
    class _Bot:
        async def send_message(self, *args, **kwargs):
            return None
    await A.on_allo_payment_paid(
        _Bot(), "tr_open",
        {"status": "paid", "metadata": {"booking_id": pending_id}})
    async with db.get_session() as s:
        canceled = await s.get(AlloBooking, pending_id)
        check("оплата по отменённой старой ссылке отправляется на возврат",
              canceled.status == "refund_requested")
    # ручное закрытие даты (/alloclose): свободных мест нет, хотя броней нет
    close_key = "2099-12-29"
    async with db.get_session() as s:
        check("до закрытия есть свободные места",
              await A._remaining(s, close_key) > 0)
        await s.merge(Meta(key=A._closed_key(close_key), value="closed"))
        await s.commit()
    async with db.get_session() as s:
        check("закрытая дата показывает 0 мест",
              await A._remaining(s, close_key) == 0)
        m = await s.get(Meta, A._closed_key(close_key))
        await s.delete(m)
        await s.commit()
    async with db.get_session() as s:
        check("после открытия места вернулись",
              await A._remaining(s, close_key) > 0)

    # Отмена списания абонемента: раньше 24 ч возвращает кредит; поздняя
    # отмена помечается forfeited и остаётся использованной.
    async with db.get_session() as s:
        used = (await s.scalars(select(AlloBooking).where(
            AlloBooking.user_id == 901, AlloBooking.plan == "use"))).first()
        used.status = "canceled"
        await s.commit()
    async with db.get_session() as s:
        _p, rem, _vu = await A._active_pass(s, 901)
        check("своевременная отмена вернула прогулку в абонемент",
              rem == config.ALLO_PASS_CREDITS)
        used = (await s.scalars(select(AlloBooking).where(
            AlloBooking.user_id == 901, AlloBooking.plan == "use"))).first()
        used.status = "forfeited"
        await s.commit()
    async with db.get_session() as s:
        _p, rem, _vu = await A._active_pass(s, 901)
        check("поздняя отмена не вернула прогулку в абонемент",
              rem == config.ALLO_PASS_CREDITS - 1)


def test_allo_schedule() -> None:
    """Планируемые форматы видны на сайте, но не продаются в боте без даты."""
    from datetime import datetime
    now = datetime.fromisoformat("2026-08-01T10:00:00+02:00")
    check("на сайте подготовлено пять форматов Allo Walks",
          len([w for w in config.ALLO_WALKS if w.get("status") != "archived"]) == 5)
    check("планируемые прогулки пока не продаются в боте",
          config.available_allo_walks(now) == [])
    check("все ключи прогулок помещаются в поле базы",
          all(len(w["key"]) <= 20 for w in config.ALLO_WALKS))
    check("вместимость Allo Walks = 8", config.ALLO_WALK_CAPACITY == 8)


async def test_allo_website() -> None:
    """Витрина отдаёт только актуальные форматы и содержит ключевой интерфейс."""
    import json
    from pathlib import Path
    from utils.allo_web import api_walks
    response = await api_walks(None)
    payload = json.loads(response.text)
    check("API сайта отдаёт пять будущих форматов", len(payload["walks"]) == 5)
    check("архивная прогулка не попадает на витрину",
          all(w["status"] != "archived" for w in payload["walks"]))
    page = (Path(__file__).resolve().parent.parent / "static" / "allo-walks" /
            "index.html").read_text(encoding="utf-8")
    check("страница содержит запись и лист ожидания",
          "/allo-walks/book" in page and "/allo-walks/waitlist" in page)


async def test_allo_referral() -> None:
    """Реферал: приводящий получает €-бонус и он списывается при оплате."""
    import handlers.allo as A
    from database.models import AlloBooking

    class _FakeBot:
        async def send_message(self, *a, **k):
            pass

    await A.register_referral(111, 222)  # 111 привёл 222
    await A._maybe_earn_referral(_FakeBot(), 222)  # 222 оплатил впервые → +€10
    async with db.get_session() as s:
        check("приводящий получил 1 бонус", await A._referral_credits(s, 111) == 1)
    # приводящий покупает разовую €35 → скидка €10 → к оплате €25
    async with db.get_session() as s:
        b = AlloBooking(walk_key=config.ALLO_WALKS[0]["key"], plan="single",
                        user_id=111, status="pending", amount="35.00")
        s.add(b); await s.commit(); await s.refresh(b)
        pay, disc = await A._reserve_credits(s, 111, "35.00", b.id)
        bid = b.id
    check("скидка применилась (€10 → к оплате €25)", pay == "25.00" and disc == 10)
    async with db.get_session() as s:
        await A._settle_credits(s, bid, paid=True)
    async with db.get_session() as s:
        check("бонус списан после оплаты", await A._referral_credits(s, 111) == 0)
    # нельзя привести самого себя / уже приведённого
    await A.register_referral(333, 333)
    await A.register_referral(999, 222)  # 222 уже приведён — не перезапишется
    async with db.get_session() as s:
        check("нельзя привести себя", await A._referral_credits(s, 333) == 0)


async def test_premiums_query() -> None:
    """Список премиум-карточек (команда /premiums) находит помеченные премиумом."""
    # test_reseed_preserves_premium уже пометил Fancy как премиум
    async with db.get_session() as s:
        rows = (await s.scalars(
            select(Specialist).where(Specialist.is_premium.is_(True)))).all()
    names = {r.name for r in rows}
    check("список премиумов не пуст", bool(rows))
    check("Fancy Beauty Space попадает в список премиумов",
          "Fancy Beauty Space" in names, f"в списке: {sorted(names)}")


async def test_personal_digest() -> None:
    """Георадиус и секции персональной подборки работают на данных бота."""
    from datetime import date, datetime, timedelta
    from handlers.digest import (
        _event_overlaps_weekend,
        _listing_is_on_weekend,
        _rotate_specialists,
        _specialist_identity,
        _shown_specialist_ids,
        _weekend_label,
        build_digest,
        digest_announcement_kb,
        digest_announcement_text,
        _listing_event_day,
        location_matches,
    )

    pref = DigestPreference(
        user_id=7001, city="Utrecht", province="Utrecht", radius_km=25,
        topics_csv="events,specialists,board,guides", enabled=True,
    )
    check("подборка: Amersfoort попадает в радиус 25 км",
          location_matches(pref, "Amersfoort"))
    check("подборка: Amsterdam не попадает в радиус 25 км",
          not location_matches(pref, "Amsterdam"))
    oss = DigestPreference(
        user_id=7003, city="Oss", province="Noord-Brabant", radius_km=25,
        topics_csv="events", enabled=True,
    )
    check("подборка: Den Bosch попадает в радиус 25 км от Oss",
          location_matches(oss, "Den Bosch"))
    exact = DigestPreference(
        user_id=7002, city="Utrecht", province="Utrecht", radius_km=0,
        topics_csv="events", enabled=True,
    )
    check("подборка: режим города не захватывает соседний город",
          not location_matches(exact, "Amersfoort"))
    province_wide = DigestPreference(
        user_id=7004, city="Utrecht", province="Utrecht", radius_km=50,
        topics_csv="specialists", enabled=True,
    )
    check("подборка: карточка без города находится по провинции при 50 км",
          location_matches(
              province_wide, "", target_province="Utrecht"
          ))
    check("подборка: карточка другой провинции без города не попадает в радиус",
          not location_matches(
              province_wide, "", target_province="Noord-Holland"
          ))
    check("подборка: точный город не подбирает карточку только по провинции",
          not location_matches(
              exact, "", target_province="Utrecht"
          ))
    check("подборка считает ближайшие выходные после четверга",
          _weekend_label(date(2026, 7, 30)) == "01.08–02.08")
    check("событие 2 августа входит в выпуск 1–2 августа",
          _event_overlaps_weekend(
              datetime(2026, 8, 2, 10),
              datetime(2026, 8, 2, 18),
              today=date(2026, 7, 30),
          ))
    check("событие 13 августа не входит в выпуск 1–2 августа",
          not _event_overlaps_weekend(
              datetime(2026, 8, 13, 10),
              datetime(2026, 8, 19, 18),
              today=date(2026, 7, 30),
          ))
    spanning_event = EventListing(
        title="Weekend festival",
        month_key="2026-08",
        starts_at=datetime(2026, 7, 31, 10),
        ends_at=datetime(2026, 8, 2, 18),
    )
    check("многодневный фестиваль остаётся, если захватывает выходные",
          _listing_is_on_weekend(
              spanning_event, today=date(2026, 7, 30)
          ))

    rotation_rows = []
    for sid, source in enumerate(
        ["self", "admin", "self", "self", "seed", "seed", "seed", "seed"],
        start=100,
    ):
        row = Specialist(
            name=f"Rotation {sid}", category="фотограф", city="Utrecht",
            province="Utrecht", source=source, status="active",
        )
        row.id = sid
        rotation_rows.append(row)
    first_mix = _rotate_specialists(
        rotation_rows, today=date(2026, 7, 23)
    )
    check("подборка берёт действительно последние новые карточки",
          {row.id for row in first_mix if row.source != "seed"} == {102, 103})
    next_mix = _rotate_specialists(
        rotation_rows, today=date(2026, 7, 30),
        shown_ids={row.id for row in first_mix},
    )
    check("подборка специалистов миксует новые и карточки старого гайда",
          {row.source == "seed" for row in first_mix} == {True, False})
    check("следующая подборка не повторяет уже доставленные карточки",
          {row.id for row in first_mix}.isdisjoint(
              row.id for row in next_mix
          ))
    check("история доставки распознаёт ссылки на карточки",
          _shown_specialist_ids([
              "https://t.me/test?start=spec_102",
              "https://t.me/test?start=spec_107",
          ]) == {102, 107})
    duplicate = Specialist(
        name=rotation_rows[2].name,
        category="фотограф",
        city="Utrecht",
        province="Utrecht",
        contact=rotation_rows[2].contact,
        source="seed",
        status="active",
    )
    duplicate.id = 999
    deduped_mix = _rotate_specialists(
        [*rotation_rows, duplicate],
        today=date(2026, 7, 30),
        shown_ids={rotation_rows[2].id},
    )
    check("региональная копия показанной карточки не считается новым специалистом",
          _specialist_identity(rotation_rows[2]) not in {
              _specialist_identity(item) for item in deduped_mix
          })
    check("в одном выпуске нет дублей специалистов с разными ID",
          len({_specialist_identity(item) for item in deduped_mix}) == len(deduped_mix))

    digest_saturday = date.today() + timedelta(
        days=(5 - date.today().weekday()) % 7
    )
    month = f"{date.today():%Y-%m}"
    async with db.get_session() as session:
        session.add(BotUser(user_id=7001, first_name="Digest", is_blocked=False))
        session.add(pref)
        session.add(EventListing(
            title="Digest test event", description="test", city="Amersfoort",
            is_nationwide=False,
            event_date=digest_saturday.strftime("%d.%m.%Y"),
            month_key=month, status="approved", link="https://example.nl/upcoming",
        ))
        session.add(EventListing(
            title="Past digest event", description="test", city="Amersfoort",
            is_nationwide=False,
            event_date=(date.today() - timedelta(days=2)).strftime("%d.%m.%Y"),
            month_key=month, status="approved", link="https://example.nl/past",
        ))
        session.add(EventListing(
            title="Later digest event", description="test", city="Amersfoort",
            is_nationwide=False,
            event_date=(date.today() + timedelta(days=14)).strftime("%d.%m.%Y"),
            month_key=month, status="approved", link="https://example.nl/later",
        ))
        session.add(Specialist(
            name="Digest test specialist", category="фотограф", city="Amersfoort",
            province="Utrecht", description="test", contact="@test", source="self",
            status="active",
        ))
        session.add(Listing(
            category="goods", title="Digest test listing", city="Amersfoort",
            is_nationwide=False, status="approved",
        ))
        await session.commit()
    text = await build_digest(pref)
    check("подборка содержит локальное мероприятие", "Digest test event" in text)
    check("подборка не содержит уже прошедшее мероприятие", "Past digest event" not in text)
    check("подборка не содержит мероприятие после ближайших выходных",
          "Later digest event" not in text)
    check("ручная афиша не угадывает дату из слова «суббота»",
          _listing_event_day("суббота") is None)
    check("подборка содержит локального специалиста", "Digest test specialist" in text)
    check("имя специалиста ведёт в его полную карточку", "?start=spec_" in text)
    check("подборка содержит локальное объявление", "Digest test listing" in text)
    check("полезное содержит самостоятельный совет, а не ссылку-заглушку",
          "Полезное на этой неделе" in text and "открой нужную тему" not in text)
    check("подборка помещается в сообщение Telegram", len(text) < 4096, str(len(text)))
    announcement = digest_announcement_text()
    announcement_callbacks = [
        button.callback_data
        for row in digest_announcement_kb().inline_keyboard
        for button in row
    ]
    check("анонс подписок помещается в сообщение Telegram",
          len(announcement) < 4096, str(len(announcement)))
    check("анонс запускает настройку и поиск событий",
          announcement_callbacks == ["dg:announce:setup", "ev_search"],
          str(announcement_callbacks))

    from utils.ai import (
        _create_with_server_tool_continuation,
        _web_search_errors,
        parse_event_cards,
        parse_event_search_places,
    )
    fixed_now = datetime(2026, 7, 21, 12, 0)
    cards = parse_event_cards(
        "<event><title>Festival</title><start>2026-07-25T19:00:00+02:00</start>"
        "<end>2026-07-25T23:00:00+02:00</end><date>25 juli · 19:00</date>"
        "<venue>De Hallen</venue><city>Amsterdam</city>"
        "<description>Музыка и еда.</description>"
        "<url>https://example.nl/event</url><source>Example</source></event>"
        "<event><title>Без ссылки</title><start>2026-07-26</start><date>26 juli</date>"
        "<url></url></event>"
        "<event><title>Уже прошло</title><start>2026-07-20T10:00:00+02:00</start>"
        "<end>2026-07-20T12:00:00+02:00</end><date>20 juli</date>"
        "<url>https://example.nl/past-event</url></event>",
        now=fixed_now,
    )
    check("афиша оставляет только будущие карточки с отдельной ссылкой",
          len(cards) == 1 and cards[0]["venue"] == "De Hallen", str(cards))
    separated = parse_event_cards(
        "<event><title>Ticketed</title><start>2026-10-10</start><end>2026-10-10</end>"
        "<date>10 oktober</date><venue>TivoliVredenburg</venue><city>Utrecht</city>"
        "<description>Concert.</description>"
        "<source_url>https://venue.example/event</source_url>"
        "<ticket_url>https://tickets.example/buy</ticket_url>"
        "<source>Venue</source><territory>Nederland</territory></event>",
        now=fixed_now,
    )
    check("афиша хранит источник и билеты как две независимые ссылки",
          bool(separated)
          and separated[0]["source_url"] == "https://venue.example/event"
          and separated[0]["ticket_url"] == "https://tickets.example/buy",
          str(separated))
    escaped = parse_event_cards(
        "&lt;event&gt;&lt;title&gt;Open dag&lt;/title&gt;"
        "&lt;start&gt;2026-10-11&lt;/start&gt;"
        "&lt;city&gt;Utrecht&lt;/city&gt;"
        "&lt;source_url&gt;[Programma](https://venue.example/open-dag)&lt;/source_url&gt;",
        now=fixed_now,
    )
    check("афиша восстанавливает экранированную и частично обрезанную карточку",
          bool(escaped)
          and escaped[0]["date"] == "2026-10-11"
          and escaped[0]["url"] == "https://venue.example/open-dag",
          str(escaped))
    search_error = {
        "content": [{
            "type": "web_search_tool_result",
            "content": {
                "type": "web_search_tool_result_error",
                "error_code": "max_uses_exceeded",
            },
        }],
    }
    check("афиша видит ошибку веб-поиска внутри успешного API-ответа",
          _web_search_errors(search_error) == ["max_uses_exceeded"])

    class FakeMessages:
        def __init__(self):
            self.calls = []

        async def create(self, **kwargs):
            from types import SimpleNamespace
            self.calls.append(kwargs)
            if len(self.calls) == 1:
                return SimpleNamespace(
                    stop_reason="pause_turn",
                    content=[{"type": "server_tool_use", "id": "search-1"}],
                )
            return SimpleNamespace(
                stop_reason="end_turn",
                content=[SimpleNamespace(type="text", text="готово", citations=[])],
            )

    from types import SimpleNamespace
    fake_messages = FakeMessages()
    completed = await _create_with_server_tool_continuation(
        SimpleNamespace(messages=fake_messages),
        model="test-model",
        max_tokens=100,
        messages=[{"role": "user", "content": "найди"}],
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
    )
    check("афиша автоматически продолжает остановленный серверный поиск",
          completed.stop_reason == "end_turn" and len(fake_messages.calls) == 2)
    check("продолжение возвращает pause_turn-контент в историю без изменений",
          fake_messages.calls[1]["messages"][-1]["role"] == "assistant"
          and fake_messages.calls[1]["messages"][-1]["content"][0]["id"] == "search-1")
    places = parse_event_search_places(
        "<place>Woudrichem</place><place>Werkendam</place>"
        "<place>Gorinchem</place><place>Woudrichem</place>",
        "Woudrichem",
    )
    check("афиша поддерживает любой небольшой город без статического списка",
          places == ["Woudrichem", "Werkendam", "Gorinchem"], str(places))

    from handlers.afisha import _event_period
    period = _event_period("12–14.08.2026")
    check("точный период мероприятия распознаётся для автоматического скрытия",
          bool(period) and period[0] < period[1], str(period))

    from handlers.events import AFISHA_SECTIONS, _auto_batch, _auto_event_kb, _catalog_kb
    catalog_callbacks = [
        button.callback_data
        for row in _catalog_kb().inline_keyboard
        for button in row
    ]
    check("общая афиша содержит отдельный раздел островов",
          "islands" in AFISHA_SECTIONS and "evcat:islands" in catalog_callbacks,
          str(catalog_callbacks))
    action_event = DiscoveredEvent(
        batch_key="actions", query_city="Nederland", radius_km=999,
        title="Event", description="Details", event_date="10 oktober",
        venue="TivoliVredenburg", city="Utrecht",
        link="https://venue.example/event", source_url="https://venue.example/event",
        ticket_url="https://tickets.example/buy", photo_url="https://img.example/event.jpg",
        source_name="Venue", territory="Nederland", section_key="music",
        starts_at=datetime(2026, 10, 10), ends_at=datetime(2026, 10, 11),
        expires_at=datetime(2026, 7, 24),
    )
    action_urls = [
        button.url
        for row in _auto_event_kb("actions", 0, 1, action_event).inline_keyboard
        for button in row if button.url
    ]
    check("карточка события содержит источник, билеты и Google Maps",
          len(action_urls) == 3
          and "venue.example" in action_urls[0]
          and "tickets.example" in action_urls[1]
          and "google.com/maps" in action_urls[2],
          str(action_urls))
    from utils.webpage import _meta_image
    check("фото берётся из официальной страницы мероприятия",
          _meta_image(
              '<meta property="og:image" content="/media/event.jpg">',
              "https://venue.example/program/event",
          ) == "https://venue.example/media/event.jpg")

    real_now = datetime.utcnow()
    async with db.get_session() as session:
        session.add(DiscoveredEvent(
            batch_key="past-batch", query_city="Pastville", radius_km=25,
            title="Finished", description="", event_date="вчера", venue="",
            city="Pastville", link="https://example.nl/finished", source_name="Example",
            starts_at=real_now - timedelta(hours=4), ends_at=real_now - timedelta(hours=1),
            expires_at=real_now + timedelta(hours=20),
        ))
        session.add(DiscoveredEvent(
            batch_key="future-batch", query_city="Futureville", radius_km=25,
            title="Upcoming", description="", event_date="завтра", venue="",
            city="Futureville", link="https://example.nl/upcoming-card", source_name="Example",
            starts_at=real_now + timedelta(hours=4), ends_at=real_now + timedelta(hours=7),
            expires_at=real_now + timedelta(hours=20),
        ))
        await session.commit()
    check("суточный кэш не возвращает уже закончившееся событие",
          await _auto_batch("Pastville", 25) is None)
    future_batch = await _auto_batch("Futureville", 25)
    check("суточный кэш возвращает будущее событие",
          bool(future_batch) and future_batch[1][0].title == "Upcoming")

    class FakeBot:
        def __init__(self):
            self.calls = []

        async def send_message(self, chat_id, text, **kwargs):
            self.calls.append(chat_id)
            return type("Sent", (), {"message_id": 991})()

    from handlers.digest import (
        ANNOUNCEMENT_KEY,
        _send_all_digests,
        _send_digest_announcement,
        _week_key,
    )
    bot = FakeBot()
    await _send_all_digests(bot, admin_id=1)
    async with db.get_session() as session:
        saved = await session.get(DigestPreference, 7001)
        delivery = (await session.scalars(select(DigestDeliveryLog).where(
            DigestDeliveryLog.user_id == 7001,
            DigestDeliveryLog.week_key == _week_key(),
        ))).first()
    check("успешная подборка отмечена отправленной на этой неделе",
          saved.last_sent_week == _week_key())
    check("доставка подборки записана с Telegram message ID",
          bool(delivery) and delivery.status == "sent" and delivery.telegram_message_id == 991)
    before = bot.calls.count(7001)
    await _send_all_digests(bot, admin_id=1)
    check("одна подборка не отправляется дважды за неделю",
          bot.calls.count(7001) == before)

    announcement_bot = FakeBot()
    sent, failed = await _send_digest_announcement(announcement_bot)
    check("разовый анонс отправляется активным пользователям",
          sent > 0 and failed == 0 and announcement_bot.calls.count(7001) == 1)
    sent_again, _ = await _send_digest_announcement(announcement_bot)
    async with db.get_session() as session:
        announcement_log = (await session.scalars(select(AnnouncementDelivery).where(
            AnnouncementDelivery.campaign_key == ANNOUNCEMENT_KEY,
            AnnouncementDelivery.user_id == 7001,
        ))).first()
    check("разовый анонс не дублируется после повторного запуска",
          sent_again == 0 and announcement_bot.calls.count(7001) == 1)
    check("доставка разового анонса записывается по пользователю",
          bool(announcement_log) and announcement_log.status == "sent")


async def test_content_center() -> None:
    from handlers.content import (
        INITIAL_SCHEDULE,
        TEMPLATES,
        publish_content_post,
        seed_content_calendar,
    )

    await seed_content_calendar()
    await seed_content_calendar()
    async with db.get_session() as session:
        rows = (await session.scalars(
            select(ContentPost).order_by(ContentPost.scheduled_at)
        )).all()
    keys = [row.campaign_key for row in rows]
    check("контент-календарь создаётся без дублей",
          len(rows) >= len(INITIAL_SCHEDULE) and len(keys) == len(set(keys)),
          str(len(rows)))
    check("первый слот назначен на 28 июля 12:30",
          rows[0].scheduled_at == datetime(2026, 7, 28, 12, 30))
    check("в календаре нет повторяющихся типов подряд",
          all(
              TEMPLATES[a.template_key].kind != TEMPLATES[b.template_key].kind
              for a, b in zip(rows, rows[1:])
          ))
    check("после первого месяца календарь продолжается автоматически",
          rows[-1].scheduled_at.date() > datetime(2026, 8, 23).date())

    class FakeMessage:
        message_id = 501

    class FakeBot:
        def __init__(self):
            self.channel_calls = []
            self.admin_calls = []

        async def send_message(self, chat_id, text, **kwargs):
            if chat_id == "@test_channel":
                self.channel_calls.append((chat_id, text, kwargs))
            else:
                self.admin_calls.append((chat_id, text, kwargs))
            return FakeMessage()

    old_channel = config.ANNOUNCE_CHANNEL
    config.ANNOUNCE_CHANNEL = "@test_channel"
    bot = FakeBot()
    try:
        first = await publish_content_post(bot, rows[0].id)
        repeated = await publish_content_post(bot, rows[0].id)
    finally:
        config.ANNOUNCE_CHANNEL = old_channel
    async with db.get_session() as session:
        saved = await session.get(ContentPost, rows[0].id)
    check("Контент-центр публикует пост с одной прямой кнопкой",
          first and len(bot.channel_calls) == 1
          and len(bot.channel_calls[0][2]["reply_markup"].inline_keyboard) == 1)
    check("один слот нельзя отправить повторно",
          repeated is False and saved.status == "sent")
    check("успешная публикация хранит Telegram message_id",
          saved.telegram_message_id == 501)


def test_wordpress_util() -> None:
    import utils.wordpress as wp
    check("публикация на сайт выключена без настроек", wp.wp_enabled() is False)
    check("ссылка на редактирование записи корректна",
          wp.edit_link(42).endswith("/wp-admin/post.php?post=42&action=edit"))
    # Галерея: пусто → пусто, много фото → сетка (не куча), все фото на месте
    imgs = [{"id": i, "source_url": f"http://x/{i}.jpg"} for i in (1, 2, 3)]
    g = wp.gallery_block(imgs)
    check("галерея пустая без фото", wp.gallery_block([]) == "")
    check("галерея — сетка колонками", "wp-block-gallery" in g and "columns-" in g)
    check("галерея содержит все фото", g.count("wp-block-image") == 3)
    # Ручная раскладка фото по разделам
    body = "<p>i</p><h2>A</h2><p>a</p><h2>B</h2><p>b</p>"
    check("разделы статьи распознаются", wp.section_titles(body) == ["A", "B"])
    content, feat = wp.build_content_with_images(body, [
        {"im": {"id": 10, "source_url": "u"}, "where": "top"},
        {"im": {"id": 11, "source_url": "u"}, "where": 1},
    ])
    check("обложка = верхнее фото", feat == 10)
    check("обложка не дублируется в теле", "wp-image-10" not in content)
    check("фото раздела 2 стоит после его заголовка",
          content.index("wp-image-11") > content.index("<h2>B</h2>"))


def test_detect_category_basic() -> None:
    from utils.geo import detect_category
    check("«маникюр» → мастер маникюра", detect_category("маникюр") == "мастер маникюра")
    check("«юрист» → юрист", detect_category("нужен юрист") == "юрист")
    check("«автомастерская» → автосервис",
          detect_category("ищу автомастерскую в Гааге") == "автосервис")
    check("«детейлинг» → автосервис",
          detect_category("химчистка салона и детейлинг авто") == "автосервис")
    check("домашняя химчистка → клининг",
          detect_category("нужна химчистка дивана") == "клининг")
    check("«ситуация» не превращается в тату",
          detect_category("помощь в сложной ситуации") is None)
    check("уроки вокала → музыкальные занятия",
          detect_category("ищу уроки вокала") == "музыкальные занятия")
    check("диджей → музыкант и диджей",
          detect_category("нужен DJ на праздник") == "музыкант и диджей")


def test_general_place_routing() -> None:
    from handlers.chat import is_general_place_query
    check("поиск мест идёт не в справочник",
          is_general_place_query("Найди интересные места в Гааге"))
    check("поиск кафе идёт не в справочник",
          is_general_place_query("Посоветуй кафе в Амстердаме"))
    check("автомастерская остаётся поиском контакта",
          not is_general_place_query("Ищу автомастерскую в Гааге"))


def test_ad_calendar_payload() -> None:
    from utils.ad_calendar import _booking_dates, _event_payload, _priority

    campaign = AdBooking(
        id=501,
        date="2026-08-29",
        dates_csv="2026-08-29,2026-09-12,2026-09-26,2026-10-10",
        fmt="numr_campaign",
        opt="std",
        status="paid",
        company="NUMR",
        amount="299.00",
    )
    payload = _event_payload(campaign, "2026-09-12")
    check("Calendar указывает клиента и номер рекламного выхода",
          payload["summary"] == "Реклама NUMR — 2-й Reel + 3 Stories")
    check("Calendar хранит полный состав и фактическую цену кампании",
          "12 Stories" in payload["description"]
          and "€299.00" in payload["description"]
          and "Все даты кампании" in payload["description"])
    check("Calendar создаёт настоящее событие на весь день",
          payload["start"] == {"date": "2026-09-12"}
          and payload["end"] == {"date": "2026-09-13"})

    repeated = AdBooking(
        id=502, date="2026-09-01", dates_csv=None, fmt="tg", opt="std",
        addon="repeat", status="pending", company="Repeat Test", amount="100.00",
    )
    check("повторный Telegram-пост добавляет второй выход через 14 дней",
          _booking_dates(repeated) == ["2026-09-01", "2026-09-15"])

    closed = AdBooking(id=503, date="2026-09-12", fmt="closed", status="closed")
    check("оплаченная бронь приоритетнее случайного ручного дубля",
          _priority(campaign) < _priority(closed))


async def test_repeat_ad_reserves_second_date() -> None:
    import handlers.ads as ads

    old_key = config.MOLLIE_API_KEY
    old_webhook = config.WEBHOOK_BASE_URL
    real_create_payment = ads.create_payment
    config.MOLLIE_API_KEY = "test_key"
    config.WEBHOOK_BASE_URL = "https://example.test"
    first_date = datetime.now().date() + timedelta(days=10)

    async def fake_create_payment(*_args, **_kwargs):
        return {"id": "tr_repeat", "checkout_url": "https://pay.example/repeat"}

    try:
        ads.create_payment = fake_create_payment
        url, error = await ads.book_and_pay(
            "tg", "std", [first_date.isoformat()],
            {
                "terms": True,
                "addon": True,
                "client_type": "business",
                "email": "repeat@example.com",
                "address": "Damrak 1, Amsterdam",
                "company": "Repeat Test",
                "postcode": "1012 LG",
            },
        )
        async with db.get_session() as session:
            booking = (await session.scalars(select(AdBooking).where(
                AdBooking.company == "Repeat Test"
            ))).first()
        repeat_date = (first_date.date() if isinstance(first_date, datetime) else first_date) + timedelta(days=14)
        check("оплачиваемый повтор резервирует обе даты в базе",
              not error and bool(url) and booking is not None
              and booking.dates_csv == f"{first_date.isoformat()},{repeat_date.isoformat()}")
        check("бронь сохраняет фактически выставленную сумму",
              booking is not None and booking.amount == "100.00")
    finally:
        ads.create_payment = real_create_payment
        config.MOLLIE_API_KEY = old_key
        config.WEBHOOK_BASE_URL = old_webhook


async def main() -> None:
    test_import_bot()
    test_specialist_premium_six_month_plan()
    test_specialist_onboarding_ux()
    test_board_ux()
    test_ad_promotion_deadline()
    test_numr_campaign_page()
    await test_db_and_categories()
    await test_board_payment_retry_and_expiry_reminder()
    await test_specialist_payment_retry_keeps_form()
    await test_saved_items()
    await test_personal_home_snapshot()
    await test_product_analytics()
    await test_notification_center()
    await test_content_center()
    await test_repair_luxar_category()
    test_fix_category_no_override()
    test_taxonomy_and_seed_categories()
    test_multi_category_discovery()
    await test_reseed_preserves_premium()
    await test_reseed_ids_stable_all()
    await test_reseed_keeps_edited_premium_card()
    await test_specialist_reminder_delivery_log()
    await test_premiums_query()
    await test_personal_digest()
    await test_allo_capacity()
    test_allo_schedule()
    await test_allo_website()
    await test_allo_referral()
    test_wordpress_util()
    test_detect_category_basic()
    test_general_place_routing()
    test_ad_calendar_payload()
    await test_repeat_ad_reserves_second_date()
    print()
    if _fails:
        print(f"❌ Провалено проверок: {len(_fails)} -> {', '.join(_fails)}")
        sys.exit(1)
    print("✅ Все проверки пройдены")


if __name__ == "__main__":
    asyncio.run(main())
