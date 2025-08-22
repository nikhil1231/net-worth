import asyncio

from sheets import sheets
from crypto import binance, balances
import hl
import util

async def update_prices():
  print('updating crypto prices')
  symbols = sheets.get_crypto_symbols()
  prices = await binance.get_symbol_prices(symbols)
  sheets.write_crypto_prices(prices)

async def update_exchange_values():
  print('updating exchange values')
  binance_spot_values = await binance.get_total_usd_value()
  binance_usd_value = binance_spot_values['total_usd_value']
  sheets.write_exchange_values([binance_usd_value])

async def update_hl():
  print('updating HL holdings')
  holdings = await util.run_async(hl.get_holdings)
  truncated_holdings = [list(holding.values())[:8] for holding in holdings]
  sheets.write_hl_values(truncated_holdings)

async def update_wallet_balances():
  print("updating wallet amounts")
  addrs = sheets.get_btc_addresses()

  vals = await asyncio.gather(*[balances.get_btc_balance(addr) for addr in addrs])
  sheets.write_btc_amounts(vals)

async def main():
  tasks = [update_prices(), update_exchange_values(), update_hl(), update_wallet_balances()]
  await asyncio.gather(*tasks)

  await binance.close_client()

if __name__ == "__main__":
  asyncio.run(main())