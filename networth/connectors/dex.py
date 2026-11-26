"""Public, read-only collateral and recovery balances. Never signs transactions."""
import asyncio

from networth import http
from networth.connectors.base import Connector, Field, connector
from networth.connectors.evm import RpcReader
from networth.models import Holding, from_units


async def uint_call(reader, contract, selector, argument):
  result = await reader._call('eth_call', [
    {'to': contract, 'data': selector + argument.rjust(64, '0')}, 'latest'])
  if result == '0x':
    raise RuntimeError('Contract returned no data')
  return int(result, 16)


@connector('intentx')
class IntentX(Connector):
  label = 'IntentX collateral (read only)'
  fields = [
    Field('wallet', 'Owner wallet', required=True),
    Field('subaccount', 'Subaccount', required=True),
    Field('settlement', 'Settlement contract', required=True),
    Field('rpc_url', 'Base RPC URL', required=True),
  ]

  async def fetch(self):
    reader = RpcReader(self.param('rpc_url'))
    contract, address = self.param('settlement'), self.param('subaccount')
    arg = address[2:].lower()
    positions, balance, allocated = await asyncio.gather(*[
      uint_call(reader, contract, selector, arg)
      for selector in ('0xec8e7124', '0x70a08231', '0x5e4a0a31')
    ])
    if positions:
      raise RuntimeError('Open IntentX positions need PnL valuation; previous collateral value retained')
    quantity = from_units(balance + allocated, 18)
    return [Holding('USDC', quantity, name='IntentX beans123 collateral',
                    wallet=self.param('wallet'), chain='Base')]


def unclaimed_dfx(rows, wallet):
  if not isinstance(rows, list):
    raise RuntimeError('Unexpected Drift eligibility response')
  amount = 0
  for row in rows:
    if row['claimant'] != wallet:
      raise RuntimeError('Drift eligibility claimant mismatch')
    amount += max(0, int(row['claimable_amount']) - int(row['claimed_amount']))
  return from_units(amount, 6)


@connector('drift_recovery')
class DriftRecovery(Connector):
  label = 'Drift DFX recovery claim (unpriced)'
  fields = [Field('wallet', 'Solana wallet', required=True)]

  async def fetch(self):
    wallet = self.param('wallet')
    rows = await http.get_json(f'https://dfx.drift.trade/api/eligibility/{wallet}')
    amount = unclaimed_dfx(rows, wallet)
    # Separate from tradable DFX and frozen legacy USDC. No assumed face value.
    return [Holding('DFX-CLAIM', amount, name='Unclaimed DFX recovery allocation',
                    wallet=wallet, chain='Solana')] if amount else []


async def fetch_positions(account, data_dir):
  from dataclasses import replace
  from networth.connectors.base import get_connector_class
  holdings = []
  for position in account.params.get('positions', []):
    child = replace(account, type=position['type'], params=position['params'])
    holdings += await get_connector_class(child.type)(child, data_dir).fetch()
  return holdings
