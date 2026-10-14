"""Lunch Flow Personal API: spending transactions here; balances via connectors/lunchflow.py."""
import asyncio
import hashlib
import os
from collections import defaultdict
from datetime import date, datetime, timedelta

import dotenv

from networth import http, spending
from networth.store import now

BASE_URL = 'https://www.lunchflow.app/api/v1'


class LunchFlowError(ValueError):
  pass


def env_path(config):
  return (config.path.resolve().parent if config.path else config.data_dir) / '.env'


def api_key(config):
  # Read .env on demand so replacing the token does not require restarting the app.
  values = dotenv.dotenv_values(env_path(config))
  return (values.get('LUNCHFLOW_API_KEY') or os.environ.get('LUNCHFLOW_API_KEY', '')).strip()


async def get(path, key, params=None):
  if not key:
    raise LunchFlowError('Set LUNCHFLOW_API_KEY in the app’s .env file first.')
  try:
    return await http.get_json(BASE_URL + path, params=params, headers={'x-api-key': key})
  except Exception as exc:
    status = getattr(getattr(exc, 'response', None), 'status_code', None)
    message = {
      401: 'Lunch Flow rejected the API key. Check your API destination settings.',
      403: 'Lunch Flow denied access. Enable this account in your API destination.',
      404: 'Lunch Flow account not found. Check your bank connection.',
      503: 'Lunch Flow is still fetching this account. Try again shortly.',
    }.get(status, 'Lunch Flow is unavailable. Check your connection and try again.')
    raise LunchFlowError(message) from None


async def discover(key):
  payload = await get('/accounts', key)
  try:
    return [dict(id=str(a['id']), name=a['name'], institution=a.get('institution_name') or '',
                 currency=a.get('currency') or '', status=a.get('status', 'ACTIVE')) for a in payload['accounts']]
  except (KeyError, TypeError):
    raise LunchFlowError('Lunch Flow returned an invalid account list.') from None


def state(store, config):
  bindings = [dict(r) for r in store.conn.execute('SELECT * FROM lunchflow_accounts ORDER BY account')]
  choices = []
  for a in config.accounts:
    if a.type == 'monzo' or a.category not in ('cash', 'liabilities'):
      continue
    last_csv = store.conn.execute("SELECT MAX(date) FROM transactions WHERE account=? AND source='csv'", (a.name,)).fetchone()[0]
    choices.append(dict(name=a.name, start_date=(date.fromisoformat(last_csv) + timedelta(days=1)).isoformat() if last_csv else ''))
  return dict(configured=bool(api_key(config)), bindings=bindings, choices=choices)


async def configure(store, config, mappings):
  key = api_key(config)
  accounts = {a['id']: a for a in await discover(key)}
  seen_ids, seen_names, validated = set(), set(), []
  old = {r['id']: dict(r) for r in store.conn.execute('SELECT * FROM lunchflow_accounts')}
  for mapping in mappings:
    remote_id, name = mapping['id'], mapping['account'].strip()
    # Some providers omit account currency; transaction currencies are always checked before saving.
    if remote_id not in accounts or accounts[remote_id]['currency'] not in ('', 'GBP') or accounts[remote_id]['status'] != 'ACTIVE':
      raise LunchFlowError('Choose an active GBP Lunch Flow account.')
    if not name or len(name) > 100 or remote_id in seen_ids or name.casefold() in seen_names:
      raise LunchFlowError('Choose a unique account name for each bank account.')
    seen_ids.add(remote_id); seen_names.add(name.casefold())
    local = next((a for a in config.accounts if a.name == name), None)
    if any(a.name.casefold() == name.casefold() and a.name != name for a in config.accounts):
      raise LunchFlowError('Use the exact existing app account name to link it.')
    if local and (local.type == 'monzo' or local.category not in ('cash', 'liabilities')):
      raise LunchFlowError('Link a cash or credit-card account without automatic Monzo syncing.')
    start = mapping.get('start_date') or None
    if start:
      try:
        date.fromisoformat(start)
      except ValueError:
        raise LunchFlowError('Start date must be YYYY-MM-DD.') from None
    if remote_id in old and old[remote_id]['account'] != name:
      raise LunchFlowError('Keep the saved account name; rename linked accounts through Settings.')
    if any(r['account'].casefold() == name.casefold() and rid != remote_id for rid, r in old.items()):
      raise LunchFlowError('This app account is already linked to a different Lunch Flow account.')
    last_csv = store.conn.execute("SELECT MAX(date) FROM transactions WHERE account=? AND source='csv'", (name,)).fetchone()[0]
    if last_csv and (not start or start <= last_csv):
      raise LunchFlowError(f'{name} has statement imports through {last_csv}. Choose a later start date to avoid duplicates.')
    previous = store.conn.execute("SELECT bank_account FROM transactions WHERE account=? AND source='csv' LIMIT 1", (name,)).fetchone()
    bank_account = old.get(remote_id, {}).get('bank_account') or (previous['bank_account'] if previous else 'lunchflow:' + remote_id)
    validated.append((remote_id, name, accounts[remote_id]['institution'], start, bank_account))
  with store.conn:
    store.conn.execute('UPDATE lunchflow_accounts SET enabled=0')
    store.conn.executemany('''INSERT INTO lunchflow_accounts(id,account,institution,start_date,bank_account) VALUES (?,?,?,?,?)
      ON CONFLICT(id) DO UPDATE SET enabled=1, start_date=excluded.start_date,
      institution=excluded.institution, bank_account=excluded.bank_account''', validated)
  return state(store, config)


def normalise(raw_rows, binding):
  if not isinstance(raw_rows, list):
    raise LunchFlowError('Lunch Flow returned an invalid transaction list.')
  rows, occurrences, ids = [], defaultdict(int), set()
  bank = 'lunchflow:' + binding['id']
  for raw in raw_rows:
    if not isinstance(raw, dict):
      raise LunchFlowError('Lunch Flow returned an invalid transaction.')
    if raw.get('currency') != 'GBP':
      raise LunchFlowError('Only GBP transactions can be imported into spending.')
    try:
      day = date.fromisoformat(raw['date']).isoformat()
      if binding['start_date'] and day < binding['start_date']:
        continue
      if str(raw['accountId']) != binding['id']:
        raise ValueError('Wrong account')
      if raw['amount'] is None or isinstance(raw['amount'], bool):
        raise ValueError('Invalid amount')
      amount = spending.money_pence(raw['amount'])
      description = raw.get('description') or raw.get('merchant') or 'Bank transaction'
      merchant = raw.get('merchant') or description
      if not isinstance(description, str) or not isinstance(merchant, str):
        raise ValueError('Invalid description')
      pending = raw.get('isPending', False)
      if not isinstance(pending, bool):
        raise ValueError('Invalid pending flag')
      # A null ID is permitted by some providers. Preserve identical purchases via an occurrence index.
      identity = raw.get('id')
      if not identity:
        fingerprint = f'{day}|{amount}|{merchant}|{description}'
        occurrences[fingerprint] += 1
        identity = f'fallback|{fingerprint}|{occurrences[fingerprint]}'
      tid = 'lunchflow:' + hashlib.sha256(f'{bank}|{identity}'.encode()).hexdigest()
      if tid in ids:
        raise ValueError('Duplicate transaction ID')
      ids.add(tid)
      rows.append(dict(id=tid, account=binding['account'], bank_account=binding['bank_account'] or bank, date=day,
                       merchant=merchant, description=description, amount=amount, category='Uncategorised',
                       kind='expense' if amount < 0 else 'income', pending=int(pending), source='lunchflow'))
    except (KeyError, TypeError, ValueError):
      raise LunchFlowError('Lunch Flow returned an invalid transaction. No transactions were changed for this account.') from None
  return rows


async def sync(store, config, due_only=False):
  outcomes = []
  for binding in store.conn.execute('SELECT * FROM lunchflow_accounts WHERE enabled=1').fetchall():
    status = store.conn.execute('SELECT last_success FROM spending_status WHERE account=?', (binding['account'],)).fetchone()
    if due_only and status and status['last_success'] and datetime.fromisoformat(now()) - datetime.fromisoformat(status['last_success']) < timedelta(hours=1):
      continue
    try:
      params = {'include_pending': 'true'}
      if binding['start_date']:
        params['from'] = binding['start_date']
      payload = await asyncio.wait_for(get(f"/accounts/{binding['id']}/transactions", api_key(config), params), 60)
      rows = normalise(payload['transactions'], binding)
      if 'total' in payload and payload['total'] != len(payload['transactions']):
        raise LunchFlowError('Lunch Flow returned incomplete history. Existing transactions are retained; try again later.')
      # The Personal API returns all available transactions (no pagination).
      # Missing pending entries have settled or disappeared; settled history is always retained.
      with store.conn:
        incoming = {r['id'] for r in rows}
        pending = store.conn.execute("""SELECT id FROM transactions WHERE bank_account=? AND source='lunchflow'
          AND pending=1 AND date>=?""", (binding['bank_account'] or 'lunchflow:' + binding['id'], binding['start_date'] or '')).fetchall()
        store.conn.executemany('DELETE FROM transactions WHERE id=?', [(r['id'],) for r in pending if r['id'] not in incoming])
        spending.save_transactions(store, rows)
        store.conn.execute('''INSERT INTO spending_status(account,last_success) VALUES (?,?)
          ON CONFLICT(account) DO UPDATE SET last_success=excluded.last_success,last_error=NULL''', (binding['account'], now()))
      outcomes.append(dict(account=binding['account'], count=len(rows), error=None))
    except Exception as exc:
      error = str(exc) if isinstance(exc, LunchFlowError) else 'Lunch Flow sync failed. Try again; existing transactions are retained.'
      with store.conn:
        store.conn.execute('''INSERT INTO spending_status(account,last_error) VALUES (?,?)
          ON CONFLICT(account) DO UPDATE SET last_error=excluded.last_error''', (binding['account'], error))
      outcomes.append(dict(account=binding['account'], count=0, error=error))
  return outcomes
