import asyncio
import json
import re

import requests
from bs4 import BeautifulSoup

from networth.config import ConfigError
from networth.connectors.base import Connector, Field, connector
from networth.models import Holding

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
    session = requests.Session()
    if self._load_cookies(session) and is_authed(session):
      return session

    step_one_html = self._login_step_one(session)
    self._login_step_two(session, step_one_html)
    if not is_authed(session):
      raise RuntimeError('HL login failed')

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

    session.post(f'{BASE_URL}/my-accounts/login-step-two', headers=FORM_HEADERS, data=data, timeout=TIMEOUT)

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


def is_authed(session):
  try:
    res = session.get(f'{BASE_URL}/ajaxx/user.php?method=getPersonalDetails&field=client_id&format=json',
                      headers=HEADERS, timeout=TIMEOUT)
    return res.json()['client_id'] != False  # noqa: E712 - HL returns false or an id
  except (ValueError, KeyError, requests.RequestException):
    return False


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
  """'£1,234.56', '123.4p', '1,000' -> float."""
  cleaned = re.sub(r'[£p,\s]', '', text)
  try:
    return float(cleaned)
  except ValueError:
    raise RuntimeError(f'HL: could not read a number from {text!r} - page layout may have changed') from None


def _find_hl_vt(html, step):
  hl_vt_input = BeautifulSoup(html, 'html.parser').find('input', {'name': 'hl_vt'})
  if hl_vt_input is None:
    raise RuntimeError(f'HL {step}: hl_vt token not found - page layout may have changed')
  return hl_vt_input['value']
