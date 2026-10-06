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
.venv/bin/python -m networth serve                # dashboard + scheduler on http://127.0.0.1:8000
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
