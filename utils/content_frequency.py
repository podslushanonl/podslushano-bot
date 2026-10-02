"""Keep one useful/action post in the Telegram channel every day.

The action-content migration had reduced bot feature posts to Tuesday + Thursday.
This layer keeps those existing slots and fills every otherwise empty day with one
rotating action post, so the bot has a useful publication every calendar day.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

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
            # A skipped slot is an explicit decision; do not refill its date.
            occupied = {row.scheduled_at.date() for row in rows}

            day = now.date()
            while day <= end:
                if day not in occupied:
                    active = [r for r in rows if r.status != "skipped"]
                    previous = [r for r in active if r.scheduled_at.date() < day]
                    following = [r for r in active if r.scheduled_at.date() > day]
                    prev = previous[-1] if previous else None
                    nxt = following[0] if following else None
                    prev_template = prev.template_key if prev else ""
                    prev_kind = prev.content_kind if prev else ""
                    next_kind = nxt.content_kind if nxt else ""

                    # Rotate deterministically by day. A newly inserted slot must not
                    # duplicate the previous OR the already-existing next content kind;
                    # otherwise a daily filler could create an adjacent pair on either side.
                    offset = day.toordinal() % len(DAILY_ACTIONS)
                    candidates = DAILY_ACTIONS[offset:] + DAILY_ACTIONS[:offset]
                    safe = [
                        k for k in candidates
                        if k in content_module.TEMPLATES
                        and k != prev_template
                        and content_module.TEMPLATES[k].kind != prev_kind
                        and content_module.TEMPLATES[k].kind != next_kind
                    ]
                    if not safe:
                        # With the current action pool this should not normally happen,
                        # but prefer preserving the previous-side invariant over crashing.
                        safe = [
                            k for k in candidates
                            if k in content_module.TEMPLATES
                            and k != prev_template
                            and content_module.TEMPLATES[k].kind != prev_kind
                        ]
                    if not safe:
                        day += timedelta(days=1)
                        continue
                    key = safe[0]
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
                    # Another seeder may have committed this campaign after our read.
                    # Ignore only this unique-key conflict; preserve existing fields.
                    await session.execute(
                        sqlite_insert(ContentPost).values(
                            campaign_key=row.campaign_key,
                            template_key=row.template_key,
                            content_kind=row.content_kind,
                            scheduled_at=row.scheduled_at,
                            status=row.status,
                            button_label=row.button_label,
                            start_payload=row.start_payload,
                        ).on_conflict_do_nothing(index_elements=["campaign_key"])
                    )
                    rows.append(row)
                    rows.sort(key=lambda r: (r.scheduled_at, r.id or 0))
                    occupied.add(day)
                day += timedelta(days=1)

            await session.commit()

    content_module.seed_content_calendar = seed_daily_action_posts
    content_module._daily_action_posts_installed = True
