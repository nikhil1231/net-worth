import ccxt.async_support as ccxt
from typing import Dict, Optional, Any, List
import util
import asyncio


def init_client():
  client = ccxt.binance({
    'apiKey': util.get_env_var('BINANCE_API_KEY'),
    'secret': util.get_env_var('BINANCE_SECRET_KEY'),
    'sandbox': False,  # Set to True for testnet
    'enableRateLimit': True,
  })
  return client

client = init_client()

async def get_symbol_price(symbol: str) -> Dict[str, Any]:
  """
  Get the current price of a given symbol.

  Args:
    symbol (str): Trading pair symbol (e.g., 'BTC/USDT', 'ETH/USDT')

  Returns:
    Dict[str, Any]: Price information including bid, ask, last, etc.

  Raises:
    Exception: If there's an error fetching the price
  """
  try:
    ticker = await client.fetch_ticker(symbol)

    return ticker['bid']
  except Exception as e:
    raise Exception(f"Error fetching price for {symbol}: {str(e)}")

async def get_symbol_prices(symbols: List[str]) -> Dict[str, Any]:
  return await asyncio.gather(*[get_symbol_price(symbol) for symbol in symbols])

async def get_spot_balances() -> Dict[str, Dict[str, Any]]:
  """
  Get the balances of the spot account.

  Returns:
    Dict[str, Dict[str, Any]]: Dictionary of balances with currency as key
                  Each balance contains free, used, and total amounts

  Raises:
    Exception: If there's an error fetching the balances
  """
  try:
    balances = await client.fetch_balance()

    # Filter out zero balances and format the response
    non_zero_balances = {}
    for currency, balance in balances['total'].items():
      if balance > 0:
        non_zero_balances[currency] = {
          'free': balances['free'].get(currency, 0),
          'used': balances['used'].get(currency, 0),
          'total': balance,
        }

    return non_zero_balances
  except Exception as e:
    raise Exception(f"Error fetching spot balances: {str(e)}")

async def get_balance_for_currency(currency: str) -> Optional[Dict[str, Any]]:
  """
  Get the balance for a specific currency.

  Args:
    currency (str): Currency symbol (e.g., 'BTC', 'USDT', 'ETH')

  Returns:
    Optional[Dict[str, Any]]: Balance information for the currency, or None if not found
  """
  try:
    balances = await get_spot_balances()
    return balances.get(currency.upper())
  except Exception as e:
    print(f"Error fetching balance for {currency}: {str(e)}")
    return None

async def get_total_usd_value() -> Dict[str, Any]:
  """
  Calculate the total USD value of the spot wallet.
  Fetches balances and prices concurrently for better performance.

  Returns:
    Dict[str, Any]: Dictionary containing total USD value and breakdown by currency
  """
  try:
    # Get all balances first
    balances = await get_spot_balances()

    if not balances:
      return {
        'total_usd_value': 0.0,
        'currencies': {},
        'error': None
      }

    # Create tasks for fetching prices of all currencies (except USDT)
    price_tasks = []
    currencies_to_price = []

    for currency in balances.keys():
      if currency not in ['USDT', 'USDC', 'GBP']:
        symbol = f"{currency}/USDT"
        price_tasks.append(get_symbol_price(symbol))
        currencies_to_price.append(currency)

    # Execute all price fetching tasks concurrently
    prices = await asyncio.gather(*price_tasks, return_exceptions=True)

    # Calculate USD values
    total_usd_value = 0.0
    currency_breakdown = {}

    # Handle USDT separately (1:1 with USD)
    if 'USDT' in balances:
      usdt_value = balances['USDT']['total']
      total_usd_value += usdt_value
      currency_breakdown['USDT'] = {
        'balance': balances['USDT']['total'],
        'price_usd': 1.0,
        'value_usd': usdt_value
      }

    if 'USDC' in balances:
      usdc_value = balances['USDC']['total']
      total_usd_value += usdc_value
      currency_breakdown['USDC'] = {
        'balance': balances['USDC']['total'],
        'price_usd': 1.0,
        'value_usd': usdc_value
      }

    # Calculate values for other currencies
    for i, currency in enumerate(currencies_to_price):
      try:
        price = prices[i]
        if isinstance(price, Exception):
          print(f"Error fetching price for {currency}: {price}")
          continue

        balance = balances[currency]['total']
        value_usd = balance * price

        total_usd_value += value_usd
        currency_breakdown[currency] = {
          'balance': balance,
          'price_usd': price,
          'value_usd': value_usd
        }
      except Exception as e:
        print(f"Error calculating value for {currency}: {str(e)}")
        continue

    return {
      'total_usd_value': round(total_usd_value, 2),
      'currencies': currency_breakdown,
      'error': None
    }

  except Exception as e:
    return {
      'total_usd_value': 0.0,
      'currencies': {},
      'error': str(e)
    }

async def close_client():
  """
  Close the async client connection.
  Should be called when done using the client.
  """
  await client.close()
