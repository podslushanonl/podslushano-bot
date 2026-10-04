# Morning Telegram publication

The community morning brief is prepared at 05:50 and published from 06:00,
always in `Europe/Amsterdam`. The existing 60-second scheduler tick means the
send normally happens during the 06:00 minute. User travel and server timezone
do not change the slot; Amsterdam daylight-saving transitions apply automatically.

- Destination: configured `ANNOUNCE_CHANNEL`, verified through Telegram as
  the channel `@podslushanovnl` with `can_post_messages` permission.
- Research: existing Anthropic verified Web Search pipeline, including KNMI,
  NS, ProRail, Arriva, 9292 and Rijkswaterstaat. Requires funded API access.
- One text message with italic introduction, bold section headings, optional
  Important blockquote, italic freshness blockquote and bold reaction CTA.
- Footer records actual research completion, not the scheduled publication time.
- Draft and research timestamp are persisted in the existing database, survive
  restarts, and can only be reused on the same Amsterdam date for 30 minutes.
- Up to three preparation attempts, at least five minutes apart; recovery ends
  at 07:00. A late successful recovery is sent with its honest check time.
- Existing global content pause remains respected. Other editorial slots and
  approval requirements are unchanged.
- Daily success shares the previous scheduler's deduplication key. A durable
  `sending` marker is saved before Telegram is called. If delivery is ambiguous,
  no automatic resend occurs; the administrator is alerted to check the channel.
- No images, extra buttons, webhook, new secrets, or database migrations.

The ChatGPT scheduled draft is a separate process; this pipeline does not read
ChatGPT conversations or forward their text. It researches independently on Railway.

Validation: `python -m pytest -q tests/test_morning_autopublish.py` and
`python tests/test_editorial_full_pipeline.py`.

Deployment verification: confirm the deployed Git SHA, `/editorialhealth`,
content pause state, and the next `Morning auto published` runtime log with a
Telegram message ID. Unit tests do not prove production API balance or delivery.
