"""
Country and sector exposure of investment holdings, for the account breakdown charts.

Single stocks come from Yahoo Finance. ETFs are looked through: iShares and Xtrackers publish
their country and sector weights and top holdings, used when the account's `look_through`
param says where to find a fund. Other funds fall back to Yahoo's sector weights and top 10
holdings, with country weights from justETF (by ISIN - found on the LSE for London listings).

  look_through:
    EMIM: {yahoo: EMIM.L, ishares: 264659}            # the portfolioId in the iShares fund URL
    XMWX: {yahoo: XMWX.L, xtrackers: IE0006WW1TQ4}    # the ISIN
    DMGI: {yahoo: DMGI.V}                             # only needed when auto-detection picks wrong
    VWRP: {justetf: IE00BK5BQT80}                     # the ISIN, for a fund not listed in London

Results are cached in SQLite (a week, failures a day) - Yahoo and the issuer files are slow.
"""
import asyncio
import csv
import html
import io
import logging
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests

from networth.pricing import PriceBook
from networth.store import Store, now

log = logging.getLogger(__name__)
# yfinance logs an error for every exchange suffix that isn't a listing - expected while resolving.
logging.getLogger('yfinance').setLevel(logging.CRITICAL)

CACHE_VERSION = 4  # bump when the shape of a classification changes, to refetch everything
CACHE_TTL = timedelta(days=7)
ERROR_TTL = timedelta(days=1)
LOOKUP_TIMEOUT = 60
MAX_CONSTITUENTS = 10  # biggest holdings kept per fund - enough to spot a big single-company exposure
CASH_ASSETS = {'GBP', 'USD', 'EUR'}
# Exchange suffixes tried, in order, when a ticker has no explicit Yahoo symbol.
YAHOO_SUFFIXES = ['', '.L', '.V', '.TO', '.NE', '.AS', '.DE', '.PA']
UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36'

ISHARES_URL = ('https://www.blackrock.com/varnish-api/uk-retail01-product-data/product-data/api/v1/get-fund-document'
               '?appType=PRODUCT_PAGE&appSubType=ISHARES&targetSite=ishares-uk&locale=en_GB&portfolioId={id}'
               '&component=fundDownloadV2&userType=individual')
XTRACKERS_URL = 'https://etf.dws.com/etfdata/export/GBR/ENG/csv/product/constituent/{isin}/'
LSE_URL = 'https://api.londonstockexchange.com/api/gw/lse/instruments/alldata/{ticker}'
JUSTETF_URL = 'https://www.justetf.com/uk/etf-profile.html'
JUSTETF_TIMEOUT = 15

# Everything is reported in GICS sector names; Yahoo uses Morningstar's.
SECTOR_ALIASES = {
  'technology': 'Information Technology',
  'financial services': 'Financials',
  'financial_services': 'Financials',
  'consumer cyclical': 'Consumer Discretionary',
  'consumer_cyclical': 'Consumer Discretionary',
  'consumer defensive': 'Consumer Staples',
  'consumer_defensive': 'Consumer Staples',
  'basic materials': 'Materials',
  'basic_materials': 'Materials',
  'healthcare': 'Health Care',
  'communication': 'Communication Services',
  'communication_services': 'Communication Services',
  'realestate': 'Real Estate',
  'cash and/or derivatives': 'Cash',
}
COUNTRY_ALIASES = {
  'Korea (South)': 'South Korea',
  'Korea': 'South Korea',
  'Korea, Republic of': 'South Korea',
  'Russian Federation': 'Russia',
  'Cash and/or Derivatives': 'Cash',
  'United States of America': 'United States',
}

_ISHARES_NS = {'ss': 'urn:schemas-microsoft-com:office:spreadsheet'}
ACRONYMS = {'AG', 'SA', 'SE', 'AB', 'ASA', 'SPA', 'NV', 'UK', 'US', 'AI', 'ASML', 'UFJ'}
ISHARES_CASH_CLASSES = {'Cash', 'Money Market', 'Cash Collateral and Margins'}


def normalise_sector(name: str) -> str:
  return SECTOR_ALIASES.get(name.strip().lower(), name.strip().title() if name.islower() else name.strip())


def normalise_country(name: str) -> str:
  return COUNTRY_ALIASES.get(name.strip(), name.strip())


def _weights(pairs, normalise) -> dict[str, float]:
  """Sum (name, weight) pairs into normalised names, scaled to add up to 1."""
  totals: dict[str, float] = {}
  for name, weight in pairs:
    if name and weight and weight > 0:
      key = normalise(name)
      totals[key] = totals.get(key, 0.0) + weight
  total = sum(totals.values())
  return {k: v / total for k, v in sorted(totals.items(), key=lambda kv: -kv[1])} if total else {}


def _display_name(name: str) -> str:
  """Issuer files shout ('TAIWAN SEMICONDUCTOR MANUFACTURING'); title-case those, keeping what look
  like acronyms ('HSBC', 'SK', 'NV') in capitals."""
  name = ' '.join(name.split())
  if not name.isupper():
    return name
  def word(i, w):
    if w in ACRONYMS or (w != 'LTD' and not set(w.lower()) & set('aeiouy')):
      return w
    return w.lower() if i and w in ('OF', 'AND', 'THE', 'DE') else w.capitalize()
  return ' '.join(word(i, w) for i, w in enumerate(name.split()))


def _constituents(rows) -> list[dict]:
  """(name, weight, sector, country) rows, same names merged, scaled to add up to 1, biggest first.
  Cash rows are named 'Cash'. Only the biggest MAX_CONSTITUENTS are kept, so the rest is implied."""
  merged: dict[str, dict] = {}
  for name, weight, sector, country in rows:
    if not name or not weight or weight <= 0:
      continue
    key = 'Cash' if sector == 'Cash' else _display_name(name)
    entry = merged.setdefault(key, {'name': key, 'weight': 0.0, 'sector': sector, 'country': country})
    entry['weight'] += weight
  total = sum(e['weight'] for e in merged.values())
  if not total:
    return []
  ranked = sorted(merged.values(), key=lambda e: -e['weight'])[:MAX_CONSTITUENTS]
  return [e | {'weight': e['weight'] / total} for e in ranked]


# --- issuer files ---

def _sheet_rows(root, name: str) -> Optional[list[list[str]]]:
  sheet = next((ws for ws in root.findall('ss:Worksheet', _ISHARES_NS)
                if ws.get(f'{{{_ISHARES_NS["ss"]}}}Name') == name), None)
  if sheet is None:
    return None
  return [[(c.find('ss:Data', _ISHARES_NS).text or '') if c.find('ss:Data', _ISHARES_NS) is not None else ''
           for c in row.findall('ss:Cell', _ISHARES_NS)]
          for row in sheet.findall('.//ss:Row', _ISHARES_NS)]


def _ishares_holdings(rows: Optional[list[list[str]]]) -> list[dict]:
  """Constituents from the 'Holdings' sheet, weighted by market value (the weight column is rounded to 0.01%)."""
  if not rows:
    return []
  header = next((r for r in rows if 'Name' in r and 'Market Value' in r), None)
  if header is None:
    return []
  col = {name: i for i, name in enumerate(header)}

  def parse(row):
    if len(row) < len(header) or row is header:
      return None
    asset_class = row[col['Asset Class']] if 'Asset Class' in col else 'Equity'
    if asset_class != 'Equity' and asset_class not in ISHARES_CASH_CLASSES:
      return None  # FX forwards and futures: notional, not holdings
    try:
      value = float(row[col['Market Value']].split()[-1].replace(',', ''))
    except (ValueError, IndexError):
      return None
    sector = 'Cash' if asset_class != 'Equity' else normalise_sector(row[col['Sector']]) if 'Sector' in col else None
    country = normalise_country(row[col['Location']]) if 'Location' in col else None
    return row[col['Name']], value, sector, country
  return _constituents(p for p in map(parse, rows) if p)


def parse_ishares(xml_text: str) -> dict:
  """Fund-level sector and country tables from the 'Exposure Breakdowns' sheet of the iShares download,
  and constituents from its 'Holdings' sheet."""
  root = ET.fromstring(xml_text.lstrip('﻿'))
  rows = _sheet_rows(root, 'Exposure Breakdowns')
  if rows is None:
    raise RuntimeError('iShares download has no Exposure Breakdowns sheet')

  tables: dict[str, list] = {}
  current = None
  for cells in rows:
    if len(cells) == 1 and cells[0] in ('Sector', 'Geography/Locations'):
      current = tables.setdefault(cells[0], [])
    elif current is not None and len(cells) >= 2 and cells[0] not in ('as of', 'Type'):
      try:
        current.append((cells[0], float(cells[1])))
      except ValueError:
        pass
    elif not cells:
      current = None

  if not tables.get('Sector') or not tables.get('Geography/Locations'):
    raise RuntimeError('iShares exposure tables not found')
  return {
    'sectors': _weights(tables['Sector'], normalise_sector),
    'countries': _weights(tables['Geography/Locations'], normalise_country),
    'holdings': _ishares_holdings(_sheet_rows(root, 'Holdings')),
  }


def parse_xtrackers(csv_text: str) -> dict:
  """Every constituent with its country and GICS sector, from the Xtrackers (DWS) constituent export."""
  rows = list(csv.DictReader(io.StringIO(csv_text.lstrip('﻿')), delimiter=';'))
  if not rows or 'Constituent Country' not in rows[0]:
    raise RuntimeError('Xtrackers constituent file not recognised')

  def weight(row):
    try:
      return float(row['Constituent Weighting'])
    except (TypeError, ValueError):
      return 0.0
  return {
    'countries': _weights(((r['Constituent Country'], weight(r)) for r in rows), normalise_country),
    'sectors': _weights(((r['Constituent Industry Classification Name'], weight(r)) for r in rows), normalise_sector),
    'holdings': _constituents((r['Constituent Name'], weight(r), normalise_sector(r['Constituent Industry Classification Name']),
                               normalise_country(r['Constituent Country'])) for r in rows),
  }


_JUSTETF_ROW = re.compile(r'countries_value_name">([^<]+)<.*?countries_value_percentage">([\d.,]+)%', re.S)


def parse_justetf_countries(page: str) -> dict[str, float]:
  """Country weights from a justETF profile page, or its 'Show more' countries response."""
  return _weights(((html.unescape(name), float(pct.replace(',', ''))) for name, pct in _JUSTETF_ROW.findall(page)),
                  normalise_country)


def justetf_countries(isin: str) -> dict[str, float]:
  """A fund's country weights from justETF. The profile page shows the top few and 'Other'; its
  'Show more' link (a Wicket AJAX call in the same session) has the rest."""
  session = requests.Session()
  session.headers['User-Agent'] = UA
  res = session.get(JUSTETF_URL, params={'isin': isin}, timeout=JUSTETF_TIMEOUT)
  res.raise_for_status()
  countries = parse_justetf_countries(res.text)
  if not countries:
    raise RuntimeError(f'justETF has no country breakdown for {isin}')
  more = re.search(r'"u":"([^"]*loadMoreCountries[^"]*)"', res.text)
  if more:
    try:
      full = session.get('https://www.justetf.com' + html.unescape(more.group(1)), timeout=JUSTETF_TIMEOUT, headers={
        'Wicket-Ajax': 'true', 'Wicket-Ajax-BaseURL': f'etf-profile.html?isin={isin}', 'X-Requested-With': 'XMLHttpRequest'})
      full.raise_for_status()
      countries = parse_justetf_countries(full.text) or countries
    except requests.RequestException as e:
      log.info('justETF full country list for %s failed, keeping the top few: %s', isin, e)
  return countries


def lse_isin(ticker: str) -> Optional[str]:
  """The ISIN of a London listing, from the LSE's instrument API."""
  res = requests.get(LSE_URL.format(ticker=ticker), headers={'User-Agent': UA}, timeout=JUSTETF_TIMEOUT)
  if res.status_code == 404:
    return None
  res.raise_for_status()
  return res.json().get('isin') or None


def _fund_countries(asset: str, symbol: str, hint: dict) -> dict[str, float]:
  """Country weights of a fund with no issuer file, from justETF. Unknown when it can't be found."""
  try:
    isin = hint.get('justetf')
    if not isin and (symbol.endswith('.L') or '.' not in symbol):
      isin = lse_isin(symbol.removesuffix('.L'))
    if isin:
      return justetf_countries(isin)
  except Exception as e:
    log.warning('justETF countries for %s failed: %s', asset, e)
  return {'Unknown': 1.0}


def _get(url: str) -> str:
  res = requests.get(url, headers={'User-Agent': UA}, timeout=LOOKUP_TIMEOUT)
  res.raise_for_status()
  return res.text


# --- Yahoo ---

def _name_matches(expected: Optional[str], found: Optional[str]) -> bool:
  """HL names are short ('iShares plc'); check the first word appears in Yahoo's long name."""
  if not expected:
    return True
  first = expected.split()[0].lower().strip('.,')
  return bool(found) and first in found.lower()


def yahoo_lookup(ticker: str, name: Optional[str] = None, symbol: Optional[str] = None) -> dict:
  """Resolve a ticker to a Yahoo symbol and return its info. Tries common exchange suffixes, unless the
  ticker already has one. Raises LookupError when there's no listing, RuntimeError when Yahoo failed."""
  import yfinance as yf  # slow import, and only the dashboard needs it

  if symbol:
    candidates = [symbol]
  elif '.' in ticker:
    candidates = [ticker]  # already says which exchange, e.g. VWRP.L
  else:
    candidates = [ticker + s for s in YAHOO_SUFFIXES]
  failures = []
  for candidate in candidates:
    info = None
    for attempt in range(2):  # a missing listing comes back empty; an exception is Yahoo having a moment
      try:
        info = yf.Ticker(candidate).info
        break
      except Exception as e:
        log.info('yahoo lookup %s failed (attempt %d): %s', candidate, attempt + 1, e)
        if attempt == 0:
          time.sleep(1)
        else:
          failures.append(f'{candidate}: {type(e).__name__}: {e}')
    if not info or info.get('quoteType') not in ('EQUITY', 'ETF', 'MUTUALFUND'):
      continue
    if not symbol and not (info.get('regularMarketPrice') or info.get('previousClose')):
      continue  # a dead or OTC listing; keep looking for the live one
    long_name = info.get('longName') or info.get('shortName')
    if symbol or _name_matches(name, long_name):
      return {'symbol': candidate, 'info': info}
  if failures:
    raise RuntimeError(f"Yahoo Finance didn't answer for {ticker}, try again in a minute ({failures[0]})")
  raise LookupError(f'No Yahoo Finance listing found for {ticker}')


def _yahoo_fund_sectors(symbol: str) -> dict[str, float]:
  import yfinance as yf
  try:
    weights = yf.Ticker(symbol).funds_data.sector_weightings or {}
  except Exception:
    return {}
  return _weights(weights.items(), normalise_sector)


def _yahoo_top_holdings(symbol: str) -> list[dict]:
  """A fund's top ~10 holdings from Yahoo, as fractions of the whole fund (not scaled up to 1)."""
  import yfinance as yf
  try:
    top = yf.Ticker(symbol).funds_data.top_holdings
  except Exception:
    return []
  return [{'name': _display_name(str(row['Name'])), 'weight': float(row['Holding Percent']), 'sector': None, 'country': None}
          for _, row in top.iterrows() if row['Holding Percent'] and row['Holding Percent'] > 0]


def _price_gbp(info: dict, prices: Optional[PriceBook]) -> Optional[float]:
  price = info.get('regularMarketPrice') or info.get('currentPrice') or info.get('previousClose')
  currency = info.get('currency')
  if price is None or currency is None:
    return None
  if currency in ('GBp', 'GBX'):
    return price / 100
  if currency == 'GBP':
    return price
  fx = prices.price(currency) if prices else None
  return price * fx if fx else None


def classify(asset: str, name: Optional[str], hint: dict, prices: Optional[PriceBook] = None) -> dict:
  """Blocking. Country and sector weights (each adding up to 1) for one holding."""
  if asset.upper() in CASH_ASSETS:
    return {'kind': 'cash', 'name': name or asset, 'symbol': None, 'countries': {'Cash': 1.0},
            'sectors': {'Cash': 1.0}, 'holdings': [], 'source': None,
            'price_gbp': 1.0 if asset.upper() == 'GBP' else None}

  found = yahoo_lookup(asset, name, hint.get('yahoo'))
  info, symbol = found['info'], found['symbol']
  result = {
    'name': info.get('longName') or info.get('shortName') or name or asset,
    'symbol': symbol,
    'price_gbp': _price_gbp(info, prices),
  }

  if info.get('quoteType') == 'EQUITY':
    return result | {
      'kind': 'stock',
      'countries': {normalise_country(info['country']): 1.0} if info.get('country') else {'Unknown': 1.0},
      'sectors': {normalise_sector(info['sector']): 1.0} if info.get('sector') else {'Unknown': 1.0},
      'holdings': [],
      'source': 'yahoo',
    }

  result['kind'] = 'fund'
  if 'ishares' in hint:
    return result | parse_ishares(_get(ISHARES_URL.format(id=hint['ishares']))) | {'source': 'ishares'}
  if 'xtrackers' in hint:
    return result | parse_xtrackers(_get(XTRACKERS_URL.format(isin=hint['xtrackers']))) | {'source': 'xtrackers'}
  return result | {
    'countries': _fund_countries(asset, symbol, hint),
    'sectors': _yahoo_fund_sectors(symbol) or {'Unknown': 1.0},
    'holdings': _yahoo_top_holdings(symbol),
    'source': 'yahoo',
  }


# Bulky or useless bits of Yahoo's info dict, left out of the details view.
DETAIL_SKIP = {'companyOfficers', 'executiveTeam', 'corporateActions', 'maxAge', 'messageBoardId', 'gmtOffSetMilliseconds',
               'customPriceAlertConfidence', 'triggerable', 'tradeable', 'cryptoTradeable', 'esgPopulated',
               'sourceInterval', 'exchangeDataDelayedBy', 'priceHint', 'quoteSourceName', 'language', 'region'}


def _frame_rows(frame) -> list[dict]:
  return [] if frame is None else [{'symbol': str(i), **{str(k): v for k, v in row.items()}} for i, row in frame.iterrows()]


def _clean(value):
  """JSON-safe: NaN and pandas' NA become None."""
  if isinstance(value, dict):
    return {k: _clean(v) for k, v in value.items()}
  if isinstance(value, list):
    return [_clean(v) for v in value]
  if isinstance(value, float) and value != value:
    return None
  if type(value).__name__ in ('NAType', 'NaTType'):
    return None
  if hasattr(value, 'item'):  # numpy scalars
    return _clean(value.item())
  return value


def details(symbol: str) -> dict:
  """Blocking. What Yahoo Finance knows about a listing, for the details view."""
  import yfinance as yf

  ticker = yf.Ticker(symbol)
  try:
    info = ticker.info
  except Exception as e:
    raise RuntimeError(f"Yahoo Finance didn't answer for {symbol}, try again in a minute ({type(e).__name__}: {e})")
  if not info or info.get('quoteType') not in ('EQUITY', 'ETF', 'MUTUALFUND'):
    raise LookupError(f'No Yahoo Finance listing for {symbol}')
  result: dict = {'symbol': symbol, 'info': {k: v for k, v in info.items() if k not in DETAIL_SKIP}}
  try:
    closes = ticker.history(period='1y', interval='1wk')['Close'].dropna()
    result['history'] = [{'date': d.date().isoformat(), 'close': float(c)} for d, c in closes.items()]
  except Exception:
    result['history'] = []

  if info.get('quoteType') != 'EQUITY':
    try:
      funds = ticker.funds_data
      result['fund'] = {
        'description': funds.description or None,
        'asset_classes': funds.asset_classes or {},
        'sectors': _weights((funds.sector_weightings or {}).items(), normalise_sector),
        'top_holdings': [{'symbol': r['symbol'], 'name': r.get('Name'), 'weight': r.get('Holding Percent')}
                         for r in _frame_rows(funds.top_holdings)],
        'operations': {r['symbol']: r.get(symbol) for r in _frame_rows(funds.fund_operations)},
      }
    except Exception as e:
      log.info('fund data for %s failed: %s', symbol, e)
  return _clean(result)


# --- cached, async entry points ---

def _fresh(cached: Optional[dict], hint: dict) -> bool:
  if cached is None or cached.get('hint') != hint or cached.get('version') != CACHE_VERSION:
    return False
  ttl = ERROR_TTL if cached.get('error') else CACHE_TTL
  return datetime.fromisoformat(cached['fetched_at']) + ttl > datetime.now(timezone.utc)


async def classify_holdings(store: Store, holdings: list[tuple[str, Optional[str]]],
                            look_through: dict, prices: Optional[PriceBook] = None) -> dict[str, dict]:
  """{asset: classification} for (asset, name) pairs, refreshing stale cache entries concurrently."""
  results: dict[str, dict] = {}
  stale = []
  for asset, name in holdings:
    hint = look_through.get(asset) or {}
    cached = store.get_classification(asset)
    if _fresh(cached, hint):
      results[asset] = cached
    else:
      stale.append((asset, name, hint))

  async def refresh(asset, name, hint):
    try:
      data = await asyncio.wait_for(asyncio.to_thread(classify, asset, name, hint, prices), LOOKUP_TIMEOUT * 2)
      data['error'] = None
    except Exception as e:
      log.warning('classify %s failed: %s', asset, e)
      data = {'kind': 'unknown', 'name': name or asset, 'symbol': None, 'countries': {'Unknown': 1.0},
              'sectors': {'Unknown': 1.0}, 'holdings': [], 'source': None, 'price_gbp': None,
              'error': f'{type(e).__name__}: {e}'}
    return asset, data | {'hint': hint, 'fetched_at': now(), 'version': CACHE_VERSION}

  for asset, data in await asyncio.gather(*[refresh(*s) for s in stale]):
    store.set_classification(asset, data)  # on the event loop thread, like all SQLite access
    results[asset] = data
  return results


async def quote(ticker: str, prices: PriceBook) -> dict:
  """A holding to add in the sandbox: name, GBP price and exposure. Not cached."""
  data = await asyncio.wait_for(asyncio.to_thread(classify, ticker.upper(), None, {}, prices), LOOKUP_TIMEOUT * 2)
  return data | {'asset': ticker.upper(), 'error': None}



_details_cache: dict[str, tuple[datetime, dict]] = {}
DETAILS_TTL = timedelta(hours=6)


async def cached_details(symbol: str) -> dict:
  """details(), kept in memory for a few hours."""
  symbol = symbol.upper()
  hit = _details_cache.get(symbol)
  if hit and hit[0] + DETAILS_TTL > datetime.now(timezone.utc):
    return hit[1]
  data = await asyncio.wait_for(asyncio.to_thread(details, symbol), LOOKUP_TIMEOUT)
  _details_cache[symbol] = (datetime.now(timezone.utc), data)
  return data
