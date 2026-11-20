import pytest

from networth.config import AccountConfig, ConfigError
from networth.connectors import hl as hl_module
from networth.connectors.hl import HargreavesLansdown, _find_hl_vt, parse_cash, parse_holdings

SUMMARY_HTML = '''
<table class="table-summary" summary="Current valuation of this account">
  <tfoot><tr><td>Total  value</td><td id="account_total_header" class="aRight">£12,345.67</td></tr></tfoot>
  <tbody>
    <tr><td>Stock value</td><td id="stock_total_header" class="aRight">£10,000.00</td></tr>
    <tr>
      <td>
        Total cash
      </td>
      <td id="cash_total_header" class="aRight">
          £2,345.67
      </td>
    </tr>
  </tbody>
</table>
'''


def test_parse_cash():
  assert parse_cash(SUMMARY_HTML) == pytest.approx(2345.67)


def test_parse_cash_missing():
  with pytest.raises(RuntimeError):
    parse_cash('<html></html>')


HOLDINGS_HTML = '''
<table id="holdings-table">
  <tbody>
    <tr>
      <td>VWRL</td>
      <td><span class="text-bold">Vanguard FTSE All-World</span></td>
      <td>1,234.5</td>
      <td>10,512.00p</td>
      <td>£129,770.64</td>
      <td>£ 100,000.00</td>
    </tr>
  </tbody>
</table>
'''


def test_parse_holdings_strips_currency_symbols():
  [row] = parse_holdings(HOLDINGS_HTML)
  assert row['ticker'] == 'VWRL'
  assert row['stock_name'] == 'Vanguard FTSE All-World'
  assert row['units'] == pytest.approx(1234.5)
  assert row['price_pence'] == pytest.approx(10512.0)
  assert row['value_gbp'] == pytest.approx(129770.64)
  assert row['cost_gbp'] == pytest.approx(100000.0)


def test_parse_holdings_empty_account():
  assert parse_holdings('<table id="holdings-table"></table>') == []


def test_parse_holdings_unreadable_number():
  with pytest.raises(RuntimeError, match='could not read a number'):
    parse_holdings(HOLDINGS_HTML.replace('1,234.5', 'n/a'))


def test_find_hl_vt_missing():
  with pytest.raises(RuntimeError, match='login step one'):
    _find_hl_vt('<html></html>', 'login step one')


STEP_TWO_HTML = '''
<input name="hl_vt" value="token">
<div class="secure-number-container__label">1st digit</div>
<div class="secure-number-container__label">4th digit</div>
<div class="secure-number-container__label">6th digit</div>
'''


def _hl(tmp_path, secure_number):
  account = AccountConfig(name='HL', type='hl', category='investments', interval=240,
                          params={'password': 'pw', 'secure_number': secure_number})
  return HargreavesLansdown(account, tmp_path)


class FakeSession:
  def post(self, url, data, **kwargs):
    self.data = data


def test_login_step_two_keeps_leading_zero(tmp_path):
  session = FakeSession()
  _hl(tmp_path, '012345')._login_step_two(session, STEP_TWO_HTML)
  assert [session.data[f'secure-number[{i}]'] for i in (1, 2, 3)] == ['0', '3', '5']


def test_login_step_two_rejects_unquoted_secure_number(tmp_path):
  with pytest.raises(ConfigError, match='quoted string'):
    _hl(tmp_path, 12345)._login_step_two(FakeSession(), STEP_TWO_HTML)


def test_login_step_two_without_prompts(tmp_path):
  with pytest.raises(RuntimeError, match='secure number prompts not found'):
    _hl(tmp_path, '012345')._login_step_two(FakeSession(), '<input name="hl_vt" value="t">')


def test_login_drops_expired_cookies(tmp_path, monkeypatch):
  hl = _hl(tmp_path, '012345')
  hl._save_cookies(type('S', (), {'cookies': type('C', (), {'get_dict': lambda self: {'HLWEBsession': 'dead'}})()})())
  seen = []

  def fake_step_one(session):
    seen.append(session.cookies.get_dict())
    return STEP_TWO_HTML

  monkeypatch.setattr(hl_module, 'is_authed', lambda session: bool(seen))  # logged out until we log in
  monkeypatch.setattr(hl, '_login_step_one', fake_step_one)
  monkeypatch.setattr(hl, '_login_step_two', lambda session, html: None)
  hl._login()
  assert seen == [{}]


class FakeResponse:
  def __init__(self, body):
    self.body = body

  def json(self):
    return self.body


class FakeGetSession:
  def __init__(self, body):
    self.body = body

  def get(self, url, **kwargs):
    return FakeResponse(self.body)


@pytest.mark.parametrize('body, authed', [
  (1234567, True),                  # logged in: a bare client id
  ({'client_id': 1234567}, True),   # older response shape
  (False, False),                   # logged out
  ({'client_id': False}, False),
  (None, False),
])
def test_is_authed(body, authed):
  assert hl_module.is_authed(FakeGetSession(body)) is authed
