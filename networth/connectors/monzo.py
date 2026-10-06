import json
import secrets
import time
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

  # --- OAuth ---

  async def _access_token(self):
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
    holdings = await self.fetch()
    print(f'\nAuthorised. Found {len(holdings)} balances.')
