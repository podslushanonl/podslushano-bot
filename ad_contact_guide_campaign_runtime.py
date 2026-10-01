"""Apply the Q4 2026 newsletter discount to Contact Guide purchases.

The public /ads page collects explicit newsletter consent. Contact Guide lives in
Telegram, so entitlement is matched by the same e-mail address entered for the
factuur. The price is re-checked server-side immediately before creating the
Mollie payment; the FSM flag is only presentation state and never authorizes a
discount by itself.
"""
from __future__ import annotations

import html
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select

import config
from database.db import get_session
from database.models import Meta, Specialist
from handlers import selfadd
from keyboards.menus import main_menu


_DISCOUNT_RATE = Decimal("0.26")
_SCRIPT_PATH = "/ads-static/q4-contact-guide.js"


def contact_guide_discount_price(value: str) -> str:
    amount = Decimal(str(value))
    discounted = (amount * (Decimal("1") - _DISCOUNT_RATE)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    return f"{discounted:.2f}"


async def _newsletter_active(email: str | None) -> bool:
    normalized = (email or "").strip().lower()
    if not normalized:
        return False
    # Imported lazily because this module is loaded from ad_products_runtime
    # before ad_season_campaign_runtime finishes defining its model.
    from ad_season_campaign_runtime import AdsNewsletterSubscriber, _campaign_active

    if not _campaign_active():
        return False
    async with get_session() as session:
        subscriber_id = await session.scalar(
            select(AdsNewsletterSubscriber.id).where(
                AdsNewsletterSubscriber.email == normalized,
                AdsNewsletterSubscriber.is_active.is_(True),
            )
        )
    return bool(subscriber_id)


_ORIGINAL_SHOW_REVIEW = selfadd._show_review
_ORIGINAL_SHOW_TIERS = selfadd._show_tiers
_ORIGINAL_SHOW_CONFIRMATION = selfadd._show_order_confirmation
_ORIGINAL_CREATE_LISTING_AND_PAY = selfadd._create_listing_and_pay


async def _show_review_q4(message, state) -> None:
    data = await state.get_data()
    active = await _newsletter_active(data.get("sp_email"))
    await state.update_data(sp_q4_discount=active)
    await _ORIGINAL_SHOW_REVIEW(message, state)


async def _show_tiers_q4(message, state) -> None:
    data = await state.get_data()
    active = await _newsletter_active(data.get("sp_email"))
    await state.update_data(sp_q4_discount=active)
    await _ORIGINAL_SHOW_TIERS(message, state)
    if active:
        await message.answer(
            "🎁 <b>Скидка −26% активна.</b>\n"
            "Мы нашли этот e-mail в подписке на рекламные обновления. "
            "Скидка действует на любой тариф Contact Guide и будет показана перед оплатой."
        )


async def _show_order_confirmation_q4(message, state) -> None:
    data = await state.get_data()
    plan = data.get("sp_plan")
    if plan not in selfadd.SELFADD_PLANS:
        await _ORIGINAL_SHOW_CONFIRMATION(message, state)
        return

    seasonal = await _newsletter_active(data.get("sp_email"))
    await state.update_data(sp_q4_discount=seasonal)
    if not seasonal:
        await _ORIGINAL_SHOW_CONFIRMATION(message, state)
        return

    info = config.plan_info(plan)
    base = info["price"]
    amount = contact_guide_discount_price(base)
    photo_note = "\n<b>Фото:</b> добавлено" if data.get("sp_photo_id") else ""
    await state.set_state(selfadd.SelfAddSpecialist.confirm)
    await message.answer(
        "<b>Заказ готов</b>\n\n"
        f"<b>Тариф:</b> {selfadd._plan_title(plan)}\n"
        f"<b>К оплате:</b> <s>{selfadd._format_euro(base)}</s> → "
        f"<b>{selfadd._format_euro(amount)}</b> · −26%\n"
        f"<b>Срок:</b> {info['days']} дней"
        f"{photo_note}\n\n"
        "🎁 Сезонная цена активирована подпиской на рекламные обновления.\n\n"
        "После оплаты:\n"
        f"1. Factuur придёт на <b>{html.escape(data.get('sp_email', ''))}</b>.\n"
        "2. Мы проверим данные и оформление карточки.\n"
        "3. Бот сообщит о публикации или необходимых исправлениях.\n\n"
        "Оплата разовая. Автоматического списания и продления нет.",
        reply_markup=selfadd._confirm_kb(),
    )


async def _create_listing_and_pay_q4(message, state, plan: str,
                                      photo_file_id: str | None, uid: int) -> None:
    """Create a Contact Guide payment, validating Q4 entitlement by e-mail."""
    info = config.plan_info(plan)
    data = await state.get_data()
    seasonal = await _newsletter_active(data.get("sp_email"))

    async with get_session() as session:
        ref_meta = await session.get(Meta, f"spref:{uid}")
        ref_sid = int(ref_meta.value) if ref_meta and ref_meta.value.isdigit() else None
        existing_id = data.get("sp_listing_id")
        sp = await session.get(Specialist, existing_id) if existing_id else None
        if sp is None or sp.submitter_user_id != uid or sp.status != "awaiting_payment":
            sp = Specialist(status="awaiting_payment", source="self", submitter_user_id=uid)
            session.add(sp)
        sp.name = data["sp_name"]
        sp.category = data["sp_category"]
        sp.city = data.get("sp_city", "")
        sp.province = data.get("sp_province", "")
        sp.description = data.get("sp_description")
        sp.contact = selfadd._build_public_contacts(data) or data.get("sp_contact", "")
        sp.is_online = data.get("sp_online", False)
        sp.is_premium = info["premium"]
        sp.photo_file_id = photo_file_id
        sp.invoice_email = data.get("sp_email")
        sp.plan = plan
        sp.referred_by_specialist_id = ref_sid
        await session.commit()
        await session.refresh(sp)
        sid, name = sp.id, sp.name
    await state.update_data(sp_listing_id=sid)

    referral_year = bool(ref_sid) and plan in ("year", "year_premium")
    if seasonal:
        amount = contact_guide_discount_price(info["price"])
        discount_label = "скидка −26% за подписку"
    elif referral_year:
        amount = config.discounted_price(info["price"])
        discount_label = "скидка 20% по приглашению"
    else:
        amount = info["price"]
        discount_label = ""

    metadata = {"specialist_id": sid, "kind": "new", "plan": plan}
    if seasonal:
        metadata["discount"] = "q4_26"

    # Use the dependency exposed by handlers.selfadd, exactly like the original
    # flow. This preserves retry semantics and lets tests/maintenance replace the
    # Mollie client without this seasonal wrapper bypassing that replacement.
    payment = await selfadd.create_payment(
        f"{selfadd.DESC_NEW}: {name}",
        metadata,
        amount,
    )
    if not payment or not payment.get("checkout_url"):
        await state.set_state(selfadd.SelfAddSpecialist.confirm)
        await message.answer(
            "Ссылку на оплату сейчас создать не удалось. Данные анкеты сохранены — "
            "попробуйте ещё раз через минуту.",
            reply_markup=selfadd._confirm_kb(),
        )
        return

    async with get_session() as session:
        sp = await session.get(Specialist, sid)
        if sp:
            sp.payment_id = payment["id"]
            await session.commit()

    await state.clear()
    if discount_label:
        tariff = (
            f"<b>{selfadd._plan_title(plan)}</b> · "
            f"<s>{selfadd._format_euro(info['price'])}</s> → "
            f"<b>{selfadd._format_euro(amount)}</b> ({discount_label})"
        )
    else:
        tariff = f"<b>{selfadd._plan_title(plan)}</b> · <b>{selfadd._format_euro(amount)}</b>"

    await message.answer(
        f"<b>Ссылка на оплату готова</b>\n\nТариф: {tariff}.\n\n"
        "После успешной оплаты factuur придёт на указанный e-mail, а анкета отправится "
        "нам на проверку. Бот сообщит, когда карточка будет опубликована.\n\n"
        f'Оплачивая, вы соглашаетесь с <a href="{config.terms_url()}">Условиями</a> '
        f'и <a href="{config.privacy_url()}">Политикой конфиденциальности</a>.',
        reply_markup=main_menu(),
        disable_web_page_preview=True,
    )
    await message.answer(
        "Нажмите кнопку, чтобы перейти к оплате:",
        reply_markup=selfadd._pay_kb(payment["checkout_url"], plan, amount),
    )


selfadd._show_review = _show_review_q4
selfadd._show_tiers = _show_tiers_q4
selfadd._show_order_confirmation = _show_order_confirmation_q4
selfadd._create_listing_and_pay = _create_listing_and_pay_q4


# Keep the existing static page simple: a small enhancement script corrects the
# Contact Guide Q4 copy/prices and the expert-live story count after page load.
from utils import webserver as _webserver  # noqa: E402

_ORIGINAL_WEB_ADS = _webserver._ads


async def _ads_with_contact_guide_q4(request):
    response = await _ORIGINAL_WEB_ADS(request)
    try:
        text = response.text
    except Exception:
        return response
    if "q4-contact-guide.js" not in text:
        text = text.replace(
            "</body>",
            f'<script src="{_SCRIPT_PATH}"></script></body>',
            1,
        )
    return _webserver.web.Response(
        text=text,
        content_type="text/html",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


_webserver._ads = _ads_with_contact_guide_q4
