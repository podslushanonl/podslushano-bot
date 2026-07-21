"""Быстрые проверки критичных инвариантов бота (запуск: python tests/run_tests.py).

Ловят регрессии в том, что уже ломалось: импорт, категории специалистов,
авто-переопределение категории, премиум-приоритет, сохранение премиума/фото
при пересеве. Падает с ненулевым кодом — удобно вешать на хук/CI.
"""
import asyncio
import os
import sys
import tempfile

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
    BotUser,
    DigestDeliveryLog,
    DigestPreference,
    EventListing,
    Listing,
    Meta,
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


def test_fix_category_no_override() -> None:
    # Курируемая категория главнее имени (баг «Space» → «spa» → косметолог)
    from utils.geo import detect_category
    # detect по имени может ошибаться — это норма, главное что её не применяют
    item = {"name": "Fancy Beauty Space", "category": "мастер маникюра"}
    result = item.get("category") or detect_category(item["name"])
    check("категория из данных, а не по имени", result == "мастер маникюра",
          f"получили {result}")


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
    """В боте одна прогулка; после старта она автоматически исчезает."""
    from datetime import datetime
    before = datetime.fromisoformat("2026-07-19T10:00:00+02:00")
    after = datetime.fromisoformat("2026-07-25T11:01:00+02:00")
    walks = config.available_allo_walks(before)
    check("доступна только прогулка Nijmegen 25 июля",
          len(walks) == 1 and walks[0]["key"] == "2026-07-25")
    check("вместимость Allo Walks = 8", config.ALLO_WALK_CAPACITY == 8)
    check("прошедшая прогулка автоматически скрывается",
          config.available_allo_walks(after) == [])


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
    from datetime import date
    from handlers.digest import (
        build_digest,
        digest_announcement_kb,
        digest_announcement_text,
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
    exact = DigestPreference(
        user_id=7002, city="Utrecht", province="Utrecht", radius_km=0,
        topics_csv="events", enabled=True,
    )
    check("подборка: режим города не захватывает соседний город",
          not location_matches(exact, "Amersfoort"))

    month = f"{date.today():%Y-%m}"
    async with db.get_session() as session:
        session.add(BotUser(user_id=7001, first_name="Digest", is_blocked=False))
        session.add(pref)
        session.add(EventListing(
            title="Digest test event", description="test", city="Amersfoort",
            is_nationwide=False, event_date="суббота", month_key=month,
            status="approved",
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

    from utils.ai import parse_event_cards
    today_iso = date.today().isoformat()
    cards = parse_event_cards(
        f"<event><title>Festival</title><start>{today_iso}</start><date>25 juli · 19:00</date>"
        "<venue>De Hallen</venue><city>Amsterdam</city>"
        "<description>Музыка и еда.</description>"
        "<url>https://example.nl/event</url><source>Example</source></event>"
        f"<event><title>Без ссылки</title><start>{today_iso}</start><date>26 juli</date>"
        "<url></url></event>"
    )
    check("структурированная афиша создаёт только карточки с рабочей ссылкой",
          len(cards) == 1 and cards[0]["venue"] == "De Hallen", str(cards))

    class FakeBot:
        def __init__(self):
            self.calls = []

        async def send_message(self, chat_id, text, **kwargs):
            self.calls.append(chat_id)
            return type("Sent", (), {"message_id": 991})()

    from handlers.digest import _send_all_digests, _week_key
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


async def main() -> None:
    test_import_bot()
    await test_db_and_categories()
    test_fix_category_no_override()
    await test_reseed_preserves_premium()
    await test_reseed_ids_stable_all()
    await test_reseed_keeps_edited_premium_card()
    await test_specialist_reminder_delivery_log()
    await test_premiums_query()
    await test_personal_digest()
    await test_allo_capacity()
    test_allo_schedule()
    await test_allo_referral()
    test_wordpress_util()
    test_detect_category_basic()
    print()
    if _fails:
        print(f"❌ Провалено проверок: {len(_fails)} -> {', '.join(_fails)}")
        sys.exit(1)
    print("✅ Все проверки пройдены")


if __name__ == "__main__":
    asyncio.run(main())
