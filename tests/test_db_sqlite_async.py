# tests/test_db_sqlite_async.py

"""SqliteAsyncDatabase: DML routed through the read path (UPDATE ... RETURNING via
get_dict/get_dicts) opens an implicit write transaction that MUST be committed - both
on the persistent connection (start()) and in per-call fallback mode. Regression for
the leaked WAL write lock that starved other connections (gunicorn workers) of writes:
one failed-login bump left `database is locked` for every other worker's UPDATE.

No pytest-asyncio in this repo - tests are sync functions driving asyncio.run().
"""

import asyncio
import pytest

pytest.importorskip("aiosqlite")
from xaeian.db import AsyncDatabase, DatabaseError

@pytest.fixture
def db_path(tmp_path):
  return str(tmp_path / "app.db")

#------------------------------------------------------------------- persistent connection

def update_returning_via_get_dict_releases_write_lock(db_path):
  async def main():
    a = AsyncDatabase("sqlite", db_path)  # worker A
    b = AsyncDatabase("sqlite", db_path)  # worker B
    await a.start()
    await b.start()
    await a.exec(
      "CREATE TABLE users (id INTEGER PRIMARY KEY, failed_logins INTEGER NOT NULL DEFAULT 0)")
    await a.exec("INSERT INTO users (id) VALUES (1)")
    row = await a.get_dict(
      "UPDATE users SET failed_logins = failed_logins + 1 WHERE id = 1 RETURNING failed_logins")
    assert row == {"failed_logins": 1}
    # the leak itself: an uncommitted implicit transaction left open on A
    assert a._persistent.in_transaction is False
    # end-to-end: another connection can write immediately (fail fast, not 5s)
    await b.exec("PRAGMA busy_timeout=100")
    assert await b.exec("UPDATE users SET failed_logins = 0 WHERE id = 1") == 1
    await a.close()
    await b.close()
  asyncio.run(main())

#------------------------------------------------------------------------- fallback mode

def update_returning_via_get_dict_persists_without_start(db_path):
  async def main():
    db = AsyncDatabase("sqlite", db_path)  # no start() - per-call connections
    await db.exec("CREATE TABLE t (id INTEGER PRIMARY KEY, n INTEGER NOT NULL)")
    await db.exec("INSERT INTO t (id, n) VALUES (1, 0)")
    row = await db.get_dict("UPDATE t SET n = 5 WHERE id = 1 RETURNING n")
    assert row == {"n": 5}
    # pre-fix the per-call connection closed uncommitted -> silent rollback -> 0
    assert await db.get_value("SELECT n FROM t WHERE id = 1") == 5
  asyncio.run(main())

#------------------------------------------------------------- transaction owns the commit

def transaction_rollback_still_discards_returning_update(db_path):
  async def main():
    db = AsyncDatabase("sqlite", db_path)
    await db.start()
    await db.exec("CREATE TABLE t (id INTEGER PRIMARY KEY, n INTEGER NOT NULL)")
    await db.exec("INSERT INTO t (id, n) VALUES (1, 0)")
    with pytest.raises(RuntimeError, match="boom"):
      async with db.transaction():
        row = await db.get_dict("UPDATE t SET n = 9 WHERE id = 1 RETURNING n")
        assert row == {"n": 9}
        raise RuntimeError("boom")
    assert await db.get_value("SELECT n FROM t WHERE id = 1") == 0
    await db.close()
  asyncio.run(main())
