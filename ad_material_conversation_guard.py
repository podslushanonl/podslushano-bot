"""Keep post-payment ad conversation active only while materials are unresolved.

The reminder runtime records a live client/manager conversation as a suppression
signal. We must not, however, hijack every normal bot question from an advertiser
for the full lifetime of a paid campaign. This guard exposes a paid ad submission
only while its linked booking is still in a material-collection state.
"""
from __future__ import annotations

from sqlalchemy import select

from database.ad_sales_models import AdSalesPipeline
from database.db import get_session
from database.models import AdBooking, Submission
from handlers import ad_sales_pipeline as sales_handlers
from utils import ad_sales_pipeline as sales_utils

_MATERIAL_CONVERSATION_STATES = {"waiting", "discussion", "partial"}
_original_active_ad_submission = sales_utils.active_ad_submission


async def active_ad_submission(user_id: int) -> Submission | None:
    # First preserve the original pre-payment lead behaviour.
    pre_payment = await _original_active_ad_submission(user_id)
    if pre_payment is not None and pre_payment.status != "paid":
        return pre_payment

    async with get_session() as session:
        rows = (await session.execute(
            select(Submission, AdSalesPipeline, AdBooking)
            .join(AdSalesPipeline, AdSalesPipeline.submission_id == Submission.id)
            .join(AdBooking, AdBooking.id == AdSalesPipeline.ad_booking_id)
            .where(
                Submission.type == "ad",
                Submission.user_id == user_id,
                Submission.status == "paid",
                AdBooking.status == "paid",
                AdBooking.materials_status.in_(_MATERIAL_CONVERSATION_STATES),
            )
            .order_by(Submission.id.desc())
            .limit(1)
        )).first()
        return rows[0] if rows else None


def install() -> None:
    if getattr(sales_utils, "_material_conversation_guard_installed", False):
        return
    # The broad runtime adds `paid` so its generic function can see post-payment
    # leads. Replace that with a precise query instead.
    sales_utils.ACTIVE_SALES.discard("paid")
    sales_utils.active_ad_submission = active_ad_submission
    sales_handlers.active_ad_submission = active_ad_submission
    sales_utils._material_conversation_guard_installed = True


install()
