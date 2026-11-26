import asyncio
import json
import re
from urllib.parse import unquote, urljoin

import requests
from bs4 import BeautifulSoup

from networth.config import ConfigError
from networth.connectors.base import Connector, Field, connector
from networth.models import Holding, to_decimal

BASE_URL = 'https://online.hl.co.uk'

HEADERS = {
  'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
  'Accept': '*/*',
  'Accept-Encoding': 'gzip, deflate, br, zstd',
  'Accept-Language': 'en-US,en;q=0.9',
  'Cache-Control': 'no-cache',
}

FORM_HEADERS = HEADERS | {'Content-Type': 'application/x-www-form-urlencoded'}
TIMEOUT = 30


_QUEUE_NEXT = re.compile(r"decodeURIComponent\('([^']+)'\)")


class HLSession(requests.Session):
  """HL fronts its site with a Queue-it waiting room. Browsers get through it with a bit of
  JavaScript that redirects to the next URL; do the same here so requests land on the real page."""

  def request(self, method, url, **kwargs):
    res = super().request(method, url, **kwargs)
    for _ in range(5):
      if 'queue.hl.co.uk' not in res.url:
        break
      match = _QUEUE_NEXT.search(res.text)
      if not match:
        raise RuntimeError('HL is showing its waiting room (queue) and it could not be passed - try again later')
      res = super().request('GET', urljoin(res.url, unquote(match.group(1))), **kwargs)
    return res


@connector('hl')
class HargreavesLansdown(Connector):
  """
  Scrapes an HL account summary page (ISA, SIPP, Fund & Share...).

  params:
    account_id: the number at the end of the account summary URL
    username, date_of_birth, password, secure_number: login details
  """
  label = 'Hargreaves Lansdown'
  fields = [
    Field('account_id', 'Account ID', 'number', required=True, help='The number at the end of the account summary URL'),
    Field('username', 'Username', 'secret', required=True),
    Field('date_of_birth', 'Date of birth', 'secret', required=True),
    Field('password', 'Password', 'secret', required=True),
    Field('secure_number', 'Secure number', 'secret', required=True),
    Field('look_through', 'Fund look-through', 'yaml',
          help='Where to find country/sector weights for funds (see networth/classify.py)'),
  ]

  async def fetch(self):
    return await asyncio.to_thread(self._fetch)

  def _fetch(self):
    session = self._login()
    res = session.get(f'{BASE_URL}/my-accounts/account_summary/account/{self.param("account_id")}',
                      headers=HEADERS, timeout=TIMEOUT)
    holdings = [
      Holding(asset=row['ticker'], quantity=row['units'], value=row['value_gbp'], currency='GBP',
              name=row['stock_name'])
      for row in parse_holdings(res.text)
    ]
    holdings.append(Holding('GBP', parse_cash(res.text), name='Cash'))
    return holdings

  def _login(self):
    session = HLSession()
    if self._load_cookies(session):
      if is_authed(session):
        return session
      # An expired session cookie makes HL redirect the login page to /my-accounts (no form, so
      # no hl_vt token), so log in from a clean session instead of on top of the dead one.
      session = HLSession()

    step_one_html = self._login_step_one(session)
    res = self._login_step_two(session, step_one_html)
    if not is_authed(session):
      raise RuntimeError(f'HL login failed: {_describe(res)}')

    self._save_cookies(session)
    return session

  def _login_step_one(self, session):
    res = session.get(f'{BASE_URL}/my-accounts/login-step-one', headers=HEADERS, timeout=TIMEOUT)
    data = {
      'hl_vt': _find_hl_vt(res.text, 'login step one'),
      'username': self.param('username'),
      'date-of-birth': self.param('date_of_birth'),
    }
    res = session.post(f'{BASE_URL}/my-accounts/login-step-one', headers=FORM_HEADERS, data=data, timeout=TIMEOUT)
    return res.text

  def _login_step_two(self, session, step_one_html):
    soup = BeautifulSoup(step_one_html, 'html.parser')
    secure_number = self.param('secure_number')
    # An unquoted number in YAML would silently lose any leading zeros
    if not isinstance(secure_number, str) or not secure_number.isdigit():
      raise ConfigError(f'{self.account.name}: secure_number must be a quoted string of digits (or ${{VAR}})')

    # HL asks for three digits of the secure number, labelled e.g. "2nd digit"
    digit_labels = soup.find_all('div', class_='secure-number-container__label')
    if not digit_labels:
      raise RuntimeError('HL login step two: secure number prompts not found - '
                         'username/date of birth may be wrong, or the page layout changed')
    digit_indices = [int(lab.get_text(strip=True)[0]) for lab in digit_labels]
    if max(digit_indices) > len(secure_number):
      raise ConfigError(f'{self.account.name}: HL asked for digit {max(digit_indices)} '
                        f'but secure_number has {len(secure_number)} digits')

    data = {
      'hl_vt': _find_hl_vt(step_one_html, 'login step two'),
      'online-password-verification': self.param('password'),
      'submit': 'Log in',
    }
    for i, idx in enumerate(digit_indices):
      data[f'secure-number[{i+1}]'] = secure_number[idx-1]

    return session.post(f'{BASE_URL}/my-accounts/login-step-two', headers=FORM_HEADERS, data=data, timeout=TIMEOUT)

  def _load_cookies(self, session):
    path = self.state_file('cookies.json')
    if not path.exists():
      return False
    for k, v in json.loads(path.read_text()).items():
      session.cookies.set(k, v)
    return True

  def _save_cookies(self, session):
    path = self.state_file('cookies.json')
    path.write_text(json.dumps(session.cookies.get_dict()))
    path.chmod(0o600)


def _describe(res):
  """Where a login attempt ended up, so a failure says why (never includes form data)."""
  soup = BeautifulSoup(res.text, 'html.parser')
  heading = soup.find(['h1', 'h2']) or soup.find('title')
  alerts = [a.get_text(' ', strip=True) for a in soup.select('.alert, .error, .error-message, [role=alert]')]
  text = ' | '.join(filter(None, [heading.get_text(' ', strip=True) if heading else '', *alerts[:2]]))
  return f'HTTP {res.status_code} at {res.url.split("?")[0]} - {text[:200] or "no message on page"}'


def is_authed(session):
  try:
    res = session.get(f'{BASE_URL}/ajaxx/user.php?method=getPersonalDetails&field=client_id&format=json',
                      headers=HEADERS, timeout=TIMEOUT)
    data = res.json()
  except (ValueError, requests.RequestException):
    return False
  # Logged in, HL returns the client id - a bare number, or an object with `client_id` in older
  # responses. Logged out, it returns a bare `false`.
  if isinstance(data, dict):
    data = data.get('client_id')
  return bool(data)


def parse_holdings(html):
  soup = BeautifulSoup(html, 'html.parser')
  table = soup.find('table', id='holdings-table')
  if table is None:
    raise RuntimeError('HL holdings table not found - page layout may have changed')
  tbody = table.find('tbody')
  if tbody is None:  # an account with nothing invested
    return []
  return [parse_holdings_row(row) for row in tbody.find_all('tr')]


def parse_cash(html):
  """Uninvested cash, from the account valuation summary above the holdings table."""
  cell = BeautifulSoup(html, 'html.parser').find('td', id='cash_total_header')
  if cell is None:
    raise RuntimeError('HL cash total not found - page layout may have changed')
  return _number(cell.get_text(strip=True))


def parse_holdings_row(row):
  cells = row.find_all('td')
  return {
    'ticker': cells[0].get_text(strip=True),
    'stock_name': cells[1].find('span', class_='text-bold').get_text(strip=True),
    'units': _number(cells[2].get_text(strip=True)),
    'price_pence': _number(cells[3].get_text(strip=True)),
    'value_gbp': _number(cells[4].get_text(strip=True)),
    'cost_gbp': _number(cells[5].get_text(strip=True)),
  }


def _number(text):
  """'£1,234.56', '123.4p', '1,000' -> Decimal."""
  cleaned = re.sub(r'[£p,\s]', '', text)
  try:
    return to_decimal(cleaned)
  except (ArithmeticError, ValueError):
    raise RuntimeError(f'HL: could not read a number from {text!r} - page layout may have changed') from None


def _find_hl_vt(html, step):
  hl_vt_input = BeautifulSoup(html, 'html.parser').find('input', {'name': 'hl_vt'})
  if hl_vt_input is None:
    raise RuntimeError(f'HL {step}: hl_vt token not found - page layout may have changed')
  return hl_vt_input['value']
