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


ACCOUNT_CATEGORIES = ('cash', 'liabilities')


def last_csv_date(store, name):
  return store.conn.execute("SELECT MAX(date) FROM transactions WHERE account=? AND source='csv'", (name,)).fetchone()[0]


def csv_start(store, name):
  """The day after the last statement import, where a Lunch Flow import should begin."""
  last = last_csv_date(store, name)
  return (date.fromisoformat(last) + timedelta(days=1)).isoformat() if last else None


def csv_bank_account(store, name):
  row = store.conn.execute("SELECT bank_account FROM transactions WHERE account=? AND source='csv' LIMIT 1", (name,)).fetchone()
  return row['bank_account'] if row else None


def config_ids(account):
  """The Lunch Flow account IDs accounts.yaml assigns to an app account (account_id or account_ids)."""
  ids = account.params.get('account_ids') or ([account.params['account_id']] if account.params.get('account_id') else [])
  return [str(i).strip() for i in ids if str(i).strip()]


def auto_link(store, config):
  """Link transaction sources straight from accounts.yaml, so there is no setup step.
  An existing binding keeps its paused/enabled flag and start date."""
  existing = {r['id']: dict(r) for r in store.conn.execute('SELECT * FROM lunchflow_accounts')}
  with store.conn:
    for a in config.accounts:
      if a.type != 'lunchflow' or a.error or a.category not in ACCOUNT_CATEGORIES:
        continue
      ids = config_ids(a)
      for remote_id in ids:
        row = existing.get(remote_id)
        if row:
          if row['account'] != a.name:  # moved to another account in accounts.yaml
            store.conn.execute('UPDATE lunchflow_accounts SET account=? WHERE id=?', (a.name, remote_id))
          continue
        previous = csv_bank_account(store, a.name)
        # Share a statement-import bank identity only when one source feeds the account; with several
        # cards each keeps its own, so one card's sync never touches another's pending rows.
        bank_account = previous if previous and len(ids) == 1 else 'lunchflow:' + remote_id
        store.conn.execute(
          'INSERT INTO lunchflow_accounts(id,account,institution,start_date,bank_account) VALUES (?,?,?,?,?)',
          (remote_id, a.name, '', csv_start(store, a.name), bank_account))


async def check_connections(store, config, accounts):
  """Verify linked sources are still accessible, without importing or changing history."""
  bindings = defaultdict(list)
  for r in store.conn.execute('SELECT * FROM lunchflow_accounts WHERE enabled=1'):
    bindings[r['account']].append(dict(r))
  linked = [a for a in accounts if a['name'] in bindings]
  if not linked:
    return
  try:
    remote = {a['id']: a for a in await asyncio.wait_for(discover(api_key(config)), 10)}
  except (LunchFlowError, asyncio.TimeoutError) as exc:
    detail = str(exc) if isinstance(exc, LunchFlowError) else 'Lunch Flow connection check timed out. Try again.'
    for a in linked:
      a.update(connection_status='unverified', connection_detail=detail)
    return
  for a in linked:
    for binding in bindings[a['name']]:
      source = remote.get(binding['id'])
      if source and source.get('institution') and source['institution'] != binding['institution']:
        with store.conn:
          store.conn.execute('UPDATE lunchflow_accounts SET institution=? WHERE id=?', (source['institution'], binding['id']))
        a['institution'] = source['institution']
      label = f"{source.get('name', binding['id'])}: " if source and len(bindings[a['name']]) > 1 else ''
      if not source:
        a.update(connection_status='unavailable', connection_detail=f"Lunch Flow account {binding['id']} is missing. Check the bank connection and Account Access settings in Lunch Flow.")
      elif source['status'] != 'ACTIVE':
        a.update(connection_status='unavailable', connection_detail=label + 'Lunch Flow reports this bank as inactive. Reconnect it in the Lunch Flow app; this page picks it up automatically.')
      elif source['currency'] not in ('', 'GBP'):
        a.update(connection_status='unavailable', connection_detail=label + 'This source no longer provides GBP transactions.')
      else:
        continue
      break


def state(store, config):
  bindings = [dict(r) for r in store.conn.execute('SELECT * FROM lunchflow_accounts ORDER BY account')]
  choices = []
  for a in config.accounts:
    if a.type == 'monzo' or a.category not in ACCOUNT_CATEGORIES:
      continue
    choices.append(dict(name=a.name, start_date=csv_start(store, a.name) or ''))
  return dict(configured=bool(api_key(config)), bindings=bindings, choices=choices)


async def configure(store, config, mappings):
  key = api_key(config)
  accounts = {a['id']: a for a in await discover(key)}
  seen_ids, validated = set(), []
  old = {r['id']: dict(r) for r in store.conn.execute('SELECT * FROM lunchflow_accounts')}
  for mapping in mappings:
    remote_id, name = mapping['id'], mapping['account'].strip()
    # Some providers omit account currency; transaction currencies are always checked before saving.
    if remote_id not in accounts or accounts[remote_id]['currency'] not in ('', 'GBP') or accounts[remote_id]['status'] != 'ACTIVE':
      raise LunchFlowError('Choose an active GBP Lunch Flow account.')
    # Several sources may share one app account (e.g. two Amex cards); each source is linked once.
    if not name or len(name) > 100 or remote_id in seen_ids:
      raise LunchFlowError('Choose an account name for each bank account.')
    seen_ids.add(remote_id)
    local = next((a for a in config.accounts if a.name == name), None)
    if any(a.name.casefold() == name.casefold() and a.name != name for a in config.accounts):
      raise LunchFlowError('Use the exact existing app account name to link it.')
    if local and (local.type == 'monzo' or local.category not in ACCOUNT_CATEGORIES):
      raise LunchFlowError('Link a cash or credit-card account without automatic Monzo syncing.')
    start = mapping.get('start_date') or None
    if start:
      try:
        date.fromisoformat(start)
      except ValueError:
        raise LunchFlowError('Start date must be YYYY-MM-DD.') from None
    if remote_id in old and old[remote_id]['account'] != name:
      raise LunchFlowError('Keep the saved account name; rename linked accounts through Settings.')
    last_csv = last_csv_date(store, name)
    if last_csv and (not start or start <= last_csv):
      raise LunchFlowError(f'{name} has statement imports through {last_csv}. Choose a later start date to avoid duplicates.')
    previous = csv_bank_account(store, name)
    shared = sum(m['account'].strip() == name for m in mappings) > 1
    bank_account = old.get(remote_id, {}).get('bank_account') or (previous if previous and not shared else 'lunchflow:' + remote_id)
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


_sync_lock = asyncio.Lock()


async def sync(store, config, due_only=False):
  async with _sync_lock:  # the scheduler, the sync button and background retries can overlap
    auto_link(store, config)
    groups = defaultdict(list)
    for binding in store.conn.execute('SELECT * FROM lunchflow_accounts WHERE enabled=1 ORDER BY account, id').fetchall():
      groups[binding['account']].append(binding)
    outcomes = []
    for account, bindings in groups.items():
      status = store.conn.execute('SELECT last_success, last_error FROM spending_status WHERE account=?', (account,)).fetchone()
      # Healthy accounts sync hourly; one that failed or never synced retries on every call.
      if due_only and status and status['last_success'] and not status['last_error'] \
          and datetime.fromisoformat(now()) - datetime.fromisoformat(status['last_success']) < timedelta(hours=1):
        continue
      count, errors = 0, []
      for binding in bindings:
        try:
          count += await _sync_binding(store, config, binding)
        except Exception as exc:
          errors.append(str(exc) if isinstance(exc, LunchFlowError) else 'Lunch Flow sync failed. Try again; existing transactions are retained.')
      error = ' '.join(dict.fromkeys(errors)) or None
      with store.conn:
        if error:
          store.conn.execute("""INSERT INTO spending_status(account,last_error) VALUES (?,?)
            ON CONFLICT(account) DO UPDATE SET last_error=excluded.last_error""", (account, error))
        else:
          store.conn.execute("""INSERT INTO spending_status(account,last_success) VALUES (?,?)
            ON CONFLICT(account) DO UPDATE SET last_success=excluded.last_success,last_error=NULL""", (account, now()))
      outcomes.append(dict(account=account, count=count, error=error))
    return outcomes


async def _sync_binding(store, config, binding):
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
  return len(rows)
