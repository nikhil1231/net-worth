import asyncio

class Source:
  def __init__(self, name, category):
    self.name = name
    self.category = category

  async def get_value(self):
    raise NotImplementedError()

class SourceController:
  def __init__(self):
    self.sources = []

  def add_source(self, source: Source):
    self.sources.append(source)

  async def get_total(self):
    return sum(await asyncio.gather(*[s.get_value() for s in self.sources]))
