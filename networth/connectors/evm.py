import asyncio
import os

from networth import http
from networth.config import ConfigError
from networth.connectors.base import Connector, Field, connector
from networth.models import Holding
from networth.connectors.token_prices import token_usd_quote

ETHERSCAN_URL = 'https://api.etherscan.io/v2/api'
DEFAULT_TOKENS = [
  {'symbol': 'USDC', 'contract': '0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48', 'decimals': 6},
]
# Etherscan's free tier allows 3 calls a second per key; leave room for network jitter.
CALL_SPACING_SECONDS = 0.4
BALANCE_OF_SELECTOR = '0x70a08231'


@connector('evm')
class EvmWallet(Connector):
  """
  Native + ERC-20 balances for a set of addresses across one or more EVM chains.

  Each chain is read via Etherscan v2 by default, or via a JSON-RPC node if `rpc_url` is set
  (for chains Etherscan's free tier doesn't cover, e.g. Base, BSC).

  params:
    addresses: list of 0x addresses
    api_key: Etherscan key, default ${ETHERSCAN} from the environment
    chains: list of chains, each:
      name: shown against each holding, e.g. Arbitrum
      chain_id: default 1
      native_symbol: default ETH
      tokens: list of {symbol, contract, decimals}; default USDC on mainnet, none elsewhere
      rpc_url: optional JSON-RPC endpoint to use instead of Etherscan
    If `chains` is omitted, chain_id / native_symbol / tokens / rpc_url can be given directly
    for a single chain.
  """
  label = 'EVM wallet (Ethereum, Arbitrum, Base...)'
  fields = [
    Field('positions', 'Protocol holdings', 'yaml', help='Read-only protocol balances belonging to these wallets'),
    Field('addresses', 'Addresses', 'list', required=True, placeholder='0x...'),
    Field('api_key', 'Etherscan API key', 'secret', help='Leave empty to use ETHERSCAN from .env'),
    Field('chains', 'Chains', 'yaml', help='One entry per chain: name, chain_id, native_symbol, tokens, rpc_url. '
                                           'Leave empty for Ethereum mainnet (ETH + USDC).',
          placeholder='- name: Ethereum\n- name: Arbitrum\n  chain_id: 42161'),
  ]

  async def fetch(self):
    chains = self.param('chains', None) or [{
      key: self.account.params[key]
      for key in ('chain_id', 'native_symbol', 'tokens', 'rpc_url') if key in self.account.params
    }]
    per_chain = await asyncio.gather(*[self._fetch_chain(chain) for chain in chains])
    holdings = [h for chain_holdings in per_chain for h in chain_holdings]
    from networth.connectors.dex import fetch_positions
    holdings += await fetch_positions(self.account, self.data_dir)
    return holdings

  async def _fetch_chain(self, chain):
    addresses = self.param('addresses')
    chain_id = chain.get('chain_id', 1)
    tokens = chain.get('tokens', DEFAULT_TOKENS if chain_id == 1 else [])
    reader = RpcReader(chain['rpc_url']) if chain.get('rpc_url') else EtherscanReader(self._api_key(), chain_id)
    name = chain.get('name') or ('Ethereum' if chain_id == 1 else f'Chain {chain_id}')

    natives, raw = await asyncio.gather(
      reader.native_balances(addresses),
      asyncio.gather(*[reader.token_balance([a], t['contract']) for a in addresses for t in tokens]))
    quantities = [[raw[i * len(tokens) + j] / 10 ** t['decimals'] for j, t in enumerate(tokens)]
                  for i in range(len(addresses))]
    # One quote per token, and only for tokens someone actually holds.
    held = [j for j in range(len(tokens)) if any(q[j] for q in quantities)]
    prices = dict(zip(held, await asyncio.gather(*[token_usd_quote(tokens[j]) for j in held])))

    holdings = []
    for address, native, amounts in zip(addresses, natives, quantities):
      holdings.append(Holding(chain.get('native_symbol', 'ETH'), native / 1e18,
                              name=name, wallet=address, chain=name))
      for j, (token, quantity) in enumerate(zip(tokens, amounts)):
        price = prices.get(j)
        holdings.append(Holding(token['symbol'], quantity, value=price * quantity if price is not None else None,
                                currency='USD', name=name, wallet=address, chain=name))
    return holdings

  def _api_key(self):
    api_key = self.param('api_key', None) or os.getenv('ETHERSCAN')
    if not api_key:
      raise ConfigError(f'{self.account.name}: no Etherscan api_key (set ETHERSCAN in .env)')
    return api_key


class EtherscanReader:
  # When the next call may start. Shared, since every chain is read with the same key and rate limit.
  _next_slot = 0.0

  def __init__(self, api_key, chain_id):
    self.api_key = api_key
    self.chain_id = chain_id

  async def native_balances(self, addresses):
    """Per-address balances, in one call."""
    res = await self._call({'action': 'balancemulti', 'address': ','.join(addresses)})
    by_address = {r['account'].lower(): int(r['balance']) for r in res}
    return [by_address[a.lower()] for a in addresses]

  async def token_balance(self, addresses, contract):
    results = await asyncio.gather(*[
      self._call({'action': 'tokenbalance', 'contractAddress': contract, 'address': addr}) for addr in addresses])
    return sum(int(r) for r in results)

  async def _throttle(self):
    now = asyncio.get_running_loop().time()
    slot = max(now, EtherscanReader._next_slot)
    EtherscanReader._next_slot = slot + CALL_SPACING_SECONDS
    await asyncio.sleep(slot - now)

  async def _call(self, params, retries=2):
    await self._throttle()
    params = {
      'chainid': self.chain_id,
      'module': 'account',
      'tag': 'latest',
      'apikey': self.api_key,
    } | params
    res = await http.get_json(ETHERSCAN_URL, params=params)
    if res.get('status') != '1':
      if retries and 'rate limit' in str(res.get('result', '')).lower():
        await asyncio.sleep(1)
        return await self._call(params, retries - 1)
      raise RuntimeError(f'Etherscan error (chain {self.chain_id}): {res.get("message")}: {res.get("result")}')
    return res['result']


class RpcReader:
  def __init__(self, url):
    self.url = url

  async def native_balances(self, addresses):
    results = await asyncio.gather(*[self._call('eth_getBalance', [addr, 'latest']) for addr in addresses])
    return [int(r, 16) for r in results]

  async def token_balance(self, addresses, contract):
    results = await asyncio.gather(*[
      self._call('eth_call', [{'to': contract, 'data': BALANCE_OF_SELECTOR + addr[2:].lower().rjust(64, '0')}, 'latest'])
      for addr in addresses
    ])
    if '0x' in results:
      raise RuntimeError(f'No token contract at {contract} on {self.url} - wrong chain?')
    return sum(int(r, 16) for r in results)

  async def _call(self, method, params):
    res = await http.post_json(self.url, json={'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params})
    if 'error' in res:
      raise RuntimeError(f'RPC error from {self.url}: {res["error"]}')
    return res['result']
