import asyncio
from datetime import date

import pytest
from fastapi.testclient import TestClient

from networth import spending
from networth.config import AccountConfig, Config
from networth.connectors.monzo import Monzo
from networth.store import Store
from networth.web.app import create_app


@pytest.fixture
def setup(tmp_path):
  config = Config([AccountConfig('Monzo','monzo','cash',15), AccountConfig('Santander','manual','cash',15)], data_dir=tmp_path)
  store = Store(config.db_path)
  yield store, config
  store.conn.close()


def tx(id, day='2026-10-01', amount=-1000, account='Monzo', merchant='Shop', **values):
  return dict(id=id, account=account, bank_account=account, date=day, merchant=merchant,
              description=merchant, amount=amount, category='Shopping', kind='expense' if amount<0 else 'income', pending=0, source='monzo', **values)


def test_totals_refunds_pending_and_transfers(setup):
  store, config = setup
  rows = [tx('purchase'), tx('refund',amount=300), tx('salary',amount=200000),tx('pending',amount=-2500),tx('pot',amount=-10000)]
  rows[1]['kind']='refund'; rows[3]['pending']=1; rows[4]['kind']='transfer'
  spending.save_transactions(store,rows)
  result = spending.report(store,config,'2026-10')
  assert result['summary'] == dict(spent=10,refunds=3,income=2000,net_spent=7,pending=25,committed=0)
  assert result['categories'] == [dict(category='Shopping',amount=7)]
  assert result['pace'][0]['current']==7


def test_sync_updates_pending_but_preserves_corrections(setup):
  store,_ = setup
  row=tx('a'); row['pending']=1
  spending.save_transactions(store,[row])
  spending.edit_transaction(store,'a',category='Bills',kind='transfer')
  row['pending']=0; row['amount']=-1200
  spending.save_transactions(store,[row])
  [actual]=spending.transactions(store)
  assert (actual['category'],actual['kind'],actual['amount'],actual['pending'])==('Bills','transfer',-1200,0)


def test_category_rule_applies_to_existing_and_future_transactions(setup):
  store,_=setup
  spending.save_transactions(store,[tx('a',merchant='Shop'),tx('b',merchant=' SHOP ')])
  spending.edit_transaction(store,'a',category='Groceries',apply_rule=True)
  spending.save_transactions(store,[tx('c',merchant='shop')])
  assert {r['category'] for r in spending.transactions(store)}=={'Groceries'}
  with pytest.raises(ValueError): spending.edit_transaction(store,'a',kind='refund')


def test_possible_transfers_require_confirmation_and_filter_keeps_suggestion(setup):
  store,config=setup
  spending.save_transactions(store,[tx('a',amount=-5000),tx('b',amount=5000,account='Santander')])
  assert all(r['possible_transfer'] for r in spending.transactions(store))
  assert spending.report(store,config,'2026-10','Monzo')['summary']['spent']==50
  assert spending.report(store,config,'2026-10','Monzo')['transactions'][0]['possible_transfer']
  spending.edit_transaction(store,'a',kind='transfer')
  spending.edit_transaction(store,'b',kind='transfer')
  assert spending.report(store,config,'2026-10')['summary']['spent']==0


def test_recurring_confirm_dismiss_cancel_and_variable_amount(setup):
  store,config=setup
  spending.save_transactions(store,[tx('a','2026-07-31',merchant='Netflix',amount=-1000),tx('b','2026-08-31',merchant='Netflix',amount=-1000),tx('c','2026-09-30',merchant='Netflix',amount=-1200)])
  [payment]=spending.recurring(store,spending.transactions(store))
  assert payment['frequency']=='Monthly'
  assert payment['next_date']=='2026-10-30'
  assert payment['monthly']==12
  assert payment['price_change']==2
  assert spending.report(store,config,'2026-10')['summary']['committed']==0
  with store.conn:
    store.conn.execute('INSERT INTO recurring_payments VALUES (?,?,?,?)',(payment['id'],'Monzo','Netflix','confirmed'))
  assert spending.report(store,config,'2026-10')['summary']['committed']==12
  store.conn.execute("UPDATE recurring_payments SET status='cancelled'")
  assert spending.report(store,config,'2026-10')['summary']['committed']==0


def test_regular_shopping_and_pending_not_recurring(setup):
  store,_=setup
  rows=[tx('a','2026-07-01'),tx('b','2026-07-03'),tx('c','2026-08-01')]
  spending.save_transactions(store,rows)
  assert spending.recurring(store,spending.transactions(store))==[]


def test_csv_money_dates_quoting_and_repeat_import(setup):
  store,_=setup
  text='Date,Description,Money out,Money in\n01/10/2026,"SHOP, LONDON","1,234.56",\n02/10/2026,Salary,,2000.00\n'
  mapping=dict(date='Date',description='Description',debit='Money out',credit='Money in')
  rows=spending.parse_csv(text,'Santander',mapping)
  assert [r['amount'] for r in rows]==[-123456,200000]
  spending.save_transactions(store,rows); spending.save_transactions(store,rows)
  assert len(spending.transactions(store))==2
  with pytest.raises(ValueError,match='Row 2'): spending.parse_csv(text.replace('1,234.56','NaN'),'Santander',mapping)
  with pytest.raises(ValueError,match='Row 2'): spending.parse_csv(text.replace('01/10/2026','broken'),'Santander',mapping)
  assert spending.money_pence('(12.99)')==-1299
  with pytest.raises(ValueError): spending.money_pence('1.001')


def test_identical_payments_preserved_and_overlapping_statement_dedup(setup):
  store,_=setup
  mapping=dict(date='Date',description='Description',amount='Amount')
  text='Date,Description,Amount\n2026-10-01,Shop,-10\n2026-10-01,Shop,-10\n'
  rows=spending.parse_csv(text,'Santander',mapping)
  assert rows[0]['id']!=rows[1]['id']
  spending.save_transactions(store,rows)
  spending.save_transactions(store,spending.parse_csv(text+'2026-10-02,Other,-20\n','Santander',mapping))
  assert len(spending.transactions(store))==3


def test_import_api_preview_commit_validation_and_month(setup):
  _,config=setup
  client=TestClient(create_app(config,run_scheduler=False))
  payload=dict(account='Santander',text='Date,Description,Amount\n2026-10-01,Shop,-10\n',mapping=dict(date='Date',description='Description',amount='Amount'))
  response=client.post('/api/spending/import',json=payload)
  assert response.status_code==200 and response.json()['new_count']==1
  assert client.get('/api/spending?month=2026-10').json()['transactions']==[]
  assert client.post('/api/spending/import',json=payload|dict(commit=True)).json()['committed']
  assert client.post('/api/spending/import',json=payload).json()['duplicates']==1
  assert client.post('/api/spending/import',json=payload|dict(account='Monzo')).status_code==400
  assert client.get('/api/spending?month=2026-13').status_code==400
  tid=client.get('/api/spending?month=2026-10').json()['transactions'][0]['id']
  assert client.patch('/api/spending/transactions/'+tid,json=dict(category='Groceries')).status_code==200
  assert client.patch('/api/spending/transactions/'+tid,json=dict(category='Invalid')).status_code==400
  assert client.patch('/api/spending/transactions/missing',json=dict(kind='transfer')).status_code==404


def test_monzo_pagination_normalisation_and_pots(setup,monkeypatch):
  store,config=setup
  connector=Monzo(config.accounts[0],config.data_dir)
  async def token(): return 'test-token'
  monkeypatch.setattr(connector,'_access_token',token)
  calls=[]
  async def get(url,params=None,headers=None):
    if url.endswith('/accounts'): return {'accounts':[dict(id='acc',type='uk_retail')]}
    calls.append(params)
    if len(calls)==1:
      return {'transactions':[dict(id=f'tx{i}',created='2026-09-30T23:30:00Z',currency='GBP',description='SHOP',amount=-100,settled='',category='shopping',merchant={'name':'Shop'}) for i in range(100)]}
    return {'transactions':[dict(id='pot',created='2026-10-01T10:00:00Z',currency='GBP',amount=-5000,settled='2026-10-01T10:00:00Z',metadata={'pot_id':'pot1'})]}
  monkeypatch.setattr('networth.connectors.monzo.http.get_json',get)
  rows,_=asyncio.run(connector.fetch_transactions())
  assert len(rows)==101 and calls[1]['since']=='tx99'
  assert rows[0]['date']=='2026-10-01' and rows[0]['pending']==1
  assert rows[-1]['kind']=='transfer'


def test_failed_sync_retains_history_and_sanitises_errors(setup,monkeypatch):
  store,config=setup
  spending.save_transactions(store,[tx('a')])
  async def fail(*args): raise RuntimeError('secret token in HTTP error')
  monkeypatch.setattr(Monzo,'fetch_transactions',fail)
  result=asyncio.run(spending.sync_monzo(store,config))
  assert 'secret' not in result[0]['error']
  assert len(spending.transactions(store))==1
  assert spending.report(store,config,'2026-10')['accounts'][0]['last_error']


def test_rename_retains_transactions_rules_and_recurring_status(setup):
  store,config=setup
  spending.save_transactions(store,[tx('a','2026-07-01'),tx('b','2026-08-01'),tx('c','2026-09-01')])
  payment=spending.recurring(store,spending.transactions(store))[0]
  store.conn.execute('INSERT INTO recurring_payments VALUES (?,?,?,?)',(payment['id'],'Monzo','Shop','confirmed'))
  spending.edit_transaction(store,'a',category='Bills',apply_rule=True)
  store.rename_account('Monzo','Main bank')
  config.accounts[0].name='Main bank'
  result=spending.report(store,config,'2026-09')
  assert result['transactions'][0]['category']=='Bills'
  assert result['recurring'][0]['status']=='confirmed'


def test_csv_identity_survives_account_rename(setup):
  store,config=setup
  client=TestClient(create_app(config,run_scheduler=False))
  payload=dict(account='Santander',text='Date,Description,Amount\n2026-10-01,Shop,-10\n',mapping=dict(date='Date',description='Description',amount='Amount'),commit=True)
  assert client.post('/api/spending/import',json=payload).status_code==200
  store.rename_account('Santander','Bills bank')
  config.accounts[1].name='Bills bank'
  result=client.post('/api/spending/import',json=payload|dict(account='Bills bank')).json()
  assert result['new_count']==0 and result['duplicates']==1
  assert len(spending.transactions(store))==1


def test_import_rejects_ambiguous_amounts_headers_and_invalid_mapping(setup):
  mapping=dict(date='Date',description='Description',debit='Out',credit='In')
  with pytest.raises(ValueError,match='Both money'):
    spending.parse_csv('Date,Description,Out,In\n2026-10-01,Shop,10,10\n','Santander',mapping)
  with pytest.raises(ValueError,match='duplicate column'):
    spending.parse_csv('Date,Description,Out,Out\n2026-10-01,Shop,10,10\n','Santander',mapping)
  with pytest.raises(ValueError,match='Column mappings'):
    spending.parse_csv('Date,Description,Out,In\n2026-10-01,Shop,10,\n','Santander',mapping|dict(date=['Date']))
  _,config=setup
  client=TestClient(create_app(config,run_scheduler=False))
  assert client.get('/api/spending?month=2026-10&account=missing').status_code==400


def test_mark_monthly_subscription_applies_to_past_future_and_survives_sync(setup):
  store,config=setup
  rows=[tx('older','2026-08-02',merchant='Service',amount=-999),tx('latest','2026-10-08',merchant='SERVICE',amount=-2499)]
  spending.save_transactions(store,rows)
  spending.edit_transaction(store,'latest',recurring_type='subscription')
  assert {r['recurring_type'] for r in spending.transactions(store)}=={'subscription'}
  payment=spending.report(store,config,'2026-10')['recurring'][0]
  assert (payment['frequency'],payment['status'],payment['monthly'],payment['manual'])==('Monthly','confirmed',24.99,True)
  assert payment['next_date']=='2026-11-08'
  spending.save_transactions(store,rows+[tx('future','2026-11-10',merchant=' service ',amount=-2999)])
  assert {r['recurring_type'] for r in spending.transactions(store)}=={'subscription'}
  result=spending.report(store,config,'2026-11')
  assert result['summary']['committed']==29.99
  assert result['recurring'][0]['price_change']==5


def test_manual_monthly_needs_only_one_settled_expense_and_can_be_removed(setup):
  store,config=setup
  spending.save_transactions(store,[tx('only',merchant='Gym',amount=-3500)])
  assert spending.report(store,config,'2026-10')['recurring']==[]
  spending.edit_transaction(store,'only',recurring_type='monthly')
  result=spending.report(store,config,'2026-10')
  assert result['summary']['committed']==35
  assert result['recurring'][0]['recurring_type']=='monthly'
  assert result['recurring'][0]['price_change']==0
  spending.edit_transaction(store,'only',recurring_type='none')
  assert spending.report(store,config,'2026-10')['recurring']==[]
  assert spending.transactions(store)[0]['recurring_type']=='none'
  spending.save_transactions(store,[tx('another','2026-11-01',merchant='Gym',amount=-3500)])
  assert spending.report(store,config,'2026-11')['recurring']==[]
  spending.edit_transaction(store,'only',recurring_type='auto')
  assert {r['recurring_type'] for r in spending.transactions(store)}=={'auto'}


def test_monthly_rule_is_scoped_to_merchant_and_bank_account(setup):
  store,config=setup
  other_bank=tx('joint',merchant='Gym'); other_bank['bank_account']='joint'
  spending.save_transactions(store,[tx('personal',merchant='Gym'),other_bank,tx('santander',merchant='Gym',account='Santander'),tx('other',merchant='Shop')])
  spending.edit_transaction(store,'personal',recurring_type='monthly')
  actual={r['id']:r['recurring_type'] for r in spending.transactions(store)}
  assert actual==dict(personal='monthly',joint='auto',santander='auto',other='auto')
  store.rename_account('Monzo','Main bank')
  config.accounts[0].name='Main bank'
  result=spending.report(store,config,'2026-10')
  assert result['recurring'][0]['status']=='confirmed'
  assert result['recurring'][0]['account']=='Main bank'


def test_manual_monthly_rejects_income_transfers_and_invalid_rule(setup):
  store,_=setup
  spending.save_transactions(store,[tx('income',amount=10000),tx('transfer')])
  spending.edit_transaction(store,'transfer',kind='transfer')
  for tid in ['income','transfer']:
    with pytest.raises(ValueError,match='Only outgoing expenses'):
      spending.edit_transaction(store,tid,recurring_type='subscription')
  with pytest.raises(ValueError,match='Unknown recurring'):
    spending.edit_transaction(store,'transfer',recurring_type='invalid')


def test_monthly_rule_api_and_cancellation(setup):
  store,config=setup
  spending.save_transactions(store,[tx('a',merchant='Gym',amount=-3500)])
  client=TestClient(create_app(config,run_scheduler=False))
  assert client.patch('/api/spending/transactions/a',json=dict(recurring_type='monthly')).status_code==200
  result=client.get('/api/spending?month=2026-10').json()
  payment=result['recurring'][0]
  assert result['summary']['committed']==35
  assert client.patch('/api/spending/recurring/'+payment['id'],json=dict(account='Monzo',merchant='Gym',status='cancelled')).status_code==200
  assert client.get('/api/spending?month=2026-10').json()['summary']['committed']==0
  assert client.patch('/api/spending/transactions/a',json=dict(recurring_type='monthly')).status_code==200
  assert client.get('/api/spending?month=2026-10').json()['summary']['committed']==35
  assert client.patch('/api/spending/transactions/a',json=dict(recurring_type='invalid')).status_code==422


def test_recent_sync_keeps_history_older_than_api_window(setup):
  store,config=setup
  spending.save_transactions(store,[tx('old','2020-01-01')])
  spending.save_transactions(store,[tx('new','2026-10-01')])
  assert len(spending.transactions(store))==2
  assert spending.report(store,config,'2020-01')['summary']['spent']==10


def test_full_history_uses_small_ranges_and_saves_each_batch(setup, monkeypatch):
  from datetime import datetime, timedelta, timezone
  store, config = setup
  connector = Monzo(config.accounts[0], config.data_dir)
  created = datetime.now(timezone.utc) - timedelta(days=220)
  async def token(): return 'test-token'
  monkeypatch.setattr(connector, '_access_token', token)
  calls = []
  async def get(url, params=None, headers=None):
    if url.endswith('/accounts'):
      return {'accounts': [dict(id='acc', type='uk_retail', created=created.isoformat())]}
    calls.append(params)
    since = datetime.fromisoformat(params['since'])
    before = datetime.fromisoformat(params['before'])
    assert timedelta(0) < before - since <= timedelta(days=89)
    return {'transactions': [dict(id=f'history{len(calls)}', created=(since+timedelta(days=1)).isoformat(),
      currency='GBP', amount=-100, settled='yes', description='Shop')]}
  monkeypatch.setattr('networth.connectors.monzo.http.get_json', get)
  batches=[]
  def save(batch):
    batches.append(batch)
    spending.save_transactions(store,batch)
  rows,_=asyncio.run(connector.fetch_transactions(full_history=True,on_batch=save))
  assert len(calls)==3 and len(batches)==3 and len(rows)==3
  assert datetime.fromisoformat(calls[-1]['since'])==created
  assert len(spending.transactions(store))==3


def test_full_history_retains_completed_batches_after_later_failure(setup, monkeypatch):
  store,config=setup
  async def partial(self, full_history=False, on_batch=None):
    assert full_history and on_batch is not None
    on_batch([tx('saved-history', '2020-02-17')])
    raise RuntimeError('later page failed')
  monkeypatch.setattr(Monzo,'fetch_transactions',partial)
  result=asyncio.run(spending.sync_monzo(store,config,full_history=True))
  assert result[0]['error']
  assert spending.transactions(store)[0]['date']=='2020-02-17'


def test_stale_confirmed_payments_stop_counting_with_recent_account_activity(setup):
  store,config=setup
  spending.save_transactions(store,[tx('old','2026-01-01',merchant='Old service'),tx('recent','2026-10-13',amount=100000,merchant='Salary')])
  spending.edit_transaction(store,'old',recurring_type='subscription')
  result=spending.report(store,config,'2026-10')
  payment=result['recurring'][0]
  assert payment['status']=='confirmed' and payment['inactive'] and not payment['active']
  assert result['summary']['committed']==0
  spending.save_transactions(store,[tx('renewed','2026-10-13',merchant='Old service')])
  result=spending.report(store,config,'2026-10')
  assert result['recurring'][0]['active']
  assert result['summary']['committed']==10


def test_no_recent_coverage_does_not_invent_a_missing_payment(setup):
  store,config=setup
  spending.save_transactions(store,[tx('old','2020-01-01',merchant='Service')])
  spending.edit_transaction(store,'old',recurring_type='monthly')
  payment=spending.report(store,config,'2026-10')['recurring'][0]
  assert payment['coverage_stale'] and payment['active'] and not payment['inactive']


def test_two_monthly_charges_same_day_are_combined(setup):
  store,config=setup
  spending.save_transactions(store,[tx('a','2026-09-01',merchant='Membership',amount=-7100),tx('b','2026-09-01',merchant='Membership',amount=-5250),tx('c','2026-10-01',merchant='Membership',amount=-7380),tx('d','2026-10-01',merchant='Membership',amount=-5410)])
  spending.edit_transaction(store,'d',recurring_type='monthly')
  payment=spending.report(store,config,'2026-10')['recurring'][0]
  assert payment['monthly']==127.90 and payment['price_change']==4.4


def test_subscription_description_rule_excludes_same_merchant_api_credits(setup):
  store,config=setup
  subscription=tx('sub','2026-10-10',merchant='OpenAI',amount=-1597);subscription['description']='OPENAI *CHATGPT SUBSCR'
  credits=tx('api','2026-10-12',merchant='OpenAI',amount=-5000);credits['description']='OPENAI API'
  spending.save_transactions(store,[subscription,credits])
  spending.edit_transaction(store,'sub',recurring_type='subscription')
  with store.conn:
    store.conn.execute("UPDATE monthly_spending_rules SET description_contains='CHATGPT SUBSCR'")
  actual={r['id']:r['recurring_type'] for r in spending.transactions(store)}
  assert actual==dict(sub='subscription',api='auto')
  result=spending.report(store,config,'2026-10')
  assert result['summary']['committed']==15.97
  assert result['recurring'][0]['description_contains']=='CHATGPT SUBSCR'


def test_annual_payment_stays_active_until_annual_renewal_is_missed(setup):
  store,config=setup
  spending.save_transactions(store,[tx('a','2024-12-01',merchant='Annual'),tx('b','2025-12-01',merchant='Annual'),tx('recent','2026-10-13',amount=100000,merchant='Salary')])
  payment=spending.report(store,config,'2026-10')['recurring'][0]
  assert payment['frequency']=='Annual' and payment['active'] and not payment['inactive']


def bank(id, merchant, amount, account='Santander', day='2026-10-01', description=None):
  return dict(tx(id, day, amount, account, merchant), description=description or merchant, category='Uncategorised', source='lunchflow')


def test_own_account_transfers_are_detected_from_shared_references_and_card_repayments(setup):
  store,config=setup
  spending.save_transactions(store,[
    bank('out','JOHN SMITH REFERENCE MONZO-ABCDE SANTANDER',-50000,description='FASTER PAYMENT TO JOHN SMITH REFERENCE MONZO-ABCDE SANTANDER'),
    dict(tx('in','2026-10-02',50000,merchant='Monzo-ABCDE'),category='Uncategorised'),
    bank('dd','AMERICAN EXPRESS',-3989,description='DIRECT DEBIT PAYMENT TO AMERICAN EXPRESS REF 3412'),
    bank('card','100000000109',3989,account='Amex',day='2026-09-29',description='PAYMENT RECEIVED - THANK YOU'),
    bank('lone','100000000110',1200,account='Amex',description='PAYMENT RECEIVED - THANK YOU'),
    bank('hl','HLAM LTD S AND S ISA CLIENT ACC',-1000000)])
  rows={r['id']:r for r in spending.transactions(store)}
  assert {k:rows[k]['kind'] for k in rows}==dict.fromkeys(rows,'transfer')
  assert rows['hl']['category']=='Savings' and not any(r['possible_transfer'] for r in rows.values())
  assert spending.report(store,config,'2026-10')['summary']['spent']==0
  # An explicit choice beats the inference.
  spending.edit_transaction(store,'out',kind='expense')
  rows={r['id']:r for r in spending.transactions(store)}
  assert rows['out']['kind']=='expense' and rows['in']['kind']=='income' and rows['in']['possible_transfer']


def test_uncategorised_bank_transactions_learn_from_categorised_merchants(setup):
  store,_=setup
  spending.save_transactions(store,[tx('m1',merchant='Tesco'),tx('m2',merchant='Tesco',day='2026-09-01'),
    bank('amex','TESCO STORES',-911,account='Amex',description='TESCO STORE 5711 LONDON'),
    bank('tfl','TFL TRAVEL CHARGE',-175,account='Amex'),
    bank('shop','GOOGLE SERVICES',-1899,account='Amex'),bank('back','GOOGLE SERVICES',122,account='Amex'),
    bank('salary','DR SMITH LIMITED',83300),bank('mystery','PAYPAL PAYMENT',-1200)])
  rows={r['id']:r for r in spending.transactions(store)}
  assert (rows['amex']['category'],rows['tfl']['category'])==('Shopping','Transport')  # learned from Monzo's 'Tesco'
  assert (rows['back']['kind'],rows['salary']['kind'],rows['mystery']['category'])==('refund','income','Uncategorised')
  assert 'category' in rows['amex']['inferred']
  spending.edit_transaction(store,'tfl',category='Travel')
  assert next(r for r in spending.transactions(store) if r['id']=='tfl')['category']=='Travel'


def test_choosing_savings_makes_it_a_transfer(setup):
  store,config=setup
  spending.save_transactions(store,[bank('a','Pot top up',-5000),bank('b','Vault',-2000,day='2026-10-03')])
  spending.edit_transaction(store,'a',category='Savings')
  spending.edit_transaction(store,'b',category='Savings',apply_rule=True)
  assert {r['kind'] for r in spending.transactions(store)}=={'transfer'}
  assert spending.report(store,config,'2026-10')['summary']['spent']==0


def test_monzo_rows_keep_their_local_time(setup):
  store,_=setup
  spending.save_transactions(store,[tx('a',time='08:05'),tx('b',time='21:40'),tx('c')])
  assert [r['time'] for r in spending.transactions(store)]==['21:40','08:05',None]


def test_report_is_json_serialisable_with_matched_transfers(setup):
  store,config=setup
  spending.save_transactions(store,[bank('dd','AMERICAN EXPRESS',-3989),bank('card','x',3989,account='Amex',description='PAYMENT RECEIVED')])
  client=TestClient(create_app(config,run_scheduler=False))
  assert client.get('/api/spending?month=2026-10').status_code==200


def test_label_survives_sync_and_clears_back_to_the_reference(setup):
  store,config=setup
  row=bank('a','PAYPAL PAYMENT',-10863)
  spending.save_transactions(store,[row])
  client=TestClient(create_app(config,run_scheduler=False))
  assert client.patch('/api/spending/transactions/a',json=dict(label='  TV for Mum ')).status_code==200
  spending.save_transactions(store,[row])
  [actual]=spending.transactions(store)
  assert (actual['label'],actual['merchant'])==('TV for Mum','PAYPAL PAYMENT')
  assert client.patch('/api/spending/transactions/a',json=dict(label='x'*101)).status_code==422
  client.patch('/api/spending/transactions/a',json=dict(label=''))
  assert spending.transactions(store)[0]['label'] is None
