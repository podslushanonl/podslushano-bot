"""Модели личных анонимных вопросов Алексу.

Принцип приватности: Telegram user_id, username, имя и ссылка на профиль здесь
никогда не сохраняются. Для антиспама используется только HMAC-хеш отправителя,
который нельзя использовать как Telegram-идентификатор.
"""
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from database.models import Base


class AnonymousQuestion(Base):
    """Анонимный вопрос из личного канала Алекса."""

    __tablename__ = "anonymous_questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sender_hash: Mapped[str] = mapped_column(String(64), index=True)
    text: Mapped[str] = mapped_column(Text)
    # pending | selected | skipped
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), index=True
    )


class AnonymousQuestionBlock(Base):
    """Заблокированный анонимный отправитель без хранения Telegram ID."""

    __tablename__ = "anonymous_question_blocks"

    sender_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AnonymousAnswer(Base):
    """Admin-authored post; contains no sender identity. One publication per question."""

    __tablename__ = "anonymous_answers"

    question_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    post_html: Mapped[str] = mapped_column(Text)
    version: Mapped[str] = mapped_column(String(32))
    # draft | publishing | published | uncertain. Never auto-retry uncertain sends.
    status: Mapped[str] = mapped_column(String(20), default="draft")
    channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
