import asyncio
from base_classes import SourceController
from sources import sources

if __name__ == "__main__":
  sc = SourceController()

  for source in sources:
    sc.add_source(source)

  print(asyncio.run(sc.get_total()))