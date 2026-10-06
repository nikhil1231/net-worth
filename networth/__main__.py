import argparse
import asyncio
import logging
import os

from networth import reports
from networth.config import load_config
from networth.connectors import get_connector_class
from networth.pricing import fetch_price_book
from networth.runner import Runner, fetch_account
from networth.store import Store


def main():
  parser = argparse.ArgumentParser(prog='networth')
  parser.add_argument('--config', default=os.getenv('NETWORTH_CONFIG', 'accounts.yaml'))
  sub = parser.add_subparsers(dest='command', required=True)

  run_p = sub.add_parser('run', help='fetch due accounts once and save a snapshot')
  run_p.add_argument('--force', action='store_true', help='fetch every account, not just due ones')

  check_p = sub.add_parser('check', help='fetch accounts and print holdings without saving')
  check_p.add_argument('accounts', nargs='*', help='account names (default: all)')

  serve_p = sub.add_parser('serve', help='run the dashboard and the scheduler')
  serve_p.add_argument('--host', default='127.0.0.1')
  serve_p.add_argument('--port', type=int, default=8000)

  monzo_p = sub.add_parser('monzo-auth', help='log in to a Monzo account')
  monzo_p.add_argument('account')

  args = parser.parse_args()
  logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
  config = load_config(args.config)

  if args.command == 'run':
    store = Store(config.db_path)
    asyncio.run(Runner(config, store).run(force=args.force))
    print_summary(reports.summary(store, config))
  elif args.command == 'check':
    asyncio.run(check(config, args.accounts))
  elif args.command == 'serve':
    import uvicorn
    from networth.web.app import create_app
    uvicorn.run(create_app(config), host=args.host, port=args.port)
  elif args.command == 'monzo-auth':
    account = config.account(args.account)
    asyncio.run(get_connector_class('monzo')(account, config.data_dir).authorize())


async def check(config, names):
  accounts = [config.account(n) for n in names] if names else config.accounts
  prices = await fetch_price_book()
  results = await asyncio.gather(*[fetch_account(a, config) for a in accounts], return_exceptions=True)
  for account, result in zip(accounts, results):
    print(f'\n{account.name} ({account.type})')
    if isinstance(result, BaseException):
      print(f'  ERROR {type(result).__name__}: {result}')
      continue
    for holding in result:
      _, value = prices.value(holding)
      value_str = f'£{value:,.2f}' if value is not None else 'unpriced'
      print(f'  {holding.asset:<10} {holding.quantity:>18,.8g}  {value_str:>14}  {holding.name or ""}')


def print_summary(s):
  print(f'\nNet worth: £{s["total"]:,.2f}')
  for category, value in s['categories'].items():
    print(f'  {category:<12} £{value:>14,.2f}')
  print()
  for account in s['accounts']:
    flag = f'  ! {account["last_error"]}' if account['last_error'] else ''
    print(f'  {account["name"]:<24} £{account["value"]:>14,.2f}{flag}')


if __name__ == '__main__':
  main()
