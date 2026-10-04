# AM Projects review moderation

A dedicated table am_project_reviews in the existing persistent bot SQLite database stores pending and published reviews. It is registered before init_db. No existing tables or polling/webhook configuration change.

Required worker variables:
- AM_REVIEWS_SECRET: dedicated random shared secret, also referenced by amprojects-web.
- AM_REVIEWS_CHAT_ID: owner chat, reference amprojects-web.TELEGRAM_CHAT_ID.

POST /api/am-reviews requires the shared bearer secret, validates consent/rating/lengths and deduplicates submissions by signed ID. Notification is sent only to the configured owner chat. Failed deliveries remain pending and can be retrieved with /amreviews. GET /api/am-reviews exposes published reviews only; contact and other private fields are never serialized.

Only existing config.ADMIN_IDS may use the Telegram controls. Publish includes a review in the feed; Delete first asks for confirmation, then removes stored personal content and retains an idempotency tombstone. Deleted records cannot be republished from a stale button. The website recalculates ratings using the public feed.

For historical review notifications without buttons: reply /amreview to the actual message sent by this bot. It is imported as pending and a new moderation card is returned. /amreviews lists the latest 20 current reviews, and is also in the admin command menu.

Deploy this bot change first, then the companion amprojects-work website change. Verify GET /api/am-reviews returns JSON before switching the website. Tests: python -m unittest discover -s tests -p test_am_reviews.py -v. Tests use temporary SQLite and mocked Telegram; no messages or reviews are published.
