# xaeian/db/mysql_async.py

"""MySQL async implementation."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any
from ..log import Logger, Print

from .abstract_async import AbstractAsyncDatabase
from .utils import _insert_sql, _upsert_sql

class MysqlAsyncDatabase(AbstractAsyncDatabase):
  """
  MySQL async database (aiomysql) with connection pooling.

  Pool runs `autocommit=True`, so every statement commits immediately; grouping statements
  needs the `transaction()` context manager.
  """
  style = "%s"
  quote = "`"
  excluded = None

  def __init__(
    self,
    db_name:str|None = None,
    host:str = "localhost",
    user:str = "root",
    password:str = "",
    port:int = 3306,
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
    import aiomysql
    return await aiomysql.connect(
      host=self.host, port=self.port,
      user=self.user, password=self.password,
      db=self.db_name,
    )

  async def _admin_conn(self):
    """
    Standalone connection bound to no database, for `CREATE`/`DROP DATABASE`.

    Admin work never borrows `self.db_name`. Blanking that field and connecting from it
    leaves a concurrent task free to build the pool against no database at all.
    """
    import aiomysql
    return await aiomysql.connect(
      host=self.host, port=self.port,
      user=self.user, password=self.password,
    )

  async def _close(self, conn):
    """
    Close a connection, pooled or standalone.

    Only the pool's wrapper carries `wait_closed`; a connection from `aiomysql.connect` does not.
    """
    conn.close()
    wait_closed = getattr(conn, "wait_closed", None)
    if wait_closed: await wait_closed()

  #-------------------------------------------------------------------------------------- Lifecycle

  async def _ensure_pool(self):
    if self._pool is not None:
      return self._pool
    async with self._pool_lock:
      if self._pool is None:
        import aiomysql
        self._pool = await aiomysql.create_pool(
          host=self.host, port=self.port,
          user=self.user, password=self.password,
          db=self.db_name,
          minsize=self._min_pool, maxsize=self._max_pool,
          autocommit=True, pool_recycle=3600,
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
    """Raw aiomysql pool."""
    return self._pool

  async def start(self) -> None:
    """Eagerly create connection pool."""
    await self._ensure_pool()

  async def close(self) -> None:
    """Close connection pool."""
    if self._pool:
      self._pool.close()
      await self._pool.wait_closed()
      self._pool = None

  #----------------------------------------------------------------------------- Backend Primitives

  async def _begin(self, conn):
    await conn.begin()
    return conn

  async def _run(self, conn, sql:str, params:tuple) -> int:
    async with conn.cursor() as cur:
      await cur.execute(sql, params)
      return self._rowcount(cur)

  async def _run_many(self, conn, sql:str, params_list:list[tuple]) -> int:
    async with conn.cursor() as cur:
      await cur.executemany(sql, params_list)
      return self._rowcount(cur)

  async def _fetch(self, conn, sql:str, params:tuple) -> tuple[list, list[str]]:
    async with conn.cursor() as cur:
      await cur.execute(sql, params)
      rows = await cur.fetchall()
      cols = [c[0] for c in cur.description] if cur.description else []
      return rows, cols

  async def _insert_returning(self, table:str, data:dict, ret:str) -> Any:
    """MySQL has no RETURNING: any truthy `returning` yields `lastrowid`, its name ignored."""
    sql, params = _insert_sql(table, data)
    sql = self._sql(sql)
    try:
      async with self._scope() as conn:
        async with conn.cursor() as cur:
          await cur.execute(sql, params)
          return cur.lastrowid
    except Exception as e:
      self._err("insert", e, sql, params)

  #----------------------------------------------------------------------------------------- Schema

  async def has_table(self, name:str) -> bool:
    return await self.get_value(
      "SELECT 1 FROM information_schema.tables WHERE table_name=? AND table_schema=?",
      (name, self.db_name),
    ) is not None

  async def tables(self) -> list[str]:
    return await self.get_column(
      "SELECT table_name FROM information_schema.tables WHERE table_schema=?",
      self.db_name,
    )

  async def has_database(self, name:str|None=None) -> bool:
    """Check if database exists, asked over a connection bound to no database."""
    name = name or self.db_name
    if not name: return False
    conn = None
    try:
      conn = await self._admin_conn()
      async with conn.cursor() as cur:
        await cur.execute("SHOW DATABASES")
        return name in [row[0] for row in await cur.fetchall()]
    except Exception as e:
      self._err("has_database", e)
    finally:
      if conn: await self._close(conn)

  #----------------------------------------------------------------------------------------- Upsert

  async def upsert(
    self,
    table:str,
    data:dict,
    on:str|list[str],
    update:list[str]|None = None,
  ) -> int:
    """
    INSERT ON DUPLICATE KEY UPDATE.

    The table's unique keys decide the conflict, not `on`.
    `update` defaults to every column except those named in `on`.
    """
    sql, params = _upsert_sql(table, data, on, update, self.excluded)
    return await self.exec(sql, params)

  #---------------------------------------------------------------------------- Database Management

  async def create_database(self, name:str|None=None) -> bool:
    """Create database. Returns `False` if it already exists."""
    if self.in_transaction(): raise RuntimeError("create_database() not allowed in transaction")
    name = name or self.db_name
    name = self._valid_db(name)
    if await self.has_database(name): return False
    try:
      conn = await self._admin_conn()
      try:
        async with conn.cursor() as cur:
          await cur.execute(f"CREATE DATABASE `{name}`")
        await conn.commit()
        return True
      finally:
        await self._close(conn)
    except Exception as e:
      self._err("create_database", e)

  async def drop_database(self, name:str|None=None) -> bool:
    """Drop database and everything in it. Returns `False` if it does not exist."""
    if self.in_transaction(): raise RuntimeError("drop_database() not allowed in transaction")
    name = name or self.db_name
    name = self._valid_db(name)
    if not await self.has_database(name): return False
    try:
      conn = await self._admin_conn()
      try:
        async with conn.cursor() as cur:
          await cur.execute(f"DROP DATABASE `{name}`")
        await conn.commit()
        return True
      finally:
        await self._close(conn)
    except Exception as e:
      self._err("drop_database", e)
