"""Описание таблиц базы данных."""
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


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
    # Статус: pending | approved | rejected
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
    # Статус: active (виден в поиске) | pending (ждёт оплаты/проверки) | expired
    status: Mapped[str] = mapped_column(String(20), default="active")
    # Откуда карточка: seed (из гайда) | admin (добавил админ) | self (само-добавление)
    source: Mapped[str] = mapped_column(String(20), default="seed")
    # Telegram-id того, кто добавил себя сам (для платного потока)
    submitter_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # До какого момента оплачено размещение (None = бессрочно: seed/admin)
    paid_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Id платежа в Mollie (для платного потока)
    payment_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Напомнили ли уже о продлении (чтобы не слать дважды)
    renewal_reminded: Mapped[bool] = mapped_column(Boolean, default=False)


class Meta(Base):
    """Служебная таблица «ключ-значение» (например, версия засева базы)."""

    __tablename__ = "meta"

    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    value: Mapped[str] = mapped_column(String(100))
