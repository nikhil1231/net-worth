import asyncio
import os
import dotenv
import requests

dotenv.load_dotenv()

async def run_async(f, *args):
  loop = asyncio.get_event_loop()
  return await loop.run_in_executor(None, f, *args)

async def get_async(url, params=None):
  def f():
    res = requests.get(url, params=params)
    return res.json()
  return await run_async(f)

def get_env_var(key):
  val = os.getenv(key)
  if not val:
    raise ValueError(f'{key} not found in environment')
  return val
