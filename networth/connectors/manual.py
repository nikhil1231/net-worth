from networth.connectors.base import Connector, Field, connector
from networth.models import Holding, to_decimal


@connector('manual')
class Manual(Connector):
  """
  Values typed into accounts.yaml, for anything without an API.

  params, either:
    value: 1234.56
    currency: default GBP
  or:
    holdings: list of {asset, quantity, name?}, priced like any other holding
  """
  label = 'Manual value'
  fields = [
    Field('value', 'Value', 'number', help='Or list holdings below instead'),
    Field('currency', 'Currency', placeholder='GBP', default='GBP'),
    Field('holdings', 'Holdings', 'yaml', help='Each {asset, quantity, name?}, priced like any other holding',
          placeholder='- {asset: BTC, quantity: 0.1}'),
  ]

  async def fetch(self):
    if 'value' in self.account.params:
      return [Holding(self.param('currency', 'GBP'), to_decimal(self.param('value')))]
    return [
      Holding(h['asset'], to_decimal(h['quantity']), name=h.get('name'))
      for h in self.param('holdings')
    ]
