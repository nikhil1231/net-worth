from dataclasses import dataclass
from typing import Optional


@dataclass
class Holding:
  """
  Something held in an account, as reported by a connector.

  Connectors report quantities and the pricing layer values them in GBP. If the source
  already knows the value (e.g. HL pricing a fund), set `value` + `currency` and that
  is used instead of a market price.
  """
  asset: str
  quantity: float
  value: Optional[float] = None
  currency: Optional[str] = None
  name: Optional[str] = None
  wallet: Optional[str] = None
  chain: Optional[str] = None
