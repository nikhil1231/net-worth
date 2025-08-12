from sheets import sheets
from crypto import binance
import asyncio

async def update_prices():
  symbols = sheets.get_crypto_symbols()
  prices = await binance.get_symbol_prices(symbols)
  sheets.write_crypto_prices(prices)

async def update_exchange_values():
  binance_spot_values = await binance.get_total_usd_value()
  binance_usd_value = binance_spot_values['total_usd_value']
  sheets.write_exchange_values([binance_usd_value])

async def main():
  await update_prices()
  await update_exchange_values()

  await binance.close_client()

if __name__ == "__main__":
  asyncio.run(main())