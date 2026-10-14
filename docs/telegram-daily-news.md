# Daily Telegram publication

Fixed destination: @podslushanovnl. All dates and schedules use Europe/Amsterdam,
including DST. ChatGPT researches current sources before each slot; the existing
worker publishes queued content every five seconds. No paid AI API calls and no
Make workflows are required by these bridges.

- 06:00: POST /api/morning, MORNING_BRIDGE_TOKEN; plain sections and approved CTA.
- 10:00 / 18:00: POST /api/news, NEWS_BRIDGE_TOKEN; five news items and source links.

News payload: date (YYYY-MM-DD), slot (morning/evening), checked_at (timezone-aware
ISO timestamp), items (exactly five objects containing plain text and HTTPS url).
The server escapes text, renders the source as clickable «тут», disables previews,
adds the dated heading and the exact fixed closing sentence. Morning news links
follow the paragraph; evening links are on the following line.

GET /api/news/status checks channel permissions, pause, schedules and the last
fourteen records. Research may be at most sixty minutes old. Intake windows are
09:00–10:45 and 17:00–18:45. dry_run=true validates fresh same-day content at any
time, returns rendered HTML, and never writes or publishes.

Persistent SQLite lives on /app/data. Date+slot uniquely identify immutable
drafts. Identical retries return the original state; changed drafts return 409.
The worker atomically claims queued drafts before sending. Ambiguous Telegram
delivery is not retried; state delivery_unknown/sending requires channel review.
Only sent plus message_id proves successful publication. A global pause blocks
publication. Never reuse yesterday's news or invent five items to fill a gap.

Credentials stay outside the repository. Unit and HTTP tests cover authentication,
HTML escaping, link format, length, freshness, DST, pause, deduplication, scheduled
delivery and ambiguous failures. Live dry runs verify formatting and access but
do not prove a scheduled publication; record its message_id after the first run.
