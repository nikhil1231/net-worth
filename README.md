# Net worth

A self-hosted dashboard that tracks everything you own in one currency (GBP, with a USD toggle):
brokerage accounts, crypto wallets and exchanges, bank accounts and cards. A scheduler pulls
each account on its own interval, prices it, and stores a snapshot, so you get your total, its
history and a breakdown. It also tracks spending and can write a weekly review of your finances.

- **Overview:** total, history chart, breakdown by category, asset and chain.
- **Investment accounts:** holdings with country and sector look-through for funds, and a
  sandbox for trying out changes without touching real data.
- **[Spending](docs/spending.md):** bank transactions, categories, transfers and recurring payments.
- **[Advisor](docs/advisor.md):** a weekly, evidence-backed review, with optional LLM commentary.

## Architecture

```mermaid
flowchart LR
  subgraph sources[Sources]
    direction TB
    broker[Hargreaves Lansdown]
    chain[Bitcoin / EVM / Solana wallets]
    cex[Exchanges via ccxt]
    bank[Monzo / Lunch Flow banks]
    manual[Manual values]
  end

  subgraph app[networth - one Python process]
    direction TB
    sched[Scheduler] --> runner[Runner]
    runner --> conn[Connectors]
    runner --> price[Pricing: Coinbase rates]
    runner --> store[(Postgres)]
    classify[Classify: Yahoo, justETF, issuers] --> store
    spend[Spending sync] --> store
    advisor[Advisor worker] --> store
    api[FastAPI] --> store
  end

  sources --> conn
  bank --> spend
  advisor -.optional.-> llm[OpenRouter]
  api --> ui[React dashboard]
  cfg[accounts.yaml / .env] --> app
```

Each run fetches the accounts that are due, values every holding in GBP and writes a snapshot of
all accounts. Accounts that weren't due, or failed, are carried forward from their last good fetch.

| Path | What it does |
| --- | --- |
| `networth/connectors/` | One module per source type. A connector returns `Holding`s. |
| `networth/runner.py` | Schedules fetches, prices holdings, writes snapshots. |
| `networth/pricing.py`, `classify.py` | GBP prices; country and sector exposure per holding. |
| `networth/spending.py`, `lunchflow.py`, `categorise.py` | Transactions, categories, transfers, recurring payments. |
| `networth/advisor.py` | The weekly review. |
| `networth/store.py`, `sqlpg.py` | Postgres storage. |
| `networth/web/` | FastAPI: the JSON API and the built dashboard. |
| `frontend/` | React, Recharts and Vite. |

## Quick start

You need Python 3.12+, Node 22+ and a Postgres database.

```bash
uv venv .venv && uv pip install -r requirements.txt
cp accounts.example.yaml accounts.yaml          # then edit; ${VARS} are read from .env
echo 'DATABASE_URL=postgresql://user:pass@localhost/networth' >> .env
(cd frontend && npm ci && npm run build)         # builds into networth/web/static/
.venv/bin/python -m networth serve               # http://127.0.0.1:8000
```

Or `docker compose up` to run the app and Postgres together.

Accounts and the schedule can also be edited on the dashboard's **Settings** page, which rewrites
`accounts.yaml` in place (keeping comments, with the previous copy in `data/accounts.yaml.prev`).
Secrets typed in literally are never sent back to the browser.

```bash
python -m networth check [ACCOUNT...]   # fetch and print holdings, saves nothing
python -m networth run [--force]        # one run, saves a snapshot
python -m networth serve                # dashboard + scheduler
python -m networth monzo-auth "Monzo"   # one-off Monzo login
```

For frontend work run `serve`, then `npm run dev` in `frontend/` (hot reload on :5173, proxied to the API).

## Tests

```bash
TEST_DATABASE_URL=postgresql://postgres:pw@localhost/postgres .venv/bin/python -m pytest
```

Each test gets its own throwaway database, so the role needs `CREATEDB`.

## Adding a connector

```python
# networth/connectors/my_bank.py, then import it in connectors/__init__.py
@connector('my_bank')
class MyBank(Connector):
  label = 'My Bank'
  fields = [Field('token', 'API token', 'secret', required=True)]

  async def fetch(self):
    balance = await http.get_json(..., headers={'Authorization': self.param('token')})
    return [Holding('GBP', balance['amount'])]
```

Add an account with `type: my_bank` to `accounts.yaml` and run `python -m networth check "<name>"`.
`self.param(key, default)` reads config; `self.state_file(suffix)` is for anything that must
persist between runs (cookies, tokens). `fields` gives the settings page a proper form.

## Wallets and protocols

Wallet accounts take a `positions` list of `{type, params}` sources for protocol holdings (IntentX
collateral and Aevo shares on EVM, unclaimed Drift DFX on Solana). Token prices come from Blockscout
or DexScreener quotes by exact contract or mint. Unpriced tokens are listed with a warning and
excluded from net worth. If a fetch fails, the previous values are kept.

## Licence

[MIT](LICENSE)
