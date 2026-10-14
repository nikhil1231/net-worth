"""Read-time inference for banks that don't categorise (Santander and Amex via Lunch Flow, statements).

Nothing here is stored: explicit choices (overrides and merchant rules) always win, and improving
these heuristics improves past transactions too."""
import re
from collections import Counter, defaultdict
from datetime import date

# Fallback when no categorised transaction (usually Monzo's) shares the merchant.
KEYWORDS = [(category, re.compile(pattern, re.I)) for category, pattern in [
  ('Transport', r'\bTFL\b|TRANSPORT FOR LONDON|\bUBER\b(?!\s*\*?\s*EATS)|TRAINLINE|NATIONAL RAIL|\bLIME\b|\bVOI\b|\bBOLT\b|ADDISON LEE|\bSHELL\b|\bBP\b|ESSO'),
  ('Groceries', r'SAINSBURY|TESCO|\bASDA\b|\bALDI\b|\bLIDL\b|WAITROSE|\bCO-?OP\b|MORRISONS|OCADO|HELLOFRESH|M&S SIMPLY|SUPERMARKET'),
  ('Eating out', r'DELIVEROO|UBER\s*\*?\s*EATS|JUST EAT|MCDONALD|GREGGS|\bPRET\b|GAIL|STARBUCKS|COSTA|NANDO|\bKFC\b|WAGAMAMA|DOMINO|RESTAURANT|\bCAFE\b|COFFEE'),
  ('Travel', r'BOOKING\.COM|AIRBNB|HOTEL|BRITISH AIRWAYS|EASYJET|RYANAIR|\bINDIGO\b|HOSTELWORLD|EXPEDIA|AGODA|SKYSCANNER|EUROSTAR'),
  ('Entertainment', r'NETFLIX|DISNEY|SPOTIFY|YOUTUBE|STEAM|PLAYSTATION|XBOX|NINTENDO|CINEMA|ODEON|VUE\b|TICKETMASTER'),
  ('Bills', r'GOOGLE ONE|GOOGLE\*|ICLOUD|APPLE\.COM/BILL|VOXI|OCTOPUS|THAMES WATER|COUNCIL TAX|\bEE\b|VODAFONE|\bO2\b|BT GROUP|VIRGIN MEDIA|TV LICENCE'),
  ('Health', r'MYPROTEIN|BOOTS|PHARMACY|DENTAL|\bGYM\b|PUREGYM|CLIMBING|SUPERDRUG'),
  ('Shopping', r'AMAZON|\bAMZN\b|\bEBAY\b|ARGOS|IKEA|JOHN LEWIS|UNIQLO|\bZARA\b|\bH&M\b|CURRYS|\bAPPLE STORE\b'),
]]
# Money moved to an investment account is saved, not spent.
INVESTMENT = re.compile(r'\bHLAM\b|HARGREAVES|\bHL\.CO\.UK\b|VANGUARD|TRADING ?212|FREETRADE|\bAJ BELL\b|INTERACTIVE INVESTOR'
                        r'|NUTMEG|MONEYBOX|COINBASE|BINANCE|KRAKEN|\bS(?: AND| &)? ?S ISA\b|STOCKS AND SHARES', re.I)
# A card's own record of being paid off: never income.
CARD_REPAYMENT_RECEIVED = re.compile(r'PAYMENT RECEIVED|THANK YOU FOR YOUR PAYMENT|DIRECT DEBIT RECEIVED', re.I)
# Either side of a credit-card repayment; only trusted with a matching opposite transaction.
CARD_REPAYMENT = re.compile(r'AMERICAN EXPRESS|\bAMEX\b|BARCLAYCARD|CREDIT CARD|CAPITAL ONE|\bMBNA\b', re.I)


def tokens(text):
  return re.findall(r'[a-z0-9]+', text.casefold().replace("'", '').replace('’', ''))


def compact(text):
  return ''.join(tokens(text))


def learn(rows):
  """Merchant -> category from transactions that already have one (Monzo's categories, your edits)."""
  votes = defaultdict(Counter)
  for row in rows:
    if row['category'] != 'Uncategorised' and row['kind'] in ('expense', 'refund'):
      votes[compact(row['merchant'])][row['category']] += 1
  learned = {}
  for key, counter in votes.items():
    category, count = counter.most_common(1)[0]
    if len(key) >= 4 and count / sum(counter.values()) >= .6:
      learned[key] = category
  return learned


def guess_category(row, learned):
  # "TESCO STORES" or "EBAY O*27-147..." match Monzo's "Tesco" / "eBay" through their leading words.
  words = tokens(row['merchant'])
  for n in range(len(words), 0, -1):
    category = learned.get(''.join(words[:n]))
    if category and len(''.join(words[:n])) >= 4:
      return category
  text = f"{row['merchant']} {row['description']}"
  return next((category for category, pattern in KEYWORDS if pattern.search(text)), None)


def shares_reference(a, b):
  # Santander's "...TO JOHN SMITH REFERENCE MONZO-ABCDE..." arrives in Monzo as "Monzo-ABCDE".
  for x, y in ((a, b), (b, a)):
    key = compact(x['merchant'])
    if len(key) >= 6 and key in compact(y['description']):
      return True
  return False


def infer(rows):
  """Fill in kind and category on rows (dicts with resolved category/kind) in place.

  Rows carry `kind_locked` / `category_locked` when the user (or a rule) chose them explicitly."""
  learned = learn(rows)
  paid = {(r['account'], compact(r['merchant'])) for r in rows if r['amount'] < 0}
  for row in rows:
    row['inferred'] = []
    if row['kind_locked']:
      continue
    text = f"{row['merchant']} {row['description']}"
    if row['amount'] < 0 and INVESTMENT.search(text):
      row['kind'] = 'transfer'
      if not row['category_locked'] and row['category'] == 'Uncategorised':
        row['category'] = 'Savings'
        row['inferred'].append('category')
      row['inferred'].append('kind')
    elif row['amount'] > 0 and row['source'] != 'monzo' and row['kind'] == 'income':
      if CARD_REPAYMENT_RECEIVED.search(text):
        row['kind'] = 'transfer'
        row['inferred'].append('kind')
      elif (row['account'], compact(row['merchant'])) in paid:
        # Money back from a merchant you've paid from this account is a refund, not income.
        row['kind'] = 'refund'
        row['inferred'].append('kind')

  # Own-account transfers: one opposite amount in another account within a few days, plus evidence.
  by_amount = defaultdict(list)
  for row in rows:
    if not row['pending']:
      by_amount[row['amount']].append(row)
  def candidates(row):
    return [other for other in by_amount[-row['amount']]
            if (other['account'], other['bank_account']) != (row['account'], row['bank_account'])
            and abs((date.fromisoformat(other['date']) - date.fromisoformat(row['date'])).days) <= 3]
  for row in rows:
    row['candidates'] = candidates(row) if not row['pending'] else []
  for row in rows:
    if len(row['candidates']) != 1 or row['amount'] >= 0:
      continue
    other = row['candidates'][0]
    # A side you've explicitly typed stays as you typed it, and blocks the pair unless it's a transfer.
    if len(other['candidates']) != 1 or any(r['kind_locked'] and r['kind'] != 'transfer' for r in (row, other)):
      continue
    if 'transfer' in (row['kind'], other['kind']) or shares_reference(row, other) or any(
        CARD_REPAYMENT.search(r['description']) or CARD_REPAYMENT_RECEIVED.search(r['description']) for r in (row, other)):
      for r in (row, other):
        if r['kind'] != 'transfer':
          r['kind'] = 'transfer'
          r['inferred'].append('kind')

  for row in rows:
    if not row['category_locked'] and row['category'] == 'Uncategorised' and row['kind'] in ('expense', 'refund'):
      category = guess_category(row, learned)
      if category:
        row['category'] = category
        row['inferred'].append('category')
    # Savings are money kept, so they never count as spending.
    if row['category'] == 'Savings' and not row['kind_locked'] and row['kind'] != 'transfer':
      row['kind'] = 'transfer'
      row['inferred'].append('kind')
  for row in rows:
    candidates = row.pop('candidates')
    row['possible_transfer'] = row['kind'] != 'transfer' and len(candidates) == 1
