"""Описание таблиц базы данных."""
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String, Text, func
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
