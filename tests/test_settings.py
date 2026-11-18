import pytest
from fastapi.testclient import TestClient

from networth.config import load_config
from networth.settings import SECRET_MASK
from networth.store import SnapshotRow, Store
from networth.models import Holding
from networth.web.app import create_app

CONFIG = """\
settings:
  tick_minutes: 15
  data_dir: {data_dir}

accounts:
  - name: Binance
    type: exchange
    category: crypto
    params:
      exchange: binance
      api_key: ${{TEST_BINANCE_KEY}}
      secret: hunter2   # pasted straight in
      # wallets: [spot, funding]

  - name: BTC cold wallet
    type: bitcoin
    category: crypto
    interval: 60
    params:
      addresses: [bc1qaaa]
"""


@pytest.fixture
def env(tmp_path, monkeypatch):
  monkeypatch.setenv('TEST_BINANCE_KEY', 'key')
  path = tmp_path / 'accounts.yaml'
  path.write_text(CONFIG.format(data_dir=tmp_path / 'data'))
  config = load_config(path)
  client = TestClient(create_app(config, run_scheduler=False))
  return path, config, client


def account(payload, name):
  return next(a for a in payload['accounts'] if a['name'] == name)


def test_read_masks_literal_secrets_only(env):
  _, _, client = env
  res = client.get('/api/config').json()
  binance = account(res, 'Binance')
  assert binance['params']['api_key'] == '${TEST_BINANCE_KEY}'
  assert binance['params']['secret'] == SECRET_MASK
  assert 'hunter2' not in str(res)
  assert account(res, 'BTC cold wallet')['interval'] == 60
  assert res['settings'] == {'tick_minutes': 15, 'default_interval': 15}
  assert res['writable'] is True
  assert {f['key'] for f in res['connectors']['bitcoin']['fields']} == {'addresses'}


def test_add_account_keeps_comments_and_reloads(env):
  path, config, client = env
  res = client.post('/api/config/accounts', json={
    'name': 'ETH wallet', 'type': 'evm', 'category': 'crypto', 'interval': None,
    'params': {'addresses': ['0xabc']},
  })
  assert res.status_code == 200, res.text
  assert account(res.json(), 'ETH wallet')['params'] == {'addresses': ['0xabc']}
  assert [a.name for a in config.accounts] == ['Binance', 'BTC cold wallet', 'ETH wallet']

  text = path.read_text()
  assert '# pasted straight in' in text and '# wallets: [spot, funding]' in text
  assert text.endswith("""\
      addresses: [bc1qaaa]

  - name: ETH wallet
    type: evm
    category: crypto
    params:
      addresses:
        - '0xabc'
""")
  assert (config.data_dir / 'accounts.yaml.prev').read_text() == CONFIG.format(data_dir=config.data_dir)


def test_edit_keeps_masked_secret_and_untouched_lines(env):
  path, config, client = env
  before = path.read_text()
  current = account(client.get('/api/config').json(), 'Binance')
  res = client.put('/api/config/accounts/Binance', json=current | {
    'params': current['params'] | {'wallets': ['spot', 'funding']},
  })
  assert res.status_code == 200, res.text
  assert config.account('Binance').params['secret'] == 'hunter2'
  assert config.account('Binance').params['wallets'] == ['spot', 'funding']
  # only the new key is added; the secret line and its comment are untouched
  assert path.read_text().replace('      wallets:\n        - spot\n        - funding\n', '') == before


def test_rename_moves_history(env):
  path, config, client = env
  store = Store(config.db_url)
  store.write_run('2026-01-01T00:00:00+00:00', [
    SnapshotRow('BTC cold wallet', 'crypto', Holding('BTC', 1), 50_000, 50_000, '2026-01-01T00:00:00+00:00')])
  store.record_attempt('BTC cold wallet', '2026-01-01T00:00:00+00:00')
  (config.data_dir / 'btc_cold_wallet.cookies.json').write_text('{}')

  current = account(client.get('/api/config').json(), 'BTC cold wallet')
  res = client.put('/api/config/accounts/BTC cold wallet', json=current | {'name': 'Ledger'})
  assert res.status_code == 200, res.text
  assert store.last_holdings('Ledger')[0] == [Holding('BTC', 1)]
  assert store.get_status('Ledger') is not None
  assert (config.data_dir / 'ledger.cookies.json').exists()
  assert '- name: Ledger' in path.read_text()


@pytest.mark.parametrize('payload, error', [
  ({'name': 'Binance', 'type': 'bitcoin', 'category': 'crypto', 'params': {'addresses': ['x']}}, 'already an account'),
  ({'name': 'New', 'type': 'bitcoin', 'category': 'crypto', 'params': {}}, 'Addresses is required'),
  ({'name': 'New', 'type': 'nope', 'category': 'crypto'}, 'Unknown connector type'),
  ({'name': 'New', 'type': 'bitcoin', 'category': 'crypto', 'interval': 0, 'params': {'addresses': ['x']}}, 'Interval'),
  ({'name': 'New', 'type': 'exchange', 'category': 'crypto',
    'params': {'exchange': 'kraken', 'api_key': 'k', 'secret': SECRET_MASK}}, 'Enter a value for API secret'),
])
def test_invalid_accounts_are_rejected(env, payload, error):
  path, _, client = env
  before = path.read_text()
  res = client.post('/api/config/accounts', json=payload)
  assert res.status_code == 400 and error in res.json()['detail']
  assert path.read_text() == before


def test_delete_account_and_settings(env):
  path, config, client = env
  assert client.delete('/api/config/accounts/Binance').status_code == 200
  assert [a.name for a in config.accounts] == ['BTC cold wallet']
  assert client.delete('/api/config/accounts/Binance').status_code == 400

  res = client.put('/api/config/settings', json={'tick_minutes': 5, 'default_interval': 30})
  assert res.json()['settings'] == {'tick_minutes': 5, 'default_interval': 30}
  assert config.tick_minutes == 5
  assert f'data_dir: {config.data_dir}' in path.read_text()


def test_read_only_config(env):
  path, _, client = env
  path.chmod(0o444)
  try:
    assert client.get('/api/config').json()['writable'] is False
    res = client.put('/api/config/settings', json={'tick_minutes': 5, 'default_interval': 30})
    assert res.status_code == 409
  finally:
    path.chmod(0o644)
