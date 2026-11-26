import asyncio
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from networth import reports, runner as runner_module
from networth.config import AccountConfig, Config, ConfigError, load_config
from networth.connectors import Connector, connector
from networth.db import Db
from networth.models import Holding, from_units, to_decimal
from networth.pricing import PriceBook
from networth.runner import Runner
from networth.store import Store

PRICES = PriceBook({'BTC': '0.00002', 'USD': '1.25', 'USDC': '1.25'})  # BTC = £50,000, $1 = £0.80

calls = []


@connector('fake')
class Fake(Connector):
  async def fetch(self):
    calls.append(self.account.name)
    if self.param('fail', False):
      raise RuntimeError('boom')
    return [Holding(h['asset'], h['quantity'], h.get('value'), h.get('currency')) for h in self.param('holdings')]


def account(name, holdings, category='crypto', interval=15, **params):
  return AccountConfig(name, 'fake', category, interval, {'holdings': holdings, **params})


@pytest.fixture
def setup(tmp_path, monkeypatch):
  async def fake_prices():
    return PRICES
  monkeypatch.setattr(runner_module, 'fetch_price_book', fake_prices)
  calls.clear()

  def make(*accounts):
    config = Config(list(accounts), data_dir=tmp_path)
    store = Store(config.db_url)
    return config, store, Runner(config, store)
  return make


def test_pricing():
  assert PRICES.value(Holding('BTC', 2)) == (50_000, Decimal('100000.00'))
  assert PRICES.value(Holding('GBP', 10)) == (1, Decimal('10.00'))
  # source-provided value in another currency is converted, not re-priced
  assert PRICES.value(Holding('VWRL', 4, value=100, currency='USD')) == (20, Decimal('80.00'))
  assert PRICES.value(Holding('NOPE', 1)) == (None, None)
  # values are rounded to the penny once, from the unrounded price
  assert PRICES.value(Holding('USD', '0.015'))[1] == Decimal('0.01')
  assert PriceBook({'USD': '3'}).value(Holding('USD', 1)) == (Decimal(1) / 3, Decimal('0.33'))


def test_amounts_are_exact_decimals():
  assert to_decimal(0.1) == Decimal('0.1')  # a float from YAML or JSON keeps the digits it was written with
  assert to_decimal(' 1.50 ') == Decimal('1.50')
  assert from_units(1234567890123456789, 18) == Decimal('1.234567890123456789')
  for bad in (float('nan'), 'inf', True, None):
    with pytest.raises((TypeError, ValueError)):
      to_decimal(bad)
  assert Holding('GBP', 0.1).quantity == Decimal('0.1')


def test_snapshot_amounts_round_trip_exactly(setup):
  wei = 1234567890123456789
  config, store, runner = setup(
    account('Bank', [{'asset': 'GBP', 'quantity': 0.1}, {'asset': 'GBP', 'quantity': 0.2}], category='cash'),
    account('Wallet', [{'asset': 'USDC', 'quantity': from_units(wei, 18)}]),
  )
  asyncio.run(runner.run())
  holdings, _ = store.last_holdings('Wallet')
  assert holdings[0].quantity == Decimal('1.234567890123456789')
  s = reports.summary(store, config)
  assert s['accounts'][1]['value'] == Decimal('0.30')  # 0.1 + 0.2 in floats is 0.30000000000000004
  assert s['total'] == Decimal('0.30') + Decimal('0.99')  # 1.2345... USDC at $1 = £0.80, to the penny


def test_float_columns_are_migrated_to_numeric():
  url = os.environ['DATABASE_URL']
  db = Db(url)
  db.execute('''CREATE TABLE snapshots (run_id BIGINT NOT NULL, account TEXT NOT NULL, category TEXT NOT NULL,
    asset TEXT NOT NULL, name TEXT, quantity DOUBLE PRECISION NOT NULL, native_value DOUBLE PRECISION, native_currency TEXT,
    price_gbp DOUBLE PRECISION, value_gbp DOUBLE PRECISION, fetched_at TEXT NOT NULL, wallet TEXT, chain TEXT)''')
  db.execute("INSERT INTO snapshots VALUES (1, 'Bank', 'cash', 'GBP', NULL, %s, NULL, NULL, 1, %s, 'ts', NULL, NULL)",
             (0.1 + 0.2, 0.1 + 0.2))
  db.close()
  store = Store(url)
  store = Store(url)  # a second start leaves the converted table alone
  row = store.snapshots(1)[0]
  assert (row['quantity'], row['value_gbp']) == (Decimal('0.3'), Decimal('0.30'))
  types = dict(store.conn.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'snapshots'").fetchall())
  assert {types[c] for c in ('quantity', 'native_value', 'price_gbp', 'value_gbp')} == {'numeric'}


def test_run_values_and_summary(setup):
  config, store, runner = setup(
    account('Wallet', [{'asset': 'BTC', 'quantity': 0.5}]),
    account('Bank', [{'asset': 'GBP', 'quantity': 1000}], category='cash'),
  )
  asyncio.run(runner.run())

  s = reports.summary(store, config)
  assert s['total'] == 26_000
  assert s['categories'] == {'crypto': 25_000, 'cash': 1000}


def test_cash_like_assets_count_as_cash_wherever_they_are(setup):
  config, store, runner = setup(
    account('Wallet', [{'asset': 'BTC', 'quantity': 0.5}, {'asset': 'USDC', 'quantity': 100}]),
    account('ISA', [{'asset': 'VWRL', 'quantity': 1, 'value': 500, 'currency': 'GBP'}, {'asset': 'GBP', 'quantity': 20}],
            category='investments'),
    account('Bank', [{'asset': 'GBP', 'quantity': 1000}], category='cash'),
  )
  asyncio.run(runner.run())

  s = reports.summary(store, config)
  assert s['categories'] == {'crypto': 25_000, 'cash': 1100, 'investments': 500}
  assert s['category_accounts']['cash'] == {'Bank': 1000, 'Wallet': 80, 'ISA': 20}
  assert next(a for a in s['accounts'] if a['name'] == 'Wallet')['category'] == 'crypto'  # accounts keep theirs

  h = reports.history(store, days=1)
  assert h['points'][-1]['values'] == {'crypto': 25_000, 'cash': 1100, 'investments': 500}
  assert reports.history(store, days=1, group_by='account')['points'][-1]['values']['Wallet'] == 25_080


def test_failed_account_is_carried_forward(setup):
  wallet = account('Wallet', [{'asset': 'BTC', 'quantity': 1}])
  config, store, runner = setup(wallet)
  asyncio.run(runner.run())

  wallet.params['fail'] = True
  asyncio.run(runner.run(force=True))

  s = reports.summary(store, config)
  assert s['total'] == 50_000
  assert s['accounts'][0]['last_error'] == 'RuntimeError: boom'


def test_only_due_accounts_are_fetched(setup):
  config, store, runner = setup(
    account('Fast', [{'asset': 'GBP', 'quantity': 1}], interval=15),
    account('Slow', [{'asset': 'GBP', 'quantity': 2}], interval=240),
  )
  asyncio.run(runner.run())
  assert sorted(calls) == ['Fast', 'Slow']

  # pretend the first run was 20 minutes ago
  earlier = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat(timespec='seconds')
  store.conn.execute('UPDATE account_status SET last_attempt = %s', (earlier,))
  calls.clear()
  asyncio.run(runner.run())

  assert calls == ['Fast']
  assert reports.summary(store, config)['total'] == 3  # Slow carried forward


def test_history_groups_by_category(setup):
  config, store, runner = setup(
    account('Wallet', [{'asset': 'BTC', 'quantity': 1}]),
    account('Bank', [{'asset': 'GBP', 'quantity': 5}], category='cash'),
  )
  asyncio.run(runner.run())
  asyncio.run(runner.run(force=True))

  h = reports.history(store, days=1)
  assert h['keys'] == ['crypto', 'cash']
  assert len(h['points']) == 2
  assert h['points'][-1]['total'] == 50_005


def test_config_env_interpolation(tmp_path, monkeypatch):
  monkeypatch.chdir(tmp_path)
  monkeypatch.setenv('SECRET', 'abc')
  path = tmp_path / 'accounts.yaml'
  path.write_text('accounts:\n  - {name: A, type: fake, category: c, params: {key: "${SECRET}", n: [1]}}\n')
  assert load_config(path).accounts[0].params == {'key': 'abc', 'n': [1]}

  # a missing var only breaks the account that uses it
  path.write_text('accounts:\n  - {name: A, type: fake, category: c, params: {key: "${MISSING_VAR}"}}\n'
                  '  - {name: B, type: fake, category: c, params: {key: "${SECRET}"}}\n')
  a, b = load_config(path).accounts
  assert 'MISSING_VAR' in a.error
  assert b.error is None
  with pytest.raises(ConfigError):
    asyncio.run(runner_module.fetch_account(a, Config([a], data_dir=tmp_path)))


def test_api_sends_decimal_amounts_as_json_numbers(setup):
  from fastapi.testclient import TestClient
  from networth.web.app import create_app
  config, store, runner = setup(account('Bank', [{'asset': 'GBP', 'quantity': '12.34'}], category='cash'))
  asyncio.run(runner.run())
  res = TestClient(create_app(config, run_scheduler=False)).get('/api/summary').json()
  assert res['total'] == 12.34 and res['accounts'][0]['holdings'][0]['quantity'] == 12.34
