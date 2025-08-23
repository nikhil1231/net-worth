import util
from typing import List
import asyncio

async def get_btc_balances(addrs: List[str]):
  return await asyncio.gather(*[get_btc_balance(addr) for addr in addrs])

async def get_btc_balance(addr: str):
  val = await util.get_async('https://blockchain.info/q/addressbalance/' + addr)
  return val / 1e8

async def get_eth_balances(addrs: List[str]):
  params = {
    'chainid': 1,
    'module': 'account',
    'action': 'balancemulti',
    'address': ','.join(addrs),
    'tag': 'latest',
    'apikey': util.get_env_var('ETHERSCAN'),
  }
  res = await util.get_async('https://api.etherscan.io/v2/api', params=params)

  return (int(r['balance']) / 1e18 for r in res['result'])

async def get_sol_balances(addrs: List[str]):
  return await asyncio.gather(*[get_sol_balance(addr) for addr in addrs])

async def get_sol_balance(addr: str):
  data = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "getBalance",
    "params": [
      addr,
      {
        "commitment": "finalized"
      }
    ]
  }
  res = await util.post_async('https://api.mainnet-beta.solana.com', data=data)
  return res['result']['value'] / 1e9
