"""
Reads and edits accounts.yaml for the dashboard's settings page.

Edits go through ruamel.yaml so comments and formatting survive. Secret params never reach the
browser: literal values are sent as SECRET_MASK, and SECRET_MASK coming back means "unchanged".
${VAR} references aren't secret, so they're shown as they are.
"""
import io
import os
import shutil
from dataclasses import asdict
from pathlib import Path
from typing import Any, Optional

import yaml
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from networth.config import ENV_PATTERN, Config, ConfigError, parse_config
from networth.connectors import connector_classes, get_connector_class
from networth.connectors.base import state_slug

SECRET_MASK = '••••••••'
BACKUP_NAME = 'accounts.yaml.prev'


def _yaml() -> YAML:
  y = YAML()
  y.preserve_quotes = True
  y.indent(mapping=2, sequence=4, offset=2)  # matches accounts.example.yaml
  y.width = 4096
  return y


def connectors_info() -> dict:
  return {
    type_name: {'label': cls.label or type_name, 'fields': [asdict(f) for f in cls.fields]}
    for type_name, cls in sorted(connector_classes().items())
  }


def read(path: Path) -> dict:
  doc = _load(path)
  settings = doc.get('settings') or {}
  tick_minutes = int(settings.get('tick_minutes', 15))
  return {
    'path': str(path),
    'writable': os.access(path, os.W_OK),
    'settings': {
      'tick_minutes': tick_minutes,
      'default_interval': int(settings.get('default_interval', tick_minutes)),
    },
    'accounts': [
      {
        'name': entry.get('name'),
        'type': entry.get('type'),
        'category': entry.get('category'),
        'interval': entry.get('interval'),
        'params': _mask(entry.get('type'), _plain(entry.get('params') or {})),
      }
      for entry in doc['accounts']
    ],
  }


def save_account(path: Path, original: Optional[str], account: dict) -> Config:
  """Add an account (`original` None) or replace the one called `original`. Returns the new config."""
  doc = _load(path)
  accounts = doc['accounts']
  index = _find(accounts, original) if original is not None else None

  name = str(account.get('name') or '').strip()
  category = str(account.get('category') or '').strip()
  type_name = str(account.get('type') or '').strip()
  if not name:
    raise ConfigError('Name is required')
  if not category:
    raise ConfigError('Category is required')
  cls = get_connector_class(type_name)
  if name != original and any(e.get('name') == name for e in accounts):
    raise ConfigError(f'There is already an account named {name!r}')
  interval = account.get('interval')
  if interval in ('', None):
    interval = None
  elif not isinstance(interval, int) or isinstance(interval, bool) or interval < 1:
    raise ConfigError('Interval must be a whole number of minutes')

  params = account.get('params') or {}
  if not isinstance(params, dict):
    raise ConfigError('params must be a mapping')
  old_params = (accounts[index].get('params') or {}) if index is not None else {}
  for field in cls.fields:
    if field.kind == 'secret' and params.get(field.key) == SECRET_MASK:
      if field.key not in old_params:
        raise ConfigError(f'Enter a value for {field.label}')
      params[field.key] = old_params[field.key]
    if field.required and params.get(field.key) in (None, '', []):
      raise ConfigError(f'{field.label} is required')

  if index is None:
    entry = CommentedMap()
    accounts.append(entry)
    if len(accounts) > 1:
      accounts.yaml_set_comment_before_after_key(len(accounts) - 1, before='\n')
  else:
    entry = accounts[index]
  _update(entry, {'name': name, 'type': type_name, 'category': category}, prune=False)
  if interval is None:
    entry.pop('interval', None)
  elif entry.get('interval') != interval:
    entry['interval'] = interval
    _move_before(entry, 'interval', 'params')
  if params:
    _update(entry.setdefault('params', CommentedMap()), params)
  else:
    entry.pop('params', None)
  return _write(path, doc)


def delete_account(path: Path, name: str) -> Config:
  doc = _load(path)
  del doc['accounts'][_find(doc['accounts'], name)]
  return _write(path, doc)


def save_settings(path: Path, settings: dict) -> Config:
  doc = _load(path)
  if doc.get('settings') is None:
    doc.insert(0, 'settings', CommentedMap())
  for key in ('tick_minutes', 'default_interval'):
    value = settings.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
      raise ConfigError(f'{key} must be a whole number of minutes')
    doc['settings'][key] = value
  return _write(path, doc)


def rename_state_files(data_dir: Path, old: str, new: str):
  """Cookies and tokens are named after the account (Connector.state_file), so they follow a rename."""
  old_slug, new_slug = state_slug(old), state_slug(new)
  if old_slug == new_slug:
    return
  for file in data_dir.glob(f'{old_slug}.*'):
    if file.name.startswith(('networth.db', 'accounts.yaml')):  # not state, whatever the account is called
      continue
    file.rename(data_dir / (new_slug + file.name[len(old_slug):]))


def _load(path: Path) -> CommentedMap:
  doc = _yaml().load(path.read_text())
  if doc is None:
    doc = CommentedMap()
  if doc.get('accounts') is None:
    doc['accounts'] = CommentedSeq()
  return doc


def _write(path: Path, doc: CommentedMap) -> Config:
  """Check the edited config loads, keep the old file as a backup, then write in place."""
  out = io.StringIO()
  _yaml().dump(doc, out)
  text = out.getvalue()
  try:
    config = parse_config(yaml.safe_load(text) or {}, path)
  except (ValueError, TypeError) as e:
    raise ConfigError(str(e))

  if not os.access(path, os.W_OK):
    raise PermissionError(f'{path} is read-only')
  backup = config.data_dir / BACKUP_NAME
  shutil.copyfile(path, backup)
  backup.chmod(0o600)
  # In place rather than write-and-rename: in Docker accounts.yaml is a bind-mounted file.
  path.write_text(text)
  return config


def _find(accounts: CommentedSeq, name: str) -> int:
  for i, entry in enumerate(accounts):
    if entry.get('name') == name:
      return i
  raise ConfigError(f'No account named {name!r} in config')


def _update(target: CommentedMap, new: dict, prune: bool = True):
  """Make `target` equal `new`, leaving unchanged keys (and their comments and quoting) alone."""
  for key in list(target) if prune else []:
    if key not in new:
      del target[key]
  for key, value in new.items():
    if key not in target or target[key] != value:
      target[key] = value


def _move_before(entry: CommentedMap, key: str, before: str):
  keys = list(entry)
  if before in keys and keys.index(key) > keys.index(before):
    entry.insert(keys.index(before), key, entry.pop(key))


def _mask(type_name: Optional[str], params: dict) -> dict:
  try:
    secrets = {f.key for f in get_connector_class(type_name or '').fields if f.kind == 'secret'}
  except ConfigError:
    secrets = set()
  return {
    k: SECRET_MASK if k in secrets and v not in (None, '') and not _is_ref(v) else v
    for k, v in params.items()
  }


def _is_ref(value: Any) -> bool:
  return isinstance(value, str) and ENV_PATTERN.fullmatch(value.strip()) is not None


def _plain(value: Any) -> Any:
  """ruamel's comment-carrying types as plain dicts, lists and scalars (for JSON)."""
  if isinstance(value, dict):
    return {str(k): _plain(v) for k, v in value.items()}
  if isinstance(value, list):
    return [_plain(v) for v in value]
  if isinstance(value, bool) or value is None:
    return value
  for t in (int, float, str):
    if isinstance(value, t):
      return t(value)
  return str(value)
