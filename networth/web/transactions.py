"""Raw Monzo transactions for other apps on the box (Sundial reads these over the edge network).

networth stays the only holder of the Monzo tokens: refresh tokens are single-use, so a second
holder would keep logging this one out. Transactions are read live from Monzo, as Monzo returns
them (merchant expanded), rather than from the spending tables, which keep only a summary."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query

from networth import http
from networth.connectors.monzo import API_URL, DEFAULT_ACCOUNT_TYPES, Monzo, MonzoAuthError

# Past the first five minutes after login, Monzo only serves the last 90 days.
MAX_DAYS = 89


def parse_since(since):
  floor = datetime.now(timezone.utc) - timedelta(days=MAX_DAYS)
  if not since:
    return floor
  try:
    start = datetime.fromisoformat(since.replace('Z', '+00:00'))
  except ValueError:
    raise HTTPException(422, 'since must be an ISO 8601 time')
  if start.tzinfo is None:
    start = start.replace(tzinfo=timezone.utc)
  return max(start, floor)


async def monzo_transactions(account, data_dir, since):
  connector = Monzo(account, data_dir)
  headers = {'Authorization': f'Bearer {await connector._access_token()}'}
  types = connector.param('account_types', DEFAULT_ACCOUNT_TYPES)
  out = []
  for bank_account in (await http.get_json(f'{API_URL}/accounts', headers=headers))['accounts']:
    if bank_account.get('closed') or bank_account.get('type') not in types:
      continue
    cursor = since.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    for _ in range(1000):
      batch = (await http.get_json(f'{API_URL}/transactions', headers=headers, params={
        'account_id': bank_account['id'], 'since': cursor, 'limit': 100, 'expand[]': 'merchant'}))['transactions']
      out.extend(batch)
      if len(batch) < 100:
        break
      if batch[-1]['id'] == cursor:
        raise ValueError('Monzo pagination did not advance')
      cursor = batch[-1]['id']   # an id as since means "after this one"
    else:
      raise ValueError('Monzo history exceeded page limit')
  return out


def router(config):
  api = APIRouter()

  @api.get('/api/transactions')
  async def transactions(since: str | None = Query(None)):
    start = parse_since(since)
    accounts = [a for a in config.accounts if a.type == 'monzo']
    if not accounts:
      raise HTTPException(503, 'no Monzo account configured')
    out = []
    for account in accounts:
      if account.error:
        raise HTTPException(503, f'{account.name}: {account.error}')
      try:
        out += await monzo_transactions(account, config.data_dir, start)
      except MonzoAuthError as e:
        raise HTTPException(503, f'{account.name}: {e}')
      except Exception as e:
        # Request errors carry URLs with account ids; say what failed, not the details.
        raise HTTPException(502, f'{account.name}: Monzo fetch failed ({type(e).__name__})')
    out.sort(key=lambda t: t.get('created') or '')
    return {'since': start.isoformat(), 'transactions': out}

  return api
