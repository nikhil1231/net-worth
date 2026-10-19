# Net worth

Tracks everything I own in GBP: HL ISA, crypto wallets and exchanges, bank accounts.
A scheduler fetches each account on its own interval, prices everything and stores a
snapshot in SQLite. The dashboard shows the total, its history and the breakdown, plus a page per
investment account with splits by product, country and sector, and a sandbox for trying out changes.

## Setup

```bash
uv venv .venv && uv pip install -r requirements.txt
cp accounts.example.yaml accounts.yaml   # then edit
cd frontend && npm ci && npm run build   # the dashboard, built into networth/web/static/
```

Secrets go in `.env` and are referenced from `accounts.yaml` as `${VAR}`.

Accounts and the schedule can also be edited from the dashboard's **Settings** page, which writes
`accounts.yaml` in place (keeping comments; the previous version is saved as `data/accounts.yaml.prev`)
and applies changes without a restart. Secrets typed in literally are never sent back to the browser.

## Commands

```bash
.venv/bin/python -m networth check [ACCOUNT...]   # fetch and print holdings, saves nothing
.venv/bin/python -m networth run [--force]        # one run, saves a snapshot
.venv/bin/python -m networth serve --host 0.0.0.0  # dashboard + scheduler on LAN port 8000
.venv/bin/python -m networth monzo-auth "Monzo"   # one-off Monzo login
```

Working on the dashboard: run `serve` (or any API on `NETWORTH_API`, default
`http://127.0.0.1:8000`), then `npm run dev` in `frontend/` for a hot-reloading copy on :5173.

## Deploying

The `Dockerfile` runs `serve`. Mount `accounts.yaml`, an env file and a `data/` volume into the container.

## How it fits together

- `networth/connectors/` - one module per source type. A connector returns `Holding`s
  (asset + quantity, or a value the source already knows).
- `networth/pricing.py` - values holdings in GBP using Coinbase's public rates (fiat + crypto).
- `networth/runner.py` - fetches due accounts, carries forward ones that weren't fetched or
  failed, and writes a snapshot of every account per run.
- `networth/store.py` / `reports.py` - SQLite storage and the summary/history queries.
- `networth/classify.py` - country and sector exposure per holding: Yahoo Finance for stocks, the
  issuer's published weights for funds listed under `look_through` in `accounts.yaml`, and justETF's
  country weights for other funds. Cached in
  SQLite for a week.
- `networth/settings.py` - reads and edits `accounts.yaml` for the settings page.
- `networth/web/` - FastAPI app serving the API and the built dashboard.
- `frontend/` - the dashboard: React + Recharts, built with Vite. Hidden holdings and sandbox
  edits live in the browser's localStorage, per account.

## Adding a connector

1. Create `networth/connectors/<name>.py`:

   ```python
   @connector('my_bank')
   class MyBank(Connector):
     async def fetch(self):
       balance = await http.get_json(..., headers={'Authorization': self.param('token')})
       return [Holding('GBP', balance['amount'])]
   ```

2. Import it in `networth/connectors/__init__.py`.
3. Add an account with `type: my_bank` to `accounts.yaml`, then `python -m networth check "<name>"`.

Give the class a `label` and a list of `fields` (`Field(key, label, kind)`) so the settings page
gets a proper form for it; params without a field are still editable as YAML.

Use `self.param(key, default)` for config and `self.state_file(suffix)` for anything that
must persist between runs (cookies, tokens).


### Protocol holdings in wallet accounts

Wallet account params may contain a `positions` list of `{type, params}` sources.
IntentX collateral and Aevo aeUSD belong to the EVM wallet account; the unclaimed
Drift DFX allocation belongs to the Solana account. These sources refresh alongside
wallet balances and retain their wallet and chain attribution.

Chain links on wallet detail pages open holdings for that chain, including protocol
labels. Unpriced tokens appear in the holdings table with a small warning and tooltip;
they are excluded from net worth. Chains without holdings are omitted.

Aevo shares use live ERC-4626 redeemable USDC value. IntentX valuation stops when open
positions need PnL valuation. DFX claims have no assumed redemption value. EVM and SPL
token configs optionally use exact-contract Blockscout or exact-mint DexScreener USD
quotes, converted to GBP. Fetch failures retain the previous wallet values.

The header GBP/USD toggle remembers the display currency in the browser. Values,
prices, chart labels and tooltips convert immediately using public Coinbase FX rates,
refreshed every 15 minutes. Stored snapshots and sandbox quantities stay in their
original units; dollar sandbox inputs convert back to GBP internally.

## Financial advisor

Open **Advisor** (`/advisor`) for a weekly, evidence-backed review. The overview also surfaces
the latest findings. Reviews run on the server, including while the browser is closed; default
is Monday at 09:00 Europe/London. Daily and manual-only schedules are available. **Run a review**
does not move the scheduled slot. The database holds settings, the queue, inputs, reports,
evidence snapshots, feedback and provider-reported usage/cost. Back these up with `networth.db`.
No new service or external scheduler is required.

The first version checks existing recorded data; it does not fetch financial news. Calculated
reviews work without an AI key. Set your goals, horizon and upcoming costs in **Your brief &
schedule**. These inform optional model commentary. The cash buffer target and selected cash
accounts also drive calculated checks. Only GBP holdings in explicitly selected accounts count
towards that buffer, net of negative GBP balances; stablecoins are excluded. Availability and
underlying dates of manual valuations cannot be verified.

Checks cover missing/stale/failed account data, unpriced assets, direct holding concentration,
spending increases against the prior four-week average, and confirmed recurring charge increases.
Concentration uses positive valued assets, excludes liabilities from its denominator, and does
not treat a fund as a single company. Cached investment country/sector data is included only when
no older than eight days; missing weights stay unknown. No classification network fetch happens
during a review. Spending uses the existing corrections and transfer inference, excludes pending
payments and transfers, and counts refunds when received. A trend alert requires transaction
dates spanning both comparison periods and recent successful syncs for every included spending
account. This is deliberately conservative: a quiet or partially imported account can prevent
the comparison. Coverage dates still do not prove completeness.

Snapshot change attribution compares current configured accounts with a snapshot at or before
seven days ago. For matching positions it calculates old quantity × GBP unit price change and
quantity change × new GBP unit price. New, removed, unpriced or otherwise unmatched positions
stay in a separate residual. Price effects include FX and stale prices; quantity changes are
not verified deposits or withdrawals. This is arithmetic attribution, **not an investment
return calculation**. Values may differ by a penny from rounding.

Optional commentary uses OpenRouter structured output. Set `OPENROUTER_API_KEY` in the server
environment and restart the app. Local development also reads `.env` beside `accounts.yaml` on each request.
Never put a provider key in the browser. Choose a compatible model in the advisor settings;
the default is `google/gemini-2.5-flash`. No new model dependency is needed.

When enabled and configured, one request receives at most 100,000 characters of prepared facts,
selected account/asset names, spending categories, recurring merchants, your brief and recent
feedback. It excludes account config, credentials, wallet address fields, bank IDs, raw account
errors, individual payment records and their descriptions. Names and free-text context are still
personal data. The request requires structured-output support, `data_collection="deny"` and
`zdr=true`. Provider reference validation checks that evidence keys exist; it cannot establish
that a model's interpretation is correct. There is no browsing or ability to change finances.

Output is limited to 1,000–8,000 tokens (default 3,000); this bounds output size, not exact cost.
There are no automatic provider retries. If the provider is unavailable, rejects the request,
or returns invalid output, the review still saves its calculated findings with a warning.
An empty holdings history never triggers a paid request. The run log shows token usage and cost
when reported by the provider. Cross-process locking and a unique active-run index prevent
overlapping reviews. One overdue review catches up after downtime; interrupted runs are marked
failed and can be rerun. Settings changes update queued/future runs, not one already running.

**Useful**, **Already know**, **Dismiss**, **Incorrect**, and written corrections persist by
finding topic. Handled findings are hidden by default and remain accessible through the filter
and historical reviews. Handled topics return as new when their signal materially changes,
or when they recur after being absent from the previous review. Small cash/allocation changes
are grouped into bands to reduce repetition; evidence still updates on every review. You can
also toggle feedback back to new yourself. The global privacy toggle hides the whole
review and brief, including narrative amounts and personal context. Written findings use GBP;
dashboard summary amounts follow the display-currency toggle.


## Spending

The **Spending** page combines GBP bank transactions into monthly spending, category,
pace and income charts. Transactions are stored separately from net-worth snapshots;
spending sync failures retain history and do not change balance snapshots.

- **Monzo:** the scheduler collects recent transactions whenever Monzo is due, and
  **sync** refreshes them on demand. Existing authorisation is reused. Regular
  syncs reread 89 days to update pending/settled payments. Monzo permits full history
  only immediately after authentication: `python -m networth monzo-auth "Monzo"`
  now attempts a full transaction import immediately after app approval.
- **Santander / manual cash accounts:** open the gear icon → **Statements**, select the account, map
  columns and preview before committing. Use a GBP CSV with a header row, date,
  description and either a signed amount (negative for outgoings), or separate money
  out and money in columns. Optional unique transaction IDs improve deduplication.
  DD/MM/YYYY and YYYY-MM-DD dates are supported, as are comma, semicolon and tab
  delimiters. Imports are limited to 5 MB / 10,000 rows. PDF and Santander text
  statements are not parsed; convert them to this CSV format first.
- **Corrections:** categories and expense/income/refund/transfer classifications
  persist across syncs. Optionally apply a category rule to all past and future
  transactions with the same merchant in that account. Choosing **Savings** also
  makes a transaction a transfer.
- **Automatic suggestions** (shown in italics; any choice you make wins): uncategorised
  bank transactions (Santander, Amex, statements) take the category Monzo or you gave
  the same merchant (e.g. `TESCO STORES` → Monzo's `Tesco`), then fall back to known
  merchant keywords. An opposite amount in another account within three days becomes a
  transfer when there is evidence it is your own money: a shared reference
  (`MONZO-ABCDE` on both sides), a credit-card repayment, or one side already marked as a
  transfer. Payments to investment platforms (HL, Vanguard, Trading 212, …) are Savings
  transfers, card "payment received" credits are transfers, and money back from a merchant
  you've paid from that account is a refund. Other amount/date matches stay suggestions
  requiring review. These are worked out when transactions are read, so improving them
  updates past transactions too.
- **Mark monthly spending:** use the transaction's **recurring icon** at the end of the row to choose
  **Monthly spend** or **Monthly subscription**. The rule marks all past and future
  expenses with the same merchant (ignoring case and extra spaces) in that bank
  account, and creates a confirmed commitment immediately after the first settled
  charge. Variable amounts and irregular dates do not undo an explicit rule. Its
  estimate uses the last settled charge. Choose **Not recurring** to suppress both
  manual tracking and suggestions, or **Automatic detection** to remove the rule.
- **Recurring payments:** consistent weekly/monthly patterns need three settled
  payments, quarterly/annual patterns need two. Confirm suggestions to include their
  monthly equivalents in commitments, dismiss shopping patterns, or mark cancelled.
  These are inferred payments, not a bank mandate feed; changing status never cancels
  a service. Expected dates and price changes are estimates from recorded payments.

Coverage shows first/last transaction dates and sync status, not a guarantee of
complete history. Charts exclude pending payments and confirmed transfers, and
show refunds in the month received. Importing identical files is safe; without bank
IDs, overlapping partial files containing identical same-day payments can be
ambiguous. Transaction amounts are stored as integer pence. The privacy toggle
hides spending amounts, merchant descriptions and charts.

Transaction history is retained indefinitely: the 89-day sync window limits what
Monzo can return on each routine fetch, not what this app keeps. Back up the SQLite
database in `data/` (or the deployed data directory) to preserve history and rules.
Older Monzo history can be backfilled by reauthorising and capturing it in the API's
five-minute full-history window. Monzo's own app can also export older statements,
but this app's CSV importer currently targets manual cash accounts, not Monzo.

The recurring list defaults to active commitments. Missing payments become inactive
once subsequent activity in the same bank account passes the expected date plus a
grace period (weekly: 14 days, monthly: 35 days, quarterly: 45 days, annual: 60 days).
Inactive, cancelled and dismissed entries are available through **Show inactive &
dismissed** and are excluded from recurring commitments. A new payment can revive
an inactive service; an explicit cancelled/dismissed status is preserved. Missing
payments are judged against recorded account activity, so simply leaving an account
unsynced does not invent a cancellation. Stale coverage is flagged.
Multiple monthly charges to one merchant on the same day are summed for its latest
commitment estimate. Description-specific rules can distinguish a subscription from
other purchases or API credits billed by the same merchant.

### Lunch Flow transactions

Set `LUNCHFLOW_API_KEY` in the `.env` file beside `accounts.yaml`, using the key
from a Lunch Flow **REST API destination**. Then open **Spending → gear icon → Bank connections**.
Connected accounts load automatically; use **Refresh** to reload them or **Retry
connection** after adding or fixing the key. Enable Santander and
American Express in the destination's Account Access settings if they do not
appear. Select each active GBP account/card and choose its app account name.
Use the exact existing app account name to link it; a new name creates an account
for spending only, without changing net-worth balances.

Balances come from the same feed: give an account `type: lunchflow` and the Lunch
Flow `account_id` (shown under Bank connections), and it reads
`/accounts/{id}/balance`. Lunch Flow signs balances from your side, so money owed on
a credit card is negative and a card in credit is positive. Use `account_ids` instead
of `account_id` to group several cards into one account; each card is a holding named
after its Lunch Flow account. Name the account the same as its spending link so
transactions and balance share one account.

Save the selections and press **sync** to import immediately. The normal
scheduler also checks Lunch Flow hourly while the app runs. Sync reads the
transactions already available in Lunch Flow; it does not force the bank to refresh.
Blank import dates fetch all available history. If the app account already contains
CSV transactions, choose a start date after the final CSV date to avoid overlap;
further CSV imports into linked accounts are blocked. Unchecking an account and
saving pauses its sync while retaining imported transactions and rules.

The API key is read server-side from `LUNCHFLOW_API_KEY` in `.env` (or the process
environment). It is never entered in or returned to the browser. Changes to `.env`
are picked up on the next API request. Keep `.env` private and back up `networth.db`
to preserve transaction history and account mappings. The integration uses the
[Lunch Flow Personal API](https://www.lunchflow.app/docs/api/personal-api-overview).

Transactions use GBP pence, stable bank IDs and per-account namespaces for repeat
syncs. Providers without transaction IDs use date/amount/description plus an
occurrence index; changed descriptions or dates can make those records ambiguous.
Pending entries are excluded from settled totals and removed when they disappear
from a successful full response. Settled history and manual category/type overrides
are retained. Lunch Flow and statement rows carry no time of day; Monzo rows do.
