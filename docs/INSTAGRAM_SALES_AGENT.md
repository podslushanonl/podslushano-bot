# Instagram Direct — Podslushano.nl AI Sales Agent (feature-gated)

## Purpose
Sell approved advertising formats inside Instagram Direct without forcing customers through a website booking form or collecting campaign materials before payment.

The public `/ads` page and existing Telegram flows are unchanged. The feature is **OFF by default**; shipping code does **not** connect Instagram, send messages or create real payments until Meta and Railway configuration is explicitly enabled.

## Data flow

```text
Instagram professional account
    ↓ Meta webhook (GET challenge + signed POST)
GET/POST /webhooks/instagram-sales
    ↓ verify HMAC SHA256 + message recipient + event age
ig_sales_events (durable / deduplicated by message mid)
    ↓ asynchronous worker
ig_sales_conversations
    ↓ only advertising intent
Anthropic classifier (when configured) / conservative deterministic fallback
    ↓ fixed allowlist of approved config.AD_FORMATS keys, server amounts only
IG DM quote + essential terms + explicit customer acceptance
    ↓ only if IG_SALES_PAYMENTS_ENABLED=1
Mollie /v2/payments (single checkout URL; metadata.kind="ig_ad_sale")
    ↓ GET Mollie status through existing /mollie-webhook
ig_sales_orders (payment id, amount, paid status)
    ↓ client & administrator notified
Post-payment billing details in Direct → PDF factuur (existing utils.invoices)
    ↓ editorial production / confirm publication dates separately
```

## Railway environment variables

| Name | Required | Description |
|---|---|---|
| `IG_SALES_ENABLED` | Yes | `1` processes inbound authenticated webhooks, default `0`. |
| `IG_SALES_SEND_ENABLED` | Yes | `1` sends automated Direct replies, default `0`. |
| `IG_SALES_PAYMENTS_ENABLED` | Yes | `1` permits creating Mollie checkout links **only after explicit consent**, default `0`. |
| `IG_SALES_ACCOUNT_ID` | Yes | Instagram professional account ID; must match webhook receiver. |
| `IG_SALES_ACCESS_TOKEN` | Yes | Long-lived Instagram access token granted by the account owner. |
| `IG_SALES_APP_SECRET` | Yes | Meta app secret used for X-Hub-Signature-256. |
| `IG_SALES_VERIFY_TOKEN` | Yes | Separate, random webhook challenge token. |
| `IG_SALES_GRAPH_VERSION` | Optional | Graph API version, default `v23.0`. |
| `MOLLIE_API_KEY` | Existing | Prefer a Mollie **test** key during acceptance tests. |
| `WEBHOOK_BASE_URL` | Existing | Public HTTPS base URL of Railway worker. |
| `ANTHROPIC_API_KEY` / `AI_CHAT_MODEL` | Existing | Intent classification; if unavailable, deterministic intent/product fallback works for basic keywords. |

**Never paste access tokens, app secrets, API keys or signed webhook payloads into chats or GitHub.** Railway variables are the only storage for these secrets. Do not enable the three production feature flags before test-mode checks and Meta approval.

Meta prerequisites: professional Instagram account, app login access, approved `instagram_business_manage_messages` permission / applicable App Review and webhook subscriptions. Incoming webhook must be authorized; outbound conversations can only follow an incoming customer message and respect Instagram's message window. Check Meta's current platform requirements before launch.

Webhook callback: `https://worker-production-ad76.up.railway.app/webhooks/instagram-sales`.

**Meta subscription**: messages for the Instagram professional account. The GET verification challenge can be configured before the agent is enabled; POST signature must always verify.

## Financial invariants

- Price comes from `config.ad_option(product_key, "std")`. The AI is not allowed to generate amounts, URLs, coupons or product terms. Private products are excluded.
- An explicit customer response to the presented offer is needed before creating the checkout.
- The checkout is from Mollie /v2/payments. This is a **unique payment URL**, not a reusable Mollie Payment Link; it supports verification via the currently installed payments webhook.
- Current Q4 **−26% is not automatically given** in Direct. It is a separate newsletter-consent offer on the existing site. Until we explicitly implement the same consent+entitlement check inside Direct, quotes are standard-price only. Do not claim that DM and site discount prices are equal.
- Never mark an order paid merely because the client says they paid or because the redirect page was loaded. Only `get_payment()` from Mollie can confirm status and the backend checks currency, amount, metadata and payment ID.
- One active checkout per Instagram conversation; duplicates return the original URL. Webhook duplicates are idempotent.
- All dates and campaign materials are agreed upon after payment. When a specific publication date is essential to the offer, the editor must check availability first; no AI guarantees dates.
- Factuur is issued **after payment**, after validated name/company, postal address and email are received. Once issuance begins, retries do not create another invoice number; failures trigger a manual-review status.
- Refusals, legal concerns, suspicious advertisers, guarantees/refunds and competitors go to an administrator. The agent never promises sales, followers or a guaranteed reach.

## Operations

- Telegram admin command: `/igsales` — flags and recent order statuses.
- `/igsales pause IG_SCOPED_USER_ID` — stop bot answers for that thread.
- `/igsales resume IG_SCOPED_USER_ID` — resume.
- Payment notifications go to existing Telegram admins, and the client receives a Direct reply only inside the permitted messaging window.
- Incoming events stored with a unique Meta message ID in `ig_sales_events`. Outgoing messages are only sent when `IG_SALES_SEND_ENABLED=1`.
- The model sees up to four recent short messages; avoid collecting sensitive personal data before payment. Invoice data must be used for billing only and must not be transmitted to the AI provider.
- Update privacy notice before enabling production to reflect direct-message processing, third-party AI classification, retention policies and invoice processing.

## Rollout checklist (must pass before a live customer)

1. Meta app account ownership, API permissions and messaging webhook verification approved.
2. Configure `IG_SALES_ENABLED=1`, `IG_SALES_SEND_ENABLED=0`, `IG_SALES_PAYMENTS_ENABLED=0`; observe signed test messages, duplicates and non-advertising messages. The agent should **not** send DMs.
3. Connect a Meta test account and validate one outbound text in API-compliant time window with `IG_SALES_SEND_ENABLED=1`.
4. Use Mollie test API key and `IG_SALES_PAYMENTS_ENABLED=1`. Test quote → explicit confirmation → checkout → paid, canceled, expired and webhook replay.
5. Validate PDF invoice and admin handoff; review legal terms / publication-date availability.
6. Only after supervised acceptance, update Mollie live key and enable production payments. Check successful Railway deploy and operations with `/igsales`.

## Follow-up work

- Direct opt-in for Q4 subscription plus server-verified 26% offer, with unsubscribe mechanism and no forced signup.
- Admin operations dashboard for interventions, payment links, failed invoices, cancellations and invoice correction.
- Reconciliation/retry of payments not confirmed by the first Mollie webhook.
- Message / content retention and privacy/data deletion process.
- Lead analytics and campaign scheduling after payment, without invasive multi-step forms.
