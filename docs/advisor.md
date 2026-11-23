# Advisor

**Advisor** (`/advisor`) produces a weekly, evidence-backed review of your recorded data. It runs on
the server, so it doesn't need a browser open. Default schedule is Monday 09:00 Europe/London; daily
and manual-only are also available. It never fetches news and has no power to change anything.

Set goals, horizon, upcoming costs and a cash-buffer target under **Your brief & schedule**.

## Checks

Calculated checks need no API key:

- missing, stale or failed account data, and unpriced assets
- concentration in a single holding (funds aren't treated as one company)
- cash buffer, counting only GBP in the accounts you select
- spending against the prior four-week average, and recurring charges that went up
- what changed since a snapshot a week ago, split into price and quantity effects

The change attribution is arithmetic, **not an investment return**: price effects include FX and
stale prices, and quantity changes aren't verified deposits. Each check needs enough recent data
to be meaningful; a quiet or half-imported account can block a comparison on purpose.

Feedback (**Useful**, **Already know**, **Dismiss**, **Incorrect**, or a written correction) is
kept per finding topic. Handled findings stay hidden until their signal changes materially.

## Optional LLM commentary

Set `OPENROUTER_API_KEY` in the server environment (the key never goes to the browser) and choose a
model in the advisor settings (default `google/gemini-2.5-flash`). A review then sends at most
100,000 characters of prepared facts, account and asset names, spending categories, recurring
merchants, your brief and recent feedback. It excludes credentials, wallet addresses, bank IDs,
raw errors and individual payments. Requests ask for structured output, `data_collection="deny"`
and zero data retention. Names and free-text notes are still personal data.

Output is capped at 1,000 to 8,000 tokens (default 3,000) and there are no automatic retries. If the
provider fails or returns something invalid, the review still saves its calculated findings with a
warning. Token usage and cost are logged when the provider reports them.

Reviews are serialised by a cross-process lock; one overdue review catches up after downtime and
interrupted runs are marked failed. The header privacy toggle hides the whole review.
