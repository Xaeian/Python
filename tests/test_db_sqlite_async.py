# tests/test_db_sqlite_async.py

"""
`SqliteAsyncDatabase`, where a write reaches the database through the read path.

`UPDATE ... RETURNING` via `get_dict` opens an implicit write transaction that must be committed,
on the persistent connection and in per-call fallback alike.
Left open, it holds the WAL write lock:
one failed-login bump answers `database is locked` to every other worker.

No pytest-asyncio here: the tests are sync functions driving `asyncio.run()`.
"""

import asyncio
import pytest

pytest.importorskip("aiosqlite")
from xaeian.db import AsyncDatabase, DatabaseError

@pytest.fixture
def db_path(tmp_path):
  return str(tmp_path / "app.db")

#---------------------------------------------------------------------------- persistent connection

def update_returning_via_get_dict_releases_write_lock(db_path):
  async def main():
    a = AsyncDatabase("sqlite", db_path) # worker A
    b = AsyncDatabase("sqlite", db_path) # worker B
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

#------------------------------------------------------------------------------------ fallback mode

def update_returning_via_get_dict_persists_without_start(db_path):
  async def main():
    db = AsyncDatabase("sqlite", db_path) # no `start()` - per-call connections
    await db.exec("CREATE TABLE t (id INTEGER PRIMARY KEY, n INTEGER NOT NULL)")
    await db.exec("INSERT INTO t (id, n) VALUES (1, 0)")
    row = await db.get_dict("UPDATE t SET n = 5 WHERE id = 1 RETURNING n")
    assert row == {"n": 5}
    # closed uncommitted, a per-call connection rolls back silently → 0
    assert await db.get_value("SELECT n FROM t WHERE id = 1") == 5
  asyncio.run(main())

#---------------------------------------------------------------------- transaction owns the commit

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

#------------------------------------------------------------------ one connection, one transaction

def a_bystander_task_does_not_end_another_tasks_transaction(db_path):
  """
  A write outside `transaction()` must not commit whatever the shared connection holds:
  a second task would end a transaction before its owner could roll it back.
  """
  async def main():
    db = AsyncDatabase("sqlite", db_path)
    await db.start()
    await db.exec("CREATE TABLE t (v TEXT)")
    open_tx, at_the_door = asyncio.Event(), asyncio.Event()
    async def owner():
      with pytest.raises(RuntimeError, match="boom"):
        async with db.transaction():
          await db.insert("t", {"v": "rolled back"})
          open_tx.set()
          await at_the_door.wait()
          raise RuntimeError("boom")
    async def bystander():
      await open_tx.wait()
      at_the_door.set() # the insert below parks on the lock, so it cannot signal afterwards
      await db.insert("t", {"v": "kept"})
    await asyncio.gather(owner(), bystander())
    assert await db.get_column("SELECT v FROM t") == ["kept"]
    await db.close()
  asyncio.run(main())

def a_transaction_belongs_to_the_task_that_opened_it(db_path):
  """
  An unrelated task that saw `in_transaction()` as `True` would join someone else's transaction,
  and its committed write would vanish when that transaction rolled back.
  """
  async def main():
    db = AsyncDatabase("sqlite", db_path)
    await db.exec("CREATE TABLE t (id INTEGER PRIMARY KEY, tag TEXT)")
    opened = asyncio.Event()
    seen = {}
    async def writer():
      async with db.transaction():
        await db.insert("t", {"tag": "rolled-back"})
        opened.set()
        await asyncio.sleep(0.2)
        raise RuntimeError("abort")
    async def bystander():
      await opened.wait()
      seen["in_transaction"] = db.in_transaction()
      await db.insert("t", {"tag": "committed"})
    await asyncio.gather(writer(), bystander(), return_exceptions=True)
    tags = await db.get_column("SELECT tag FROM t")
    await db.close()
    assert seen["in_transaction"] is False, "an unrelated task was swept into the transaction"
    assert tags == ["committed"], f"the bystander's write did not survive: {tags}"
  asyncio.run(main())

def cancelling_a_transaction_rolls_it_back(db_path):
  """
  `CancelledError` is not an `Exception`:
  under `except Exception`, a cancelled transaction stays open on the connection,
  and the next write commits it.
  """
  async def main():
    db = AsyncDatabase("sqlite", db_path)
    await db.start()
    await db.exec("CREATE TABLE t (v TEXT)")
    open_tx = asyncio.Event()
    async def victim():
      async with db.transaction():
        await db.insert("t", {"v": "cancelled"})
        open_tx.set()
        await asyncio.Event().wait() # never set: parks until cancelled
    task = asyncio.create_task(victim())
    await open_tx.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
      await task
    assert db._persistent.in_transaction is False
    await db.insert("t", {"v": "later"})
    assert await db.get_column("SELECT v FROM t") == ["later"]
    await db.close()
  asyncio.run(main())

#--------------------------------------------------------------------------------- same as the sync

def per_call_connections_enforce_foreign_keys_and_keep_date_strings(db_path):
  """`start()` is optional, so a per-call connection has to behave as the persistent one does."""
  async def main():
    db = AsyncDatabase("sqlite", db_path)
    await db.exec("CREATE TABLE p (id INTEGER PRIMARY KEY, day TEXT)")
    await db.exec("CREATE TABLE c (pid INTEGER REFERENCES p(id))")
    with pytest.raises(DatabaseError):
      await db.insert("c", {"pid": 7})
    await db.insert("p", {"day": "2025-03-01"})
    assert await db.get_value("SELECT day FROM p") == "2025-03-01"
  asyncio.run(main())
