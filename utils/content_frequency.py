"""Restore a steadier action-post cadence in the Telegram channel.

The action-content migration reduced bot feature posts to Tuesday + Thursday only.
Keep those slots and add one Saturday slot, yielding three useful/action posts per
week without flooding the channel.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta

from sqlalchemy import select

from database.db import get_session
from database.models import ContentPost


SATURDAY_ACTIONS = (
    "action_events",
    "action_board",
    "action_specialists",
    "action_digest",
    "action_letter",
    "action_salary",
    "action_notifications",
)


def install_content_frequency(content_module) -> None:
    if getattr(content_module, "_three_weekly_posts_installed", False):
        return

    original_seed = content_module.seed_content_calendar

    async def seed_three_weekly_posts() -> None:
        await original_seed()
        now = content_module._local_now()
        end = now.date() + timedelta(days=content_module.ROLLING_DAYS)

        async with get_session() as session:
            rows = (await session.scalars(
                select(ContentPost).where(
                    ContentPost.scheduled_at >= now - timedelta(days=14),
                    ContentPost.scheduled_at < datetime.combine(end + timedelta(days=1), time.min),
                ).order_by(ContentPost.scheduled_at, ContentPost.id)
            )).all()
            occupied = {row.scheduled_at.date() for row in rows if row.status != "skipped"}

            # Track last actually relevant action to avoid adjacent repeats by template or kind.
            ordered = [r for r in rows if r.status != "skipped"]
            last_template = ordered[-1].template_key if ordered else ""
            last_kind = ordered[-1].content_kind if ordered else ""

            day = max(now.date(), (ordered[-1].scheduled_at.date() + timedelta(days=1)) if ordered else now.date())
            while day <= end:
                if day.weekday() == 5 and day not in occupied:  # Saturday
                    offset = (day.toordinal() // 7) % len(SATURDAY_ACTIONS)
                    candidates = SATURDAY_ACTIONS[offset:] + SATURDAY_ACTIONS[:offset]
                    key = next(
                        k for k in candidates
                        if k in content_module.TEMPLATES
                        and k != last_template
                        and content_module.TEMPLATES[k].kind != last_kind
                    )
                    template = content_module.TEMPLATES[key]
                    campaign = f"auto3_{day:%y%m%d}_{key}"
                    session.add(ContentPost(
                        campaign_key=campaign,
                        template_key=key,
                        content_kind=template.kind,
                        scheduled_at=datetime.combine(day, time(15, 0)),
                        status="scheduled",
                        button_label=template.button,
                        start_payload=f"content_{campaign}",
                    ))
                    occupied.add(day)
                    last_template = key
                    last_kind = template.kind
                day += timedelta(days=1)

            await session.commit()

    content_module.seed_content_calendar = seed_three_weekly_posts
    content_module._three_weekly_posts_installed = True
