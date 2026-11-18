import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from networth import reports, runner as runner_module
from networth.config import AccountConfig, Config, ConfigError, load_config
from networth.connectors import Connector, connector
from networth.models import Holding
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
  assert PRICES.value(Holding('BTC', 2)) == pytest.approx((50_000, 100_000))
  assert PRICES.value(Holding('GBP', 10)) == (1, 10)
  # source-provided value in another currency is converted, not re-priced
  assert PRICES.value(Holding('VWRL', 4, value=100, currency='USD')) == pytest.approx((20, 80))
  assert PRICES.value(Holding('NOPE', 1)) == (None, None)


def test_run_values_and_summary(setup):
  config, store, runner = setup(
    account('Wallet', [{'asset': 'BTC', 'quantity': 0.5}]),
    account('Bank', [{'asset': 'GBP', 'quantity': 1000}], category='cash'),
  )
  asyncio.run(runner.run())

  s = reports.summary(store, config)
  assert s['total'] == pytest.approx(26_000)
  assert s['categories'] == pytest.approx({'crypto': 25_000, 'cash': 1000})


def test_cash_like_assets_count_as_cash_wherever_they_are(setup):
  config, store, runner = setup(
    account('Wallet', [{'asset': 'BTC', 'quantity': 0.5}, {'asset': 'USDC', 'quantity': 100}]),
    account('ISA', [{'asset': 'VWRL', 'quantity': 1, 'value': 500, 'currency': 'GBP'}, {'asset': 'GBP', 'quantity': 20}],
            category='investments'),
    account('Bank', [{'asset': 'GBP', 'quantity': 1000}], category='cash'),
  )
  asyncio.run(runner.run())

  s = reports.summary(store, config)
  assert s['categories'] == pytest.approx({'crypto': 25_000, 'cash': 1100, 'investments': 500})
  assert s['category_accounts']['cash'] == pytest.approx({'Bank': 1000, 'Wallet': 80, 'ISA': 20})
  assert next(a for a in s['accounts'] if a['name'] == 'Wallet')['category'] == 'crypto'  # accounts keep theirs

  h = reports.history(store, days=1)
  assert h['points'][-1]['values'] == pytest.approx({'crypto': 25_000, 'cash': 1100, 'investments': 500})
  assert reports.history(store, days=1, group_by='account')['points'][-1]['values']['Wallet'] == pytest.approx(25_080)


def test_failed_account_is_carried_forward(setup):
  wallet = account('Wallet', [{'asset': 'BTC', 'quantity': 1}])
  config, store, runner = setup(wallet)
  asyncio.run(runner.run())

  wallet.params['fail'] = True
  asyncio.run(runner.run(force=True))

  s = reports.summary(store, config)
  assert s['total'] == pytest.approx(50_000)
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
  store.conn.execute('UPDATE account_status SET last_attempt = ?', (earlier,))
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
  assert h['points'][-1]['total'] == pytest.approx(50_005)


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
