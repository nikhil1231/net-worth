import asyncio
import logging
import math
import time
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from networth import classify, reports, settings
from networth.config import Config, ConfigError
from networth.pricing import fetch_price_book
from networth.runner import Runner
from networth.store import Store

log = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).parent / 'static'


async def schedule(runner: Runner):
  while True:
    try:
      await runner.run()
    except Exception:
      log.exception('scheduled run failed')
    await asyncio.sleep(runner.config.tick_minutes * 60)  # read each time: the settings page can change it


def create_app(config: Config, run_scheduler: bool = True) -> FastAPI:
  store = Store(config.db_path)
  runner = Runner(config, store)

  @asynccontextmanager
  async def lifespan(app):
    task = asyncio.create_task(schedule(runner)) if run_scheduler else None
    yield
    if task:
      task.cancel()

  # Handlers are async so all SQLite access happens on the event loop thread.
  app = FastAPI(title='Net worth', lifespan=lifespan)

  fx_cache = {}
  fx_lock = asyncio.Lock()

  @app.get('/api/fx')
  async def fx():
    async with fx_lock:
      if not fx_cache or time.monotonic() - fx_cache['cached_at'] > 900:
        try:
          prices = await fetch_price_book()
          usd = prices.rates.get('USD')
          if usd is None or not math.isfinite(usd) or usd <= 0:
            raise ValueError('No valid GBP/USD rate')
          currencies = ('GBP', 'USD', 'EUR', 'JPY', 'CAD', 'AUD', 'CHF', 'HKD', 'CNY', 'NZD', 'SGD', 'INR')
          rates = {c: prices.rates[c] for c in currencies
                   if c in prices.rates and math.isfinite(prices.rates[c]) and prices.rates[c] > 0}
          fx_cache.update(cached_at=time.monotonic(), data={
            'base': 'GBP', 'rates': rates, 'updated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
          })
        except Exception as e:
          log.warning('Display exchange rates unavailable: %s', e)
          raise HTTPException(502, 'Exchange rates are temporarily unavailable')
      return fx_cache['data']

  @app.get('/health')
  async def health():
    return {'ok': True}

  @app.get('/api/summary')
  async def summary():
    return reports.summary(store, config)

  @app.get('/api/history')
  async def history(days: Optional[int] = Query(None, ge=1), group: str = Query('category', pattern='^(category|account)$')):
    return reports.history(store, days, group)

  @app.post('/api/refresh')
  async def refresh(account: Optional[str] = None):
    if account and account not in {a.name for a in config.accounts}:
      raise HTTPException(404, f'No account named {account!r}')
    await runner.run(force=True, only=[account] if account else None)
    return reports.summary(store, config)

  @app.get('/api/accounts/{name}')
  async def account_detail(name: str):
    """One account's holdings, plus country/sector exposure for investment accounts."""
    account = next((a for a in reports.summary(store, config)['accounts'] if a['name'] == name), None)
    if account is None:
      raise HTTPException(404, f'No account named {name!r}')
    classifications = {}
    if account['category'] == 'investments' and account['holdings']:
      look_through = config.account(name).params.get('look_through') or {}
      classifications = await classify.classify_holdings(
        store, [(h['asset'], h['name']) for h in account['holdings']], look_through)
    return account | {'classifications': classifications} | reports.wallet_details(store, config, name)

  @app.get('/api/accounts/{name}/chains/{chain}')
  async def chain_detail(name: str, chain: str):
    try:
      return reports.chain_details(store, config, name, chain)
    except (ConfigError, ValueError) as e:
      raise HTTPException(404, str(e))

  @app.get('/api/accounts/{name}/wallets/{wallet}')
  async def wallet_detail(name: str, wallet: str):
    try:
      return reports.crypto_details(store, config, name, wallet=wallet)
    except (ConfigError, ValueError) as e:
      raise HTTPException(404, str(e))

  @app.get('/api/quote')
  async def quote(ticker: str = Query(..., min_length=1, max_length=20, pattern=r'^[A-Za-z0-9.\-]+$')):
    """Price and exposure of a ticker that isn't held, for the sandbox."""
    try:
      return await classify.quote(ticker, await fetch_price_book())
    except LookupError as e:
      raise HTTPException(404, str(e))
    except (RuntimeError, asyncio.TimeoutError) as e:
      raise HTTPException(502, str(e) or f'Yahoo Finance took too long for {ticker}')

  @app.get('/api/details')
  async def details(symbol: str = Query(..., min_length=1, max_length=24, pattern=r'^[A-Za-z0-9.\-]+$')):
    """Everything Yahoo Finance has on a listing (a classification's `symbol`), for the details view."""
    try:
      return await classify.cached_details(symbol)
    except LookupError as e:
      raise HTTPException(404, str(e))
    except RuntimeError as e:
      raise HTTPException(502, str(e))
    except asyncio.TimeoutError:
      raise HTTPException(504, f'Yahoo Finance took too long for {symbol}')

  # --- settings: edit accounts.yaml, then swap the new accounts into the running config ---

  def config_path():
    if config.path is None:
      raise HTTPException(409, 'Config was not loaded from a file')
    return config.path

  def edit_config(edit):
    try:
      new = edit(config_path())
    except ConfigError as e:
      raise HTTPException(400, str(e))
    except OSError as e:
      raise HTTPException(409, f"Couldn't write {config.path}: {e}")
    config.accounts = new.accounts
    config.tick_minutes = new.tick_minutes
    return config_payload()

  def config_payload():
    return settings.read(config_path()) | {'connectors': settings.connectors_info()}

  @app.get('/api/config')
  async def get_config():
    return config_payload()

  @app.post('/api/config/accounts')
  async def add_account(account: dict = Body(...)):
    return edit_config(lambda path: settings.save_account(path, None, account))

  @app.put('/api/config/accounts/{name}')
  async def update_account(name: str, account: dict = Body(...)):
    result = edit_config(lambda path: settings.save_account(path, name, account))
    new_name = str(account.get('name') or '').strip()
    if new_name != name:
      store.rename_account(name, new_name)
      settings.rename_state_files(config.data_dir, name, new_name)
    return result

  @app.delete('/api/config/accounts/{name}')
  async def delete_account(name: str):
    return edit_config(lambda path: settings.delete_account(path, name))

  @app.put('/api/config/settings')
  async def update_settings(values: dict = Body(...)):
    return edit_config(lambda path: settings.save_settings(path, values))

  # The React app (built from frontend/ into static/). Client-side routes all serve index.html.
  if (STATIC_DIR / 'assets').is_dir():
    app.mount('/assets', StaticFiles(directory=STATIC_DIR / 'assets'), name='assets')

  @app.get('/{path:path}', include_in_schema=False)
  async def spa(path: str):
    if path.startswith('api/'):
      raise HTTPException(404)
    file = STATIC_DIR / path
    if path and file.is_file() and file.resolve().is_relative_to(STATIC_DIR.resolve()):
      return FileResponse(file)
    index = STATIC_DIR / 'index.html'
    if not index.exists():
      return HTMLResponse('<p>Dashboard not built - run <code>npm run build</code> in frontend/.</p>', 503)
    return FileResponse(index)

  return app
