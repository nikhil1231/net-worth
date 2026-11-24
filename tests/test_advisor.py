import asyncio
import fcntl
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from networth import advisor, spending
from networth.config import AccountConfig, Config
from networth.models import Holding
from networth.store import SnapshotRow, Store
from networth.web.app import create_app

NOW = datetime(2026, 10, 18, 12, tzinfo=timezone.utc)


@pytest.fixture
def setup(tmp_path, monkeypatch):
  monkeypatch.delenv('OPENROUTER_API_KEY', raising=False)
  config = Config([
    AccountConfig('Bank', 'monzo', 'cash', 60, {'secret': 'secret-config-value'}),
    AccountConfig('ISA', 'hl', 'investments', 60),
    AccountConfig('Wallet', 'solana', 'crypto', 60),
  ], data_dir=tmp_path)
  store = Store(config.db_url)
  advisor.initial(store)
  yield config, store
  store.conn.close()


def snapshot(store, ts, bank=1000, units=10, price=10, wallet=0):
  stamp = advisor.stamp(ts)
  rows = [SnapshotRow('Bank', 'cash', Holding('GBP', bank), 1, bank, stamp),
          SnapshotRow('ISA', 'investments', Holding('FUND', units, name='A fund'), price, units*price, stamp),
          SnapshotRow('Wallet', 'crypto', Holding('USDC', wallet, wallet='private-wallet-address', chain='solana'), .8, wallet*.8, stamp)]
  for name in ('Bank', 'ISA', 'Wallet'):
    store.record_attempt(name, stamp)
  return store.write_run(stamp, rows)


def payment(store, ident, day, amount, kind='expense', pending=False):
  spending.save_transactions(store, [dict(id=ident, account='Bank', bank_account='private-bank-id', date=str(day),
    merchant='Shop', description='private-description', amount=amount, kind=kind,
    pending=pending, category='Shopping', source='csv')])
  store.conn.execute('UPDATE transactions SET kind_override=%s WHERE id=%s', (kind, ident))


def test_value_change_reconciles_without_claiming_returns(setup):
  config, store = setup
  snapshot(store, NOW-timedelta(days=7), units=10, price=10)
  snapshot(store, NOW, units=12, price=12)
  payload, checks = advisor.build_review(store, config, advisor.Settings(), NOW)
  facts = payload['evidence']['value-change']['facts']
  assert facts['value_change_gbp'] == 44
  assert facts['matched_price_and_fx_effect_gbp'] == 20
  assert facts['matched_quantity_effect_gbp'] == 24
  assert facts['other_position_and_coverage_change_gbp'] == 0
  assert 'not a return calculation' in facts['note']
  raw = advisor.encode(payload)
  assert 'private-wallet-address' not in raw
  assert 'secret-config-value' not in raw


def test_new_unpriced_and_removed_positions_stay_explicit(setup):
  config, store = setup
  snapshot(store, NOW-timedelta(days=7), bank=1000)
  run = snapshot(store, NOW, bank=1200)
  with store.conn:
    store.conn.execute("UPDATE snapshots SET asset='NEW', value_gbp=NULL, price_gbp=NULL WHERE run_id=%s AND account='ISA'", (run,))
  payload, checks = advisor.build_review(store, config, advisor.Settings(), NOW)
  f = payload['evidence']['value-change']['facts']
  assert f['value_change_gbp'] == 100
  assert f['matched_quantity_effect_gbp'] == 200
  assert f['other_position_and_coverage_change_gbp'] == -100
  assert any(c['topic'].startswith('unpriced-') for c in checks)


def test_removed_account_history_does_not_fake_a_loss(setup):
  config, store = setup
  snapshot(store, NOW-timedelta(days=7), wallet=1000)
  snapshot(store, NOW, wallet=0)
  config.accounts = [a for a in config.accounts if a.name != 'Wallet']
  payload, _ = advisor.build_review(store, config, advisor.Settings(), NOW)
  assert payload['evidence']['value-change']['facts']['value_change_gbp'] == 0


def test_cash_requires_selection_and_does_not_count_stablecoins(setup):
  config, store = setup
  snapshot(store, NOW, bank=500, wallet=100000)
  s = advisor.Settings(cash_buffer_gbp=1000)
  _, checks = advisor.build_review(store, config, s, NOW)
  assert any(c['topic'] == 'cash-buffer-setup' for c in checks)
  s.cash_accounts = ['Bank', 'Wallet']
  payload, checks = advisor.build_review(store, config, s, NOW)
  assert payload['evidence']['cash-buffer']['facts']['recorded_gbp'] == 500
  assert any(c['topic'] == 'cash-buffer-below-target' for c in checks)


def test_manual_and_stale_balances_do_not_get_confident_cash_alerts(setup):
  config, store = setup
  snapshot(store, NOW-timedelta(days=3), bank=500)
  config.accounts[0].type = 'manual'
  payload, checks = advisor.build_review(store, config, advisor.Settings(cash_buffer_gbp=1000, cash_accounts=['Bank']), NOW)
  assert not payload['evidence']['cash-buffer']['facts']['reliable']
  finding = next(c for c in checks if c['topic'] == 'cash-buffer-below-target')
  assert finding['priority'] == 'review' and finding['caveats']
  assert any(c['topic'].startswith('coverage-') for c in checks)


def test_spending_respects_pending_refunds_transfers_and_excludes_private_records(setup):
  config, store = setup
  day = NOW.date()-timedelta(days=1)
  for ident, value, kind, pending in [('e',-10000,'expense',False),('r',2000,'refund',False),
      ('p',-90000,'expense',True),('t',-30000,'transfer',False),('i',50000,'income',False)]:
    payment(store, ident, day, value, kind, pending)
  payload, checks = advisor.build_review(store, config, advisor.Settings(), NOW)
  facts = payload['evidence']['spending']['facts']
  assert facts['spent_gbp'] == 100 and facts['refunds_gbp'] == 20
  assert facts['net_spent_gbp'] == 80 and facts['income_gbp'] == 500
  assert facts['pending_count'] == 1
  assert not facts['comparison_coverage']
  assert not any(c['topic'] == 'spending-above-baseline' for c in checks)
  assert 'private-description' not in advisor.encode(payload)
  assert 'private-bank-id' not in advisor.encode(payload)


def test_complete_comparison_flags_material_spending_change(setup):
  config, store = setup
  config.accounts = config.accounts[:1]
  day = NOW.date()-timedelta(days=1)
  for i in range(35):
    payment(store, str(i), day-timedelta(days=i), -1000 if i>=7 else -10000)
  with store.conn:
    store.conn.execute('INSERT INTO spending_status(account,last_success) VALUES (%s,%s)', ('Bank',advisor.stamp(NOW)))
  payload, checks = advisor.build_review(store, config, advisor.Settings(), NOW)
  assert payload['evidence']['spending']['facts']['comparison_coverage']
  assert any(c['topic'] == 'spending-above-baseline' for c in checks)


def test_cached_exposure_keeps_unknown_coverage_and_skips_stale_cache(setup):
  config, store = setup
  snapshot(store, NOW)
  store.set_classification('FUND', dict(countries={'UK':.5}, sectors={'Energy':.4}, fetched_at=advisor.stamp(NOW)))
  payload, _ = advisor.build_review(store, config, advisor.Settings(), NOW)
  facts = payload['evidence']['investment-exposure']['facts']
  assert facts['country_gbp'] == {'UK':50} and facts['sector_gbp'] == {'Energy':40}
  store.set_classification('FUND', dict(countries={'UK':1}, fetched_at=advisor.stamp(NOW-timedelta(days=9))))
  payload, _ = advisor.build_review(store, config, advisor.Settings(), NOW)
  assert payload['evidence']['investment-exposure']['facts']['classified_value_gbp'] == 0


def test_schedule_manual_run_dst_and_settings_persistence(setup):
  config, store = setup
  s = advisor.Settings()
  assert advisor.next_run(s, NOW) == '2026-10-19T08:00:00+00:00'
  s.cadence, s.local_time = 'daily', '01:30'
  assert advisor.next_run(s, datetime(2026,10,25,0,35,tzinfo=timezone.utc)) == '2026-10-26T01:30:00+00:00'
  assert advisor.next_run(s, datetime(2026,3,28,12,tzinfo=timezone.utc)) == '2026-03-29T01:30:00+00:00'
  advisor.save_settings(store, config, advisor.Settings(cadence='manual', goals='My goals'), NOW)
  assert store.conn.execute('SELECT next_run FROM advisor_settings').fetchone()[0] is None
  advisor.queue(store, now=NOW)
  assert advisor.settings(store).goals == 'My goals'
  assert store.conn.execute('SELECT next_run FROM advisor_settings').fetchone()[0] is None


def test_concurrent_enqueue_is_deduplicated(setup):
  config, store = setup
  others = [Store(config.db_url) for _ in range(2)]
  with ThreadPoolExecutor(2) as pool:
    ids = list(pool.map(lambda s: advisor.queue(s, now=NOW)['id'], others))
  assert ids[0] == ids[1]
  for s in others:
    s.conn.close()


def test_calculated_review_runs_without_key_and_remembers_feedback(setup):
  config, store = setup
  snapshot(store, NOW)
  first = advisor.queue(store, now=NOW)
  asyncio.run(advisor.tick(store, config, NOW))
  row = store.conn.execute('SELECT * FROM advisor_runs WHERE id=%s',(first['id'],)).fetchone()
  report = advisor.view_run(row, True)['report']
  assert row['status'] == 'completed' and report['mode'] == 'calculated'
  assert report['findings'][0]['evidence'][0]['snapshot']['facts']
  topic = report['findings'][0]['topic']
  with store.conn:
    store.conn.execute("UPDATE advisor_findings SET feedback='known',answer='Already reviewed' WHERE topic=%s",(topic,))
  advisor.queue(store, now=NOW)
  asyncio.run(advisor.tick(store, config, NOW))
  row = store.conn.execute('SELECT * FROM advisor_runs ORDER BY id DESC LIMIT 1').fetchone()
  assert next(f for f in json.loads(row['report'])['findings'] if f['topic']==topic)['feedback'] == 'known'
  assert 'Already reviewed' in row['payload']


def test_schedule_catches_up_once_and_restart_recovers(setup):
  config, store = setup
  with store.conn:
    store.conn.execute('UPDATE advisor_settings SET next_run=%s', (advisor.stamp(NOW-timedelta(days=15)),))
  asyncio.run(advisor.tick(store, config, NOW))
  asyncio.run(advisor.tick(store, config, NOW))
  assert store.conn.execute('SELECT COUNT(*) FROM advisor_runs').fetchone()[0] == 1
  assert store.conn.execute('SELECT next_run FROM advisor_settings').fetchone()[0] > advisor.stamp(NOW)
  run = advisor.queue(store, now=NOW)
  with store.conn:
    store.conn.execute("UPDATE advisor_runs SET status='running' WHERE id=%s",(run['id'],))
  asyncio.run(advisor.tick(store, config, NOW))
  assert store.conn.execute('SELECT status FROM advisor_runs WHERE id=%s',(run['id'],)).fetchone()[0] == 'failed'


def test_provider_uses_strict_schema_data_policy_and_validates_references(setup, monkeypatch):
  config, store = setup
  snapshot(store, NOW)
  payload, _ = advisor.build_review(store, config, advisor.Settings(), NOW)
  captured = {}
  class Response:
    status_code = 200
    def json(self):
      return dict(choices=[dict(finish_reason='stop',message=dict(content=advisor.encode(dict(summary='Review', findings=[]))))],usage=dict(cost=.002, total_tokens=100, extra='secret'))
  def post(*args, **kwargs):
    captured.update(kwargs)
    return Response()
  monkeypatch.setattr(advisor.requests, 'post', post)
  report, usage = advisor.request_report('private-key', advisor.Settings(), payload)
  assert report.summary == 'Review' and usage == {'cost':.002,'total_tokens':100}
  assert captured['json']['provider'] == dict(require_parameters=True,data_collection='deny',zdr=True)
  assert captured['json']['response_format']['json_schema']['strict']
  finding = dict(topic='invented',kind='question',priority='review',title='Question',observation='Observation',suggestion='',caveats='',evidence=[dict(ref='nonexistent',explanation='Invalid')])
  Response.json = lambda self: dict(choices=[dict(finish_reason='stop',message=dict(content=advisor.encode(dict(summary='Review',findings=[finding]))))])
  with pytest.raises(ValueError, match='unsupported evidence'):
    advisor.request_report('private-key', advisor.Settings(), payload)


def test_provider_failure_keeps_calculated_findings_and_never_persists_secrets(setup, monkeypatch):
  config, store = setup
  snapshot(store, NOW)
  monkeypatch.setenv('OPENROUTER_API_KEY', 'private-key')
  class Response:
    status_code = 401
    text = 'private-key and private-provider-body'
  monkeypatch.setattr(advisor.requests, 'post', lambda *args, **kw: Response())
  advisor.queue(store, now=NOW)
  asyncio.run(advisor.tick(store, config, NOW))
  row = dict(store.conn.execute('SELECT * FROM advisor_runs').fetchone())
  assert row['status'] == 'completed'
  report = json.loads(row['report'])
  assert report['findings'] and 'rejected the API key' in report['warning']
  assert 'private-key' not in advisor.encode(row) and 'private-provider-body' not in advisor.encode(row)


def test_empty_history_does_not_call_model_even_with_key(setup, monkeypatch):
  config, store = setup
  monkeypatch.setenv('OPENROUTER_API_KEY', 'private-key')
  monkeypatch.setattr(advisor, 'request_report', lambda *args: pytest.fail('Empty history should not trigger a paid request'))
  advisor.queue(store, now=NOW)
  asyncio.run(advisor.tick(store, config, NOW))
  assert store.conn.execute('SELECT status FROM advisor_runs').fetchone()[0] == 'completed'


def test_cross_process_lock_leaves_queued_review_untouched(setup):
  config, store = setup
  advisor.queue(store, now=NOW)
  with open(config.data_dir / 'advisor.lock', 'a') as lock:
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    asyncio.run(advisor.tick(store, config, NOW))
  assert store.conn.execute('SELECT status FROM advisor_runs').fetchone()[0] == 'queued'


def test_material_cash_change_returns_but_small_noise_stays_handled(setup):
  config, store = setup
  advisor.save_settings(store, config, advisor.Settings(cadence='manual', cash_buffer_gbp=1000, cash_accounts=['Bank']), NOW)
  def review(bank):
    snapshot(store, NOW, bank=bank)
    advisor.queue(store, now=NOW)
    asyncio.run(advisor.tick(store, config, NOW))
    return store.conn.execute("SELECT feedback FROM advisor_findings WHERE topic='cash-buffer-below-target'").fetchone()[0]
  assert review(450) == 'new'
  with store.conn:
    store.conn.execute("UPDATE advisor_findings SET feedback='known' WHERE topic='cash-buffer-below-target'")
  assert review(449) == 'known'
  assert review(200) == 'new'


def test_api_validation_history_feedback_and_queued_settings(setup):
  config, store = setup
  client = TestClient(create_app(config, run_scheduler=False))
  s = client.get('/api/advisor').json()['settings']['values']
  assert 'configured' not in s
  s['cash_accounts'] = ['Bank', 'Bank']
  assert client.put('/api/advisor/settings', json=s).status_code == 400
  s['cash_accounts'] = ['Bank']
  s['local_time'] = '29:90'
  assert client.put('/api/advisor/settings', json=s).status_code == 422
  s['local_time'] = '09:00'
  first = client.post('/api/advisor/run').json()
  assert client.post('/api/advisor/run').json()['id'] == first['id']
  s['goals'] = 'Save for a home'
  assert client.put('/api/advisor/settings', json=s).status_code == 200
  assert json.loads(store.conn.execute('SELECT settings FROM advisor_runs').fetchone()[0])['goals'] == s['goals']
  asyncio.run(advisor.tick(store, config, NOW))
  run = client.get(f"/api/advisor/runs/{first['id']}").json()
  topic = run['report']['findings'][0]['topic']
  result = client.put(f'/api/advisor/findings/{topic}/feedback', json=dict(feedback='known', answer='Done'))
  assert result.status_code == 200
  assert client.get('/api/advisor').json()['feedback'][topic]['answer'] == 'Done'
  assert next(f for f in client.get('/api/advisor').json()['latest']['report']['findings']
              if f['topic'] == topic)['feedback'] == 'new'  # Run snapshot is immutable; summary uses current feedback.
  remaining = len(run['report']['findings']) - 1
  assert client.get('/api/advisor/summary').json()['count'] == remaining
  assert client.get('/api/advisor/runs/999999').status_code == 404
  assert client.put('/api/advisor/findings/unknown/feedback',json=dict(feedback='known')).status_code == 404
