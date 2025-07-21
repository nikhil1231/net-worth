import asyncio
import os
import dotenv

dotenv.load_dotenv()

async def run_async(f, *args):
  loop = asyncio.get_event_loop()
  return await loop.run_in_executor(None, f, *args)

def get_env_var(key):
  val = os.getenv(key)
  if not val:
    raise ValueError(f'{key} not found in environment')
  return val
