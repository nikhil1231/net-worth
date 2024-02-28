from base_classes import Source
import requests
import asyncio
import util

CATEGORY = 'crypto'

class BitcoinHardSource(Source):
  def __init__(self, name, *addresses):
    super(BitcoinHardSource, self).__init__(name, CATEGORY)
    self.addresses = addresses

  async def get_value(self):
    _btcusd = util.run_async(BitcoinHardSource.__get_btc_value)

    _balances = [util.run_async(BitcoinHardSource.__get_address_balance, addr) for addr in self.addresses]

    btcusd, *balances = await asyncio.gather(_btcusd, *_balances)

    return btcusd * sum(balances) / 1e8

  def __get_btc_value():
    url = 'https://blockchain.info/ticker'
    res = requests.get(url)
    return res.json()['USD']['last']

  def __get_address_balance(address):
    url = 'https://blockchain.info/q/addressbalance/{}'
    res = requests.get(url.format(address))
    return res.json()