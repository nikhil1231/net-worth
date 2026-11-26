from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Optional

PENNY = Decimal('0.01')


def to_decimal(value) -> Decimal:
  """
  An exact Decimal from a str, int or Decimal. A float (from YAML, a JSON number or ccxt) goes through
  its shortest repr, so 0.1 becomes Decimal('0.1') rather than 0.1000000000000000055511151231257827.
  """
  if isinstance(value, Decimal):
    result = value
  elif isinstance(value, bool):
    raise TypeError(f'Not a number: {value!r}')
  elif isinstance(value, (int, str)):
    result = Decimal(value.strip() if isinstance(value, str) else value)
  elif isinstance(value, float):
    result = Decimal(repr(value))
  else:
    raise TypeError(f'Not a number: {value!r}')
  if not result.is_finite():
    raise ValueError(f'Not a finite number: {value!r}')
  return result


def from_units(raw: int, decimals: int) -> Decimal:
  """An integer on-chain balance (sats, wei, lamports) in whole units, exactly."""
  return Decimal(int(raw)).scaleb(-decimals)


def pennies(value: Decimal) -> Decimal:
  return value.quantize(PENNY, rounding=ROUND_HALF_EVEN)


@dataclass
class Holding:
  """
  Something held in an account, as reported by a connector.

  Connectors report quantities and the pricing layer values them in GBP. If the source
  already knows the value (e.g. HL pricing a fund), set `value` + `currency` and that
  is used instead of a market price. Both are kept as exact Decimals.
  """
  asset: str
  quantity: Decimal
  value: Optional[Decimal] = None
  currency: Optional[str] = None
  name: Optional[str] = None
  wallet: Optional[str] = None
  chain: Optional[str] = None

  def __post_init__(self):
    self.quantity = to_decimal(self.quantity)
    if self.value is not None:
      self.value = to_decimal(self.value)
