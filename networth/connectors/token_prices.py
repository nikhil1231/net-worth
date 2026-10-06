"""Optional exact-contract USD quotes; never guesses a token from its ticker."""
import logging
import math
from networth import http

log = logging.getLogger(__name__)


async def token_usd_price(token, quantity):
  """USD value of `quantity`, or None if there's no quote. A failed quote never fails the balance."""
  if not quantity:
    return None
  price = await token_usd_quote(token)
  return None if price is None else price * quantity


async def token_usd_quote(token):
  """USD price of one token, or None if it has no price_url or the quote failed."""
  if not token.get('price_url'):
    return None
  try:
    return await _quote(token)
  except Exception as e:
    log.warning('%s: no quote from %s (%s: %s)', token['symbol'], token['price_url'], type(e).__name__, e)
    return None


async def _quote(token):
  data = await http.get_json(token['price_url'])
  if token.get('price_source') == 'dexscreener':
    address = token.get('mint') or token['contract']
    pairs = [p for p in data
             if p['baseToken']['address'].lower() == address.lower()
             and p.get('priceUsd') and float(p.get('liquidity', {}).get('usd') or 0) > 0]
    if not pairs:
      raise RuntimeError(f"No liquid exact-mint quote for {token['symbol']}")
    data = max(pairs, key=lambda p: float(p['liquidity']['usd']))
    raw = data['priceUsd']
  else:
    raw = data.get('exchange_rate')
  if raw is None:
    raise RuntimeError(f"No exact-contract quote for {token['symbol']}")
  price = float(raw)
  if not math.isfinite(price) or price <= 0:
    raise RuntimeError(f"Invalid quote for {token['symbol']}")
  return price
