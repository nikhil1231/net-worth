import asyncio
import pytest

from networth import reports
from networth.config import AccountConfig, Config
from networth.connectors import dex
from networth.connectors.token_prices import token_usd_price
from networth.models import Holding
from networth.pricing import PriceBook
from networth.store import SnapshotRow, Store, now


def test_intentx_open_positions_do_not_misreport_collateral_as_equity(monkeypatch, tmp_path):
  async def call(reader, contract, selector, arg):
    return 1 if selector == '0xec8e7124' else 10 ** 18
  monkeypatch.setattr(dex, 'uint_call', call)
  config = AccountConfig('IntentX', 'intentx', 'crypto', 15,
    {'wallet': 'owner', 'subaccount': '0x' + 'b' * 40, 'settlement': 'test', 'rpc_url': 'test'})
  with pytest.raises(RuntimeError, match='PnL'):
    asyncio.run(dex.IntentX(config, tmp_path).fetch())


def test_drift_claim_subtracts_claimed_and_is_excluded_from_total(tmp_path):
  rows = [{'claimant': 'mrq', 'claimable_amount': '3246374', 'claimed_amount': '1000000'}]
  quantity = dex.unclaimed_dfx(rows, 'mrq')
  assert quantity == pytest.approx(2.246374)
  with pytest.raises(RuntimeError, match='mismatch'):
    dex.unclaimed_dfx(rows, 'other')
  holding = Holding('DFX-CLAIM', quantity)
  assert PriceBook({'USD': 1}).value(holding) == (None, None)
  config = Config([AccountConfig('Drift', 'drift_recovery', 'crypto', 15,
                    {'note': 'Unclaimed recovery', 'coverage': 'unpriced'})], data_dir=tmp_path)
  store = Store(config.db_url)
  store.write_run(now(), [SnapshotRow('Drift', 'crypto', holding, None, None, now()),
                         SnapshotRow('Drift', 'crypto', Holding('EMPTY', 0), None, None, now())])
  result = reports.summary(store, config)
  assert result['total'] == 0
  assert result['accounts'][0]['unpriced'][0]['quantity'] == quantity
  assert len(result['accounts'][0]['unpriced']) == 1


def test_quote_selects_exact_mint_even_when_other_pair_has_more_liquidity(monkeypatch):
  async def get(*args, **kwargs):
    return [
      {'baseToken': {'address': 'wrong'}, 'priceUsd': '100', 'liquidity': {'usd': 10000}},
      {'baseToken': {'address': 'mint'}, 'priceUsd': '0.01', 'liquidity': {'usd': 50}}]
  monkeypatch.setattr(dex.http, 'get_json', get)
  token = {'symbol': 'WOOF', 'mint': 'mint', 'price_url': 'test', 'price_source': 'dexscreener'}
  assert asyncio.run(token_usd_price(token, 200000)) == 2000


def test_failed_quote_leaves_token_unpriced_instead_of_failing(monkeypatch):
  async def get(*args, **kwargs):
    raise RuntimeError('403 Forbidden')
  monkeypatch.setattr(dex.http, 'get_json', get)
  token = {'symbol': 'OX', 'contract': '0x', 'price_url': 'test'}
  assert asyncio.run(token_usd_price(token, 5)) is None


def test_chain_details_keep_protocol_value_and_unpriced_claim_without_extra_accounts(tmp_path):
  config = Config([AccountConfig('Wallets', 'evm', 'crypto', 15)], data_dir=tmp_path)
  store = Store(config.db_url)
  ts = now()
  holdings = [
    Holding('USDC', 1, name='Base', wallet='owner', chain='Base'),
    Holding('USDC', 690, name='IntentX collateral', wallet='owner', chain='Base'),
    Holding('DFX-CLAIM', 3, wallet='owner', chain='Solana'),
  ]
  store.write_run(ts, [SnapshotRow('Wallets', 'crypto', h, None,
                       None if h.asset == 'DFX-CLAIM' else h.quantity, ts) for h in holdings])
  base = reports.chain_details(store, config, 'Wallets', 'Base')
  assert base['value'] == 691
  assert len(base['holdings']) == 1
  assert 'IntentX' in base['holdings'][0]['name']
  assert reports.chain_details(store, config, 'Wallets', 'Solana')['unpriced'][0]['quantity'] == 3
  assert len(reports.summary(store, config)['accounts']) == 1
  assert reports.summary(store, config)['total'] == 691
  with pytest.raises(ValueError, match='No holdings'):
    reports.chain_details(store, config, 'Wallets', 'HyperEVM')


def test_protocol_sources_inherit_wallet_account_and_keep_chain(monkeypatch, tmp_path):
  async def fetch(self):
    return [Holding('DFX-CLAIM', 3, wallet=self.param('wallet'), chain='Solana')]
  monkeypatch.setattr(dex.DriftRecovery, 'fetch', fetch)
  account = AccountConfig('Solana wallets', 'solana', 'crypto', 15,
    {'positions': [{'type': 'drift_recovery', 'params': {'wallet': 'mrq'}}]})
  holdings = asyncio.run(dex.fetch_positions(account, tmp_path))
  assert [(h.wallet, h.chain, h.quantity) for h in holdings] == [('mrq', 'Solana', 3)]
  assert account.type == 'solana'


def test_wallet_price_uses_combined_contract_values_not_first_empty_slot(tmp_path):
  config = Config([AccountConfig('SOL', 'solana', 'crypto', 15)], data_dir=tmp_path)
  store = Store(config.db_url)
  ts = now()
  store.write_run(ts, [
    SnapshotRow('SOL', 'crypto', Holding('JUP', 0), 0.00001, 0, ts),
    SnapshotRow('SOL', 'crypto', Holding('JUP', 50, value=16.4, currency='USD'), 0.248, 12.4, ts)])
  h = reports.summary(store, config)['accounts'][0]['holdings'][0]
  assert h['price'] == pytest.approx(0.248)
  assert h['value'] == 12.4
