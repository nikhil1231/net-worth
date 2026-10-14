import asyncio
import json
import secrets
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from urllib.parse import parse_qs, urlencode, urlparse

from networth import http
from networth.connectors.base import Connector, Field, connector
from networth.models import Holding

API_URL = 'https://api.monzo.com'
AUTH_URL = 'https://auth.monzo.com/'
DEFAULT_REDIRECT_URI = 'http://localhost:8765/callback'
DEFAULT_ACCOUNT_TYPES = ['uk_retail', 'uk_retail_joint']


class MonzoAuthError(Exception):
  pass


# Refresh tokens are single-use: two refreshes at once (a scheduled run and an API call) would
# spend the same one, and the loser is logged out.
_token_lock = asyncio.Lock()


@connector('monzo')
class Monzo(Connector):
  """
  Current account + pot balances via the Monzo developer API.

  Create a confidential OAuth client at https://developers.monzo.com, then run
  `python -m networth monzo-auth "<account name>"` once to log in.

  params:
    client_id, client_secret: from the Monzo developer portal
    redirect_uri: must match the client, default http://localhost:8765/callback
    include_pots: default true
    account_types: default [uk_retail, uk_retail_joint]
  """
  label = 'Monzo'
  fields = [
    Field('client_id', 'Client ID', 'secret', required=True),
    Field('client_secret', 'Client secret', 'secret', required=True),
    Field('include_pots', 'Include pots', 'bool', default=True),
    Field('account_types', 'Account types', 'list', placeholder='\n'.join(DEFAULT_ACCOUNT_TYPES)),
    Field('redirect_uri', 'Redirect URI', placeholder=DEFAULT_REDIRECT_URI),
  ]

  async def fetch(self):
    token = await self._access_token()
    headers = {'Authorization': f'Bearer {token}'}
    account_types = self.param('account_types', DEFAULT_ACCOUNT_TYPES)

    res = await http.get_json(f'{API_URL}/accounts', headers=headers)
    holdings = []
    for account in res['accounts']:
      if account.get('closed') or account['type'] not in account_types:
        continue
      label = account.get('description', account['type'])

      balance = await http.get_json(f'{API_URL}/balance', params={'account_id': account['id']}, headers=headers)
      holdings.append(Holding(balance['currency'], balance['balance'] / 100, name=label))

      if self.param('include_pots', True):
        pots = await http.get_json(f'{API_URL}/pots', params={'current_account_id': account['id']}, headers=headers)
        for pot in pots['pots']:
          if not pot.get('deleted'):
            holdings.append(Holding(pot['currency'], pot['balance'] / 100, name=f'Pot: {pot["name"]}'))

    return holdings

  async def fetch_transactions(self, full_history=False, on_batch=None):
    from networth.spending import CATEGORIES
    headers = {'Authorization': f'Bearer {await self._access_token()}'}
    response = await http.get_json(f'{API_URL}/accounts', headers=headers)
    sync_end = datetime.now(timezone.utc)
    since = (sync_end - timedelta(days=89)).isoformat()
    history_from = since[:10]
    rows = []
    categories = {'groceries': 'Groceries', 'eating_out': 'Eating out', 'shopping': 'Shopping',
                  'transport': 'Transport', 'bills': 'Bills', 'entertainment': 'Entertainment',
                  'holidays': 'Travel', 'personal_care': 'Health', 'education': 'Education',
                  'gifts': 'Gifts', 'family': 'Family', 'savings': 'Savings'}
    for account in response['accounts']:
      if account.get('closed') or account.get('type') not in self.param('account_types', DEFAULT_ACCOUNT_TYPES):
        continue
      start = datetime.fromisoformat(account.get('created', '2000-01-01T00:00:00Z').replace('Z', '+00:00')) if full_history else datetime.fromisoformat(since)
      history_from = min(history_from, start.date().isoformat())
      window_end = sync_end
      # Monzo also limits individual requests to a range of under 90 days.
      while window_end > start:
        window_start = max(start, window_end - timedelta(days=89))
        cursor = window_start.isoformat()
        seen = set()
        for _ in range(1000):
          batch = (await http.get_json(f'{API_URL}/transactions', headers=headers,
                   params={'account_id': account['id'], 'since': cursor, 'before': window_end.isoformat(), 'limit': 100, 'expand[]': 'merchant'}))['transactions']
          if not batch:
            break
          batch_start = len(rows)
          for tx in batch:
            if tx['id'] in seen:
              continue
            seen.add(tx['id'])
            if tx.get('currency') != 'GBP':
              raise ValueError('Spending currently supports GBP accounts only')
            merchant = tx.get('merchant') if isinstance(tx.get('merchant'), dict) else {}
            meta = tx.get('metadata') or {}
            transfer = bool(meta.get('pot_id') or meta.get('pot_account_id')) or tx.get('category') == 'savings'
            amount = int(tx['amount'])
            kind = 'transfer' if transfer else 'expense' if amount < 0 else 'refund' if merchant and not tx.get('is_load') else 'income'
            if tx.get('decline_reason'):
              amount = 0
            created = datetime.fromisoformat(tx['created'].replace('Z','+00:00')).astimezone(ZoneInfo('Europe/London'))
            rows.append(dict(id='monzo:'+tx['id'], account=self.account.name, bank_account=account['id'],
                        date=created.date().isoformat(), time=created.strftime('%H:%M'),
                        merchant=merchant.get('name') or tx.get('description') or 'Unknown merchant',
                        description=tx.get('description') or '', amount=amount,
                        category=categories.get(tx.get('category'), CATEGORIES[0]), kind=kind,
                        pending=int(not bool(tx.get('settled')) and amount != 0), source='monzo'))
          if on_batch is not None:
            on_batch(rows[batch_start:])
          if len(batch) < 100:
            break
          next_cursor = batch[-1]['id']
          if next_cursor == cursor:
            raise ValueError('Monzo pagination did not advance')
          cursor = next_cursor
        else:
          raise ValueError('Monzo history exceeded page limit')
        window_end = window_start
    return rows, history_from

  # --- OAuth ---

  async def _access_token(self):
    async with _token_lock:
      return await self._refresh_if_needed()

  async def _refresh_if_needed(self):
    tokens = self._load_tokens()
    if tokens['expires_at'] - 60 > time.time():
      return tokens['access_token']

    try:
      new_tokens = await http.post_json(f'{API_URL}/oauth2/token', data={
        'grant_type': 'refresh_token',
        'client_id': self.param('client_id'),
        'client_secret': self.param('client_secret'),
        'refresh_token': tokens['refresh_token'],
      })
    except Exception as e:
      raise MonzoAuthError(f'Token refresh failed ({e}) - re-run monzo-auth') from e
    new_tokens.setdefault('refresh_token', tokens['refresh_token'])
    self._save_tokens(new_tokens)
    return new_tokens['access_token']

  def _load_tokens(self):
    path = self.state_file('tokens.json')
    if not path.exists():
      raise MonzoAuthError(f'Not authorised - run: python -m networth monzo-auth "{self.account.name}"')
    return json.loads(path.read_text())

  def _save_tokens(self, res):
    path = self.state_file('tokens.json')
    path.write_text(json.dumps({
      'access_token': res['access_token'],
      'refresh_token': res['refresh_token'],
      'expires_at': time.time() + res['expires_in'],
    }))
    path.chmod(0o600)

  async def authorize(self):
    """Interactive one-off login. Monzo emails a magic link, then asks you to approve in the app."""
    redirect_uri = self.param('redirect_uri', DEFAULT_REDIRECT_URI)
    state = secrets.token_urlsafe(16)
    url = AUTH_URL + '?' + urlencode({
      'client_id': self.param('client_id'),
      'redirect_uri': redirect_uri,
      'response_type': 'code',
      'state': state,
    })
    print(f'1. Open this URL and log in:\n\n   {url}\n')
    print('2. Monzo emails you a link. Opening it redirects to localhost, which will fail to load -')
    print('   that is expected. Copy the full URL from the address bar.\n')
    redirected = input('Paste the URL here: ').strip()

    query = parse_qs(urlparse(redirected).query)
    if query.get('state', [None])[0] != state:
      raise MonzoAuthError('State mismatch - paste the URL from this login attempt')

    res = await http.post_json(f'{API_URL}/oauth2/token', data={
      'grant_type': 'authorization_code',
      'client_id': self.param('client_id'),
      'client_secret': self.param('client_secret'),
      'redirect_uri': redirect_uri,
      'code': query['code'][0],
    })
    if 'refresh_token' not in res:
      raise MonzoAuthError('No refresh token returned - make sure the Monzo client is "confidential"')
    self._save_tokens(res)

    input('\n3. Approve the access request in the Monzo app, then press Enter...')
    # Capture history immediately after approval while Monzo permits a full backfill.
    from networth.config import Config
    from networth.store import Store
    from networth.spending import sync_monzo
    config = Config([self.account], data_dir=self.data_dir)
    store = Store(config.db_path)
    try:
      result = await sync_monzo(store, config, full_history=True)
      print('Transaction history:', result[0]['error'] or f"{result[0]['count']} transactions saved")
    finally:
      store.conn.close()
    holdings = await self.fetch()
    print(f'\nAuthorised. Found {len(holdings)} balances.')
