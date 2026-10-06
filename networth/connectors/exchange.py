import ccxt.async_support as ccxt

from networth.config import ConfigError
from networth.connectors.base import Connector, Field, connector
from networth.models import Holding


@connector('exchange')
class Exchange(Connector):
  """
  Any exchange ccxt supports (binance, coinbase, kraken, ...). Use read-only API keys.

  params:
    exchange: ccxt exchange id
    api_key, secret: credentials (Coinbase: CDP key name + PEM private key)
    password: for exchanges that need a passphrase
    wallets: optional list of balance types to sum, e.g. [spot, funding] on Binance
    options: optional dict passed through to ccxt's `options`
  """
  label = 'Exchange'
  fields = [
    Field('exchange', 'Exchange', required=True, help='ccxt id: binance, coinbase, kraken...', placeholder='binance'),
    Field('api_key', 'API key', 'secret', required=True, help='Read-only. A ${VAR} keeps it in .env'),
    Field('secret', 'API secret', 'secret', required=True),
    Field('password', 'Passphrase', 'secret', help='Only for exchanges that need one'),
    Field('wallets', 'Wallets', 'list', help='Balance types to sum, e.g. spot and funding on Binance'),
    Field('options', 'ccxt options', 'yaml'),
  ]

  async def fetch(self):
    exchange_id = self.param('exchange')
    if not hasattr(ccxt, exchange_id):
      raise ConfigError(f'{self.account.name}: unknown ccxt exchange {exchange_id!r}')

    client = getattr(ccxt, exchange_id)({
      'apiKey': self.param('api_key'),
      'secret': self.param('secret'),
      'password': self.param('password', None),
      'enableRateLimit': True,
      'options': self.param('options', {}),
    })
    try:
      wallets = self.param('wallets', None)
      if wallets:
        balances = [await client.fetch_balance({'type': wallet}) for wallet in wallets]
      else:
        balances = [await client.fetch_balance()]
    finally:
      await client.close()

    totals: dict[str, float] = {}
    for balance in balances:
      for asset, amount in balance['total'].items():
        if amount:
          totals[asset] = totals.get(asset, 0) + amount

    return [Holding(asset, amount) for asset, amount in totals.items()]
