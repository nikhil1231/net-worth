import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from networth import classify
from networth.config import AccountConfig, Config
from networth.models import Holding
from networth.store import SnapshotRow, Store
from networth.web.app import create_app

ISHARES_XML = '''<?xml version="1.0"?>
<ss:Workbook xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">
<ss:Worksheet ss:Name="Holdings"><ss:Table>
<ss:Row><ss:Cell><ss:Data ss:Type="String">All</ss:Data></ss:Cell></ss:Row><ss:Row><ss:Cell><ss:Data ss:Type="String">as of</ss:Data></ss:Cell><ss:Cell><ss:Data ss:Type="String">30/Sept/2026</ss:Data></ss:Cell></ss:Row><ss:Row><ss:Cell><ss:Data ss:Type="String">Issuer Ticker</ss:Data></ss:Cell><ss:Cell><ss:Data ss:Type="String">Name</ss:Data></ss:Cell><ss:Cell><ss:Data ss:Type="String">Sector</ss:Data></ss:Cell><ss:Cell><ss:Data ss:Type="String">Asset Class</ss:Data></ss:Cell><ss:Cell><ss:Data ss:Type="String">Market Value</ss:Data></ss:Cell><ss:Cell><ss:Data ss:Type="String">Weight (%)</ss:Data></ss:Cell><ss:Cell><ss:Data ss:Type="String">Notional Value</ss:Data></ss:Cell><ss:Cell><ss:Data ss:Type="String">Nominal</ss:Data></ss:Cell><ss:Cell><ss:Data ss:Type="String">Market Currency</ss:Data></ss:Cell></ss:Row><ss:Row><ss:Cell><ss:Data ss:Type="String">2330</ss:Data></ss:Cell><ss:Cell><ss:Data ss:Type="String">TAIWAN SEMICONDUCTOR MANUFACTURING</ss:Data></ss:Cell><ss:Cell><ss:Data ss:Type="String">Information Technology</ss:Data></ss:Cell><ss:Cell><ss:Data ss:Type="String">Equity</ss:Data></ss:Cell><ss:Cell><ss:Data ss:Type="String">USD 600.00</ss:Data></ss:Cell><ss:Cell><ss:Data ss:Type="String">60.00</ss:Data></ss:Cell><ss:Cell><ss:Data ss:Type="String">600</ss:Data></ss:Cell><ss:Cell><ss:Data ss:Type="String">1</ss:Data></ss:Cell><ss:Cell><ss:Data ss:Type="String">TWD</ss:Data></ss:Cell></ss:Row><ss:Row><ss:Cell><ss:Data ss:Type="String">000660</ss:Data></ss:Cell><ss:Cell><ss:Data ss:Type="String">SK HYNIX</ss:Data></ss:Cell><ss:Cell><ss:Data ss:Type="String">Information Technology</ss:Data></ss:Cell><ss:Cell><ss:Data ss:Type="String">Equity</ss:Data></ss:Cell><ss:Cell><ss:Data ss:Type="String">USD 300.00</ss:Data></ss:Cell><ss:Cell><ss:Data ss:Type="String">30.00</ss:Data></ss:Cell><ss:Cell><ss:Data ss:Type="String">300</ss:Data></ss:Cell><ss:Cell><ss:Data ss:Type="String">1</ss:Data></ss:Cell><ss:Cell><ss:Data ss:Type="String">KRW</ss:Data></ss:Cell></ss:Row><ss:Row><ss:Cell><ss:Data ss:Type="String">USD</ss:Data></ss:Cell><ss:Cell><ss:Data ss:Type="String">USD CASH</ss:Data></ss:Cell><ss:Cell><ss:Data ss:Type="String">Cash and/or Derivatives</ss:Data></ss:Cell><ss:Cell><ss:Data ss:Type="String">Cash</ss:Data></ss:Cell><ss:Cell><ss:Data ss:Type="String">USD 60.00</ss:Data></ss:Cell><ss:Cell><ss:Data ss:Type="String">6.00</ss:Data></ss:Cell><ss:Cell><ss:Data ss:Type="String">60</ss:Data></ss:Cell><ss:Cell><ss:Data ss:Type="String">60</ss:Data></ss:Cell><ss:Cell><ss:Data ss:Type="String">USD</ss:Data></ss:Cell></ss:Row><ss:Row><ss:Cell><ss:Data ss:Type="String">ICSUAGD</ss:Data></ss:Cell><ss:Cell><ss:Data ss:Type="String">BLK ICS USD LIQ AGENCY DIS</ss:Data></ss:Cell><ss:Cell><ss:Data ss:Type="String">Cash and/or Derivatives</ss:Data></ss:Cell><ss:Cell><ss:Data ss:Type="String">Money Market</ss:Data></ss:Cell><ss:Cell><ss:Data ss:Type="String">USD 40.00</ss:Data></ss:Cell><ss:Cell><ss:Data ss:Type="String">4.00</ss:Data></ss:Cell><ss:Cell><ss:Data ss:Type="String">40</ss:Data></ss:Cell><ss:Cell><ss:Data ss:Type="String">40</ss:Data></ss:Cell><ss:Cell><ss:Data ss:Type="String">USD</ss:Data></ss:Cell></ss:Row><ss:Row><ss:Cell><ss:Data ss:Type="String">USD</ss:Data></ss:Cell><ss:Cell><ss:Data ss:Type="String">FX FUTURES</ss:Data></ss:Cell><ss:Cell><ss:Data ss:Type="String">Cash and/or Derivatives</ss:Data></ss:Cell><ss:Cell><ss:Data ss:Type="String">FX</ss:Data></ss:Cell><ss:Cell><ss:Data ss:Type="String">USD 500.00</ss:Data></ss:Cell><ss:Cell><ss:Data ss:Type="String">0.00</ss:Data></ss:Cell><ss:Cell><ss:Data ss:Type="String">500</ss:Data></ss:Cell><ss:Cell><ss:Data ss:Type="String">500</ss:Data></ss:Cell><ss:Cell><ss:Data ss:Type="String">USD</ss:Data></ss:Cell></ss:Row><ss:Row><ss:Cell><ss:Data ss:Type="String">CNH</ss:Data></ss:Cell><ss:Cell><ss:Data ss:Type="String">CNH CASH</ss:Data></ss:Cell><ss:Cell><ss:Data ss:Type="String">Cash and/or Derivatives</ss:Data></ss:Cell><ss:Cell><ss:Data ss:Type="String">Cash</ss:Data></ss:Cell><ss:Cell><ss:Data ss:Type="String">USD -5.00</ss:Data></ss:Cell><ss:Cell><ss:Data ss:Type="String">0.00</ss:Data></ss:Cell><ss:Cell><ss:Data ss:Type="String">-5</ss:Data></ss:Cell><ss:Cell><ss:Data ss:Type="String">-5</ss:Data></ss:Cell><ss:Cell><ss:Data ss:Type="String">CNH</ss:Data></ss:Cell></ss:Row>
</ss:Table></ss:Worksheet>
<ss:Worksheet ss:Name="Exposure Breakdowns"><ss:Table>
<ss:Row><ss:Cell><ss:Data ss:Type="String">Sector</ss:Data></ss:Cell></ss:Row>
<ss:Row><ss:Cell><ss:Data ss:Type="String">as of</ss:Data></ss:Cell><ss:Cell><ss:Data ss:Type="String">30/Sept/2026</ss:Data></ss:Cell></ss:Row>
<ss:Row><ss:Cell><ss:Data ss:Type="String">Type</ss:Data></ss:Cell><ss:Cell><ss:Data ss:Type="String">Fund</ss:Data></ss:Cell></ss:Row>
<ss:Row><ss:Cell><ss:Data ss:Type="String">Information Technology</ss:Data></ss:Cell><ss:Cell><ss:Data ss:Type="String">60.00</ss:Data></ss:Cell></ss:Row>
<ss:Row><ss:Cell><ss:Data ss:Type="String">Communication</ss:Data></ss:Cell><ss:Cell><ss:Data ss:Type="String">39.00</ss:Data></ss:Cell></ss:Row>
<ss:Row><ss:Cell><ss:Data ss:Type="String">Cash and/or Derivatives</ss:Data></ss:Cell><ss:Cell><ss:Data ss:Type="String">1.00</ss:Data></ss:Cell></ss:Row>
<ss:Row><ss:Cell><ss:Data ss:Type="String">Other</ss:Data></ss:Cell><ss:Cell><ss:Data ss:Type="String">0.00</ss:Data></ss:Cell></ss:Row>
<ss:Row></ss:Row>
<ss:Row><ss:Cell><ss:Data ss:Type="String">Geography/Locations</ss:Data></ss:Cell></ss:Row>
<ss:Row><ss:Cell><ss:Data ss:Type="String">Type</ss:Data></ss:Cell><ss:Cell><ss:Data ss:Type="String">Fund</ss:Data></ss:Cell></ss:Row>
<ss:Row><ss:Cell><ss:Data ss:Type="String">Taiwan</ss:Data></ss:Cell><ss:Cell><ss:Data ss:Type="String">75.00</ss:Data></ss:Cell><ss:Cell><ss:Data ss:Type="String">TW</ss:Data></ss:Cell></ss:Row>
<ss:Row><ss:Cell><ss:Data ss:Type="String">Korea (South)</ss:Data></ss:Cell><ss:Cell><ss:Data ss:Type="String">25.00</ss:Data></ss:Cell><ss:Cell><ss:Data ss:Type="String">KR</ss:Data></ss:Cell></ss:Row>
<ss:Row></ss:Row>
<ss:Row><ss:Cell><ss:Data ss:Type="String">Allocations are subject to change.</ss:Data></ss:Cell></ss:Row>
</ss:Table></ss:Worksheet>
</ss:Workbook>
'''

XTRACKERS_CSV = (
  '﻿ShareClass ISIN;Constituent ISIN;Constituent Name;Constituent Country;Constituent Currency ISO Code;'
  'Constituent Weighting;Constituent Rating;Constituent Main Exchange Name;Constituent Industry Classification Name\r\n'
  'IE0006WW1TQ4;NL0010273215;ASML HOLDING NV;Netherlands;EUR;0.03;Baa2;Euronext Amsterdam;Information Technology\r\n'
  'IE0006WW1TQ4;GB0005405286;HSBC HOLDINGS PLC;United Kingdom;GBP;0.02;Aa3;London Stock Exchange;Financials\r\n'
  'IE0006WW1TQ4;JP3633400001;TOYOTA MOTOR CORP;Japan;JPY;0.04;;Tokyo;Consumer Discretionary\r\n'
  'IE0006WW1TQ4;JP0000000000;OTHER JAPAN CO;Japan;JPY;0.01;;Tokyo;Financials\r\n'
)


def test_parse_ishares():
  result = classify.parse_ishares(ISHARES_XML)
  assert result['sectors'] == pytest.approx({'Information Technology': 0.6, 'Communication Services': 0.39, 'Cash': 0.01})
  assert result['countries'] == pytest.approx({'Taiwan': 0.75, 'South Korea': 0.25})
  # constituents weighted by market value; cash merged, FX and negative positions left out
  assert [(h['name'], h['sector']) for h in result['holdings']] == [
    ('Taiwan Semiconductor Manufacturing', 'Information Technology'), ('SK Hynix', 'Information Technology'), ('Cash', 'Cash')]
  assert [h['weight'] for h in result['holdings']] == pytest.approx([0.6, 0.3, 0.1])


def test_parse_ishares_missing_sheet():
  with pytest.raises(RuntimeError):
    classify.parse_ishares('<ss:Workbook xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet"/>')


def test_parse_xtrackers_sums_and_normalises():
  result = classify.parse_xtrackers(XTRACKERS_CSV)
  assert result['countries'] == pytest.approx({'Japan': 0.5, 'Netherlands': 0.3, 'United Kingdom': 0.2})
  assert list(result['countries'])[0] == 'Japan'  # biggest first
  assert result['sectors'] == pytest.approx({'Consumer Discretionary': 0.4, 'Information Technology': 0.3, 'Financials': 0.3})
  assert result['holdings'][0] == pytest.approx(
    {'name': 'Toyota Motor Corp', 'weight': 0.4, 'sector': 'Consumer Discretionary', 'country': 'Japan'})
  assert result['holdings'][1]['name'] == 'ASML Holding NV'


JUSTETF_ROWS = '''<tr data-testid="etf-holdings_countries_row"> <td data-testid="tl_etf-holdings_countries_value_name">United States</td>
<td> <span data-testid="tl_etf-holdings_countries_value_percentage">60.00%</span> </td> </tr>
<tr data-testid="etf-holdings_countries_row"> <td data-testid="tl_etf-holdings_countries_value_name">Korea</td>
<td> <span data-testid="tl_etf-holdings_countries_value_percentage">15.00%</span> </td> </tr>
<tr data-testid="etf-holdings_countries_row"> <td data-testid="tl_etf-holdings_countries_value_name">Other</td>
<td> <span data-testid="tl_etf-holdings_countries_value_percentage">25.00%</span> </td> </tr>'''


def test_parse_justetf_countries():
  assert classify.parse_justetf_countries(JUSTETF_ROWS) == pytest.approx(
    {'United States': 0.6, 'Other': 0.25, 'South Korea': 0.15})


def test_fund_countries_fall_back_to_unknown(monkeypatch):
  def fail(ticker):
    raise RuntimeError('LSE down')
  monkeypatch.setattr(classify, 'lse_isin', fail)
  assert classify._fund_countries('VWRP', 'VWRP.L', {}) == {'Unknown': 1.0}
  assert classify._fund_countries('XYZ', 'XYZ.DE', {}) == {'Unknown': 1.0}  # not in London, no ISIN given


def test_constituents_keep_only_the_biggest(monkeypatch):
  monkeypatch.setattr(classify, 'MAX_CONSTITUENTS', 2)
  result = classify._constituents([('A', 5, None, None), ('B', 3, None, None), ('C', 2, None, None), ('A', 0, None, None)])
  assert [(h['name'], h['weight']) for h in result] == pytest.approx([('A', 0.5), ('B', 0.3)])


@pytest.fixture
def fake_yahoo(monkeypatch):
  """A stand-in yfinance: `listings` are found, `flaky` raise once, anything else comes back empty."""
  import sys
  import types
  state = {'listings': {}, 'flaky': set(), 'down': False, 'calls': []}

  class Ticker:
    def __init__(self, symbol):
      self.symbol = symbol

    @property
    def info(self):
      state['calls'].append(self.symbol)
      if state['down'] or self.symbol in state['flaky']:
        state['flaky'].discard(self.symbol)
        raise RuntimeError('Too Many Requests')
      return state['listings'].get(self.symbol, {'trailingPegRatio': None})
  monkeypatch.setitem(sys.modules, 'yfinance', types.SimpleNamespace(Ticker=Ticker))
  monkeypatch.setattr(classify.time, 'sleep', lambda s: None)
  return state


def test_yahoo_lookup_uses_an_explicit_exchange_as_is(fake_yahoo):
  fake_yahoo['listings']['VWRP.L'] = {'quoteType': 'ETF', 'regularMarketPrice': 145.6, 'longName': 'Vanguard FTSE All-World'}
  fake_yahoo['flaky'].add('VWRP.L')
  assert classify.yahoo_lookup('VWRP.L')['symbol'] == 'VWRP.L'
  assert fake_yahoo['calls'] == ['VWRP.L', 'VWRP.L']  # retried once, never tried VWRP.L.L


def test_yahoo_lookup_tells_missing_from_failing(fake_yahoo):
  with pytest.raises(LookupError):
    classify.yahoo_lookup('NOPE')
  fake_yahoo['down'] = True
  with pytest.raises(RuntimeError, match="didn't answer"):
    classify.yahoo_lookup('VWRP.L')


def test_yahoo_sector_names_become_gics():
  assert classify.normalise_sector('Technology') == 'Information Technology'
  assert classify.normalise_sector('consumer_cyclical') == 'Consumer Discretionary'
  assert classify.normalise_sector('Financials') == 'Financials'


def test_cash_needs_no_lookup():
  result = classify.classify('GBP', 'Cash', {})
  assert result['kind'] == 'cash' and result['countries'] == {'Cash': 1.0}


def test_classify_holdings_caches_and_isolates_failures(tmp_path, monkeypatch):
  calls = []

  def fake_classify(asset, name, hint, prices=None):
    calls.append(asset)
    if asset == 'BAD':
      raise LookupError('nope')
    return {'kind': 'stock', 'name': name, 'symbol': asset, 'countries': {'United States': 1.0},
            'sectors': {'Financials': 1.0}, 'source': 'yahoo', 'price_gbp': 1.0}
  monkeypatch.setattr(classify, 'classify', fake_classify)
  store = Store(tmp_path / 'db.sqlite')

  result = asyncio.run(classify.classify_holdings(store, [('MSTR', 'Strategy'), ('BAD', None)], {}))
  assert result['MSTR']['countries'] == {'United States': 1.0}
  assert result['BAD']['kind'] == 'unknown' and 'nope' in result['BAD']['error']

  asyncio.run(classify.classify_holdings(store, [('MSTR', 'Strategy'), ('BAD', None)], {}))
  assert calls == ['MSTR', 'BAD']  # both cached, including the failure

  # changing the account's look_through hint for an asset invalidates its cache entry
  asyncio.run(classify.classify_holdings(store, [('MSTR', 'Strategy')], {'MSTR': {'yahoo': 'MSTR'}}))
  assert calls == ['MSTR', 'BAD', 'MSTR']


def test_stale_cache_is_refreshed():
  old = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
  fresh = datetime.now(timezone.utc).isoformat()
  assert not classify._fresh({'hint': {}, 'fetched_at': old, 'version': classify.CACHE_VERSION}, {})
  assert classify._fresh({'hint': {}, 'fetched_at': fresh, 'version': classify.CACHE_VERSION}, {})
  assert not classify._fresh({'hint': {}, 'fetched_at': fresh}, {})  # cached by an older version


@pytest.fixture
def client(tmp_path, monkeypatch):
  async def fake_classify_holdings(store, holdings, look_through, prices=None):
    return {asset: {'kind': 'stock', 'look_through': look_through.get(asset)} for asset, _ in holdings}
  monkeypatch.setattr(classify, 'classify_holdings', fake_classify_holdings)

  config = Config([
    AccountConfig('ISA', 'manual', 'investments', 15, {'look_through': {'EMIM': {'ishares': 1}}}),
    AccountConfig('Bank', 'manual', 'cash', 15, {}),
  ], data_dir=tmp_path)
  store = Store(config.db_path)
  store.write_run('2026-10-01T00:00:00+00:00', [
    SnapshotRow('ISA', 'investments', Holding('EMIM', 10, 400, 'GBP', 'iShares plc'), 40, 400, '2026-10-01T00:00:00+00:00'),
    SnapshotRow('Bank', 'cash', Holding('GBP', 100), 1, 100, '2026-10-01T00:00:00+00:00'),
  ])
  store.conn.close()
  return TestClient(create_app(config, run_scheduler=False))


def test_account_detail(client):
  isa = client.get('/api/accounts/ISA').json()
  assert isa['value'] == 400
  assert isa['classifications']['EMIM']['look_through'] == {'ishares': 1}
  # only investment accounts get country/sector lookups
  assert client.get('/api/accounts/Bank').json()['classifications'] == {}
  assert client.get('/api/accounts/Nope').status_code == 404


def test_unknown_api_paths_are_not_swallowed_by_the_spa(client):
  assert client.get('/api/nope').status_code == 404
  assert client.get('/accounts/ISA').status_code in (200, 503)  # index.html, or "not built"
