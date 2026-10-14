import os

from networth import lunchflow
from networth.connectors.base import Connector, Field, connector
from networth.models import Holding


@connector('lunchflow')
class LunchFlow(Connector):
  """
  A bank account or card balance via the Lunch Flow Personal API (the same feed spending syncs from).

  The balance is signed from the account holder's side: money owed on a credit card is negative.

  params:
    account_id: the Lunch Flow account ID (Spending → gear icon → Bank connections lists them)
    api_key: default LUNCHFLOW_API_KEY from the environment (.env)
  """
  label = 'Lunch Flow'
  fields = [
    Field('account_id', 'Lunch Flow account ID', required=True),
    Field('api_key', 'API key', 'secret', placeholder='${LUNCHFLOW_API_KEY}'),
  ]

  async def fetch(self):
    key = self.param('api_key', None) or os.environ.get('LUNCHFLOW_API_KEY', '')
    res = await lunchflow.get(f"/accounts/{self.param('account_id')}/balance", key.strip())
    balance = res['balance']
    return [Holding(balance['currency'] or 'GBP', float(balance['amount']))]
