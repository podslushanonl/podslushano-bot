"""Connect the €299 advertising campaign with Contact Guide Premium.

The public /ads form transports the Guide draft inside the existing optional
phone field after a private marker.  This keeps the legacy /ads endpoint
compatible while allowing the campaign checkout to create a hidden Guide card
before Mollie.  The card becomes Premium for 60 days only after confirmed
payment.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import base64
import json
import logging

from sqlalchemy import func, select

import config
from database.db import get_session
from database.models import AdBooking, Specialist
from handlers import ads, selfadd
from utils.geo import CATEGORIES, province_of_city

log = logging.getLogger(__name__)

_MARKER = "|||GUIDE64:"
_SOURCE = "ad_campaign"
_ORIGINAL_BOOK = ads.book_and_pay
_ORIGINAL_PAID = ads.on_ad_payment_paid


def _decode_phone_payload(raw: str) -> tuple[str, dict | None]:
    value = (raw or "").strip()
    if _MARKER not in value:
        return value, None
    billing_phone, encoded = value.split(_MARKER, 1)
    try:
        padding = "=" * (-len(encoded) % 4)
        data = json.loads(base64.urlsafe_b64decode((encoded + padding).encode()).decode())
        if not isinstance(data, dict):
            data = None
    except Exception:
        data = None
    return billing_phone.strip(), data


def _clean_guide(data: dict | None) -> tuple[dict | None, str | None]:
    if not data:
        return None, "Заполните данные карточки Contact Guide."
    name = " ".join(str(data.get("name") or "").split())
    category = " ".join(str(data.get("category") or "").lower().split())
    city = " ".join(str(data.get("city") or "").split())
    description = " ".join(str(data.get("description") or "").split())
    contact = " ".join(str(data.get("contact") or "").split())
    is_online = bool(data.get("online"))

    if not selfadd._valid_name(name):
        return None, "Проверьте имя или название для Contact Guide."
    if category not in CATEGORIES:
        return None, "Выберите категорию Contact Guide из списка."
    if not is_online and len(city) < 2:
        return None, "Укажите город для карточки или выберите «Онлайн / вся страна»."
    if not selfadd._valid_description(description):
        return None, "Описание карточки должно понятно объяснять услугу (минимум 3 слова)."
    if not selfadd._valid_contact(contact):
        return None, "Укажите рабочий контакт для карточки: Instagram, Telegram, сайт, e-mail или телефон."
    return {
        "name": name,
        "category": category,
        "city": "" if is_online else city,
        "province": "" if is_online else (province_of_city(city) or ""),
        "description": description,
        "contact": contact,
        "is_online": is_online,
    }, None


async def _draft_card(email: str, guide: dict) -> int:
    """Create/reuse a hidden campaign Guide draft; never changes a live card pre-payment."""
    normalized = (email or "").strip().lower()
    async with get_session() as session:
        draft = await session.scalar(
            select(Specialist).where(
                Specialist.source == _SOURCE,
                Specialist.status == "awaiting_payment",
                func.lower(Specialist.invoice_email) == normalized,
            ).order_by(Specialist.id.desc())
        )
        if draft is None:
            draft = Specialist(source=_SOURCE, status="awaiting_payment")
            session.add(draft)
        draft.name = guide["name"]
        draft.category = guide["category"]
        draft.city = guide["city"]
        draft.province = guide["province"]
        draft.description = guide["description"]
        draft.contact = guide["contact"]
        draft.is_online = guide["is_online"]
        draft.is_premium = True
        draft.invoice_email = normalized
        draft.plan = "month_premium"
        await session.commit()
        await session.refresh(draft)
        return draft.id


async def book_and_pay(fmt: str, opt: str, dates: list, fields: dict):
    draft_id = None
    if fmt == "ad_campaign":
        billing_phone, payload = _decode_phone_payload(fields.get("phone") or "")
        fields = dict(fields)
        fields["phone"] = billing_phone
        guide, error = _clean_guide(payload)
        if error:
            return None, error
        draft_id = await _draft_card(fields.get("email") or "", guide)

    checkout, error = await _ORIGINAL_BOOK(fmt, opt, dates, fields)
    if draft_id is None:
        return checkout, error

    async with get_session() as session:
        draft = await session.get(Specialist, draft_id)
        if not checkout:
            if draft:
                draft.status = "expired"
                await session.commit()
            return checkout, error

        booking = await session.scalar(
            select(AdBooking).where(
                AdBooking.fmt == "ad_campaign",
                func.lower(AdBooking.email) == (fields.get("email") or "").strip().lower(),
                AdBooking.status == "pending",
            ).order_by(AdBooking.created_at.desc(), AdBooking.id.desc())
        )
        if draft and booking and booking.payment_id:
            draft.payment_id = booking.payment_id
            await session.commit()
    return checkout, error


async def _activate_campaign_guide(bot, payment_id: str) -> dict | None:
    now = datetime.utcnow()
    async with get_session() as session:
        draft = await session.scalar(
            select(Specialist).where(
                Specialist.source == _SOURCE,
                Specialist.payment_id == payment_id,
            ).order_by(Specialist.id.desc())
        )
        if draft is None:
            return None
        if draft.status not in ("awaiting_payment", "pending"):
            return {"status": "already", "specialist_id": draft.id, "name": draft.name}

        existing = (
            await session.scalars(
                select(Specialist).where(
                    Specialist.id != draft.id,
                    func.lower(Specialist.invoice_email) == (draft.invoice_email or "").lower(),
                    Specialist.status.in_(("active", "pending", "expired")),
                ).order_by(Specialist.id.desc())
            )
        ).all()

        if len(existing) == 1:
            card = existing[0]
            card.name = draft.name
            card.category = draft.category
            card.city = draft.city
            card.province = draft.province
            card.description = draft.description
            card.contact = draft.contact
            card.is_online = draft.is_online
            card.is_premium = True
            card.invoice_email = draft.invoice_email
            card.payment_id = payment_id
            card.plan = "month_premium"
            base = card.paid_until if card.paid_until and card.paid_until > now else now
            card.paid_until = base + timedelta(days=60)
            premium_base = card.premium_until if card.premium_until and card.premium_until > now else now
            card.premium_until = premium_base + timedelta(days=60)
            if card.status == "expired":
                card.status = "pending"
            await session.delete(draft)
            mode = "updated"
        else:
            card = draft
            card.source = "self"
            card.status = "pending"
            card.is_premium = True
            card.plan = "month_premium"
            card.paid_until = now + timedelta(days=60)
            card.premium_until = now + timedelta(days=60)
            card.payment_id = payment_id
            mode = "created"

        await session.commit()
        await session.refresh(card)
        card_id = card.id
        card_text = selfadd._card_text(card)
        end = card.premium_until

    for admin_id in config.ADMIN_IDS:
        try:
            if mode == "created":
                await bot.send_message(
                    admin_id,
                    "⭐ <b>Кампания €299: Contact Guide Premium</b>\n\n"
                    "Карточка создана автоматически после оплаты и ждёт проверки.\n\n"
                    + card_text,
                    reply_markup=selfadd._review_kb(card_id),
                )
            else:
                await bot.send_message(
                    admin_id,
                    "⭐ <b>Кампания €299: Contact Guide Premium</b>\n\n"
                    f"Существующая карточка <b>#{card_id}</b> обновлена и Premium продлён до "
                    f"<b>{end:%d.%m.%Y}</b>.\n\n" + card_text,
                )
        except Exception as exc:  # noqa: BLE001
            log.warning("Не уведомил админа о Contact Guide кампании: %s", exc)
    return {"status": mode, "specialist_id": card_id, "name": card.name, "ends_at": end}


async def on_ad_payment_paid(bot, payment_id: str, payment: dict) -> None:
    await _ORIGINAL_PAID(bot, payment_id, payment)
    status = payment.get("status")
    if status == "paid":
        try:
            await _activate_campaign_guide(bot, payment_id)
        except Exception as exc:  # noqa: BLE001
            log.exception("Не активировал Contact Guide для кампании %s: %s", payment_id, exc)
    elif status in ("failed", "canceled", "expired"):
        async with get_session() as session:
            draft = await session.scalar(
                select(Specialist).where(
                    Specialist.source == _SOURCE,
                    Specialist.payment_id == payment_id,
                    Specialist.status == "awaiting_payment",
                ).order_by(Specialist.id.desc())
            )
            if draft:
                draft.status = "expired"
                await session.commit()


# Install the runtime wrappers. utils.webserver imports these module attributes
# at request time, so no route rewrite is required.
ads.book_and_pay = book_and_pay
ads.on_ad_payment_paid = on_ad_payment_paid
