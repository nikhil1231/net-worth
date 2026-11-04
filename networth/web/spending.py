"""Spending endpoints; imports are parsed identically for preview and commit."""
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from networth import lunchflow, spending
from networth.config import ConfigError


class TransactionEdit(BaseModel):
  category: str | None = None
  kind: str | None = None
  apply_rule: bool = False
  recurring_type: Literal['auto', 'monthly', 'subscription', 'none'] | None = None
  label: str | None = Field(None, max_length=100)


class StatementImport(BaseModel):
  account: str
  text: str = Field(max_length=5_000_000)
  mapping: dict[str, str | bool]
  commit: bool = False


class RecurringEdit(BaseModel):
  account: str
  merchant: str
  status: Literal['confirmed', 'dismissed', 'cancelled', 'detected']


class LunchFlowMapping(BaseModel):
  id: str = Field(pattern=r'^\d+$', max_length=30)
  account: str = Field(min_length=1, max_length=100)
  start_date: str | None = None


class LunchFlowSetup(BaseModel):
  mappings: list[LunchFlowMapping] = Field(max_length=100)


def router(store, config, runner):
  api = APIRouter(prefix='/api/spending')

  @api.get('')
  async def report(month: str = Query(pattern=r'^\d{4}-\d{2}$'), account: str | None = None):
    try:
      if account and not store.conn.execute('SELECT 1 FROM lunchflow_accounts WHERE account=?', (account,)).fetchone():
        config.account(account)
      result = spending.report(store, config, month, account)
      await lunchflow.check_connections(store, config, result['accounts'])
      return result
    except (ValueError, LookupError, ConfigError) as e:
      raise HTTPException(400, str(e))

  @api.post('/sync')
  async def sync():
    # Share the scheduler lock so rotating OAuth tokens cannot race.
    async with runner.lock:
      return await spending.sync_monzo(store, config) + await lunchflow.sync(store, config)

  @api.get('/lunchflow')
  async def lunchflow_status():
    return lunchflow.state(store, config)

  @api.post('/lunchflow/accounts')
  async def lunchflow_accounts():
    try:
      return await lunchflow.discover(lunchflow.api_key(config))
    except lunchflow.LunchFlowError as e:
      raise HTTPException(400, str(e))

  @api.put('/lunchflow')
  async def lunchflow_setup(values: LunchFlowSetup):
    async with runner.lock:
      try:
        return await lunchflow.configure(store, config, [m.model_dump() for m in values.mappings])
      except lunchflow.LunchFlowError as e:
        raise HTTPException(400, str(e))

  @api.patch('/transactions/{transaction_id}')
  async def edit(transaction_id: str, values: TransactionEdit):
    try:
      spending.edit_transaction(store, transaction_id, **values.model_dump())
    except LookupError as e:
      raise HTTPException(404, str(e))
    except ValueError as e:
      raise HTTPException(400, str(e))
    return {'ok': True}

  @api.post('/import')
  async def statement(values: StatementImport):
    account = next((a for a in config.accounts if a.name == values.account), None)
    linked = store.conn.execute('SELECT 1 FROM lunchflow_accounts WHERE account=?', (values.account,)).fetchone()
    if account is None or account.category != 'cash' or account.type == 'monzo' or linked:
      raise HTTPException(400, 'Choose a cash account without automatic bank syncing')
    try:
      previous = store.conn.execute("SELECT bank_account FROM transactions WHERE account=? AND source='csv' LIMIT 1", (values.account,)).fetchone()
      rows = spending.parse_csv(values.text, values.account, values.mapping, previous['bank_account'] if previous else None)
    except ValueError as e:
      raise HTTPException(400, str(e))
    existing = {r['id'] for r in store.conn.execute('SELECT id FROM transactions WHERE account=?', (values.account,))}
    new = [r for r in rows if r['id'] not in existing]
    if values.commit:
      spending.save_transactions(store, rows)
      with store.conn:
        store.conn.execute('''INSERT INTO spending_status(account,last_success) VALUES (?,?)
          ON CONFLICT(account) DO UPDATE SET last_success=excluded.last_success,last_error=NULL''', (values.account, spending.now()))
    return dict(count=len(rows), new_count=len(new), duplicates=len(rows)-len(new),
                first_date=min(r['date'] for r in rows), last_date=max(r['date'] for r in rows),
                preview=rows[:8], committed=values.commit)

  @api.patch('/recurring/{recurring_id}')
  async def recurring(recurring_id: str, values: RecurringEdit):
    candidates = spending.recurring(store, spending.transactions(store))
    match = next((r for r in candidates if r['id']==recurring_id), None)
    if not match or (match['account'], match['merchant']) != (values.account, values.merchant):
      raise HTTPException(404, 'Recurring payment not found')
    with store.conn:
      store.conn.execute('INSERT OR REPLACE INTO recurring_payments VALUES (?,?,?,?)',
                         (recurring_id, values.account, values.merchant, values.status))
    return {'ok': True}

  return api
