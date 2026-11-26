from decimal import Decimal
from typing import Optional

from networth import http
from networth.models import Holding, pennies, to_decimal

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
  """
  GBP prices for assets, from rates expressed as units of asset per 1 GBP (Coinbase sends them as strings).

  Values are divided by the rate rather than multiplied by a rounded price, and rounded to the penny once.
  A price is 1 / rate to 28 significant digits: market data, as exact as it is ever going to be.
  """

  def __init__(self, rates: dict[str, str | Decimal | float]):
    self.rates = {k.upper(): to_decimal(v) for k, v in rates.items()}
    self.rates[BASE_CURRENCY] = Decimal(1)

  def _rate(self, asset: str) -> Optional[Decimal]:
    asset = asset.upper()
    rate = self.rates.get(ALIASES.get(asset, asset))
    return rate if rate else None

  def price(self, asset: str) -> Optional[Decimal]:
    rate = self._rate(asset)
    return 1 / rate if rate else None

  def value(self, holding: Holding) -> tuple[Optional[Decimal], Optional[Decimal]]:
    """Returns (price per unit in GBP, total value in GBP to the penny); None where unknown."""
    if holding.value is not None:
      rate = self._rate(holding.currency or BASE_CURRENCY)
      if rate is None:
        return None, None
      value = holding.value / rate
      return (value / holding.quantity if holding.quantity else None), pennies(value)

    rate = self._rate(holding.asset)
    if rate is None:
      return None, None
    return 1 / rate, pennies(holding.quantity / rate)


async def fetch_price_book() -> PriceBook:
  res = await http.get_json(RATES_URL, params={'currency': BASE_CURRENCY})
  return PriceBook(res['data']['rates'])
