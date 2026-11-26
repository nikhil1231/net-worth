import asyncio
from decimal import Decimal

from networth import http
from networth.connectors.base import Connector, Field, connector
from networth.models import Holding, from_units
from networth.connectors.token_prices import token_usd_price

DEFAULT_RPC = 'https://api.mainnet-beta.solana.com'
TOKEN_PROGRAMS = [
  'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA',  # SPL Token
  'TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb',  # Token-2022
]


@connector('solana')
class SolanaWallet(Connector):
  """
  params:
    addresses: list of SOL addresses
    tokens: optional list of {symbol, mint} SPL tokens to include
    rpc_url: default public mainnet RPC
  """
  label = 'Solana wallet'
  fields = [
    Field('positions', 'Protocol holdings', 'yaml', help='Read-only protocol balances belonging to these wallets'),
    Field('addresses', 'Addresses', 'list', required=True),
    Field('tokens', 'SPL tokens', 'yaml', help='Tokens to include besides SOL, each {symbol, mint}',
          placeholder='- {symbol: USDC, mint: EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v}'),
    Field('rpc_url', 'RPC URL', placeholder=DEFAULT_RPC),
  ]

  async def fetch(self):
    addresses = self.param('addresses')
    tokens = self.param('tokens', [])

    lamports = await asyncio.gather(*[
      self._rpc('getBalance', [addr, {'commitment': 'finalized'}]) for addr in addresses
    ])
    holdings = [Holding('SOL', from_units(r['value'], 9), wallet=addr, chain='Solana')
                for addr, r in zip(addresses, lamports)]

    if tokens:
      # The public RPC rejects mint-filtered lookups, so fetch every token account per program
      # and pick out the configured mints here.
      results = await asyncio.gather(*[
        self._rpc('getTokenAccountsByOwner', [addr, {'programId': program}, {'encoding': 'jsonParsed'}])
        for addr in addresses for program in TOKEN_PROGRAMS
      ])
      for i, addr in enumerate(addresses):
        amounts: dict[str, Decimal] = {}
        for r in results[i * len(TOKEN_PROGRAMS):(i + 1) * len(TOKEN_PROGRAMS)]:
          for acc in r['value']:
            info = acc['account']['data']['parsed']['info']
            amount = info['tokenAmount']  # the raw integer string, not the float uiAmount
            amounts[info['mint']] = amounts.get(info['mint'], 0) + from_units(amount['amount'], amount['decimals'])
        for token in tokens:
          quantity = amounts.get(token['mint'], 0)
          value = await token_usd_price(token, quantity)
          holdings.append(Holding(token['symbol'], quantity, value=value, currency='USD',
                                  wallet=addr, chain='Solana'))

    from networth.connectors.dex import fetch_positions
    holdings += await fetch_positions(self.account, self.data_dir)
    return holdings

  async def _rpc(self, method, params):
    data = {'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params}
    res = await http.post_json(self.param('rpc_url', DEFAULT_RPC), json=data)
    if 'error' in res:
      raise RuntimeError(f'Solana RPC error: {res["error"]}')
    return res['result']
