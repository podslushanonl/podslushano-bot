"""Keep one useful/action post in the Telegram channel every day.

The action-content migration had reduced bot feature posts to Tuesday + Thursday.
This layer keeps those existing slots and fills every otherwise empty day with one
rotating action post, so the bot has a useful publication every calendar day.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta

from sqlalchemy import select

from database.db import get_session
from database.models import ContentPost


DAILY_ACTIONS = (
    "action_events",
    "action_board",
    "action_specialists",
    "action_digest",
    "action_letter",
    "action_salary",
    "action_notifications",
)


def install_content_frequency(content_module) -> None:
    if getattr(content_module, "_daily_action_posts_installed", False):
        return

    original_seed = content_module.seed_content_calendar

    async def seed_daily_action_posts() -> None:
        await original_seed()
        now = content_module._local_now()
        end = now.date() + timedelta(days=content_module.ROLLING_DAYS)

        async with get_session() as session:
            rows = list((await session.scalars(
                select(ContentPost).where(
                    ContentPost.scheduled_at >= now - timedelta(days=14),
                    ContentPost.scheduled_at < datetime.combine(end + timedelta(days=1), time.min),
                ).order_by(ContentPost.scheduled_at, ContentPost.id)
            )).all())
            occupied = {row.scheduled_at.date() for row in rows if row.status != "skipped"}

            day = now.date()
            while day <= end:
                if day not in occupied:
                    previous = [r for r in rows if r.status != "skipped" and r.scheduled_at.date() < day]
                    prev = previous[-1] if previous else None
                    last_template = prev.template_key if prev else ""
                    last_kind = prev.content_kind if prev else ""

                    # Rotate deterministically by day, but never repeat the same action
                    # or the same broad content kind immediately after the previous slot.
                    offset = day.toordinal() % len(DAILY_ACTIONS)
                    candidates = DAILY_ACTIONS[offset:] + DAILY_ACTIONS[:offset]
                    key = next(
                        k for k in candidates
                        if k in content_module.TEMPLATES
                        and k != last_template
                        and content_module.TEMPLATES[k].kind != last_kind
                    )
                    template = content_module.TEMPLATES[key]
                    campaign = f"autodaily_{day:%y%m%d}_{key}"
                    row = ContentPost(
                        campaign_key=campaign,
                        template_key=key,
                        content_kind=template.kind,
                        scheduled_at=datetime.combine(day, time(15, 0)),
                        status="scheduled",
                        button_label=template.button,
                        start_payload=f"content_{campaign}",
                    )
                    session.add(row)
                    rows.append(row)
                    rows.sort(key=lambda r: r.scheduled_at)
                    occupied.add(day)
                day += timedelta(days=1)

            await session.commit()

    content_module.seed_content_calendar = seed_daily_action_posts
    content_module._daily_action_posts_installed = True
