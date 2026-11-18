from fastapi.testclient import TestClient

from networth.config import Config
from networth.pricing import PriceBook
from networth.store import Store
from networth.web import app as web


def test_fx_is_cached_and_does_not_rewrite_snapshots(monkeypatch, tmp_path):
  calls = []
  async def prices():
    calls.append(1)
    return PriceBook({'USD': 1.25, 'EUR': 1.1})
  monkeypatch.setattr(web, 'fetch_price_book', prices)
  config = Config([], data_dir=tmp_path)
  client = TestClient(web.create_app(config, run_scheduler=False))
  first = client.get('/api/fx')
  assert first.status_code == 200
  assert first.json()['rates'] == {'GBP': 1.0, 'USD': 1.25, 'EUR': 1.1}
  assert client.get('/api/fx').json() == first.json()
  assert len(calls) == 1
  assert Store(config.db_url).latest_run() is None


def test_invalid_fx_does_not_return_a_fabricated_conversion(monkeypatch, tmp_path):
  async def prices():
    return PriceBook({'USD': 0})
  monkeypatch.setattr(web, 'fetch_price_book', prices)
  client = TestClient(web.create_app(Config([], data_dir=tmp_path), run_scheduler=False))
  assert client.get('/api/fx').status_code == 502
