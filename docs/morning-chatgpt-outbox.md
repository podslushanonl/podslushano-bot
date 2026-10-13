# ChatGPT morning publication

ChatGPT researches the morning briefing at 05:40 Europe/Amsterdam, then submits
plain-text sections to POST /api/morning. The existing Railway worker stores the
payload on its persistent volume and publishes at 06:00 (5-second scheduler).
No Anthropic/OpenAI API calls are made by this bridge. Keep
EDITORIAL_MORNING_AUTO_ENABLED=0 to avoid the old independent paid generator.

Authentication: dedicated MORNING_BRIDGE_TOKEN bearer credential. It is not the
Telegram bot token. GET /api/morning/status verifies the fixed channel
@podslushanovnl, bot posting permissions, global pause and latest delivery state.

Payload: date (Amsterdam YYYY-MM-DD), checked_at (ISO timestamp with timezone),
intro, weather, transport, roads, optional important, sources (>=3 HTTPS URLs).
Content must be freshly researched, with sources separate from public text.
The server renders escaped Telegram HTML with the approved formatting, an honest
research timestamp and the fixed reaction CTA. Optional dry_run=true validates
without storing or publishing.

Only same-day submissions between 05:20 and 06:45 are accepted. Research must be
no more than 45 minutes old at intake and send time. One immutable draft per day;
identical retries return the existing record. Different content returns 409.
Persistent sending state is written before Telegram; unknown delivery is never
retried automatically. The legacy daily key is respected and updated on success.
Global content pause remains respected. Stale drafts are rejected, never reused.

Check queued/sent/message_id through authenticated status. Unit tests cover
escaping, freshness, Amsterdam DST, authentication, no early send, successful
deduplication and ambiguous-delivery suppression. Deployment verification must
also check authenticated status and a dry run; these do not count as a live post.
