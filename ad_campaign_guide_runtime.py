"""Connect the €299 advertising campaign with Contact Guide Premium.

The campaign checkout collects the Guide data (including photo/logo) before
Mollie.  A hidden draft is created before payment and becomes a moderated
Premium card for 60 days only after confirmed payment.

This module is imported before ``init_db()`` so its small photo-asset table is
created by SQLAlchemy together with the rest of the schema.  It also installs a
few narrow runtime wrappers so the legacy ad checkout and regular Contact Guide
flow remain backwards-compatible.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import base64
import json
import logging

from sqlalchemy import LargeBinary, String, func, select
from sqlalchemy.orm import Mapped, mapped_column

import config
from database.db import get_session
from database.models import AdBooking, Base, Specialist
from handlers import ads, contacts, selfadd
from utils.geo import CATEGORIES, province_of_city

log = logging.getLogger(__name__)

_MARKER = "|||GUIDE64:"
_SOURCE = "ad_campaign"
_MAX_PHOTO_BYTES = 600_000
_ALLOWED_PHOTO_MIME = {"image/jpeg", "image/png"}
_ORIGINAL_BOOK = ads.book_and_pay
_ORIGINAL_PAID = ads.on_ad_payment_paid
_ORIGINAL_SELF_CONFIRM = selfadd._show_order_confirmation
_ORIGINAL_SELF_CREATE_PAY = selfadd._create_listing_and_pay
_ORIGINAL_SPEC_TEXT = contacts._spec_text


class CampaignGuidePhoto(Base):
    """Persistent uploaded photo/logo for a Contact Guide campaign card."""

    __tablename__ = "campaign_guide_photos"

    specialist_id: Mapped[int] = mapped_column(primary_key=True)
    mime: Mapped[str] = mapped_column(String(32), default="image/jpeg")
    data: Mapped[bytes] = mapped_column(LargeBinary)


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


def _photo_from_payload(data: dict) -> tuple[bytes | None, str | None, str | None]:
    raw = str(data.get("photo_b64") or "").strip()
    mime = str(data.get("photo_mime") or "").strip().lower()
    if not raw:
        return None, None, "Добавьте фото или логотип для Premium-карточки."
    if mime not in _ALLOWED_PHOTO_MIME:
        return None, None, "Фото/логотип должен быть JPG или PNG."
    try:
        photo = base64.b64decode(raw, validate=True)
    except Exception:
        return None, None, "Не удалось прочитать фото или логотип. Загрузите файл ещё раз."
    if not photo or len(photo) > _MAX_PHOTO_BYTES:
        return None, None, "Фото слишком большое. Загрузите другое изображение."
    if mime == "image/jpeg" and not photo.startswith(b"\xff\xd8\xff"):
        return None, None, "Файл не похож на корректное JPG-изображение."
    if mime == "image/png" and not photo.startswith(b"\x89PNG\r\n\x1a\n"):
        return None, None, "Файл не похож на корректное PNG-изображение."
    return photo, mime, None


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
        return None, "Укажите рабочий контакт: Instagram, Telegram, сайт, e-mail или телефон."

    photo, photo_mime, photo_error = _photo_from_payload(data)
    if photo_error:
        return None, photo_error

    return {
        "name": name,
        "category": category,
        "city": "" if is_online else city,
        "province": "" if is_online else (province_of_city(city) or ""),
        "description": description,
        "contact": contact,
        "is_online": is_online,
        "photo": photo,
        "photo_mime": photo_mime,
    }, None


def _normalized(value: str | None) -> str:
    return " ".join((value or "").lower().split())


async def _save_asset(session, specialist_id: int, photo: bytes, mime: str) -> None:
    asset = await session.get(CampaignGuidePhoto, specialist_id)
    if asset is None:
        asset = CampaignGuidePhoto(specialist_id=specialist_id, mime=mime, data=photo)
        session.add(asset)
    else:
        asset.mime = mime
        asset.data = photo


async def _move_asset(session, old_id: int, new_id: int) -> None:
    old = await session.get(CampaignGuidePhoto, old_id)
    if old is None:
        return
    current = await session.get(CampaignGuidePhoto, new_id)
    if current is None:
        current = CampaignGuidePhoto(
            specialist_id=new_id,
            mime=old.mime,
            data=old.data,
        )
        session.add(current)
    else:
        current.mime = old.mime
        current.data = old.data
    await session.delete(old)


def _campaign_photo_url(specialist_id: int) -> str:
    base = (config.WEBHOOK_BASE_URL or "").rstrip("/")
    return f"{base}/sp-photo/{specialist_id}" if base else ""


async def _draft_card(email: str, guide: dict) -> int:
    """Create a hidden campaign draft without touching any live card pre-payment."""
    normalized_email = (email or "").strip().lower()
    async with get_session() as session:
        draft = Specialist(
            source=_SOURCE,
            status="awaiting_payment",
            name=guide["name"],
            category=guide["category"],
            city=guide["city"],
            province=guide["province"],
            description=guide["description"],
            contact=guide["contact"],
            is_online=guide["is_online"],
            is_premium=True,
            invoice_email=normalized_email,
            plan="month_premium",
        )
        session.add(draft)
        await session.flush()
        await _save_asset(
            session,
            draft.id,
            guide["photo"],
            guide["photo_mime"],
        )
        await session.commit()
        return draft.id


async def _discard_draft(draft_id: int) -> None:
    async with get_session() as session:
        draft = await session.get(Specialist, draft_id)
        asset = await session.get(CampaignGuidePhoto, draft_id)
        if asset:
            await session.delete(asset)
        if draft and draft.status == "awaiting_payment":
            draft.status = "expired"
        await session.commit()


async def book_and_pay(fmt: str, opt: str, dates: list, fields: dict):
    draft_id = None
    if fmt == "ad_campaign":
        billing_phone, payload = _decode_phone_payload(fields.get("phone") or "")
        fields = dict(fields)
        fields["phone"] = billing_phone
        guide, error = _clean_guide(payload)
        if error:
            return None, error
        if not config.WEBHOOK_BASE_URL:
            return None, "Contact Guide временно недоступен. Попробуйте позже."
        draft_id = await _draft_card(fields.get("email") or "", guide)

    checkout, error = await _ORIGINAL_BOOK(fmt, opt, dates, fields)
    if draft_id is None:
        return checkout, error

    if not checkout:
        await _discard_draft(draft_id)
        return checkout, error

    async with get_session() as session:
        booking = await session.scalar(
            select(AdBooking).where(
                AdBooking.fmt == "ad_campaign",
                func.lower(AdBooking.email) == (fields.get("email") or "").strip().lower(),
                AdBooking.status == "pending",
            ).order_by(AdBooking.created_at.desc(), AdBooking.id.desc())
        )
        draft = await session.get(Specialist, draft_id)
        if draft and booking and booking.payment_id:
            draft.payment_id = booking.payment_id
            await session.commit()
    return checkout, error


async def _find_existing_card(session, draft: Specialist) -> Specialist | None:
    email = (draft.invoice_email or "").strip().lower()
    if not email:
        return None
    existing = (
        await session.scalars(
            select(Specialist).where(
                Specialist.id != draft.id,
                Specialist.source != _SOURCE,
                func.lower(Specialist.invoice_email) == email,
                Specialist.status.in_(("active", "pending", "expired")),
            ).order_by(Specialist.id.desc())
        )
    ).all()
    if not existing:
        return None

    exact = [
        row for row in existing
        if _normalized(row.name) == _normalized(draft.name)
        or (
            _normalized(row.contact)
            and _normalized(row.contact) == _normalized(draft.contact)
        )
    ]
    if len(exact) == 1:
        return exact[0]
    if len(existing) == 1:
        return existing[0]
    # One invoice e-mail may legitimately manage several different cards.
    # If there is no exact identity match we create a separate card rather than
    # overwriting an unrelated business.
    return None


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

        card = await _find_existing_card(session, draft)
        mode = "updated" if card is not None else "created"
        if card is None:
            card = draft
        else:
            old_id = draft.id
            card.name = draft.name
            card.category = draft.category
            card.city = draft.city
            card.province = draft.province
            card.description = draft.description
            card.contact = draft.contact
            card.is_online = draft.is_online
            card.invoice_email = draft.invoice_email
            card.payment_id = payment_id
            await _move_asset(session, old_id, card.id)
            await session.delete(draft)

        card.is_premium = True
        card.status = "pending"  # every new/updated card must be moderated before publication
        if mode == "created":
            card.source = _SOURCE
            card.payment_id = payment_id
            card.plan = "month_premium"

        premium_base = card.premium_until if card.premium_until and card.premium_until > now else now
        card.premium_until = premium_base + timedelta(days=60)
        if card.paid_until is None or card.paid_until < card.premium_until:
            card.paid_until = card.premium_until
        card.photo_file_id = _campaign_photo_url(card.id)

        await session.commit()
        await session.refresh(card)
        card_id = card.id
        card_text = selfadd._card_text(card)
        end = card.premium_until
        photo_url = card.photo_file_id

    caption = (
        "⭐ <b>Кампания €299: Contact Guide Premium</b>\n\n"
        + ("Существующая карточка обновлена и снята с выдачи до повторной проверки.\n\n"
           if mode == "updated" else "Новая карточка создана автоматически после оплаты.\n\n")
        + card_text
        + f"\n\nPremium оплачен до <b>{end:%d.%m.%Y}</b>."
    )
    for admin_id in config.ADMIN_IDS:
        try:
            try:
                await bot.send_photo(
                    admin_id,
                    photo_url,
                    caption=caption,
                    reply_markup=selfadd._review_kb(card_id),
                )
            except Exception:
                await bot.send_message(
                    admin_id,
                    caption,
                    reply_markup=selfadd._review_kb(card_id),
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
                asset = await session.get(CampaignGuidePhoto, draft.id)
                if asset:
                    await session.delete(asset)
                draft.status = "expired"
                await session.commit()


async def _premium_photo_required_confirmation(message, state) -> None:
    """Regular self-add Premium also cannot be completed without its promised photo."""
    data = await state.get_data()
    plan = data.get("sp_plan")
    if plan in selfadd.SELFADD_PLANS and config.plan_info(plan)["premium"] and not data.get("sp_photo_id"):
        await state.set_state(selfadd.SelfAddSpecialist.photo)
        await message.answer(
            "<b>Для Премиум-карточки нужно фото или логотип.</b>\n\n"
            "Это часть Premium: изображение показывается в карточке вместе с бейджем 🌟, "
            "а сама карточка располагается выше стандартных. Пришлите фото одним сообщением."
        )
        return
    await _ORIGINAL_SELF_CONFIRM(message, state)


async def _premium_create_and_pay(message, state, plan: str, photo_file_id: str | None, uid: int) -> None:
    if plan in selfadd.SELFADD_PLANS and config.plan_info(plan)["premium"] and not photo_file_id:
        await state.set_state(selfadd.SelfAddSpecialist.photo)
        await message.answer(
            "Для Premium сначала пришлите фото или логотип карточки. Без изображения Premium не оформляется."
        )
        return
    await _ORIGINAL_SELF_CREATE_PAY(message, state, plan, photo_file_id, uid)


def _premium_spec_text(spec: Specialist, badge: str = "", reviews=None) -> str:
    """Premium is not the archived product name «Эксперт месяца»."""
    text = _ORIGINAL_SPEC_TEXT(spec, badge, reviews)
    return text.replace(
        "⭐ <b>Рекомендуем · Эксперт месяца</b>\n",
        "🌟 <b>Премиум</b>\n",
        1,
    )


# Install handler-level wrappers.  Existing registered handlers look these
# functions up through their module globals at execution time.
ads.book_and_pay = book_and_pay
ads.on_ad_payment_paid = on_ad_payment_paid
selfadd._show_order_confirmation = _premium_photo_required_confirmation
selfadd._create_listing_and_pay = _premium_create_and_pay
contacts._spec_text = _premium_spec_text


# Web wrappers are installed before ``start_webserver()`` registers routes.
from utils import webserver as _webserver  # noqa: E402

_ORIGINAL_WEB_ADS = _webserver._ads
_ORIGINAL_SP_PHOTO = _webserver._sp_photo


async def _ads_with_campaign_photo(request):
    response = await _ORIGINAL_WEB_ADS(request)
    try:
        text = response.text
    except Exception:
        return response
    if "campaign-guide-photo.js" not in text:
        text = text.replace(
            "</body>",
            '<script src="/ads-static/campaign-guide-photo.js"></script></body>',
            1,
        )
    return _webserver.web.Response(
        text=text,
        content_type="text/html",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


async def _sp_photo_with_campaign_asset(request):
    sid_s = request.match_info.get("sid", "")
    if sid_s.isdigit():
        async with get_session() as session:
            asset = await session.get(CampaignGuidePhoto, int(sid_s))
        if asset is not None:
            response = _webserver.web.Response(body=asset.data, content_type=asset.mime)
            response.headers["Cache-Control"] = "public, max-age=86400"
            response.headers["Access-Control-Allow-Origin"] = "*"
            return response
    return await _ORIGINAL_SP_PHOTO(request)


_webserver._ads = _ads_with_campaign_photo
_webserver._sp_photo = _sp_photo_with_campaign_asset
