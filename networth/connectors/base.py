from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Optional

from networth.config import AccountConfig, ConfigError
from networth.models import Holding

_REGISTRY: dict[str, type['Connector']] = {}
_REQUIRED = object()


@dataclass
class Field:
  """
  A param as the settings page shows it. Kinds: text, secret (masked unless it's a ${VAR}), number,
  list (of strings, one per line), bool, yaml (anything nested). Params without a Field still work,
  they're just edited as YAML.
  """
  key: str
  label: str
  kind: Literal['text', 'secret', 'number', 'list', 'bool', 'yaml'] = 'text'
  required: bool = False
  help: Optional[str] = None
  placeholder: Optional[str] = None
  default: Any = None  # what the connector uses when it's left out


def connector(type_name: str):
  """Register a connector class under the `type` used in accounts.yaml."""
  def register(cls):
    if type_name in _REGISTRY:
      raise ValueError(f'Connector type {type_name!r} registered twice')
    cls.type = type_name
    _REGISTRY[type_name] = cls
    return cls
  return register


def connector_classes() -> dict[str, type['Connector']]:
  return dict(_REGISTRY)


def state_slug(account_name: str) -> str:
  return ''.join(c if c.isalnum() else '_' for c in account_name.lower())


def get_connector_class(type_name: str) -> type['Connector']:
  if type_name not in _REGISTRY:
    known = ', '.join(sorted(_REGISTRY))
    raise ConfigError(f'Unknown connector type {type_name!r} (known: {known})')
  return _REGISTRY[type_name]


class Connector(ABC):
  """
  A source of holdings. Subclasses implement `fetch` and register with @connector.

  `data_dir` is somewhere to persist state between runs (cookies, OAuth tokens).
  """
  type: str
  label: str = ''  # for the settings page
  fields: list[Field] = []

  def __init__(self, account: AccountConfig, data_dir: Path):
    self.account = account
    self.data_dir = data_dir

  def param(self, key: str, default: Any = _REQUIRED) -> Any:
    if key in self.account.params:
      return self.account.params[key]
    if default is _REQUIRED:
      raise ConfigError(f'{self.account.name}: missing param {key!r}')
    return default

  def state_file(self, suffix: str) -> Path:
    return self.data_dir / f'{state_slug(self.account.name)}.{suffix}'

  @abstractmethod
  async def fetch(self) -> list[Holding]:
    ...
