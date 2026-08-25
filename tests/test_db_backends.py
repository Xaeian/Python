# tests/test_db_backends.py

"""
One contract, every backend, against a real server.

Skipped unless a password is exported, so the default suite stays hermetic:

  $env:XAEIAN_TEST_POSTGRES = 'secret'   # PostgreSQL on localhost:5432, user postgres
  $env:XAEIAN_TEST_MYSQL = 'secret'      # MySQL/MariaDB on localhost:3306, user root

Every test body is backend-agnostic. A backend that needs a special case here is a backend
whose contract has drifted.
"""

import asyncio
import os
import pytest
from xaeian.db import Database, AsyncDatabase, KeyValue, AsyncKeyValue

BACKENDS = [
  pytest.param(("postgres", "postgres", "XAEIAN_TEST_POSTGRES"), id="postgres"),
  pytest.param(("mysql", "root", "XAEIAN_TEST_MYSQL"), id="mysql"),
]

AUTO_ID = {
  "postgres": "id SERIAL PRIMARY KEY",
  "mysql": "id INT AUTO_INCREMENT PRIMARY KEY",
}

@pytest.fixture(params=BACKENDS)
def live(request):
  """A throwaway database on a real server, dropped afterwards whatever the test did."""
  backend, user, env = request.param
  password = os.environ.get(env)
  if not password: pytest.skip(f"{env} not set")
  name = f"xaeian_test_{backend}"
  admin = Database(backend, None if backend == "mysql" else "postgres",
    user=user, password=password)
  if admin.has_database(name): admin.drop_database(name)
  db = Database(backend, name, user=user, password=password)
  db.create_database(name)
  db.exec(f"CREATE TABLE t ({AUTO_ID[backend]}, name VARCHAR(32), n INT)")
  try:
    yield backend, user, password, name, db
  finally:
    admin.drop_database(name)

#--------------------------------------------------------------------------------- placeholders (?)

def raw_sql_takes_a_question_mark(live):
  _, _, _, _, db = live
  db.insert("t", {"name": "a", "n": 1})
  assert db.get_dicts("SELECT name FROM t WHERE n = ?", 1) == [{"name": "a"}]

def update_never_collides_with_the_callers_where(live):
  """SET and WHERE both bind `?`; numbering them twice used to write the wrong column."""
  _, _, _, _, db = live
  db.insert("t", {"name": "a", "n": 1})
  db.insert("t", {"name": "b", "n": 2})
  assert db.update("t", {"n": 99}, "name = ?", "a") == 1
  assert db.find("t", n=99) == [{"id": 1, "name": "a", "n": 99}]
  assert db.get_value("SELECT n FROM t WHERE name = ?", "b") == 2

def insert_many_binds_by_column_name(live):
  _, _, _, _, db = live
  db.insert_many("t", [{"name": "c", "n": 3}, {"n": 4, "name": "d"}])
  assert db.find("t", name="d")[0]["n"] == 4

def upsert_replaces_the_conflicting_row(live):
  _, _, _, _, db = live
  db.insert("t", {"name": "a", "n": 1})
  db.upsert("t", {"id": 1, "name": "a", "n": 7}, "id")
  assert db.find("t", id=1)[0]["n"] == 7

#---------------------------------------------------------------------------------- admin isolation

def admin_ddl_leaves_the_object_pointing_at_its_own_database(live):
  """`create_database` used to leave the pool bound to the maintenance database."""
  backend, _, _, name, db = live
  assert db.has_database(name) is True
  assert db.db_name == name
  current = "SELECT current_database()" if backend == "postgres" else "SELECT DATABASE()"
  assert db.get_value(current) == name

#----------------------------------------------------------------------------------------- KeyValue

def key_value_survives_a_reserved_column_name(live):
  """`key` is reserved in MySQL, so the store quotes every identifier it owns."""
  _, _, _, _, db = live
  kv = KeyValue(db)
  kv.set("mode", {"fast": True})
  kv.set("limit", 42)
  kv.set("limit", 43)
  assert kv.read_all() == {"limit": 43, "mode": {"fast": True}}
  assert kv.has("mode") and kv.delete("mode") and not kv.has("mode")

#-------------------------------------------------------------------------------------------- async

def the_async_half_honours_the_same_contract(live):
  backend, user, password, name, _ = live

  async def run():
    db = AsyncDatabase(backend, name, user=user, password=password)
    await db.insert("t", {"name": "a", "n": 1})
    assert await db.update("t", {"n": 99}, "name = ?", "a") == 1
    await db.insert_many("t", [{"name": "c", "n": 3}, {"n": 4, "name": "d"}])
    assert (await db.find("t", name="d"))[0]["n"] == 4
    async with db.transaction():
      await db.insert("t", {"name": "tx", "n": 5})
    kv = AsyncKeyValue(db, table="_akv")
    await kv.set("k", [1, 2, 3])
    assert await kv.read_all() == {"k": [1, 2, 3]}
    rows = await db.find("t")
    await db.close()
    return rows

  assert len(asyncio.run(run())) == 4

def a_failed_begin_leaves_no_transaction_and_no_lost_connection(live):
  """The `ContextVar` token and the pooled connection both hang on `_begin` succeeding."""
  backend, user, password, name, _ = live

  async def run():
    db = AsyncDatabase(backend, name, user=user, password=password)
    await db.start()
    async def boom(conn): raise RuntimeError("begin refused")
    db._begin = boom
    with pytest.raises(RuntimeError, match="begin refused"):
      async with db.transaction(): pass
    assert db.in_transaction() is False
    del db._begin
    async with db.transaction(): # the connection came back, so this one opens
      await db.insert("t", {"name": "after", "n": 1})
    rows = await db.find("t", name="after")
    await db.close()
    return rows

  assert asyncio.run(run()) == [{"id": 1, "name": "after", "n": 1}]

def cancelling_an_async_transaction_rolls_it_back(live):
  """`CancelledError` is not an `Exception`; the connection goes back clean or not at all."""
  backend, user, password, name, _ = live

  async def run():
    db = AsyncDatabase(backend, name, user=user, password=password)
    await db.start()
    open_tx = asyncio.Event()
    async def victim():
      async with db.transaction():
        await db.insert("t", {"name": "cancelled", "n": 1})
        open_tx.set()
        await asyncio.Event().wait() # never set: parks until cancelled
    task = asyncio.create_task(victim())
    await open_tx.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
      await task
    await db.insert("t", {"name": "after", "n": 2}) # the same pool, no transaction left open
    rows = await db.get_column("SELECT name FROM t")
    await db.close()
    return rows

  assert asyncio.run(run()) == ["after"]
