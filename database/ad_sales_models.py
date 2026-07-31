"""Таблицы полного цикла продаж рекламы.

Вынесены отдельно, чтобы не раздувать основной models.py. Модуль импортируется
в database.db до Base.metadata.create_all().
"""
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from database.models import Base


class AdConversationMessage(Base):
    """Одно сообщение или системное событие внутри рекламного лида."""

    __tablename__ = "ad_conversation_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    submission_id: Mapped[int] = mapped_column(Integer, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    # client | manager | ai | system
    role: Mapped[str] = mapped_column(String(20), index=True)
    # inbound | outbound | suggestion | status | payment | production
    kind: Mapped[str] = mapped_column(String(20), default="inbound", index=True)
    text: Mapped[str] = mapped_column(Text)
    telegram_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class AdSalesPipeline(Base):
    """Связь рекламной заявки, оплаты и производственного этапа."""

    __tablename__ = "ad_sales_pipeline"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    submission_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    # new | contacted | awaiting_payment | paid | rejected | closed
    sales_status: Mapped[str] = mapped_column(String(30), default="new", index=True)
    # not_started | waiting_materials | materials_received | scheduled | published | completed
    production_status: Mapped[str] = mapped_column(String(30), default="not_started", index=True)
    ad_booking_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    payment_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    format_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    publish_dates: Mapped[str | None] = mapped_column(Text, nullable=True)
    materials_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
