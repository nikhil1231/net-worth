import asyncio

async def run_async(f, *args):
  loop = asyncio.get_event_loop()
  return await loop.run_in_executor(None, f, *args)
