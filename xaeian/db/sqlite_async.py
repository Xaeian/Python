# xaeian/db/sqlite_async.py

"""SQLite async implementation with persistent connection."""
from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from typing import Any
from ..log import Logger, Print

from .abstract_async import AbstractAsyncDatabase
from .utils import _upsert_sql

class SqliteAsyncDatabase(AbstractAsyncDatabase):
  """
  SQLite async database (aiosqlite). `db_name` is a file path or `":memory:"`.

  Without `start()`, every query opens and closes its own connection,
  so a `":memory:"` database starts empty each time.
  `insert(returning=...)` uses `RETURNING`, so it needs SQLite 3.35+.
  """
  def __init__(self, db_name:str, log:Logger|Print|None=None) -> None:
    super().__init__()
    self.db_name:str = db_name
    self.log = log
    self._persistent:Any = None
    self._lock = asyncio.Lock()

  async def conn(self) -> Any:
    """New standalone connection, outside the persistent one."""
    import aiosqlite
    return await aiosqlite.connect(self.db_name)

  #-------------------------------------------------------------------------------------- Lifecycle

  @asynccontextmanager
  async def _exclusive(self):
    """
    The persistent connection, held alone for the caller's whole span, or a throwaway one.

    One sqlite connection carries one transaction, so it is lent out and not shared:
    a second task slipping in mid-span would write inside someone else's transaction, and end it.
    """
    if self._persistent:
      async with self._lock:
        yield self._persistent
    else:
      conn = await self.conn()
      try:
        yield conn
      finally:
        await conn.close()

  @asynccontextmanager
  async def _connect(self):
    """One call's connection, rolled back if the call fails."""
    async with self._exclusive() as conn:
      try:
        yield conn
      except BaseException:
        try: await conn.rollback()
        except Exception: pass
        raise

  async def start(self) -> None:
    """Open persistent connection and set pragmas: WAL for file databases, `foreign_keys=ON`."""
    if self._persistent: return
    self._persistent = await self.conn()
    if self.db_name != ":memory:":
      await self._persistent.execute("PRAGMA journal_mode=WAL")
      await self._persistent.execute("PRAGMA synchronous=NORMAL")
    await self._persistent.execute("PRAGMA busy_timeout=5000")
    await self._persistent.execute("PRAGMA foreign_keys=ON")

  async def close(self) -> None:
    """Close persistent connection."""
    if self._persistent:
      await self._persistent.close()
      self._persistent = None

  #----------------------------------------------------------------------------- Backend Primitives

  async def _begin(self, conn):
    """`BEGIN` is explicit: the driver opens one only for DML, leaving DDL outside."""
    await conn.execute("BEGIN")
    return conn

  @asynccontextmanager
  async def _scope(self):
    """As the base, plus a commit: sqlite holds writes open until someone ends them."""
    conn = self._conn
    if conn is not None:
      yield conn
      return
    async with self._connect() as conn:
      yield conn
      if conn.in_transaction: await conn.commit() # a write outside transaction() lands here

  async def _run(self, conn, sql:str, params:tuple) -> int:
    cur = await conn.execute(sql, params)
    rc = self._rowcount(cur)
    await cur.close()
    return rc

  async def _run_many(self, conn, sql:str, params_list:list[tuple]) -> int:
    cur = await conn.executemany(sql, params_list)
    rc = self._rowcount(cur)
    await cur.close()
    return rc

  async def _fetch(self, conn, sql:str, params:tuple) -> tuple[list, list[str]]:
    cur = await conn.execute(sql, params)
    rows = await cur.fetchall()
    cols = [c[0] for c in cur.description] if cur.description else []
    await cur.close()
    return rows, cols

  #----------------------------------------------------------------------------------------- Schema

  async def has_table(self, name:str) -> bool:
    return await self.get_value(
      "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", name
    ) is not None

  async def tables(self) -> list[str]:
    return await self.get_column("SELECT name FROM sqlite_master WHERE type='table'")

  async def has_database(self, name:str|None=None) -> bool:
    """Check the database file exists on disk; `":memory:"` is never a file, so `False`."""
    n = name or self.db_name
    return os.path.isfile(n) if n else False

  #----------------------------------------------------------------------------------------- Upsert

  async def upsert(
    self,
    table:str,
    data:dict,
    on:str|list[str],
    update:list[str]|None = None,
  ) -> int:
    """INSERT ON CONFLICT (SQLite 3.24+). `on` must be a UNIQUE or PRIMARY KEY column set."""
    sql, params = _upsert_sql(table, data, on, update, self.excluded)
    return await self.exec(sql, params)

  #---------------------------------------------------------------------------- Database Management

  async def create_database(self, name:str|None=None) -> bool:
    """Create database file. Returns `False` if it already exists."""
    if self.in_transaction(): raise RuntimeError("create_database() not allowed in transaction")
    import aiosqlite
    n = name or self.db_name
    if not n: raise ValueError("db_name required")
    if await self.has_database(n): return False
    conn = await aiosqlite.connect(n)
    await conn.close()
    return True

  async def drop_database(self, name:str|None=None) -> bool:
    """Delete database file. Returns `False` if it does not exist."""
    if self.in_transaction(): raise RuntimeError("drop_database() not allowed in transaction")
    n = name or self.db_name
    if not n: raise ValueError("db_name required")
    if not await self.has_database(n): return False
    try:
      os.remove(n)
      return True
    except OSError as e:
      self._err("drop_database", e)
