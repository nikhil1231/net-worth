import asyncio
import os

from networth import lunchflow
from networth.config import ConfigError
from networth.connectors.base import Connector, Field, connector
from networth.models import Holding


@connector('lunchflow')
class LunchFlow(Connector):
  """
  A bank account or card balance via the Lunch Flow Personal API (the same feed spending syncs from).

  The balance is signed from the account holder's side: money owed on a credit card is negative.

  params:
    account_id: the Lunch Flow account ID (Spending → gear icon → Bank connections lists them)
    account_ids: several IDs to group into one account, e.g. the Amex cards (one holding each)
    api_key: default LUNCHFLOW_API_KEY from the environment (.env)
  """
  label = 'Lunch Flow'
  fields = [
    Field('account_id', 'Lunch Flow account ID', help='Or group several accounts below'),
    Field('account_ids', 'Grouped Lunch Flow account IDs', 'list', help='One per line; each becomes a holding in this account'),
    Field('api_key', 'API key', 'secret', placeholder='${LUNCHFLOW_API_KEY}'),
  ]

  async def fetch(self):
    key = (self.param('api_key', None) or os.environ.get('LUNCHFLOW_API_KEY', '')).strip()
    ids = self.param('account_ids', None)
    if ids is None:
      return [await self._balance(str(self.param('account_id')), key)]
    if not isinstance(ids, list) or not ids:
      raise ConfigError(f'{self.account.name}: account_ids must list at least one Lunch Flow account')
    if self.account.params.get('account_id') not in (None, ''):
      raise ConfigError(f'{self.account.name}: use either account_id or account_ids, not both')
    ids = [str(i) for i in ids]
    names = {a['id']: a['name'] for a in await lunchflow.discover(key)}
    balances = await asyncio.gather(*(self._balance(i, key) for i in ids))
    return [Holding(h.asset, h.quantity, name=names.get(i, i)) for i, h in zip(ids, balances)]

  async def _balance(self, account_id: str, key: str) -> Holding:
    res = await lunchflow.get(f'/accounts/{account_id}/balance', key)
    balance = res['balance']
    return Holding(balance['currency'] or 'GBP', float(balance['amount']))
