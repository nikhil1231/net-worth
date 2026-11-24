"""Postgres access: one shared psycopg connection, and rows that index by position or by column name."""
import threading

import psycopg
from psycopg.adapt import Loader
from psycopg.types.numeric import Int8Dumper


class Row(tuple):
  """A tuple that also indexes by column name: r[0], r['name'], dict(r), r.keys()."""
  __slots__ = ()
  _names: tuple = ()

  def __getitem__(self, key):
    if isinstance(key, str):
      try:
        key = self._names.index(key)
      except ValueError:
        raise IndexError(f'No column named {key!r}') from None
    return tuple.__getitem__(self, key)

  def keys(self):
    return list(self._names)


_row_classes = {}


def _row_factory(cursor):
  if cursor.description is None:
    return tuple
  names = tuple(d.name for d in cursor.description)
  if names not in _row_classes:
    _row_classes[names] = type('Row', (Row,), {'__slots__': (), '_names': names})
  return _row_classes[names]


class _NumericLoader(Loader):
  """numeric -> int when it has no fraction (a SUM of integers), else float, rather than Decimal."""
  def load(self, data):
    text = bytes(data).decode()
    return int(text) if text.lstrip('-').isdigit() else float(text)


class Db:
  """
  One long-lived connection shared by every thread. Each statement commits by itself; `with db:` groups
  the statements inside it into one transaction (commit on success, rollback on an exception), and
  nested blocks join the outer one. Reconnects if the server dropped the connection.
  """
  def __init__(self, url: str):
    self.url = url
    self.lock = threading.RLock()
    self.depth = 0
    self.pg = None
    self._connect()

  def _connect(self):
    self.pg = psycopg.connect(self.url, autocommit=True, connect_timeout=10, options='-c timezone=UTC',
                              row_factory=_row_factory)
    self.pg.adapters.register_loader('numeric', _NumericLoader)
    self.pg.adapters.register_dumper(bool, Int8Dumper)  # flags are stored as 0/1 integers

  def _alive(self):
    if (self.pg.closed or self.pg.broken) and not self.depth:
      self._connect()

  def execute(self, sql, params=None):
    with self.lock:
      self._alive()
      return self.pg.execute(sql, params)

  def executemany(self, sql, rows):
    with self.lock:
      self._alive()
      cursor = self.pg.cursor()
      cursor.executemany(sql, rows)
      return cursor

  def __enter__(self):
    with self.lock:
      self._alive()
      if not self.depth:
        self.pg.execute('BEGIN')
      self.depth += 1
    return self

  def __exit__(self, kind, value, tb):
    with self.lock:
      if not self.depth:  # an inner block already rolled everything back
        return False
      self.depth = 0 if kind else self.depth - 1
      if not self.depth:
        self.pg.execute('ROLLBACK' if kind else 'COMMIT')
    return False

  def close(self):
    with self.lock:
      if self.pg and not self.pg.closed:
        self.pg.close()
