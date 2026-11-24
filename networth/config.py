import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import dotenv
import yaml

ENV_PATTERN = re.compile(r'\$\{(\w+)\}')


class ConfigError(Exception):
  pass


@dataclass
class AccountConfig:
  name: str
  type: str
  category: str
  interval: int  # minutes between fetches
  params: dict[str, Any] = field(default_factory=dict)
  # Set when params can't be resolved (e.g. a missing env var); only this account fails.
  error: Optional[str] = None


@dataclass
class Config:
  accounts: list[AccountConfig]
  tick_minutes: int = 15
  data_dir: Path = Path('data')
  path: Optional[Path] = None  # the accounts.yaml this came from, for the settings page to edit

  @property
  def db_url(self) -> str:
    """The Postgres database (DATABASE_URL)."""
    return os.environ['DATABASE_URL']

  def account(self, name: str) -> AccountConfig:
    for account in self.accounts:
      if account.name == name:
        return account
    raise ConfigError(f'No account named {name!r} in config')


def load_config(path: str | Path = 'accounts.yaml') -> Config:
  dotenv.load_dotenv()
  path = Path(path)
  if not path.exists():
    raise ConfigError(f'{path} not found - copy accounts.example.yaml to get started')

  return parse_config(yaml.safe_load(path.read_text()) or {}, path)


def parse_config(raw: dict, path: Optional[Path] = None) -> Config:
  settings = raw.get('settings') or {}
  tick_minutes = int(settings.get('tick_minutes', 15))
  default_interval = int(settings.get('default_interval', tick_minutes))

  accounts = []
  for i, entry in enumerate(raw.get('accounts') or []):
    for key in ('name', 'type', 'category'):
      if key not in entry:
        raise ConfigError(f'Account #{i + 1} is missing {key!r}')
    try:
      params, error = _interpolate_env(entry.get('params') or {}), None
    except ConfigError as e:
      params, error = {}, str(e)
    accounts.append(AccountConfig(
      name=entry['name'],
      type=entry['type'],
      category=entry['category'],
      interval=int(entry.get('interval', default_interval)),
      params=params,
      error=error,
    ))

  names = [a.name for a in accounts]
  duplicates = {n for n in names if names.count(n) > 1}
  if duplicates:
    raise ConfigError(f'Duplicate account names: {", ".join(sorted(duplicates))}')

  data_dir = Path(settings.get('data_dir', 'data'))
  data_dir.mkdir(parents=True, exist_ok=True)

  return Config(accounts=accounts, tick_minutes=tick_minutes, data_dir=data_dir, path=path)


def _interpolate_env(value):
  """Replace ${VAR} in any string within params with the environment variable's value."""
  if isinstance(value, dict):
    return {k: _interpolate_env(v) for k, v in value.items()}
  if isinstance(value, list):
    return [_interpolate_env(v) for v in value]
  if isinstance(value, str):
    def replace(match):
      key = match.group(1)
      if key not in os.environ:
        raise ConfigError(f'{key} not found in environment (.env)')
      return os.environ[key]
    return ENV_PATTERN.sub(replace, value)
  return value
