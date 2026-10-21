"""Описание таблиц базы данных."""
import enum
from datetime import datetime, timezone

from sqlalchemy import (BigInteger, Boolean, CheckConstraint, DateTime, Enum, Float, ForeignKey, Index, Integer, LargeBinary,
                        String, Text, UniqueConstraint, func)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, validates


class Base(DeclarativeBase):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Country(str, enum.Enum):
    """Страны приложения. В базе хранится русское название (значение), а не код."""

    NL = "Нидерланды"
    DE = "Германия"
    BE = "Бельгия"

    @classmethod
    def parse(cls, value: "Country | str") -> "Country":
        """Строгая проверка: только эти три названия (или сам элемент перечисления), иначе ValueError."""
        if isinstance(value, cls):
            return value
        text = str(value or "").strip()
        for c in cls:
            if text == c.value:
                return c
        raise ValueError(f"Неизвестная страна: {text!r}")


class FriendStatus(str, enum.Enum):
    PENDING = "pending"     # заявка отправлена, ждёт ответа
    ACCEPTED = "accepted"   # в друзьях
    BLOCKED = "blocked"     # user_id заблокировал friend_id


def _enum(cls: type[enum.Enum], name: str, length: int) -> Enum:
    # Не родной ENUM базы, а VARCHAR + CHECK: одинаково работает в SQLite и PostgreSQL и легко расширяется
    return Enum(cls, name=name, native_enum=False, create_constraint=True, length=length,
                values_callable=lambda e: [x.value for x in e], validate_strings=True)


class Submission(Base):
    """Заявка от пользователя: история, вопрос, видео или реклама."""

    __tablename__ = "submissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Тип заявки: story | question | video | ad
    type: Mapped[str] = mapped_column(String(20))
    # Кто прислал (для истории остаётся анонимным при публикации, но мы храним для модерации)
    user_id: Mapped[int] = mapped_column(BigInteger)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Текст заявки
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Вложение (видео/фото/документ), если есть — храним telegram file_id
    file_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Структурированные данные анкеты (JSON). Для видео: авторство, контекст,
    # параметры файла и зафиксированное согласие на публикацию.
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Статус: pending | approved (контент-банк) | published | rejected
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Specialist(Base):
    """Специалист из гайда контактов (стоматолог, юрист и т.д.)."""

    __tablename__ = "specialists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200))
    # Категория (ключ из utils/geo.py CATEGORIES), напр. "стоматолог"
    category: Mapped[str] = mapped_column(String(50))
    city: Mapped[str] = mapped_column(String(100))
    # Провинция вычисляется по городу при загрузке (для поиска по соседям)
    province: Mapped[str] = mapped_column(String(50))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Контакт: телефон / @username / ссылка / сайт
    contact: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # Онлайн-специалист (работает по всей стране) — показываем для любого города
    is_online: Mapped[bool] = mapped_column(Boolean, default=False)
    # Премиум-размещение: выше в выдаче + бейдж
    is_premium: Mapped[bool] = mapped_column(Boolean, default=False)
    # Статус: active (виден в поиске) | pending (ждёт оплаты/проверки) | expired
    status: Mapped[str] = mapped_column(String(20), default="active")
    # Откуда карточка: seed (из гайда) | admin (добавил админ) | self (само-добавление)
    source: Mapped[str] = mapped_column(String(20), default="seed")
    # Telegram-id того, кто добавил себя сам (для платного потока)
    submitter_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # E-mail для счёта (factuur)
    invoice_email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # До какого момента оплачено размещение (None = бессрочно: seed/admin)
    paid_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Id платежа в Mollie (для платного потока)
    payment_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Тариф размещения, например month | year | 6m_premium (для продления той же ценой)
    plan: Mapped[str] = mapped_column(String(20), default="year")
    # Напомнили ли уже о продлении (чтобы не слать дважды)
    renewal_reminded: Mapped[bool] = mapped_column(Boolean, default=False)
    # Фото карточки (Telegram file_id) — для премиум-размещения
    photo_file_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Бонусный премиум до этого момента (реферальная награда). None = не бонусный.
    premium_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Кто привёл этого специалиста (id карточки реферера) — для реф-программы
    referred_by_specialist_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Цвет плитки стандартной карточки на сайте: red | white | blue | green | orange
    card_color: Mapped[str | None] = mapped_column(String(10), nullable=True)


class SpecialistReminderLog(Base):
    """Попытка отправить специалисту напоминание о продлении.

    В отличие от ``Specialist.renewal_reminded`` эта таблица хранит проверяемый
    результат каждой попытки: Telegram message_id при успехе либо текст ошибки.
    ``paid_until`` привязывает запись к конкретному оплаченному периоду, чтобы
    после продления история не смешивалась с новым сроком.
    """

    __tablename__ = "specialist_reminder_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    specialist_id: Mapped[int] = mapped_column(Integer, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    # renewal = напоминание за 7 дней | expiry = карточка уже скрыта
    kind: Mapped[str] = mapped_column(String(20), index=True)
    paid_until: Mapped[datetime] = mapped_column(DateTime, index=True)
    # sent | failed
    status: Mapped[str] = mapped_column(String(20), index=True)
    message_text: Mapped[str] = mapped_column(Text)
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    error_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class SpecialistEdit(Base):
    """Предложенная специалистом правка своей карточки — ждёт одобрения модератора."""

    __tablename__ = "specialist_edits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    specialist_id: Mapped[int] = mapped_column(Integer, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger)
    # Какое поле меняем: name | category | city | description | contact | photo
    field: Mapped[str] = mapped_column(String(30))
    # Новое значение (для photo — Telegram file_id)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Статус: pending | approved | rejected
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class SpecialistClaim(Base):
    """Заявка специалиста на привязку к себе карточки из гайда — ждёт одобрения."""

    __tablename__ = "specialist_claims"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    specialist_id: Mapped[int] = mapped_column(Integer, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Необязательное пояснение от заявителя (подтверждение, что это его карточка)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Статус: pending | approved | rejected
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AuthorAgreementAcceptance(Base):
    """Фиксация принятия условий участия автором podslushano.nl."""

    __tablename__ = "author_agreement_acceptances"
    __table_args__ = (
        UniqueConstraint("email", "agreement_version", name="uq_author_agreement_email_version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    full_name: Mapped[str] = mapped_column(String(200))
    city: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(200), index=True)
    telegram: Mapped[str] = mapped_column(String(200))
    instagram: Mapped[str | None] = mapped_column(String(200), nullable=True)
    phone_model: Mapped[str] = mapped_column(String(120))
    agreement_version: Mapped[str] = mapped_column(String(20))
    agreement_sha256: Mapped[str] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    accepted_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class AdminChannel(Base):
    """Telegram-канал, добавленный администратором для ручных публикаций."""

    __tablename__ = "admin_channels"

    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    added_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Meta(Base):
    """Служебная таблица «ключ-значение» (например, версия засева базы)."""

    __tablename__ = "meta"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)   # бывают длинные ключи-отметки
    value: Mapped[str] = mapped_column(Text)   # бывают file_id Telegram и списки id — длиннее 100 символов


class EditorialIdea(Base):
    """A research-radar candidate and the editor's decision about it."""

    __tablename__ = "editorial_ideas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stream_key: Mapped[str] = mapped_column(String(24), index=True)
    headline: Mapped[str] = mapped_column(String(240))
    payload_json: Mapped[str] = mapped_column(Text)
    # pending | selected | reserved | rejected
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    chosen_format: Mapped[str | None] = mapped_column(String(24), nullable=True)
    feedback_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class AdLead(Base):
    """Заявка на рекламу с публичной страницы /reklama (без цен)."""

    __tablename__ = "ad_leads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    business: Mapped[str | None] = mapped_column(String(200), nullable=True)
    contact: Mapped[str | None] = mapped_column(String(200), nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AdBooking(Base):
    """Бронь рекламного слота на дату (с сайта) или закрытая дата (админом)."""

    __tablename__ = "ad_bookings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Дата размещения в формате ГГГГ-ММ-ДД
    date: Mapped[str] = mapped_column(String(10), index=True)
    # Формат: expert | promo | afisha | afisha_plus | closed (закрыто админом)
    fmt: Mapped[str] = mapped_column(String(20), default="closed")
    # Вариант длительности формата (ключ из AD_FORMATS[...]["options"])
    opt: Mapped[str] = mapped_column(String(20), default="std")
    # Выбранная доп-услуга (напр. повторная публикация), ключ или None
    addon: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Все даты выхода через запятую (для форматов с несколькими публикациями)
    dates_csv: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Статус: pending (ждёт оплаты) | paid | closed (бронь админа) | canceled
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    # Реквизиты покупателя для фактуры
    client_type: Mapped[str | None] = mapped_column(String(20), nullable=True)  # person|business
    buyer_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    company: Mapped[str | None] = mapped_column(String(200), nullable=True)
    btw: Mapped[str | None] = mapped_column(String(40), nullable=True)
    kvk: Mapped[str | None] = mapped_column(String(40), nullable=True)
    address: Mapped[str | None] = mapped_column(String(300), nullable=True)
    postcode: Mapped[str | None] = mapped_column(String(20), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    payment_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Фактически выставленная сумма. Она может отличаться от текущей цены
    # формата (например, если бронь была сделана во время акции).
    amount: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # waiting | received. Напоминания отправляются только пока материалы не получены.
    materials_status: Mapped[str] = mapped_column(String(20), default="waiting", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AdReminderLog(Base):
    """Результат автоматического напоминания по конкретному рекламному выходу."""

    __tablename__ = "ad_reminder_logs"
    __table_args__ = (
        UniqueConstraint("booking_id", "publish_date", "kind", name="uq_ad_reminder_delivery"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    booking_id: Mapped[int] = mapped_column(Integer, index=True)
    publish_date: Mapped[str] = mapped_column(String(10), index=True)
    # 48h | 24h | day_of
    kind: Mapped[str] = mapped_column(String(20), index=True)
    channel: Mapped[str] = mapped_column(String(20), default="email")
    # sent | failed
    status: Mapped[str] = mapped_column(String(20), index=True)
    recipient: Mapped[str | None] = mapped_column(String(200), nullable=True)
    error_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), index=True
    )


class Event(Base):
    """Событие для аналитики: поиск, заявка, оплата и т.п."""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(String(30), index=True)
    key: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ProductEvent(Base):
    """Псевдонимизированное продуктовое действие конкретного пользователя.

    Telegram ID нужен для уникальных пользователей и retention; текст сообщений,
    имя, username и контактные данные не сохраняются. Отдельная
    таблица сохраняет совместимость со старой агрегированной таблицей ``events``.
    """

    __tablename__ = "product_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    name: Mapped[str] = mapped_column(String(50), index=True)
    entity_type: Mapped[str] = mapped_column(String(30), default="", index=True)
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str] = mapped_column(String(30), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), index=True
    )


class Review(Base):
    """Отзыв и оценка специалиста. Привязка по стабильному ключу (имя+контакт),
    чтобы оценки не терялись при пере-засеве базы (где меняются id)."""

    __tablename__ = "reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    spec_key: Mapped[str] = mapped_column(String(500), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger)
    rating: Mapped[int] = mapped_column(Integer)  # 1..5
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class BotUser(Base):
    """Пользователь бота — для рассылок-анонсов."""

    __tablename__ = "users"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # Заблокировал ли бота (тогда рассылку ему не шлём)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    # Кто пригласил (Telegram-id реферера) — для роста по реферальным ссылкам
    referred_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class DigestPreference(Base):
    """Настройки нативной персональной подборки пользователя."""

    __tablename__ = "digest_preferences"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    city: Mapped[str] = mapped_column(String(100), default="")
    province: Mapped[str] = mapped_column(String(50), default="")
    # 0 — только город, 25/50 — радиус в километрах, 999 — вся страна.
    radius_km: Mapped[int] = mapped_column(Integer, default=25)
    # CSV из events,walks,specialists,board,guides.
    topics_csv: Mapped[str] = mapped_column(
        String(120), default="events,walks"
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_sent_week: Mapped[str | None] = mapped_column(String(8), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class DigestDeliveryLog(Base):
    """Проверяемый результат доставки еженедельной подборки."""

    __tablename__ = "digest_delivery_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    week_key: Mapped[str] = mapped_column(String(8), index=True)
    city: Mapped[str] = mapped_column(String(100), default="")
    status: Mapped[str] = mapped_column(String(10))  # sent | failed
    message_text: Mapped[str] = mapped_column(Text)
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    error_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class SavedItem(Base):
    """Карточка, которую пользователь сохранил в «Мой podslushano.nl»."""

    __tablename__ = "saved_items"
    __table_args__ = (
        UniqueConstraint("user_id", "item_type", "item_id", name="uq_saved_user_item"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    # specialist | listing | event | discovered_event.
    item_type: Mapped[str] = mapped_column(String(20), index=True)
    item_id: Mapped[int] = mapped_column(Integer, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class NotificationPreference(Base):
    """Добровольные оперативные уведомления пользователя.

    Еженедельная подборка остаётся в ``DigestPreference``: здесь только
    напоминания о сохранённых событиях, новые локальные объявления и изменения
    статусов собственных действий.
    """

    __tablename__ = "notification_preferences"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    event_reminders: Mapped[bool] = mapped_column(Boolean, default=False)
    new_listings: Mapped[bool] = mapped_column(Boolean, default=False)
    action_updates: Mapped[bool] = mapped_column(Boolean, default=False)
    # daily | weekly. Напоминания о событиях всегда приходят накануне.
    frequency: Mapped[str] = mapped_column(String(10), default="daily")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class NotificationDelivery(Base):
    """Проверяемая доставка одного элемента персонального уведомления."""

    __tablename__ = "notification_deliveries"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "delivery_key", name="uq_notification_user_delivery"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    # event:event:12:2026-07-24 | listing:44 | status:listing:9:approved
    delivery_key: Mapped[str] = mapped_column(String(120), index=True)
    kind: Mapped[str] = mapped_column(String(30), index=True)
    status: Mapped[str] = mapped_column(String(10), default="sent")
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    error_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class NotificationState(Base):
    """Последний известный статус собственного действия пользователя."""

    __tablename__ = "notification_states"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "entity_type", "entity_id",
            name="uq_notification_user_entity",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    entity_type: Mapped[str] = mapped_column(String(30), index=True)
    entity_id: Mapped[int] = mapped_column(Integer, index=True)
    last_status: Mapped[str] = mapped_column(String(30))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class AnnouncementDelivery(Base):
    """Поштучный журнал разовой массовой рассылки.

    Пара ``campaign_key + user_id`` не позволяет отправить один и тот же анонс
    повторно после рестарта, а отсутствие записи позволяет продолжить рассылку
    с оставшихся пользователей.
    """

    __tablename__ = "announcement_deliveries"
    __table_args__ = (
        UniqueConstraint("campaign_key", "user_id", name="uq_announcement_campaign_user"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_key: Mapped[str] = mapped_column(String(80), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    status: Mapped[str] = mapped_column(String(10))  # sent | blocked | failed
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    error_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ContentPost(Base):
    """Запланированная публикация Контент-центра в Telegram-канал."""

    __tablename__ = "content_posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    template_key: Mapped[str] = mapped_column(String(40), index=True)
    content_kind: Mapped[str] = mapped_column(String(30), index=True)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    # scheduled | sending | sent | skipped | failed
    status: Mapped[str] = mapped_column(String(12), default="scheduled", index=True)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    button_label: Mapped[str] = mapped_column(String(60))
    start_payload: Mapped[str] = mapped_column(String(64), unique=True)
    dynamic_refs: Mapped[str] = mapped_column(Text, default="")
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    error_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ContentClick(Base):
    """Уникальный переход пользователя из публикации в нужный раздел бота."""

    __tablename__ = "content_clicks"
    __table_args__ = (
        UniqueConstraint("campaign_key", "user_id", name="uq_content_campaign_user"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_key: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    is_new_user: Mapped[bool] = mapped_column(Boolean, default=False)
    destination_opened: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class EventListing(Base):
    """Платное мероприятие в «Афише месяца» (подаёт организатор, после оплаты и
    проверки админом публикуется)."""

    __tablename__ = "event_listings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Ссылка на билеты / соцсети
    link: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Постер мероприятия (Telegram file_id) — обязателен при подаче
    photo_file_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Город проведения ("" + is_nationwide=True — по всей стране/онлайн)
    city: Mapped[str] = mapped_column(String(100), default="")
    is_nationwide: Mapped[bool] = mapped_column(Boolean, default=False)
    # Дата или период проведения (свободным текстом, напр. «12–14 июля»)
    event_date: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Точные границы для автоматического скрытия после завершения. У старых
    # заявок могут быть NULL; новые анкеты требуют однозначную цифровую дату.
    starts_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    # Месяц афиши в формате ГГГГ-ММ (напр. «2026-07»)
    month_key: Mapped[str] = mapped_column(String(7), index=True)
    # Кто подал (Telegram-id) и e-mail для счёта
    submitter_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    invoice_email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Статус: awaiting_payment | pending (оплачено, на проверке) | approved | rejected
    status: Mapped[str] = mapped_column(String(20), default="awaiting_payment")
    payment_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    # С сайта: время начала, место, категория и откуда пришла заявка (bot | site)
    event_time: Mapped[str | None] = mapped_column(String(40), nullable=True)
    venue: Mapped[str | None] = mapped_column(String(200), nullable=True)
    category: Mapped[str | None] = mapped_column(String(40), nullable=True)
    source: Mapped[str | None] = mapped_column(String(10), nullable=True)


class DiscoveredEvent(Base):
    """Проверяемое мероприятие, найденное живым поиском и сохранённое для карусели.

    Один поиск создаёт batch_key. Благодаря этому один и тот же результат можно
    показать всем пользователям сегмента, не оплачивая новый AI-запрос на каждого.
    """

    __tablename__ = "discovered_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_key: Mapped[str] = mapped_column(String(24), index=True)
    query_city: Mapped[str] = mapped_column(String(100), index=True)
    radius_km: Mapped[int] = mapped_column(Integer, default=25)
    title: Mapped[str] = mapped_column(String(240))
    description: Mapped[str] = mapped_column(Text, default="")
    event_date: Mapped[str] = mapped_column(String(160), default="")
    venue: Mapped[str] = mapped_column(String(200), default="")
    city: Mapped[str] = mapped_column(String(100), default="")
    link: Mapped[str] = mapped_column(String(700))
    source_name: Mapped[str] = mapped_column(String(120), default="")
    # Раздел общей афиши: highlights | music | culture | family | markets |
    # islands | nearby. Старое поле link остаётся канонической страницей
    # события; отдельная билетная ссылка показывается второй кнопкой.
    section_key: Mapped[str] = mapped_column(String(24), default="nearby", index=True)
    source_url: Mapped[str] = mapped_column(String(700), default="")
    ticket_url: Mapped[str] = mapped_column(String(700), default="")
    photo_url: Mapped[str] = mapped_column(String(1000), default="")
    territory: Mapped[str] = mapped_column(String(100), default="Nederland")
    # Нормализованное время начала. Для событий без указанного времени хранится
    # конец календарного дня, чтобы дневное событие не исчезало утром.
    starts_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)


class Listing(Base):
    """Объявление на доске (бесплатная подача, модерация, платное «поднятие»)."""

    __tablename__ = "listings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Категория (ключ из handlers/board.py: housing|goods|free|services|jobs|rides|other)
    category: Mapped[str] = mapped_column(String(20), index=True)
    # Намерение внутри категории: offer|seek|driver|passenger (у старых карточек None)
    intent: Mapped[str | None] = mapped_column(String(20), nullable=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Цена свободным текстом: «€50», «договорная», «даром»
    price: Mapped[str | None] = mapped_column(String(100), nullable=True)
    city: Mapped[str] = mapped_column(String(100), default="")
    is_nationwide: Mapped[bool] = mapped_column(Boolean, default=False)
    photo_file_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Все фото объявления из приложения (JSON-список file_id, первое = photo_file_id); у объявлений из бота — пусто
    photos: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Контакт автора, который показываем покупателям (@username / телефон / сайт)
    contact: Mapped[str | None] = mapped_column(String(300), nullable=True)
    submitter_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    submitter_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Автор из приложения podslushano (app_users.id); у поданных через бота — None
    app_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    # Статус: awaiting_payment | pending | approved | rejected | closed | expired | archived
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    # Платёж за «поднятие» (если было) и время поднятия (для сортировки вверх)
    payment_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    bumped_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AlloBooking(Base):
    """Запись на прогулку allowalks (разовая или абонемент на 3)."""

    __tablename__ = "allo_bookings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Ключ прогулки (дата, напр. 2026-07-11) или "pass" для абонемента на все 3
    walk_key: Mapped[str] = mapped_column(String(20), index=True)
    plan: Mapped[str] = mapped_column(String(10), default="single")  # single | pass
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    amount: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # pending | paid | expired | canceled | forfeited | canceled_no_refund |
    # refund_requested | refunded
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    payment_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    agreed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AlloReferral(Base):
    """Реферал allowalks: кто кого привёл. Приводящий получает €10-кредит,
    когда приведённый впервые оплачивает прогулку."""

    __tablename__ = "allo_referrals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    referrer_uid: Mapped[int] = mapped_column(BigInteger, index=True)  # кто привёл
    referred_uid: Mapped[int] = mapped_column(BigInteger, index=True)  # кого привели
    # pending (привели, ещё не оплатил) | earned (доступный €10) |
    # reserved (держим под конкретную бронь) | spent (потрачен)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    booking_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AlloWebCode(Base):
    """Purchased gift balance or a reviewed legacy three-walk entitlement."""

    __tablename__ = "allo_web_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    code_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    kind: Mapped[str] = mapped_column(String(10))  # gift | pass
    owner_email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    value_cents: Mapped[int] = mapped_column(Integer, default=0)
    total_uses: Mapped[int] = mapped_column(Integer, default=0)
    issued_sale_id: Mapped[int | None] = mapped_column(Integer, unique=True, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    email_sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AlloWebSale(Base):
    """Website checkout. Pending orders reserve one seat or gift balance for 60 min."""

    __tablename__ = "allo_web_sales"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    kind: Mapped[str] = mapped_column(String(10))  # walk | gift
    event_key: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    event_title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    event_starts_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    event_meeting: Mapped[str | None] = mapped_column(String(500), nullable=True)
    event_capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    buyer_name: Mapped[str] = mapped_column(String(120))
    buyer_email: Mapped[str] = mapped_column(String(200))
    recipient_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    recipient_email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    gift_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    gross_cents: Mapped[int] = mapped_column(Integer)
    discount_cents: Mapped[int] = mapped_column(Integer, default=0)
    amount_cents: Mapped[int] = mapped_column(Integer)
    code_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    payment_id: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    email_state: Mapped[str] = mapped_column(String(16), default="pending")
    email_attempted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Подарок: дата отправки получателю (YYYY-MM-DD, Амстердам); None — сразу после оплаты
    send_on: Mapped[str | None] = mapped_column(String(10), nullable=True)


class CommentReplyDraft(Base):
    """Temporary AI suggestions shown to an admin for an Instagram comment."""

    __tablename__ = "comment_reply_drafts"

    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    post_context: Mapped[str] = mapped_column(Text, default="")
    payload_json: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    chosen_reply: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class CommentReplyExample(Base):
    """An explicit editor choice used as a future brand-voice example."""

    __tablename__ = "comment_reply_examples"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_comment: Mapped[str] = mapped_column(Text)
    post_context: Mapped[str] = mapped_column(Text, default="")
    action: Mapped[str] = mapped_column(String(20))
    reply: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class SiteGuide(Base):
    """Практическая справка на сайте («Как получить BSN»), которую пишет и обновляет бот.

    key — тема из utils/site_guides.TOPICS (или предложенная ИИ), одна справка на тему.
    status: published | failed. updated_at — когда текст последний раз переписан.
    """

    __tablename__ = "site_guides"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(80), unique=True)
    query: Mapped[str] = mapped_column(String(300), default="")
    title: Mapped[str] = mapped_column(String(300), default="")
    status: Mapped[str] = mapped_column(String(16), index=True)
    wp_post_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    wp_link: Mapped[str | None] = mapped_column(String(500), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), index=True
    )


class SiteNewsItem(Base):
    """Статья из новостной ленты, которую бот уже рассмотрел для сайта.

    По source_url бот понимает, что новость уже видел, и не берёт её повторно.
    status: skipped (не подошла / первый запуск) | published | failed.
    """

    __tablename__ = "site_news_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_url: Mapped[str] = mapped_column(String(500), unique=True)
    title_nl: Mapped[str] = mapped_column(String(500), default="")
    status: Mapped[str] = mapped_column(String(16), index=True)
    wp_post_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    wp_link: Mapped[str | None] = mapped_column(String(500), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # UTC без часового пояса — пишем явно из Python, чтобы считать сутки по Амстердаму.
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), index=True
    )


class NsSubscription(Base):
    """Подписка на уведомления о сбоях NS по станции (сайт → бот ?start=ns_<код>)."""

    __tablename__ = "ns_subscriptions"
    __table_args__ = (UniqueConstraint("user_id", "station_code", name="uq_ns_sub_user_station"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    station_code: Mapped[str] = mapped_column(String(8), index=True)
    station_name: Mapped[str] = mapped_column(String(80), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )


class NsAlertSent(Base):
    """Какие сбои уже отправлены человеку, чтобы не повторять одно и то же."""

    __tablename__ = "ns_alerts_sent"
    __table_args__ = (UniqueConstraint("user_id", "disruption_id", name="uq_ns_alert_user_dis"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    disruption_id: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), index=True
    )


class WeekSubscriber(Base):
    """Подписчик пятничной рассылки «Неделя в Нидерландах» (подписка с подтверждением почты)."""

    __tablename__ = "week_subscribers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    # pending (ждёт подтверждения) | active | unsubscribed
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    source: Mapped[str] = mapped_column(String(40), default="site")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    unsubscribed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class SavingsReminder(Base):
    """«Напомнить до 31 декабря» из раздела «Сэкономить» (одно напоминание на тему в год)."""

    __tablename__ = "savings_reminders"
    __table_args__ = (UniqueConstraint("user_id", "topic", "year", name="uq_savings_rem"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    topic: Mapped[str] = mapped_column(String(20), default="zorg")
    year: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class LinkClick(Base):
    """Переход по ссылке раздела «Сэкономить» через /go/<ключ> (бот, сайт, Instagram)."""

    __tablename__ = "link_clicks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(40), index=True)
    source: Mapped[str] = mapped_column(String(20), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), index=True
    )


class AppUser(Base):
    """Аккаунт в приложении podslushano: вход по коду на телефон или почту и/или через Telegram."""

    __tablename__ = "app_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str | None] = mapped_column(String(200), unique=True, nullable=True, index=True)
    tg_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, nullable=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(20), unique=True, nullable=True, index=True)   # +31612345678
    name: Mapped[str] = mapped_column(String(80), default="")
    city: Mapped[str] = mapped_column(String(80), default="")
    country: Mapped[Country] = mapped_column(_enum(Country, "ck_app_user_country", 20), default=Country.NL,
                                             server_default=Country.NL.value, nullable=False,
                                             index=True)   # частый фильтр: люди и лента по стране
    bio: Mapped[str] = mapped_column(String(160), default="", server_default="")   # статус / «о себе»
    avatar: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True, deferred=True)   # JPEG 512 px
    avatar_v: Mapped[int] = mapped_column(Integer, default=0, server_default="0")   # версия — для кэша картинки
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )
    last_seen: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    rules_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)      # принял правила сообщества
    banned_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # бан в чатах и постах
    # Закрытый аккаунт: публикации, друзей и личные сообщения видят только друзья (статус accepted)
    is_private: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    # «Завершить другие сеансы»: токены, выданные раньше этого момента без записи сеанса, не принимаются
    sessions_reset_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Синяя галочка: платная верификация (3.99 €/мес) или аккаунт создателя (config.ADMIN_IDS / VERIFIED_EMAILS)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    # Обложка профиля (широкий баннер над аватаром): JPEG до 1500 px, версия — для кэша картинки
    cover: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True, deferred=True)
    cover_v: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # @username: строго lowercase, уникальный; выдаётся автоматически, человек может сменить в профиле
    username: Mapped[str | None] = mapped_column(String(30), unique=True, nullable=True, index=True)
    # Местоположение по GPS (для ленты «Рядом» в радиусе 50 км); город и страну определяет Google по координатам
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    geo_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Платная галочка: до какой даты оплачена (NULL у галочки, выданной администратором, — бессрочно)
    verified_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    @validates("country")
    def _check_country(self, _key, value):
        return Country.parse(value)


class AppPayment(Base):
    """Платёж в приложении (сейчас — подписка «Премиум верификация» 3,99 € в месяц).
    provider: stripe | mock (проверка без реальной оплаты — только при BILLING_MOCK=1)."""
    __tablename__ = "app_payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    kind: Mapped[str] = mapped_column(String(20), default="verify")
    provider: Mapped[str] = mapped_column(String(10), default="stripe")
    amount_cents: Mapped[int] = mapped_column(Integer, default=399)
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    status: Mapped[str] = mapped_column(String(12), default="pending")   # pending | paid | canceled
    external_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)   # Checkout Session / подписка
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AppSession(Base):
    """Устройство, вошедшее в аккаунт приложения (раздел «Активные сессии» в настройках).
    id — случайная строка, она же лежит в токене входа: удалённый или завершённый сеанс токен больше не пускает."""

    __tablename__ = "app_sessions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    device: Mapped[str] = mapped_column(String(120), default="")   # «iPhone · Safari», «Android · приложение»
    ip: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )
    last_seen: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)


class Friendship(Base):
    """Связь двух аккаунтов приложения. Одна запись на пару для заявки и дружбы:
    user_id — кто отправил заявку, friend_id — кому. Блокировка направленная: user_id заблокировал friend_id
    (встречные блокировки — две записи). Личные сообщения доступны только при статусе accepted.
    pair_key «меньший:больший id» у заявки и дружбы (у блокировки пусто) уникален, поэтому
    одновременные встречные заявки не создадут две записи на одну пару."""

    __tablename__ = "friendships"
    __table_args__ = (
        Index("ix_friendship_pair", "user_id", "friend_id", unique=True),
        Index("ix_friendship_friend_status", "friend_id", "status"),
        Index("ix_friendship_pair_key", "pair_key", unique=True),
        CheckConstraint("user_id <> friend_id", name="ck_friendship_not_self"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("app_users.id", ondelete="CASCADE"))
    friend_id: Mapped[int] = mapped_column(Integer, ForeignKey("app_users.id", ondelete="CASCADE"))
    status: Mapped[FriendStatus] = mapped_column(_enum(FriendStatus, "ck_friendship_status", 10), default=FriendStatus.PENDING)
    pair_key: Mapped[str | None] = mapped_column(String(24), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class AppLogin(Base):
    """Ожидающий вход: код на почту (email) или телефон (phone), или подтверждение в Telegram (nonce)."""

    __tablename__ = "app_logins"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(10))            # email | phone | tg
    key: Mapped[str] = mapped_column(String(200), index=True)  # почта, номер или nonce
    code_hash: Mapped[str] = mapped_column(String(64), default="")
    tg_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    tg_name: Mapped[str] = mapped_column(String(80), default="")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    used: Mapped[bool] = mapped_column(Boolean, default=False)


class AppFavorite(Base):
    """Избранное пользователя приложения (сейчас — события афиши)."""

    __tablename__ = "app_favorites"
    __table_args__ = (UniqueConstraint("user_id", "kind", "key", name="uq_app_fav"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    kind: Mapped[str] = mapped_column(String(20), default="event")
    key: Mapped[str] = mapped_column(String(120))
    title: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )


class ChatRoom(Base):
    """Комната чата приложения: город или тема. country пустая — общая комната для всех стран."""

    __tablename__ = "chat_rooms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String(40), unique=True)
    title: Mapped[str] = mapped_column(String(80))
    kind: Mapped[str] = mapped_column(String(10), default="city")   # city | topic
    country: Mapped[Country | None] = mapped_column(_enum(Country, "ck_chat_room_country", 20), nullable=True)
    sort: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class ChatMessage(Base):
    """Сообщение в комнате чата."""

    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    room_id: Mapped[int] = mapped_column(Integer, index=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), index=True
    )
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)   # удалил сам автор
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)    # скрыто модерацией / жалобами


class UserPost(Base):
    """Пост пользователя в ленте приложения. Репост — пост с repost_of (свой текст необязателен)."""

    __tablename__ = "user_posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    text: Mapped[str] = mapped_column(Text)
    city: Mapped[str] = mapped_column(String(80), default="")
    # Страна автора на момент публикации — для ленты «Рядом»
    country: Mapped[Country] = mapped_column(_enum(Country, "ck_user_post_country", 20), default=Country.NL,
                                             server_default=Country.NL.value, nullable=False, index=True)
    repost_of: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    photo_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Формат первого фото (ширина/высота), приведённый к стандарту: 1.0 — квадрат 1:1,
    # 0.8 — вертикальный 4:5 (1080×1350), 1.7778 — горизонтальный 16:9. Пусто — пост без фото или старый.
    photo_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Координаты автора в момент публикации (лента «Рядом» по радиусу); NULL — только по городу
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    # «Поделиться в профиле» новостью или событием: ссылка-превью на стене
    share_kind: Mapped[str | None] = mapped_column(String(10), nullable=True)       # news | event
    share_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    share_title: Mapped[str] = mapped_column(String(300), default="", server_default="")
    share_url: Mapped[str] = mapped_column(String(700), default="", server_default="")
    share_img: Mapped[str] = mapped_column(String(700), default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), index=True
    )
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)   # удалил сам автор
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)    # скрыто модерацией / жалобами

    @validates("country")
    def _check_country(self, _key, value):
        return Country.parse(value)


class PostPhoto(Base):
    """Фото поста: JPEG прямо в базе (не зависит от Telegram), до 4 на пост."""

    __tablename__ = "post_photos"
    __table_args__ = (UniqueConstraint("post_id", "idx", name="uq_post_photo"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    post_id: Mapped[int] = mapped_column(Integer, index=True)
    idx: Mapped[int] = mapped_column(Integer, default=0)
    data: Mapped[bytes] = mapped_column(LargeBinary)


class PostLike(Base):
    """Лайк поста: один на человека."""

    __tablename__ = "post_likes"
    __table_args__ = (UniqueConstraint("post_id", "user_id", name="uq_post_like"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    post_id: Mapped[int] = mapped_column(Integer, index=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class ItemLike(Base):
    """Лайк новости или события ленты (kind + key), один на человека."""

    __tablename__ = "item_likes"
    __table_args__ = (UniqueConstraint("kind", "key", "user_id", name="uq_item_like"),
                      Index("ix_item_like_target", "kind", "key"))

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(10))
    key: Mapped[str] = mapped_column(String(120))
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class ItemComment(Base):
    """Комментарий к новости или событию ленты. Правила и модерация — как у комментариев к постам."""

    __tablename__ = "item_comments"
    __table_args__ = (Index("ix_item_comment_target", "kind", "key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(10))
    key: Mapped[str] = mapped_column(String(120))
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)


class PostComment(Base):
    """Комментарий к посту. Те же правила, что у сообщений: мат, ссылки, лимиты, жалобы."""

    __tablename__ = "post_comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    post_id: Mapped[int] = mapped_column(Integer, index=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)


class ContentReport(Base):
    """Жалоба на сообщение чата или пост; уходит модераторам в Telegram."""

    __tablename__ = "content_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(10))       # msg | post | comment
    target_id: Mapped[int] = mapped_column(Integer, index=True)
    reporter_id: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )
    resolved: Mapped[str] = mapped_column(String(20), default="")   # "" | deleted | kept | banned


class DmConversation(Base):
    """Личный диалог двух друзей в приложении: просто переписка (listing_id пустой) или по объявлению барахолки."""

    __tablename__ = "dm_conversations"
    __table_args__ = (UniqueConstraint("listing_id", "buyer_id", "seller_id", name="uq_dm_pair"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    listing_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)   # старые объявления из бота
    item_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)      # объявление барахолки приложения
    buyer_id: Mapped[int] = mapped_column(Integer, index=True)    # кто начал диалог
    seller_id: Mapped[int] = mapped_column(Integer, index=True)   # автор объявления
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )
    last_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), index=True
    )
    # До какого сообщения каждый участник прочитал (id последнего прочитанного)
    buyer_read: Mapped[int] = mapped_column(Integer, default=0)
    seller_read: Mapped[int] = mapped_column(Integer, default=0)
    # До какого сообщения каждому участнику доставлено (он был в сети или открыл список) — вторая галочка
    buyer_got: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    seller_got: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Когда продавцу последний раз уходило напоминание в Telegram (не чаще раза в 10 минут)
    nudged_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class DmMessage(Base):
    """Сообщение личного диалога."""

    __tablename__ = "dm_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conv_id: Mapped[int] = mapped_column(Integer, index=True)
    sender_id: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )


# ---------------------------------------------------------------- длина строк
# PostgreSQL, в отличие от SQLite, не принимает строку длиннее VARCHAR(n) и роняет запрос.
# Подрезаем такие значения перед записью (с предупреждением в лог), чтобы длинный ввод
# из формы или от ИИ не превращался в ошибку 500. Enum и Text не трогаем.
import logging as _logging

from sqlalchemy import event as _event

_log = _logging.getLogger(__name__)


@_event.listens_for(Base, "before_insert", propagate=True)
@_event.listens_for(Base, "before_update", propagate=True)
def _fit_strings(mapper, _connection, target) -> None:
    for col in mapper.columns:
        if isinstance(col.type, Enum) or not isinstance(col.type, String):   # Text — тоже String
            continue
        key = mapper.get_property_by_column(col).key
        value = getattr(target, key, None)
        if isinstance(value, str) and "\x00" in value:
            # Нулевой символ (бывает в тексте с сайтов) PostgreSQL не принимает вовсе
            value = value.replace("\x00", "")
            setattr(target, key, value)
        n = getattr(col.type, "length", None)
        # Ключи (первичные и уникальные) не подрезаем: подрезанные ключи совпадут и перезапишут
        # друг друга — пусть лучше база вернёт ошибку
        if n and isinstance(value, str) and len(value) > n and not (col.primary_key or col.unique):
            _log.warning("%s.%s: %d символов > %d, подрезано", mapper.class_.__name__, key, len(value), n)
            setattr(target, key, value[:n])


@_event.listens_for(Friendship, "before_insert")
@_event.listens_for(Friendship, "before_update")
def _friendship_pair_key(_mapper, _connection, row: Friendship) -> None:
    a, b = sorted((row.user_id, row.friend_id))
    row.pair_key = None if row.status == FriendStatus.BLOCKED else f"{a}:{b}"


class MarketItem(Base):
    """Объявление барахолки приложения. Живёт только в приложении (API + PostgreSQL), фото — в market_photos.
    Публикуется сразу; жалобы скрывают его (status=hidden) до решения модератора."""

    __tablename__ = "market_items"
    __table_args__ = (Index("ix_market_items_feed", "status", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    # wardrobe | home | tech | sport | tickets | housing | services | free (utils/app_market.CATEGORIES)
    category: Mapped[str] = mapped_column(String(20), index=True)
    title: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text, default="")
    price: Mapped[int | None] = mapped_column(Integer, nullable=True)   # в евро; 0 — бесплатно, пусто — договорная
    city: Mapped[str] = mapped_column(String(80), default="", index=True)
    status: Mapped[str] = mapped_column(String(12), default="active", index=True)   # active | closed | hidden
    photo_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class MarketPhoto(Base):
    """Фото объявления барахолки: JPEG в базе, до 5 на объявление."""

    __tablename__ = "market_photos"
    __table_args__ = (UniqueConstraint("item_id", "idx", name="uq_market_photo"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    item_id: Mapped[int] = mapped_column(Integer, index=True)
    idx: Mapped[int] = mapped_column(Integer, default=0)
    data: Mapped[bytes] = mapped_column(LargeBinary)


class Story(Base):
    """История на 24 часа во весь экран (9:16): фото или видео (файл на диске сервера, utils.media)
    или репост поста — карточка-наклейка поверх цветного фона."""

    __tablename__ = "stories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    kind: Mapped[str] = mapped_column(String(10), default="photo")   # photo | video | post
    file: Mapped[str] = mapped_column(String(120), default="", index=True)   # имя файла в media/stories (у репоста пусто)
    post_id: Mapped[int | None] = mapped_column(Integer, nullable=True)       # репост: какой пост на наклейке
    bg: Mapped[str] = mapped_column(String(20), default="", server_default="")  # фон репоста: ключ градиента
    caption: Mapped[str] = mapped_column(String(200), default="", server_default="")   # подпись поверх истории
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)


class StoryReaction(Base):
    """Быстрая реакция-эмодзи на историю (одна от человека, можно сменить)."""

    __tablename__ = "story_reactions"
    __table_args__ = (UniqueConstraint("story_id", "user_id", name="uq_story_reaction"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    story_id: Mapped[int] = mapped_column(Integer, index=True)
    user_id: Mapped[int] = mapped_column(Integer)
    emoji: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )


class PulseClip(Base):
    """Вертикальное видео ленты Pulse. Файл — на диске сервера (utils.media), в базе — описание и счётчики."""

    __tablename__ = "pulse_clips"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    text: Mapped[str] = mapped_column(String(500), default="")
    file: Mapped[str] = mapped_column(String(120), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), index=True
    )
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)   # удалил сам автор
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)    # скрыто модерацией / жалобами


class PulseLike(Base):
    __tablename__ = "pulse_likes"
    __table_args__ = (UniqueConstraint("clip_id", "user_id", name="uq_pulse_like"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    clip_id: Mapped[int] = mapped_column(Integer, index=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)


class PulseSave(Base):
    """Закладка: видео Pulse, сохранённое себе."""

    __tablename__ = "pulse_saves"
    __table_args__ = (UniqueConstraint("clip_id", "user_id", name="uq_pulse_save"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    clip_id: Mapped[int] = mapped_column(Integer, index=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )


class PulseComment(Base):
    __tablename__ = "pulse_comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    clip_id: Mapped[int] = mapped_column(Integer, index=True)
    user_id: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)
