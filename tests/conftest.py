"""Every test gets its own empty Postgres database as DATABASE_URL (from TEST_DATABASE_URL, a role that may
create databases), dropped afterwards."""
import os
import secrets
import time

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict, make_conninfo


@pytest.fixture(autouse=True)
def database(monkeypatch):
  base = os.environ.get('TEST_DATABASE_URL')
  if not base:
    pytest.skip('TEST_DATABASE_URL is not set')
  name = f'test_networth_{secrets.token_hex(4)}'
  with psycopg.connect(base, autocommit=True) as admin:
    admin.execute(f'CREATE DATABASE "{name}"')
  monkeypatch.setenv('DATABASE_URL', make_conninfo(base, dbname=name))
  yield
  for attempt in range(10):  # an autovacuum worker on it can't be ended by a non-superuser: wait for it
    try:
      with psycopg.connect(base, autocommit=True) as admin:
        admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
      return
    except (psycopg.errors.InsufficientPrivilege, psycopg.errors.ObjectInUse):
      if attempt == 9:
        raise
      time.sleep(0.5)
