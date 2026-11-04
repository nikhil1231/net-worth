import asyncio

import pytest
from fastapi.testclient import TestClient

from networth import lunchflow, spending
from networth.config import AccountConfig, Config
from networth.store import Store
from networth.web.app import create_app


@pytest.fixture
def setup(tmp_path, monkeypatch):
  monkeypatch.delenv('LUNCHFLOW_API_KEY', raising=False)
  config = Config([AccountConfig('Santander', 'manual', 'cash', 15),
                   AccountConfig('Monzo', 'monzo', 'cash', 15)], data_dir=tmp_path)
  store = Store(config.db_path)
  calls, records, failures = [], {}, set()
  async def get(url, params=None, headers=None):
    calls.append((url, params, headers))
    if url.endswith('/accounts'):
      return {'accounts': [dict(id=1, name='Current account', institution_name='Santander', currency='GBP', status='ACTIVE'),
                           dict(id=2, name='Gold', institution_name='American Express', currency='GBP', status='ACTIVE'),
                           dict(id=3, name='Euro', currency='EUR', status='ACTIVE')]}
    account_id = int(url.split('/')[-2])
    if account_id in failures:
      raise RuntimeError('secret-key: private bank response')
    return {'transactions': records.get(account_id, []), 'total': len(records.get(account_id, []))}
  monkeypatch.setattr(lunchflow.http, 'get_json', get)
  yield store, config, calls, records, failures
  store.conn.close()


def mapping(id='1', account='Santander', start_date=None):
  return dict(id=id, account=account, start_date=start_date)


def transaction(id='purchase', account_id=1, **values):
  return dict(id=id, accountId=account_id, date='2026-10-01', amount=-12.34,
              currency='GBP', merchant='Shop', description='Shop London', isPending=False) | values


def configure(setup, mappings=None):
  store, config, *_ = setup
  lunchflow.env_path(config).write_text('LUNCHFLOW_API_KEY=secret-key\n')
  return asyncio.run(lunchflow.configure(store, config, mappings if mappings is not None else [mapping(), mapping('2', 'American Express')]))


def test_report_checks_remote_connections_and_keeps_month_and_history_separate(setup, monkeypatch):
  store, config, _, records, _ = setup
  configure(setup)
  records[1] = [transaction(), transaction('november', date='2026-11-02')]
  records[2] = [transaction('card', account_id=2)]
  asyncio.run(lunchflow.sync(store, config))
  client = TestClient(create_app(config, run_scheduler=False))
  result = client.get('/api/spending?month=2026-11').json()
  accounts = {a['name']: a for a in result['accounts']}
  assert len(result['transactions']) == 1
  assert accounts['Santander']['count'] == 2
  assert accounts['American Express']['connection_status'] == 'connected'
  assert accounts['American Express']['institution'] == 'American Express'

  async def discover(key):
    return [dict(id='1', status='INACTIVE', currency='GBP')]
  monkeypatch.setattr(lunchflow, 'discover', discover)
  result = client.get('/api/spending?month=2026-10&account=Santander').json()
  accounts = {a['name']: a for a in result['accounts']}
  assert accounts['Santander']['connection_status'] == 'unavailable'
  assert 'inactive' in accounts['Santander']['connection_detail']
  assert accounts['American Express']['connection_status'] == 'unavailable'
  assert 'missing' in accounts['American Express']['connection_detail']
  assert accounts['American Express']['count'] == 1
  assert len(spending.transactions(store)) == 3


def test_report_cannot_show_connected_when_remote_check_fails(setup, monkeypatch):
  store, config, *_ = setup
  configure(setup)
  asyncio.run(lunchflow.sync(store, config))
  async def discover(key):
    raise lunchflow.LunchFlowError('Lunch Flow denied access.')
  monkeypatch.setattr(lunchflow, 'discover', discover)
  result = TestClient(create_app(config, run_scheduler=False)).get('/api/spending?month=2026-11').json()
  account = next(a for a in result['accounts'] if a['name'] == 'Santander')
  assert account['connection_status'] == 'unverified'
  assert account['connection_detail'] == 'Lunch Flow denied access.'
  assert account['last_success']


def test_report_surfaces_paused_failed_and_stale_syncs(setup):
  store, config, _, _, failures = setup
  configure(setup)
  asyncio.run(lunchflow.sync(store, config))
  failures.add(1)
  asyncio.run(lunchflow.sync(store, config))
  with store.conn:
    store.conn.execute("UPDATE spending_status SET last_success='2020-01-01T00:00:00+00:00' WHERE account='American Express'")
  accounts = {a['name']: a for a in spending.report(store, config, '2026-11')['accounts']}
  assert accounts['Santander']['connection_status'] == 'error'
  assert accounts['American Express']['connection_status'] == 'stale'
  asyncio.run(lunchflow.configure(store, config, []))
  accounts = spending.report(store, config, '2026-11')['accounts']
  assert all(a['connection_status'] == 'paused' for a in accounts if a['type'] == 'lunchflow')


def test_setup_discovery_secret_storage_and_spending_only_accounts(setup):
  store, config, calls, records, _ = setup
  client = TestClient(create_app(config, run_scheduler=False))
  assert not client.get('/api/spending/lunchflow').json()['configured']
  lunchflow.env_path(config).write_text('LUNCHFLOW_API_KEY=secret-key\n')
  found = client.post('/api/spending/lunchflow/accounts').json()
  assert found[1]['institution'] == 'American Express'
  response = client.put('/api/spending/lunchflow', json=dict(mappings=[mapping(), mapping('2', 'American Express')]))
  assert response.status_code == 200 and response.json()['configured']
  assert 'secret-key' not in response.text
  assert not (config.data_dir / 'lunchflow.key').exists()
  assert lunchflow.env_path(config).read_text() == 'LUNCHFLOW_API_KEY=secret-key\n'
  records[2] = [transaction(account_id=2)]
  assert client.post('/api/spending/sync').status_code == 200
  report = client.get('/api/spending?month=2026-10&account=American%20Express').json()
  assert report['summary']['spent'] == 12.34
  assert report['transactions'][0]['account'] == 'American Express'
  assert len(config.accounts) == 2
  assert store.conn.execute('SELECT COUNT(*) FROM snapshots').fetchone()[0] == 0
  assert calls[-1][2] == {'x-api-key': 'secret-key'}
  assert [call for call in calls if call[0].endswith('/transactions')][-1][1] == {'include_pending': 'true'}


def test_repeated_sync_settlement_and_user_corrections(setup):
  store, config, _, records, _ = setup
  configure(setup)
  records[1] = [transaction(isPending=True)]
  asyncio.run(lunchflow.sync(store, config))
  [row] = spending.transactions(store)
  assert (row['pending'], row['amount']) == (1, -1234)
  spending.edit_transaction(store, row['id'], category='Groceries', kind='transfer')
  records[1] = [transaction(amount=-13.45)]
  asyncio.run(lunchflow.sync(store, config)); asyncio.run(lunchflow.sync(store, config))
  [row] = spending.transactions(store)
  assert (row['pending'], row['amount'], row['category'], row['kind']) == (0, -1345, 'Groceries', 'transfer')
  records[1] = []
  asyncio.run(lunchflow.sync(store, config))
  assert len(spending.transactions(store)) == 1  # settled history survives upstream windows


def test_disappearing_pending_is_removed_only_for_its_bank(setup):
  store, config, _, records, _ = setup
  configure(setup)
  records[1] = [transaction(isPending=True)]
  records[2] = [transaction(account_id=2, isPending=True)]
  asyncio.run(lunchflow.sync(store, config))
  records[1] = [transaction(id='settled')]
  asyncio.run(lunchflow.sync(store, config))
  rows = spending.transactions(store)
  assert len(rows) == 2 and sum(r['pending'] for r in rows) == 1


def test_failure_isolated_and_private_history_retained(setup):
  store, config, _, records, failures = setup
  configure(setup)
  records[1] = [transaction()]
  asyncio.run(lunchflow.sync(store, config))
  failures.add(1)
  records[2] = [transaction(account_id=2)]
  result = asyncio.run(lunchflow.sync(store, config))
  assert result[0]['error'] and result[1]['count'] == 1
  assert 'secret-key' not in str(result)
  assert len(spending.transactions(store)) == 2
  status = store.conn.execute("SELECT * FROM spending_status WHERE account='Santander'").fetchone()
  assert status['last_success'] and status['last_error']


def test_csv_cutoff_and_block_further_csv_imports(setup):
  store, config, calls, records, _ = setup
  rows = spending.parse_csv('Date,Description,Amount\n2026-10-01,Shop,-12.34\n', 'Santander', dict(date='Date', description='Description', amount='Amount'))
  spending.save_transactions(store, rows)
  assert lunchflow.state(store, config)['choices'][0]['start_date'] == '2026-10-02'
  with pytest.raises(lunchflow.LunchFlowError, match='statement imports'):
    configure(setup, [mapping()])
  configure(setup, [mapping(start_date='2026-10-02')])
  records[1] = [transaction(), transaction(id='new', date='2026-10-02')]
  asyncio.run(lunchflow.sync(store, config))
  assert len(spending.transactions(store)) == 2
  assert calls[-1][1]['from'] == '2026-10-02'
  client = TestClient(create_app(config, run_scheduler=False))
  assert client.post('/api/spending/import', json=dict(account='Santander', text='', mapping={})).status_code == 400


@pytest.mark.parametrize('mappings', [
  [mapping(), mapping('2', 'Santander')], [mapping('3')], [mapping(account='Monzo')],
  [mapping(start_date='invalid')], [mapping(account='santander')], [mapping('999')],
])
def test_invalid_bindings_do_not_save_key_or_mapping(setup, mappings):
  store, config, *_ = setup
  with pytest.raises(lunchflow.LunchFlowError):
    configure(setup, mappings)
  assert not (config.data_dir / 'lunchflow.key').exists()
  assert not lunchflow.state(store, config)['bindings']


def test_pausing_retains_history_and_rename_keeps_remote_identity(setup):
  store, config, calls, records, _ = setup
  configure(setup, [mapping()])
  records[1] = [transaction()]
  asyncio.run(lunchflow.sync(store, config))
  tid = spending.transactions(store)[0]['id']
  store.rename_account('Santander', 'Main bank')
  config.accounts[0].name = 'Main bank'
  asyncio.run(lunchflow.sync(store, config))
  assert spending.transactions(store)[0]['id'] == tid
  assert spending.transactions(store)[0]['account'] == 'Main bank'
  configure(setup, [])
  assert asyncio.run(lunchflow.sync(store, config)) == []
  report = spending.report(store, config, '2026-10')
  assert report['summary']['spent'] == 12.34
  assert not next(a for a in report['accounts'] if a['name'] == 'Main bank')['sync_enabled']


def test_hourly_sync_throttling_and_manual_override(setup):
  store, config, calls, records, _ = setup
  configure(setup, [mapping()])
  asyncio.run(lunchflow.sync(store, config, due_only=True))
  count = len(calls)
  assert asyncio.run(lunchflow.sync(store, config, due_only=True)) == []
  assert len(calls) == count
  asyncio.run(lunchflow.sync(store, config))
  assert len(calls) == count + 1


def test_null_ids_preserve_identical_payments_and_are_stable(setup):
  store, config, _, records, _ = setup
  configure(setup, [mapping()])
  records[1] = [transaction(id=None), transaction(id=None)]
  asyncio.run(lunchflow.sync(store, config)); asyncio.run(lunchflow.sync(store, config))
  rows = spending.transactions(store)
  assert len(rows) == 2 and rows[0]['id'] != rows[1]['id']


@pytest.mark.parametrize('bad', [dict(amount='NaN'), dict(currency='EUR'), dict(accountId=2), dict(date='broken'), dict(isPending='false'), dict(amount=None)])
def test_malformed_response_does_not_remove_pending_or_write_partial_rows(setup, bad):
  store, config, _, records, _ = setup
  configure(setup, [mapping()])
  records[1] = [transaction(isPending=True)]
  asyncio.run(lunchflow.sync(store, config))
  records[1] = [transaction(id='valid'), transaction(id='invalid', **bad)]
  assert asyncio.run(lunchflow.sync(store, config))[0]['error']
  [row] = spending.transactions(store)
  assert row['pending']


def test_csv_handover_keeps_recurring_rules_and_one_commitment(setup):
  store, config, _, records, _ = setup
  rows = spending.parse_csv('Date,Description,Amount\n2026-09-01,Gym,-35.00\n', 'Santander', dict(date='Date', description='Description', amount='Amount'))
  spending.save_transactions(store, rows)
  spending.edit_transaction(store, rows[0]['id'], recurring_type='subscription')
  configure(setup, [mapping(start_date='2026-09-02')])
  records[1] = [transaction(merchant='Gym', amount=-35)]
  asyncio.run(lunchflow.sync(store, config))
  actual = spending.transactions(store)
  assert {r['bank_account'] for r in actual} == {'Santander'}
  assert {r['recurring_type'] for r in actual} == {'subscription'}
  report = spending.report(store, config, '2026-10')
  assert len(report['recurring']) == 1
  assert report['summary']['committed'] == 35
  # Stable transaction IDs and monthly rules also survive an app account rename.
  store.rename_account('Santander', 'Main bank')
  config.accounts[0].name = 'Main bank'
  asyncio.run(lunchflow.sync(store, config))
  assert len(spending.transactions(store)) == 2
  assert spending.report(store, config, '2026-10')['summary']['committed'] == 35


def test_incomplete_upstream_response_retains_pending(setup, monkeypatch):
  store, config, _, records, _ = setup
  configure(setup, [mapping()])
  records[1] = [transaction(isPending=True)]
  asyncio.run(lunchflow.sync(store, config))
  async def incomplete(*args, **kwargs):
    return {'transactions': [], 'total': 1}
  monkeypatch.setattr(lunchflow, 'get', incomplete)
  result = asyncio.run(lunchflow.sync(store, config))
  assert 'incomplete history' in result[0]['error']
  assert spending.transactions(store)[0]['pending']


def test_env_token_changes_are_picked_up_without_restart(setup):
  store, config, *_ = setup
  path = lunchflow.env_path(config)
  path.write_text('OTHER_SETTING=keep\nLUNCHFLOW_API_KEY=first\n')
  assert lunchflow.api_key(config) == 'first'
  path.write_text('OTHER_SETTING=keep\nLUNCHFLOW_API_KEY=second\n')
  assert lunchflow.api_key(config) == 'second'
  assert 'second' not in str(lunchflow.state(store, config))
  assert path.read_text().startswith('OTHER_SETTING=keep\n')


def test_process_env_and_missing_key(setup, monkeypatch):
  _, config, *_ = setup
  assert lunchflow.api_key(config) == ''
  with pytest.raises(lunchflow.LunchFlowError, match='LUNCHFLOW_API_KEY'):
    asyncio.run(lunchflow.discover(lunchflow.api_key(config)))
  monkeypatch.setenv('LUNCHFLOW_API_KEY', 'process-key')
  assert lunchflow.api_key(config) == 'process-key'


def test_discovery_handles_live_accounts_without_currency(setup, monkeypatch):
  store, config, *_ = setup
  async def get(url, params=None, headers=None):
    if url.endswith('/accounts'):
      return {'accounts': [dict(id=1, name='Current account', institution_name='Santander Personal', status='ACTIVE')], 'total': 1}
    return {'transactions': [transaction()], 'total': 1}
  monkeypatch.setattr(lunchflow.http, 'get_json', get)
  configure(setup, [mapping()])
  [account] = asyncio.run(lunchflow.discover(lunchflow.api_key(config)))
  assert account['currency'] == ''
  result = asyncio.run(lunchflow.sync(store, config))
  assert result[0]['error'] is None
  assert spending.transactions(store)[0]['amount'] == -1234


def test_balance_connector_keeps_lunchflow_sign(tmp_path, monkeypatch):
  from networth.connectors import get_connector_class
  monkeypatch.setenv('LUNCHFLOW_API_KEY', 'env-key')
  calls = []
  async def get(url, params=None, headers=None):
    calls.append((url, headers))
    return {'balance': {'amount': -91.94, 'currency': 'GBP'}}
  monkeypatch.setattr(lunchflow.http, 'get_json', get)
  card = get_connector_class('lunchflow')(AccountConfig('Amex', 'lunchflow', 'liabilities', 60, {'account_id': 42}), tmp_path)
  [holding] = asyncio.run(card.fetch())
  assert (holding.asset, holding.quantity) == ('GBP', -91.94)
  assert calls == [(lunchflow.BASE_URL + '/accounts/42/balance', {'x-api-key': 'env-key'})]


def test_grouped_balance_connector_names_each_card(tmp_path, monkeypatch):
  from networth.connectors import get_connector_class
  monkeypatch.setenv('LUNCHFLOW_API_KEY', 'env-key')
  calls = []
  async def get(url, params=None, headers=None):
    calls.append((url, headers))
    if url.endswith('/accounts'):
      return {'accounts': [dict(id=1, name='British Airways Amex'), dict(id=2, name='Platinum Cashback Amex')]}
    amounts = {'1': -120.5, '2': -80.25}
    return {'balance': {'amount': amounts[url.split('/')[-2]], 'currency': 'GBP'}}
  monkeypatch.setattr(lunchflow.http, 'get_json', get)
  cards = get_connector_class('lunchflow')(AccountConfig('Amex', 'lunchflow', 'liabilities', 60, {'account_ids': [1, 2]}), tmp_path)
  holdings = asyncio.run(cards.fetch())
  assert [(h.name, h.asset, h.quantity) for h in holdings] == [
    ('British Airways Amex', 'GBP', -120.5), ('Platinum Cashback Amex', 'GBP', -80.25)]
  assert calls == [
    (lunchflow.BASE_URL + '/accounts', {'x-api-key': 'env-key'}),
    (lunchflow.BASE_URL + '/accounts/1/balance', {'x-api-key': 'env-key'}),
    (lunchflow.BASE_URL + '/accounts/2/balance', {'x-api-key': 'env-key'}),
  ]
