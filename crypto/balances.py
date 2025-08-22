import util

async def get_btc_balance(addr: str):
  val = await util.get_async('https://blockchain.info/q/addressbalance/' + addr)
  return val / 1e8