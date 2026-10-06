from datetime import datetime, timedelta, timezone
from typing import Optional

from networth.config import Config
from networth.store import Store

CHANGE_PERIODS = {'24h': timedelta(days=1), '7d': timedelta(days=7), '30d': timedelta(days=30), '1y': timedelta(days=365)}
MAX_HISTORY_POINTS = 400
# Fiat and stablecoins count as cash wherever they're held (ISA cash, USDC in a wallet, the bank).
CASH_CATEGORY = 'cash'
CASH_ASSETS = {'GBP', 'USD', 'EUR', 'USDC', 'USDC.E', 'USDT', 'USDB', 'DAI', 'USDS', 'USDE', 'PYUSD', 'FDUSD',
               'TUSD', 'BUSD', 'GUSD', 'USDP', 'FRAX', 'LUSD', 'EURC'}


def bucket(category: str, asset: str) -> str:
  """The category a holding counts towards on the dashboard: cash-like assets are cash anywhere."""
  return CASH_CATEGORY if asset.upper() in CASH_ASSETS else category


def summary(store: Store, config: Config) -> dict:
  run = store.latest_run()
  status = store.all_status()
  accounts = {
    a.name: {
      'name': a.name, 'category': a.category, 'type': a.type, 'value': 0.0, 'fetched_at': None,
      'holdings': [], 'unpriced': [],
      'last_success': status[a.name]['last_success'] if a.name in status else None,
      'last_error': status[a.name]['last_error'] if a.name in status else None,
    }
    for a in config.accounts
  }
  if run is None:
    return {'ts': None, 'total': 0.0, 'categories': {}, 'category_accounts': {}, 'accounts': list(accounts.values()),
            'changes': {}}

  for row in store.snapshots(run['id']):
    account = accounts.get(row['account'])
    if account is None:  # removed from config since this run
      continue
    account['fetched_at'] = row['fetched_at']
    if row['quantity'] == 0 and row['value_gbp'] is None:
      continue  # Empty token slots are not unpriced holdings.
    holding = {
      'asset': row['asset'], 'name': row['name'], 'quantity': row['quantity'],
      'price': row['price_gbp'], 'value': row['value_gbp'],
      'locations': [{'wallet': row['wallet'], 'chain': row['chain'], 'quantity': row['quantity'],
                     'value': row['value_gbp'], 'name': row['name']}] if row['wallet'] and row['quantity'] else [],
    }
    if row['value_gbp'] is None:
      account['unpriced'].append(holding)
    else:
      account['value'] += row['value_gbp']
      account['holdings'].append(holding)

  for account in accounts.values():
    for field in ('holdings', 'unpriced'):
      grouped = {}
      for h in account[field]:
        key = (h['asset'], None if account['type'] in ('evm', 'bitcoin', 'solana') else h['name'])
        if key not in grouped:
          grouped[key] = dict(h)
          if account['type'] in ('evm', 'bitcoin', 'solana'):
            grouped[key]['name'] = h['asset']
        else:
          grouped[key]['locations'] = grouped[key]['locations'] + h['locations']
          grouped[key]['quantity'] += h['quantity']
          if h['value'] is not None:
            grouped[key]['value'] += h['value']
      account[field] = list(grouped.values())
      if field == 'holdings':
        for h in account[field]:
          h['price'] = h['value'] / h['quantity'] if h['quantity'] else h['price']
    account['holdings'].sort(key=lambda h: h['value'], reverse=True)

  total = sum(a['value'] for a in accounts.values())
  category_accounts: dict[str, dict[str, float]] = {}  # {category: {account: value}}
  for account in accounts.values():
    for h in account['holdings']:
      if not h['value']:
        continue
      per_account = category_accounts.setdefault(bucket(account['category'], h['asset']), {})
      per_account[account['name']] = per_account.get(account['name'], 0.0) + h['value']
  categories = {c: sum(v.values()) for c, v in category_accounts.items()}

  run_ts = datetime.fromisoformat(run['ts'])
  changes = {}
  for label, delta in CHANGE_PERIODS.items():
    prev = store.run_at_or_before((run_ts - delta).isoformat(timespec='seconds'))
    if prev is not None:
      prev_total = store.run_total(prev['id'])
      changes[label] = {'ts': prev['ts'], 'value': total - prev_total, 'previous': prev_total}

  return {
    'ts': run['ts'],
    'total': total,
    'categories': dict(sorted(categories.items(), key=lambda kv: kv[1], reverse=True)),
    'category_accounts': {c: dict(sorted(v.items(), key=lambda kv: kv[1], reverse=True))
                          for c, v in category_accounts.items()},
    'accounts': sorted(accounts.values(), key=lambda a: a['value'], reverse=True),
    'changes': changes,
  }


def history(store: Store, days: Optional[int], group_by: str = 'category') -> dict:
  """Totals per run, grouped by category or account, downsampled to at most MAX_HISTORY_POINTS."""
  since = ''
  if days:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec='seconds')

  runs: dict[int, dict] = {}
  keys: dict[str, float] = {}
  for row in store.totals_since(since, group_by, CASH_CATEGORY, CASH_ASSETS):
    point = runs.setdefault(row['run_id'], {'ts': row['ts'], 'values': {}})
    point['values'][row['key']] = row['value'] or 0.0
    keys[row['key']] = row['value'] or 0.0  # ends up holding the latest value per key

  points = list(runs.values())
  if len(points) > MAX_HISTORY_POINTS:
    start = datetime.fromisoformat(points[0]['ts']).timestamp()
    end = datetime.fromisoformat(points[-1]['ts']).timestamp()
    bucket_seconds = (end - start) / MAX_HISTORY_POINTS
    buckets: dict[int, dict] = {}
    for point in points:  # keep the last point in each bucket
      buckets[int((datetime.fromisoformat(point['ts']).timestamp() - start) // bucket_seconds)] = point
    points = list(buckets.values())

  for point in points:
    point['total'] = sum(point['values'].values())

  return {
    'keys': sorted(keys, key=lambda k: keys[k], reverse=True),
    'points': points,
  }


def wallet_details(store: Store, config: Config, name: str) -> dict:
  account = config.account(name)
  if account.type not in ('bitcoin', 'evm', 'solana') or account.error:
    return {}
  addresses = list(dict.fromkeys(account.params.get('addresses', [])))
  wallets = {address: {'address': address, 'label': f'Wallet {i + 1}', 'value': 0.0,
                       'holdings': [], 'fetched_at': None} for i, address in enumerate(addresses)}
  run = store.latest_run()
  unattributed = 0.0
  unattributed_holdings = False
  if run:
    for row in store.snapshots(run['id']):
      if row['account'] != name:
        continue
      if row['wallet'] not in wallets:
        unattributed += row['value_gbp'] or 0
        unattributed_holdings = True
        continue
      w = wallets[row['wallet']]
      w['fetched_at'] = row['fetched_at']
      w['value'] += row['value_gbp'] or 0
      w['holdings'].append({'asset': row['asset'], 'chain': row['chain'], 'quantity': row['quantity'],
                            'value': row['value_gbp'], 'price': row['price_gbp']})
  return {'wallets': list(wallets.values()), 'wallet_breakdown_available': not unattributed_holdings and
          any(w['fetched_at'] for w in wallets.values()), 'unattributed_value': unattributed}



def crypto_details(store: Store, config: Config, name: str, chain: Optional[str] = None,
                   wallet: Optional[str] = None) -> dict:
  account = config.account(name)
  if account.type not in ('evm', 'solana', 'bitcoin'):
    raise ValueError('This account has no wallet holdings')
  if wallet and wallet not in account.params.get('addresses', []):
    raise ValueError('Unknown wallet')
  overview = next(a for a in summary(store, config)['accounts'] if a['name'] == name)
  result = overview | {'name': chain or wallet, 'parent_account': name,
                       'holdings': [], 'unpriced': [], 'value': 0.0, 'classifications': {}}
  run = store.latest_run()
  grouped = {}
  if run:
    for row in store.snapshots(run['id']):
      if row['account'] != name or (chain and row['chain'] != chain) or (wallet and row['wallet'] != wallet) or not row['quantity']:
        continue
      key = (row['asset'], row['value_gbp'] is None)
      if key not in grouped:
        grouped[key] = {'asset': row['asset'], 'name': row['name'] or row['asset'],
                        'quantity': 0.0, 'value': None if key[1] else 0.0, 'price': None, 'locations': []}
      h = grouped[key]
      h['quantity'] += row['quantity']
      h['locations'].append({'wallet': row['wallet'], 'chain': row['chain'],
                            'quantity': row['quantity'], 'value': row['value_gbp'], 'name': row['name']})
      if row['name'] and row['name'] not in h['name']:
        h['name'] += ' / ' + row['name']
      if row['value_gbp'] is not None:
        h['value'] += row['value_gbp']
  if not grouped:
    raise ValueError('No holdings on this chain or wallet')
  for h in grouped.values():
    if h['value'] is None:
      result['unpriced'].append(h)
    else:
      h['price'] = h['value'] / h['quantity']
      result['holdings'].append(h)
      result['value'] += h['value']
  if wallet:
    attribution = wallet_details(store, config, name)
    result.update(attribution | {'wallets': [w for w in attribution['wallets'] if w['address'] == wallet]})
  return result


def chain_details(store: Store, config: Config, name: str, chain: str) -> dict:
  return crypto_details(store, config, name, chain=chain)
