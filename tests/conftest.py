"""Every test gets its own empty Postgres database as DATABASE_URL (from TEST_DATABASE_URL, a role that may
create databases), dropped afterwards."""
import os

import pytest

from networth import sqlpg


@pytest.fixture(autouse=True)
def database(monkeypatch):
  base = os.environ.get('TEST_DATABASE_URL')
  if not base:
    pytest.skip('TEST_DATABASE_URL is not set')
  url = sqlpg.create_test_database(base, 'test_networth')
  monkeypatch.setenv('DATABASE_URL', url)
  yield url
  sqlpg.drop_test_database(base, url)
