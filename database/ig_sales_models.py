"""Isolated Instagram Direct sales persistence, registered before init_db()."""
from datetime import datetime
from sqlalchemy import DateTime, Integer, String, Text, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column
from database.models import Base


class IgSalesConversation(Base):
    __tablename__ = "ig_sales_conversations"

    ig_user_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    state: Mapped[str] = mapped_column(String(28), default="new", index=True)
    product_key: Mapped[str | None] = mapped_column(String(40), nullable=True)
    order_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    last_inbound_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    invoice_email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    invoice_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    invoice_address: Mapped[str | None] = mapped_column(String(300), nullable=True)
    history_json: Mapped[str] = mapped_column(Text, default="[]")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class IgSalesEvent(Base):
    __tablename__ = "ig_sales_events"

    message_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    ig_user_id: Mapped[str] = mapped_column(String(100), index=True)
    text: Mapped[str] = mapped_column(Text)
    sent_at: Mapped[datetime] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class IgSalesOrder(Base):
    __tablename__ = "ig_sales_orders"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    ig_user_id: Mapped[str] = mapped_column(String(100), index=True)
    product_key: Mapped[str] = mapped_column(String(40))
    option_key: Mapped[str] = mapped_column(String(30), default="std")
    amount: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(28), default="creating", index=True)
    payment_id: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)
    checkout_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    invoice_status: Mapped[str] = mapped_column(String(24), default="not_requested")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
