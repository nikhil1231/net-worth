"""Transaction storage and spending reports. Amounts are integer GBP pence."""
import asyncio
import calendar
import csv
import hashlib
import io
import re
import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from networth import categorise
from networth.store import now

CATEGORIES = ['Uncategorised', 'Groceries', 'Eating out', 'Shopping', 'Transport', 'Bills',
              'Entertainment', 'Health', 'Travel', 'Housing', 'Education', 'Gifts', 'Savings']
KINDS = ['expense', 'income', 'refund', 'transfer']
SCHEMA = '''
CREATE TABLE IF NOT EXISTS transactions (
  id TEXT PRIMARY KEY, account TEXT NOT NULL, bank_account TEXT NOT NULL,
  date TEXT NOT NULL, merchant TEXT NOT NULL, description TEXT NOT NULL,
  amount INTEGER NOT NULL, category TEXT NOT NULL, kind TEXT NOT NULL,
  pending INTEGER NOT NULL DEFAULT 0, source TEXT NOT NULL,
  category_override TEXT, kind_override TEXT
);
CREATE INDEX IF NOT EXISTS transactions_date ON transactions(date);
CREATE TABLE IF NOT EXISTS spending_rules (
  account TEXT NOT NULL, merchant TEXT NOT NULL, category TEXT NOT NULL,
  PRIMARY KEY(account, merchant)
);
CREATE TABLE IF NOT EXISTS monthly_spending_rules (
  account TEXT NOT NULL, bank_account TEXT NOT NULL, merchant TEXT NOT NULL,
  recurring_type TEXT NOT NULL,
  PRIMARY KEY(account, bank_account, merchant)
);
CREATE TABLE IF NOT EXISTS recurring_payments (
  id TEXT PRIMARY KEY, account TEXT NOT NULL, merchant TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'detected'
);
CREATE TABLE IF NOT EXISTS spending_status (
  account TEXT PRIMARY KEY, last_success TEXT, last_error TEXT, history_from TEXT
);
CREATE TABLE IF NOT EXISTS lunchflow_accounts (
  id TEXT PRIMARY KEY, account TEXT NOT NULL UNIQUE, institution TEXT NOT NULL,
  start_date TEXT, enabled INTEGER NOT NULL DEFAULT 1, bank_account TEXT NOT NULL DEFAULT ''
);
'''


def initialise(store):
  store.conn.executescript(SCHEMA)
  columns = {r['name'] for r in store.conn.execute('PRAGMA table_info(monthly_spending_rules)')}
  if 'description_contains' not in columns:
    store.conn.execute("ALTER TABLE monthly_spending_rules ADD COLUMN description_contains TEXT NOT NULL DEFAULT ''")
  if 'time' not in {r['name'] for r in store.conn.execute('PRAGMA table_info(transactions)')}:
    store.conn.execute('ALTER TABLE transactions ADD COLUMN time TEXT')
  if 'bank_account' not in {r['name'] for r in store.conn.execute('PRAGMA table_info(lunchflow_accounts)')}:
    store.conn.execute("ALTER TABLE lunchflow_accounts ADD COLUMN bank_account TEXT NOT NULL DEFAULT ''")
  store.conn.commit()


def merchant_key(value):
  return re.sub(r'\s+', ' ', value.strip()).casefold()


def save_transactions(store, rows):
  with store.conn:
    for row in rows:
      store.conn.execute('''INSERT INTO transactions
        (id,account,bank_account,date,time,merchant,description,amount,category,kind,pending,source)
        VALUES (:id,:account,:bank_account,:date,:time,:merchant,:description,:amount,:category,:kind,:pending,:source)
        ON CONFLICT(id) DO UPDATE SET date=excluded.date, time=excluded.time, merchant=excluded.merchant,
        description=excluded.description, amount=excluded.amount, category=excluded.category,
        kind=excluded.kind, pending=excluded.pending''', {'time': None, **row})


def transactions(store, account=None):
  rules = {(r['account'], r['merchant']): r['category'] for r in store.conn.execute('SELECT * FROM spending_rules')}
  monthly_rules = {(r['account'], r['bank_account'], r['merchant']): (r['recurring_type'], r['description_contains'])
                   for r in store.conn.execute('SELECT * FROM monthly_spending_rules')}
  rows = []
  for raw in store.conn.execute("SELECT * FROM transactions ORDER BY date DESC, COALESCE(time, '') DESC, id"):
    row = dict(raw)
    rule = rules.get((row['account'], merchant_key(row['merchant'])))
    row['category'] = row['category_override'] or rule or row['category']
    row['category_locked'] = bool(row['category_override'] or rule)
    row['kind'] = row['kind_override'] or row['kind']
    row['kind_locked'] = bool(row['kind_override'])
    rule_type, description_match = monthly_rules.get((row['account'], row['bank_account'], merchant_key(row['merchant'])), ('auto', ''))
    row['recurring_type'] = rule_type if description_match.casefold() in row['description'].casefold() else 'auto'
    row['recurring_match'] = description_match if row['recurring_type'] != 'auto' else ''
    rows.append(row)
  # Transfers are matched across every account, so infer before narrowing to one.
  categorise.infer(rows)
  return [r for r in rows if not account or r['account'] == account]


def edit_transaction(store, transaction_id, category=None, kind=None, apply_rule=False, recurring_type=None):
  row = store.conn.execute('SELECT * FROM transactions WHERE id=?', (transaction_id,)).fetchone()
  if row is None:
    raise LookupError('Transaction not found')
  if category is not None and category not in CATEGORIES:
    raise ValueError('Unknown category')
  if kind is not None and kind not in KINDS:
    raise ValueError('Unknown transaction type')
  if kind == 'refund' and row['amount'] <= 0 or kind == 'expense' and row['amount'] >= 0 or kind == 'income' and row['amount'] <= 0:
    raise ValueError('Transaction type does not match the amount direction')
  if recurring_type is not None:
    if recurring_type not in ('auto', 'monthly', 'subscription', 'none'):
      raise ValueError('Unknown recurring payment type')
    effective_kind = kind or row['kind_override'] or row['kind']
    if recurring_type in ('monthly', 'subscription') and (row['amount'] >= 0 or effective_kind != 'expense'):
      raise ValueError('Only outgoing expenses can be marked as monthly spending or subscriptions')
  with store.conn:
    if recurring_type is not None:
      key = merchant_key(row['merchant'])
      rule_key = (row['account'], row['bank_account'], key)
      rid = hashlib.sha256(f"{row['bank_account']}|{key}".encode()).hexdigest()
      if recurring_type == 'auto':
        store.conn.execute('DELETE FROM monthly_spending_rules WHERE account=? AND bank_account=? AND merchant=?', rule_key)
      else:
        store.conn.execute('''INSERT INTO monthly_spending_rules (account,bank_account,merchant,recurring_type) VALUES (?,?,?,?)
          ON CONFLICT(account,bank_account,merchant) DO UPDATE SET recurring_type=excluded.recurring_type''', (*rule_key, recurring_type))
      store.conn.execute('DELETE FROM recurring_payments WHERE id=?', (rid,))
      if recurring_type in ('monthly', 'subscription'):
        store.conn.execute('INSERT INTO recurring_payments VALUES (?,?,?,?)', (rid, row['account'], row['merchant'], 'confirmed'))
    if category == 'Savings' and kind is None:
      # Saved money is moved, not spent.
      kind = 'transfer'
    if category is not None:
      store.conn.execute('UPDATE transactions SET category_override=? WHERE id=?', (category, transaction_id))
      if apply_rule:
        store.conn.execute('INSERT OR REPLACE INTO spending_rules VALUES (?,?,?)',
                           (row['account'], merchant_key(row['merchant']), category))
        # The new merchant rule also applies to earlier explicit categorisations.
        for other in store.conn.execute('SELECT id,merchant FROM transactions WHERE account=?', (row['account'],)).fetchall():
          if merchant_key(other['merchant']) == merchant_key(row['merchant']):
            store.conn.execute('UPDATE transactions SET category_override=NULL WHERE id=?', (other['id'],))
    if kind is not None:
      store.conn.execute('UPDATE transactions SET kind_override=? WHERE id=?', (kind, transaction_id))


def add_months(day, months):
  index = day.year * 12 + day.month - 1 + months
  year, month = divmod(index, 12)
  return date(year, month + 1, min(day.day, calendar.monthrange(year, month + 1)[1]))


def recurring(store, rows):
  groups = defaultdict(list)
  for row in rows:
    if row['kind'] == 'expense' and not row['pending'] and row['amount'] < 0 and row.get('recurring_type') != 'none':
      groups[(row['account'], row['bank_account'], merchant_key(row['merchant']))].append(row)
  latest_by_account = {}
  for row in rows:
    account_key = (row['account'], row['bank_account'])
    latest_by_account[account_key] = max(latest_by_account.get(account_key, date.min), date.fromisoformat(row['date']))
  saved = {r['id']: r['status'] for r in store.conn.execute('SELECT * FROM recurring_payments')}
  result = []
  today = datetime.now(ZoneInfo('Europe/London')).date()
  for (account, bank_account, key), items in groups.items():
    marked = [r for r in items if r.get('recurring_type') in ('monthly', 'subscription')]
    if marked:
      items = marked
    items.sort(key=lambda r: r['date'])
    days = [date.fromisoformat(r['date']) for r in items]
    recurring_type = items[-1].get('recurring_type', 'auto')
    manual = recurring_type in ('monthly', 'subscription')
    amounts = [-r['amount'] for r in items]
    if manual:
      # Multiple monthly charges to the same merchant form one combined commitment.
      daily = defaultdict(int)
      for row in items:
        daily[date.fromisoformat(row['date'])] -= row['amount']
      days = sorted(daily)
      amounts = [daily[day] for day in days]
    frequency = 'Monthly' if manual else None
    if not manual:
      # Repeated purchases on one day and uneven shopping intervals aren't recurring bills.
      if len(days) < 2 or len(set(days)) != len(days):
        continue
      gaps = [(b-a).days for a,b in zip(days, days[1:])]
      interval = statistics.median(gaps)
      frequency = next((name for name, low, high in [('Weekly', 6, 8), ('Monthly', 26, 35),
                        ('Quarterly', 80, 100), ('Annual', 350, 380)]
                        if low <= interval <= high and all(low <= gap <= high for gap in gaps)), None)
      if not frequency or frequency in ('Weekly', 'Monthly') and len(items) < 3:
        continue
      typical = statistics.median(amounts)
      if max(amounts) > typical * 1.5 or min(amounts) < typical * .5:
        continue
    rid = hashlib.sha256(f'{bank_account}|{key}'.encode()).hexdigest()
    status = saved.get(rid, 'confirmed' if manual else 'detected')
    next_date = days[-1] + timedelta(days=7) if frequency == 'Weekly' else add_months(days[-1], {'Monthly':1, 'Quarterly':3, 'Annual':12}[frequency])
    grace = {'Weekly':14, 'Monthly':35, 'Quarterly':45, 'Annual':60}[frequency]
    reference = latest_by_account[(account, bank_account)]
    coverage_stale = (today - reference).days > 7
    inactive = reference > next_date + timedelta(days=grace)
    active = status not in ('dismissed', 'cancelled') and not inactive
    result.append(dict(id=rid, account=account, merchant=items[-1]['merchant'], status=status,
                       frequency=frequency, recurring_type=recurring_type, manual=manual, amount=amounts[-1]/100,
                       active=active, inactive=inactive, coverage_stale=coverage_stale,
                       description_contains=items[-1].get('recurring_match', ''),
                       monthly=amounts[-1]/100 * {'Weekly':52/12, 'Monthly':1, 'Quarterly':1/3, 'Annual':1/12}[frequency],
                       last_date=items[-1]['date'], next_date=next_date.isoformat(),
                       overdue=next_date < today, variable=len(set(amounts)) > 1,
                       price_change=(amounts[-1]-amounts[-2])/100 if len(amounts)>1 else 0))
  return sorted(result, key=lambda r: (not r['active'], r['next_date']))


def report(store, config, month, account=None):
  try:
    start = date.fromisoformat(month + '-01')
  except ValueError:
    raise ValueError('Month must be YYYY-MM')
  if not 2000 <= start.year <= 2100:
    raise ValueError('Choose a month between 2000 and 2100')
  end = add_months(start, 1)
  all_rows = transactions(store)
  lunchflow = {r['account']: dict(r) for r in store.conn.execute('SELECT * FROM lunchflow_accounts')}
  active_names = {a.name for a in config.accounts} | lunchflow.keys()
  all_rows = [r for r in all_rows if r['account'] in active_names]
  recurring_rows = recurring(store, [r for r in all_rows if not account or r['account'] == account])
  rows = [r for r in all_rows if not account or r['account'] == account]
  selected = [r for r in rows if start.isoformat() <= r['date'] < end.isoformat()]
  def totals(items):
    return dict(spent=round(sum(-r['amount'] for r in items if r['kind']=='expense' and not r['pending'])/100, 2),
                refunds=round(sum(r['amount'] for r in items if r['kind']=='refund' and not r['pending'])/100, 2),
                income=round(sum(r['amount'] for r in items if r['kind']=='income' and not r['pending'])/100, 2))
  summary = totals(selected)
  summary['net_spent'] = round(summary['spent']-summary['refunds'], 2)
  summary['pending'] = sum(-r['amount'] for r in selected if r['pending'] and r['amount'] < 0 and r['kind'] != 'transfer')/100
  summary['committed'] = sum(r['monthly'] for r in recurring_rows if r['status']=='confirmed' and r['active'])
  cats = defaultdict(int)
  for r in selected:
    if not r['pending'] and r['kind'] in ('expense', 'refund'):
      cats[r['category']] -= r['amount']
  categories = [dict(category=c, amount=v/100) for c,v in sorted(cats.items(), key=lambda item: -item[1])]
  history = []
  for offset in range(-5, 1):
    left = add_months(start, offset).isoformat()
    right = add_months(start, offset+1).isoformat()
    history.append(dict(month=left[:7], **totals([r for r in rows if left<=r['date']<right])))
  previous = add_months(start, -1)
  today = datetime.now(ZoneInfo('Europe/London')).date()
  current_days = min(today.day, calendar.monthrange(start.year,start.month)[1]) if month == today.strftime('%Y-%m') else calendar.monthrange(start.year,start.month)[1]
  pace = []
  current_total = previous_total = 0
  for day in range(1, calendar.monthrange(start.year,start.month)[1]+1):
    for r in rows:
      if r['pending'] or r['kind'] not in ('expense','refund'):
        continue
      if r['date'] == start.replace(day=day).isoformat():
        current_total -= r['amount']
      if day <= calendar.monthrange(previous.year,previous.month)[1] and r['date']==previous.replace(day=day).isoformat():
        previous_total -= r['amount']
    pace.append(dict(day=day, current=current_total/100 if day<=current_days else None, previous=previous_total/100))
  statuses = {r['account']: dict(r) for r in store.conn.execute('SELECT * FROM spending_status')}
  accounts = []
  names = [a.name for a in config.accounts if a.category == 'cash' or a.name in lunchflow or any(r['account']==a.name for r in all_rows)]
  names += [name for name in lunchflow if name not in names]
  for name in names:
    dates = [r['date'] for r in all_rows if r['account']==name]
    kind = 'lunchflow' if name in lunchflow else config.account(name).type
    accounts.append(dict(name=name, type=kind, first_date=min(dates) if dates else None,
                         last_date=max(dates) if dates else None, count=len(dates),
                         sync_enabled=bool(lunchflow[name]['enabled']) if name in lunchflow else kind == 'monzo',
                         **{k:v for k,v in statuses.get(name,{}).items() if k!='account'}))
  return dict(month=month, summary=summary, categories=categories, history=history, pace=pace,
              transactions=selected, recurring=recurring_rows, accounts=accounts, category_options=CATEGORIES,
              review_count=sum(r['category']=='Uncategorised' or r['possible_transfer'] for r in selected))


def money_pence(value):
  cleaned = str(value or '').strip().replace('£', '').replace(',', '')
  if not cleaned:
    return 0
  if cleaned.startswith('(') and cleaned.endswith(')'):
    cleaned = '-' + cleaned[1:-1]
  try:
    number = Decimal(cleaned)
    if not number.is_finite() or number != number.quantize(Decimal('.01')) or abs(number) > Decimal('1000000000'):
      raise ValueError('Invalid money amount')
    return int(number * 100)
  except InvalidOperation:
    raise ValueError('Invalid money amount')


def parse_csv(text, account, mapping, identity=None):
  identity = identity or account
  if len(text.encode()) > 5_000_000:
    raise ValueError('Statement must be under 5 MB')
  try:
    dialect = csv.Sniffer().sniff(text[:8192], delimiters=',;\t')
  except csv.Error:
    dialect = csv.excel
  reader = csv.DictReader(io.StringIO(text.lstrip('\ufeff')), dialect=dialect)
  headers = reader.fieldnames or []
  if len(set(headers)) != len(headers):
    raise ValueError('Statement header contains duplicate column names')
  if not isinstance(mapping.get('invert', False), bool):
    raise ValueError('Reverse amount signs must be true or false')
  if any(not isinstance(v, str) for k,v in mapping.items() if k != 'invert'):
    raise ValueError('Column mappings must be column names')
  required = ['date', 'description'] + (['amount'] if mapping.get('amount') else ['debit','credit'])
  if any(not mapping.get(k) or mapping[k] not in headers for k in required):
    raise ValueError('Choose date, description and either amount or both money out / money in columns')
  rows, occurrences = [], defaultdict(int)
  for line, raw in enumerate(reader, 2):
    if line > 10002:
      raise ValueError('Import up to 10,000 transactions at a time')
    if not any(raw.values()):
      continue
    try:
      value = raw[mapping['date']].strip()
      parsed = None
      for fmt in ('%d/%m/%Y', '%Y-%m-%d', '%d-%m-%Y', '%d %b %Y', '%d/%m/%y'):
        try:
          parsed = datetime.strptime(value, fmt).date()
          break
        except ValueError:
          pass
      if parsed is None:
        raise ValueError('Unsupported date (use DD/MM/YYYY or YYYY-MM-DD)')
      description = raw[mapping['description']].strip()
      if not description or len(description) > 1000:
        raise ValueError('Description is missing or too long')
      if mapping.get('amount'):
        amount = money_pence(raw[mapping['amount']])
      else:
        debit, credit = abs(money_pence(raw[mapping['debit']])), abs(money_pence(raw[mapping['credit']]))
        if debit and credit:
          raise ValueError('Both money in and money out are filled; choose a signed amount column instead')
        amount = credit - debit
      if mapping.get('invert'):
        amount = -amount
      if not amount:
        continue
      key = f'{identity}|{parsed.isoformat()}|{description}|{amount}'
      occurrences[key] += 1
      bank_id = raw.get(mapping.get('id', ''), '').strip()
      tid = hashlib.sha256((f'{identity}|id|{bank_id}' if bank_id else f'{key}|{occurrences[key]}').encode()).hexdigest()
      rows.append(dict(id='csv:'+tid, account=account, bank_account=identity, date=parsed.isoformat(),
                       merchant=description, description=description, amount=amount, category='Uncategorised',
                       kind='expense' if amount<0 else 'income', pending=0, source='csv'))
    except (ValueError, AttributeError, KeyError, TypeError) as e:
      raise ValueError(f'Row {line}: {e}') from None
  if not rows:
    raise ValueError('No transactions found')
  if len({r['id'] for r in rows}) != len(rows):
    raise ValueError('Transaction ID column contains duplicates')
  return rows


async def sync_monzo(store, config, account=None, full_history=False):
  from networth.connectors.monzo import Monzo
  outcomes = []
  for a in config.accounts:
    if a.type != 'monzo' or account and a.name != account:
      continue
    try:
      if a.error:
        raise ValueError(a.error)
      connector = Monzo(a, config.data_dir)
      fetch = (connector.fetch_transactions(True, on_batch=lambda batch: save_transactions(store, batch))
               if full_history else connector.fetch_transactions(False))
      rows, history_from = await asyncio.wait_for(fetch, 180)
      save_transactions(store, rows)
      with store.conn:
        store.conn.execute('''INSERT INTO spending_status(account,last_success,last_error,history_from) VALUES (?,?,NULL,?)
          ON CONFLICT(account) DO UPDATE SET last_success=excluded.last_success,last_error=NULL,
          history_from=MIN(COALESCE(spending_status.history_from,excluded.history_from),excluded.history_from)''', (a.name, now(), history_from))
      outcomes.append(dict(account=a.name, count=len(rows), error=None))
    except Exception:
      # HTTP exceptions can contain request URLs; never persist tokens or transaction details.
      error = 'Monzo sync failed. Check account authorisation and try again; existing transactions are retained.'
      with store.conn:
        store.conn.execute('''INSERT INTO spending_status(account,last_error) VALUES (?,?)
          ON CONFLICT(account) DO UPDATE SET last_error=excluded.last_error''', (a.name,error))
      outcomes.append(dict(account=a.name, count=0, error=error))
  return outcomes
