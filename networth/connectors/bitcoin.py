import asyncio

from networth import http
from networth.connectors.base import Connector, Field, connector
from networth.models import Holding, from_units


@connector('bitcoin')
class BitcoinWallet(Connector):
  """
  params:
    addresses: list of BTC addresses
  """
  label = 'Bitcoin wallet'
  fields = [Field('addresses', 'Addresses', 'list', required=True, placeholder='bc1q...')]

  async def fetch(self):
    addresses = self.param('addresses')
    sats = await asyncio.gather(*[
      http.get_json(f'https://blockchain.info/q/addressbalance/{addr}') for addr in addresses
    ])
    return [Holding('BTC', from_units(value, 8), wallet=address, chain='Bitcoin')
            for address, value in zip(addresses, sats)]
