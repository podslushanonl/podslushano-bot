"""Reliability guard for the rolling Telegram content calendar.

If the bot starts after a gap, the rolling scheduler intentionally does not
backfill old dates. That can make the first newly generated monthly commercial
slot have the same kind as the last historical slot. Keep the calendar
invariant: adjacent posts must not have the same content kind.
"""
from sqlalchemy import select

from database.db import get_session
from database.models import ContentPost


def install_content_calendar_reliability(content_module) -> None:
    if getattr(content_module, "_calendar_reliability_installed", False):
        return

    original_seed = content_module.seed_content_calendar

    async def reliable_seed_content_calendar() -> None:
        await original_seed()

        async with get_session() as session:
            rows = (await session.scalars(
                select(ContentPost).order_by(ContentPost.scheduled_at, ContentPost.id)
            )).all()

            previous_kind = None
            changed = False
            for row in rows:
                template = content_module.TEMPLATES.get(row.template_key)
                current_kind = template.kind if template else row.content_kind

                # Only remove automatically generated rolling rows. Never rewrite
                # curated history or anything that was actually delivered. A row
                # already marked "skipped" by the action-content migration is
                # still safe to delete and otherwise keeps breaking adjacency.
                is_auto = (row.campaign_key or "").startswith("auto")
                was_delivered = row.status in {"sent", "published"}
                if previous_kind and current_kind == previous_kind and is_auto and not was_delivered:
                    await session.delete(row)
                    changed = True
                    continue

                previous_kind = current_kind

            if changed:
                await session.commit()

    content_module.seed_content_calendar = reliable_seed_content_calendar
    content_module._calendar_reliability_installed = True
