# xaeian/db/postgres_async.py

"""PostgreSQL async implementation."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any
from ..log import Logger, Print

from .abstract_async import AbstractAsyncDatabase
from .utils import _upsert_sql

def _rows_affected(status:str) -> int:
  """Count from an asyncpg status string like `INSERT 0 1` or `UPDATE 5`."""
  parts = status.split() if status else []
  return int(parts[-1]) if parts and parts[-1].isdigit() else 0

class PostgresAsyncDatabase(AbstractAsyncDatabase):
  """PostgreSQL async database (asyncpg) with connection pooling."""
  style = "$"
  excluded = "EXCLUDED"

  def __init__(
    self,
    db_name:str|None = None,
    host:str = "localhost",
    user:str = "postgres",
    password:str = "",
    port:int = 5432,
    log:Logger|Print|None = None,
    min_pool:int = 1,
    max_pool:int = 10,
  ) -> None:
    super().__init__()
    self.host = host
    self.port = port
    self.user = user
    self.password = password
    self.db_name = db_name
    self.log = log
    self._pool:Any = None
    self._pool_lock = asyncio.Lock()
    self._min_pool = min_pool
    self._max_pool = max_pool

  async def conn(self) -> Any:
    """Standalone connection, outside the pool."""
    import asyncpg
    return await asyncpg.connect(
      host=self.host, port=self.port,
      user=self.user, password=self.password,
      database=self.db_name,
    )

  async def _admin_conn(self):
    """
    Standalone connection to the `postgres` maintenance database.

    Admin work never borrows `self.db_name`.
    The pool binds to whatever `db_name` says the first time it is built,
    so building it while that points at `postgres` would silently send every later insert
    and query to the maintenance database.
    """
    import asyncpg
    return await asyncpg.connect(
      host=self.host, port=self.port,
      user=self.user, password=self.password,
      database="postgres",
    )

  #-------------------------------------------------------------------------------------- Lifecycle

  async def _ensure_pool(self):
    if self._pool is not None:
      return self._pool
    async with self._pool_lock:
      if self._pool is None:
        import asyncpg
        self._pool = await asyncpg.create_pool(
          host=self.host, port=self.port,
          user=self.user, password=self.password,
          database=self.db_name,
          min_size=self._min_pool, max_size=self._max_pool,
        )
    return self._pool

  @asynccontextmanager
  async def _exclusive(self):
    """Connection from the pool, lent for the caller's whole span."""
    pool = await self._ensure_pool()
    async with pool.acquire() as conn:
      yield conn

  @property
  def pool(self) -> Any:
    """Raw asyncpg pool for COPY protocol, etc."""
    return self._pool

  async def start(self) -> None:
    """Eagerly create connection pool."""
    await self._ensure_pool()

  async def close(self) -> None:
    """Close connection pool."""
    if self._pool:
      await self._pool.close()
      self._pool = None

  #----------------------------------------------------------------------------- Backend Primitives

  async def _begin(self, conn):
    tr = conn.transaction()
    await tr.start()
    return tr

  async def _run(self, conn, sql:str, params:tuple) -> int:
    return _rows_affected(await conn.execute(sql, *params))

  async def _run_many(self, conn, sql:str, params_list:list[tuple]) -> int:
    """asyncpg reports no count for `executemany`, so the tuple count stands in."""
    await conn.executemany(sql, params_list)
    return len(params_list)

  async def _fetch(self, conn, sql:str, params:tuple) -> tuple[list, list[str]]:
    rows = await conn.fetch(sql, *params)
    cols = list(rows[0].keys()) if rows else []
    return [list(r) for r in rows], cols

  #----------------------------------------------------------------------------------------- Schema

  async def has_table(self, name:str) -> bool:
    return await self.get_value(
      "SELECT 1 FROM information_schema.tables WHERE table_name=? AND table_schema='public'",
      name,
    ) is not None

  async def tables(self) -> list[str]:
    return await self.get_column(
      "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
    )

  async def has_database(self, name:str|None=None) -> bool:
    """Check if database exists, asked over a standalone maintenance connection."""
    name = name or self.db_name
    if not name: return False
    conn = None
    try:
      conn = await self._admin_conn()
      return await conn.fetchval("SELECT 1 FROM pg_database WHERE datname=$1", name) is not None
    except Exception as e:
      self._err("has_database", e)
    finally:
      if conn: await conn.close()

  #----------------------------------------------------------------------------------------- Upsert

  async def upsert(
    self,
    table:str,
    data:dict,
    on:str|list[str],
    update:list[str]|None = None,
  ) -> int:
    """INSERT ON CONFLICT (PostgreSQL 9.5+). `on` must be a UNIQUE or PRIMARY KEY column set."""
    sql, params = _upsert_sql(table, data, on, update, self.excluded)
    return await self.exec(sql, params)

  #---------------------------------------------------------------------------- Database Management

  async def create_database(self, name:str|None=None) -> bool:
    """Create database. Returns `False` if it already exists."""
    if self.in_transaction(): raise RuntimeError("create_database() not allowed in transaction")
    name = name or self.db_name
    name = self._valid_db(name)
    if await self.has_database(name): return False
    conn = None
    try:
      conn = await self._admin_conn()
      await conn.execute(f'CREATE DATABASE "{name}"')
      return True
    except Exception as e:
      self._err("create_database", e)
    finally:
      if conn: await conn.close()

  async def drop_database(self, name:str|None=None) -> bool:
    """Drop database and everything in it. Returns `False` if it does not exist."""
    if self.in_transaction(): raise RuntimeError("drop_database() not allowed in transaction")
    name = name or self.db_name
    name = self._valid_db(name)
    if not await self.has_database(name): return False
    conn = None
    try:
      conn = await self._admin_conn()
      await conn.execute(f'DROP DATABASE "{name}"')
      return True
    except Exception as e:
      self._err("drop_database", e)
    finally:
      if conn: await conn.close()
