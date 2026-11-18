import asyncio
import os
from networth.config import AccountConfig, Config
from networth.models import Holding
from networth.store import Store, SnapshotRow, now
from networth import reports
from networth.connectors.evm import EvmWallet, RpcReader
from networth.connectors.solana import SolanaWallet, TOKEN_PROGRAMS


def test_wallet_attribution(tmp_path):
  store = Store(os.environ['DATABASE_URL'])
  config = Config([AccountConfig('EVM wallets', 'evm', 'crypto', 15, {'addresses': ['a', 'b']})], data_dir=tmp_path)
  ts = now()
  store.write_run(ts, [SnapshotRow('EVM wallets', 'crypto', Holding('ETH', 3), 10, 30, ts)])
  assert not reports.wallet_details(store, config, 'EVM wallets')['wallet_breakdown_available']
  holdings = [Holding('ETH', 1, name='Ethereum', wallet='a', chain='Ethereum'),
              Holding('ETH', 2, name='Base', wallet='b', chain='Base'),
              Holding('NO_PRICE', 4, wallet='b', chain='Base')]
  store.write_run(ts, [SnapshotRow('EVM wallets', 'crypto', h, 10 if h.asset == 'ETH' else None,
                                  h.quantity * 10 if h.asset == 'ETH' else None, ts) for h in holdings])
  saved, _ = store.last_holdings('EVM wallets')
  assert [(h.wallet, h.chain) for h in saved] == [('a', 'Ethereum'), ('b', 'Base'), ('b', 'Base')]
  detail = reports.wallet_details(store, config, 'EVM wallets')
  assert detail['wallet_breakdown_available']
  assert [w['value'] for w in detail['wallets']] == [10, 20]
  assert detail['wallets'][1]['holdings'][1]['value'] is None
  summary = reports.summary(store, config)
  assert summary['total'] == 30
  assert len(summary['accounts'][0]['holdings']) == 1
  assert summary['accounts'][0]['holdings'][0]['quantity'] == 3
  store.rename_account('EVM wallets', 'Renamed')
  assert len(store.last_holdings('Renamed')[0]) == 3


def test_evm_keeps_address_and_chain(monkeypatch, tmp_path):
  async def native(self, addresses):
    return [{'a': 10**18, 'b': 2*10**18}[a] for a in addresses]
  async def token(self, addresses, contract):
    return {'a': 10**6, 'b': 2*10**6}[addresses[0]]
  monkeypatch.setattr(RpcReader, 'native_balances', native)
  monkeypatch.setattr(RpcReader, 'token_balance', token)
  account = AccountConfig('EVM', 'evm', 'crypto', 15, {'addresses': ['a', 'b'], 'chains': [
    {'name': 'Base', 'chain_id': 8453, 'rpc_url': 'test', 'tokens': [{'symbol': 'USDC', 'contract': 'x', 'decimals': 6}]}]})
  h = asyncio.run(EvmWallet(account, tmp_path).fetch())
  assert [(x.wallet, x.chain, x.asset, x.quantity) for x in h] == [
    ('a', 'Base', 'ETH', 1), ('a', 'Base', 'USDC', 1), ('b', 'Base', 'ETH', 2), ('b', 'Base', 'USDC', 2)]


def test_solana_token_programs_stay_with_owner(monkeypatch, tmp_path):
  async def rpc(self, method, params):
    if method == 'getBalance': return {'value': 10**9}
    amount = (2 if params[0] == 'a' else 7) if params[1]['programId'] == TOKEN_PROGRAMS[0] else 1
    return {'value': [{'account': {'data': {'parsed': {'info': {'mint': 'mint', 'tokenAmount': {'uiAmount': amount}}}}}}]}
  monkeypatch.setattr(SolanaWallet, '_rpc', rpc)
  account = AccountConfig('SOL', 'solana', 'crypto', 15, {'addresses': ['a', 'b'], 'tokens': [{'symbol': 'USDC', 'mint': 'mint'}]})
  h = asyncio.run(SolanaWallet(account, tmp_path).fetch())
  assert [(x.wallet, x.quantity) for x in h if x.asset == 'USDC'] == [('a', 3), ('b', 8)]


def test_wallet_detail_separates_usdc_owners_and_preserves_token_links(tmp_path):
  addresses = ['wallet-4DD', 'wallet-9F3']
  config = Config([AccountConfig('EVM', 'evm', 'crypto', 15, {'addresses': addresses})], data_dir=tmp_path)
  store = Store(config.db_url)
  ts = now()
  holdings = [
    Holding('USDC', 415.110072, wallet=addresses[0], chain='Ethereum'),
    Holding('USDC', 2979.964906, wallet=addresses[1], chain='Ethereum'),
    Holding('USDC', 10, wallet=addresses[0], chain='Base'),
  ]
  store.write_run(ts, [SnapshotRow('EVM', 'crypto', h, 0.75, h.quantity * 0.75, ts) for h in holdings])
  detail = reports.crypto_details(store, config, 'EVM', wallet=addresses[0])
  assert detail['parent_account'] == 'EVM'
  assert detail['holdings'][0]['quantity'] == 425.110072
  assert {h['wallet'] for h in detail['holdings'][0]['locations']} == {addresses[0]}
  assert {h['chain'] for h in detail['holdings'][0]['locations']} == {'Ethereum', 'Base'}
  combined = reports.summary(store, config)['accounts'][0]['holdings'][0]
  assert {h['wallet'] for h in combined['locations']} == set(addresses)
  assert len(detail['wallets']) == 1
