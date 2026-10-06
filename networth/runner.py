import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

from networth.config import AccountConfig, Config, ConfigError
from networth.connectors import get_connector_class
from networth.models import Holding
from networth.pricing import fetch_price_book
from networth.store import SnapshotRow, Store, now

log = logging.getLogger(__name__)

FETCH_TIMEOUT_SECONDS = 180


async def fetch_account(account: AccountConfig, config: Config) -> list[Holding]:
  if account.error:
    raise ConfigError(account.error)
  connector = get_connector_class(account.type)(account, config.data_dir)
  return await asyncio.wait_for(connector.fetch(), FETCH_TIMEOUT_SECONDS)


class Runner:
  def __init__(self, config: Config, store: Store):
    self.config = config
    self.store = store
    self.lock = asyncio.Lock()

  def is_due(self, account: AccountConfig, ts: str) -> bool:
    status = self.store.get_status(account.name)
    if status is None or status['last_attempt'] is None:
      return True
    next_due = datetime.fromisoformat(status['last_attempt']) + timedelta(minutes=account.interval)
    # Small slack so an account on the same interval as the tick doesn't skip a tick.
    return next_due <= datetime.fromisoformat(ts) + timedelta(seconds=30)

  async def run(self, force: bool = False, only: Optional[list[str]] = None) -> int:
    """
    Fetch every due account (or `only` these, or all if `force`), value everything in GBP and
    write a snapshot. Accounts not fetched, or whose fetch failed, are carried forward.
    """
    async with self.lock:
      ts = now()
      accounts = self.config.accounts  # the settings page can swap in a new list mid-run
      due = [
        a for a in accounts
        if (a.name in only if only else force or self.is_due(a, ts))
      ]
      log.info('run: fetching %s', ', '.join(a.name for a in due) or 'nothing')

      prices_task = asyncio.create_task(fetch_price_book())
      results = await asyncio.gather(
        *[fetch_account(a, self.config) for a in due], return_exceptions=True
      )
      prices = await prices_task

      fetched: dict[str, list[Holding]] = {}
      for account, result in zip(due, results):
        if isinstance(result, BaseException):
          error = f'{type(result).__name__}: {result}'
          log.warning('%s failed: %s', account.name, error)
          self.store.record_attempt(account.name, ts, error)
        else:
          fetched[account.name] = result
          self.store.record_attempt(account.name, ts)

      rows = []
      for account in accounts:
        if account.name in fetched:
          holdings, fetched_at = fetched[account.name], ts
        else:
          holdings, fetched_at = self.store.last_holdings(account.name)
        for holding in holdings:
          price, value = prices.value(holding)
          if value is None:
            log.warning('%s: no GBP price for %s', account.name, holding.asset)
          rows.append(SnapshotRow(account.name, account.category, holding, price, value, fetched_at))

      run_id = self.store.write_run(ts, rows)
      log.info('run %d: total £%.2f', run_id, sum(r.value_gbp or 0 for r in rows))
      return run_id
