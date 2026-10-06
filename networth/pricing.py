from typing import Optional

from networth import http
from networth.models import Holding

# Coinbase's public rates endpoint covers fiat and ~650 crypto assets in one unauthenticated call.
RATES_URL = 'https://api.coinbase.com/v2/exchange-rates'
BASE_CURRENCY = 'GBP'
# Assets Coinbase doesn't list, priced as an equivalent one.
ALIASES = {
  'XBT': 'BTC',
  'USDB': 'USD',     # Blast's USD stablecoin
  'USDC.E': 'USDC',  # bridged USDC
}


class PriceBook:
  """GBP prices for assets, from rates expressed as units of asset per 1 GBP."""

  def __init__(self, rates: dict[str, float]):
    self.rates = {k.upper(): float(v) for k, v in rates.items()}
    self.rates[BASE_CURRENCY] = 1.0

  def price(self, asset: str) -> Optional[float]:
    asset = asset.upper()
    rate = self.rates.get(ALIASES.get(asset, asset))
    return 1 / rate if rate else None

  def value(self, holding: Holding) -> tuple[Optional[float], Optional[float]]:
    """Returns (price per unit in GBP, total value in GBP); None where unknown."""
    if holding.value is not None:
      fx = self.price(holding.currency or BASE_CURRENCY)
      if fx is None:
        return None, None
      value = holding.value * fx
      return (value / holding.quantity if holding.quantity else None), value

    price = self.price(holding.asset)
    if price is None:
      return None, None
    return price, holding.quantity * price


async def fetch_price_book() -> PriceBook:
  res = await http.get_json(RATES_URL, params={'currency': BASE_CURRENCY})
  return PriceBook(res['data']['rates'])
