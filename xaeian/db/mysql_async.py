# xaeian/db/mysql_async.py

"""MySQL async implementation with connection pooling."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any
from ..log import Logger, Print

from .abstract_async import AbstractAsyncDatabase
from .utils import (
  listify, to_dicts, ident, ph, serialize_params,
  serialize_dict, split_sql, parse_row,
)

class MysqlAsyncDatabase(AbstractAsyncDatabase):
  """
  MySQL async database (aiomysql) with connection pooling.

  Pool is created lazily on first query or explicitly via `start()`.
  Pool uses `autocommit=True` — each statement commits immediately.
  Transactions use explicit `begin()`/`commit()`.

  Args:
    db_name: Database name.
    host: Server hostname.
    user: Username.
    password: Password.
    port: Server port.
    log: Logger instance.
    min_pool: Minimum pool connections.
    max_pool: Maximum pool connections.

  Example:
    >>> db = MysqlAsyncDatabase("mydb", user="root", password="secret")
    >>> await db.start()
    >>> await db.insert("users", {"name": "Jan"})
    >>> await db.close()
  """
  def __init__(
    self,
    db_name: str|None = None,
    host: str = "localhost",
    user: str = "root",
    password: str = "",
    port: int = 3306,
    log: Logger|Print|None = None,
    min_pool: int = 1,
    max_pool: int = 10,
  ):
    super().__init__()
    self.host = host
    self.port = port
    self.user = user
    self.password = password
    self.db_name = db_name
    self.ph = "%s"
    self.log = log
    self._pool = None
    self._pool_lock = asyncio.Lock()
    self._min_pool = min_pool
    self._max_pool = max_pool

  async def conn(self):
    """Create standalone connection (outside pool)."""
    import aiomysql
    return await aiomysql.connect(
      host=self.host, port=self.port,
      user=self.user, password=self.password,
      db=self.db_name
    )

  async def _close(self, conn):
    conn.close()
    await conn.wait_closed()

  #--------------------------------------------------------------------------------- Lifecycle

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
  async def _connect(self):
    """Acquire connection from pool."""
    pool = await self._ensure_pool()
    async with pool.acquire() as conn:
      yield conn

  @property
  def pool(self):
    """Raw aiomysql pool."""
    return self._pool

  async def start(self):
    """Eagerly create connection pool."""
    await self._ensure_pool()

  async def close(self):
    """Close connection pool."""
    if self._pool:
      self._pool.close()
      await self._pool.wait_closed()
      self._pool = None

  #-------------------------------------------------------------------------------- Transaction

  @asynccontextmanager
  async def transaction(self):
    if self._conn is not None: raise RuntimeError("Transaction already active")
    pool = await self._ensure_pool()
    conn = await pool.acquire()
    self._conn = conn
    await conn.begin()
    try:
      yield self
      await self._conn.commit()
    except Exception:
      await self._conn.rollback()
      raise
    finally:
      self._conn = None
      pool.release(conn)

  def _rowcount(self, cur) -> int:
    return max(0, cur.rowcount) if cur.rowcount is not None else 0

  #------------------------------------------------------------------------------------ Execute

  async def exec(self, sql:str, params=None) -> int:
    import aiomysql
    p = serialize_params(params)
    if self.debug: self._debug("exec", sql, p)
    if self.in_transaction():
      try:
        async with self._conn.cursor() as cur:
          await cur.execute(sql, p)
          return self._rowcount(cur)
      except aiomysql.Error as e:
        self._err("exec", e, sql, p)
    try:
      async with self._connect() as conn:
        async with conn.cursor() as cur:
          await cur.execute(sql, p)
          return self._rowcount(cur)
    except aiomysql.Error as e:
      self._err("exec", e, sql, p)

  async def exec_many(self, sql:str, params_list:list) -> int:
    import aiomysql
    pl = [serialize_params(p) for p in params_list]
    if self.in_transaction():
      try:
        async with self._conn.cursor() as cur:
          await cur.executemany(sql, pl)
          return self._rowcount(cur)
      except aiomysql.Error as e:
        self._err("exec_many", e, sql, tuple(pl))
    try:
      async with self._connect() as conn:
        await conn.begin()
        try:
          async with conn.cursor() as cur:
            await cur.executemany(sql, pl)
            rc = self._rowcount(cur)
          await conn.commit()
          return rc
        except Exception:
          await conn.rollback()
          raise
    except aiomysql.Error as e:
      self._err("exec_many", e, sql, tuple(pl))

  async def exec_batch(self, sqls:list[tuple[str, Any]]|list[str]|str) -> int:
    import aiomysql

    async def run(cur) -> int:
      total = 0
      if isinstance(sqls, str):
        for s in split_sql(sqls):
          await cur.execute(s)
          total += self._rowcount(cur)
      elif sqls and isinstance(sqls[0], tuple):
        for sql, params in sqls:
          await cur.execute(sql, serialize_params(params))
          total += self._rowcount(cur)
      else:
        for sql in sqls:
          await cur.execute(sql)
          total += self._rowcount(cur)
      return total

    if self.in_transaction():
      try:
        async with self._conn.cursor() as cur:
          return await run(cur)
      except aiomysql.Error as e:
        self._err("exec_batch", e)
    try:
      async with self._connect() as conn:
        await conn.begin()
        try:
          async with conn.cursor() as cur:
            total = await run(cur)
          await conn.commit()
          return total
        except Exception:
          await conn.rollback()
          raise
    except aiomysql.Error as e:
      self._err("exec_batch", e)

  #-------------------------------------------------------------------------------------- Query

  async def get_rows(self, sql:str, params=None, json:list[int]|None=None) -> list[list]:
    import aiomysql
    p = serialize_params(params)
    jset = set(json) if json else None

    def process(rows):
      rows = listify(rows)
      if jset: return [parse_row(r, jset) for r in rows]
      return rows

    if self.in_transaction():
      try:
        async with self._conn.cursor() as cur:
          await cur.execute(sql, p)
          return process(await cur.fetchall())
      except aiomysql.Error as e:
        self._err("get_rows", e, sql, p)
    try:
      async with self._connect() as conn:
        async with conn.cursor() as cur:
          await cur.execute(sql, p)
          return process(await cur.fetchall())
    except aiomysql.Error as e:
      self._err("get_rows", e, sql, p)

  async def get_dicts(self, sql:str, params=None, cols:list[str]|None=None, json:list[str]|None=None) -> list[dict]:
    import aiomysql
    p = serialize_params(params)
    if self.in_transaction():
      try:
        async with self._conn.cursor() as cur:
          await cur.execute(sql, p)
          rows = await cur.fetchall()
          columns = cols or [c[0] for c in cur.description]
        return to_dicts(rows, columns, json)
      except aiomysql.Error as e:
        self._err("get_dicts", e, sql, p)
    try:
      async with self._connect() as conn:
        async with conn.cursor() as cur:
          await cur.execute(sql, p)
          rows = await cur.fetchall()
          columns = cols or [c[0] for c in cur.description]
        return to_dicts(rows, columns, json)
    except aiomysql.Error as e:
      self._err("get_dicts", e, sql, p)

  async def _insert_returning(self, table:str, data:dict, ret:str) -> Any:
    """MySQL uses `lastrowid` (ignores `ret` column name)."""
    import aiomysql
    d = serialize_dict(data)
    t = ident(table)
    cols = ", ".join(ident(k) for k in d.keys())
    vals = ph(len(d), self.ph)
    sql = f"INSERT INTO {t} ({cols}) VALUES {vals}"
    if self.in_transaction():
      try:
        async with self._conn.cursor() as cur:
          await cur.execute(sql, tuple(d.values()))
          return cur.lastrowid
      except aiomysql.Error as e:
        self._err("insert", e, sql, tuple(d.values()))
    try:
      async with self._connect() as conn:
        async with conn.cursor() as cur:
          await cur.execute(sql, tuple(d.values()))
          return cur.lastrowid
    except aiomysql.Error as e:
      self._err("insert", e, sql, tuple(d.values()))

  #------------------------------------------------------------------------------------- Schema

  async def has_table(self, name:str) -> bool:
    return await self.get_value(
      "SELECT 1 FROM information_schema.tables WHERE table_name=%s AND table_schema=%s",
      (name, self.db_name),
    ) is not None

  async def tables(self) -> list[str]:
    return await self.get_column(
      "SELECT table_name FROM information_schema.tables WHERE table_schema=%s",
      self.db_name,
    )

  async def has_database(self, name:str|None=None) -> bool:
    name = name or self.db_name
    if not name: return False
    return name in (await self.get_column("SHOW DATABASES"))

  #------------------------------------------------------------------------------------- Upsert

  async def upsert(self, table:str, data:dict, on:str|list[str], update:list[str]|None=None) -> int:
    """INSERT ON DUPLICATE KEY UPDATE. `on` param ignored — uses table's unique keys."""
    d = serialize_dict(data)
    t = ident(table)
    cols = ", ".join(ident(k) for k in d.keys())
    vals = ph(len(d), self.ph)
    upd_cols = update or [k for k in d.keys() if k not in (on if isinstance(on, list) else [on])]
    sets = ", ".join(f"{ident(k)} = VALUES({ident(k)})" for k in upd_cols)
    sql = f"INSERT INTO {t} ({cols}) VALUES {vals} ON DUPLICATE KEY UPDATE {sets}"
    return await self.exec(sql, tuple(d.values()))

  #------------------------------------------------------------------------ Database Management

  async def create_database(self, name:str|None=None) -> bool:
    if self.in_transaction(): raise RuntimeError("create_database() not allowed in transaction")
    import aiomysql
    name = name or self.db_name
    self._valid_db(name)
    if await self.has_database(name): return False
    backup, self.db_name = self.db_name, None
    try:
      conn = await self.conn()
      try:
        async with conn.cursor() as cur:
          await cur.execute(f"CREATE DATABASE `{name}`")
        await conn.commit()
        return True
      finally:
        await self._close(conn)
    except aiomysql.Error as e:
      self._err("create_database", e)
    finally:
      self.db_name = backup

  async def drop_database(self, name:str|None=None) -> bool:
    if self.in_transaction(): raise RuntimeError("drop_database() not allowed in transaction")
    import aiomysql
    name = name or self.db_name
    self._valid_db(name)
    if not await self.has_database(name): return False
    backup, self.db_name = self.db_name, None
    try:
      conn = await self.conn()
      try:
        async with conn.cursor() as cur:
          await cur.execute(f"DROP DATABASE `{name}`")
        await conn.commit()
        return True
      finally:
        await self._close(conn)
    except aiomysql.Error as e:
      self._err("drop_database", e)
    finally:
      self.db_name = backup