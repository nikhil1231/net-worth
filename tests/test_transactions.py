from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from networth.config import AccountConfig, Config
from networth.connectors.monzo import Monzo
from networth.web import transactions as transactions_module
from networth.web.app import create_app


def tx(i, created):
  return {'id': f'tx_{i:03}', 'created': created, 'amount': -100 - i, 'currency': 'GBP',
          'merchant': {'name': 'Pret', 'address': {'latitude': 51.5, 'longitude': -0.1}},
          'category': 'eating_out', 'settled': '', 'account_id': 'acc_1'}


def setup(tmp_path, monkeypatch, pages):
  account = AccountConfig(name='Monzo', type='monzo', category='cash', interval=60, params={'client_id': 'x', 'client_secret': 'y'})
  config = Config(accounts=[account], data_dir=tmp_path)
  calls = []

  async def fake_token(self):
    return 'token'

  async def fake_get_json(url, params=None, headers=None):
    calls.append((url, params))
    if url.endswith('/accounts'):
      return {'accounts': [{'id': 'acc_1', 'type': 'uk_retail'}, {'id': 'acc_2', 'type': 'uk_retail', 'closed': True}]}
    return {'transactions': pages.pop(0)}

  monkeypatch.setattr(Monzo, '_access_token', fake_token)
  monkeypatch.setattr(transactions_module.http, 'get_json', fake_get_json)
  return TestClient(create_app(config, run_scheduler=False)), calls


def test_pages_through_monzo_from_since(tmp_path, monkeypatch):
  first = [tx(i, '2026-10-10T12:00:00Z') for i in range(100)]
  client, calls = setup(tmp_path, monkeypatch, [first, [tx(100, '2026-10-11T12:00:00Z')]])
  since = (datetime.now(timezone.utc) - timedelta(days=3)).strftime('%Y-%m-%dT%H:%M:%SZ')
  body = client.get('/api/transactions', params={'since': since}).json()
  assert len(body['transactions']) == 101
  tx_calls = [p for u, p in calls if u.endswith('/transactions')]
  assert tx_calls[0]['since'] == since and tx_calls[0]['account_id'] == 'acc_1'
  assert tx_calls[1]['since'] == 'tx_099'   # the next page continues after the last id
  assert body['transactions'][0]['merchant']['address']['latitude'] == 51.5


def test_since_is_clamped_to_what_monzo_serves(tmp_path, monkeypatch):
  client, calls = setup(tmp_path, monkeypatch, [[]])
  body = client.get('/api/transactions', params={'since': '2015-01-01T00:00:00Z'}).json()
  start = datetime.fromisoformat(body['since'])
  assert datetime.now(timezone.utc) - start < timedelta(days=90)


def test_no_monzo_account_is_not_a_404(tmp_path):
  client = TestClient(create_app(Config(accounts=[], data_dir=tmp_path), run_scheduler=False))
  assert client.get('/api/transactions').status_code == 503
