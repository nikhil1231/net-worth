import asyncio

import requests

TIMEOUT = 30


async def get_json(url, params=None, headers=None):
  def f():
    res = requests.get(url, params=params, headers=headers, timeout=TIMEOUT)
    res.raise_for_status()
    return res.json()
  return await asyncio.to_thread(f)


async def post_json(url, json=None, data=None, headers=None):
  def f():
    res = requests.post(url, json=json, data=data, headers=headers, timeout=TIMEOUT)
    res.raise_for_status()
    return res.json()
  return await asyncio.to_thread(f)
