# xaeian/db/postgres_async.py

"""PostgreSQL async implementation."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any
from ..log import Logger, Print

from .abstract_async import AbstractAsyncDatabase
from .utils import (
  ident, serialize_params, split_sql, parse_json, parse_row, _insert_sql, _upsert_sql,
)

class PostgresAsyncDatabase(AbstractAsyncDatabase):
  """
  PostgreSQL async database (asyncpg) with connection pooling.

  `start()` opens `min_pool` connections up front, otherwise the pool is built on first query.
  """
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
  ):
    super().__init__()
    self.host = host
    self.port = port
    self.user = user
    self.password = password
    self.db_name = db_name
    self.log = log
    self.ph = "$"
    self._pool = None
    self._pool_lock = asyncio.Lock()
    self._min_pool = min_pool
    self._max_pool = max_pool

  def _pg(self, sql:str) -> str:
    """
    Convert `?` or `%s` placeholders to `$1`, `$2`, ... (quoted literals untouched).

    Every `?` outside a single-quoted literal counts as a placeholder, so the jsonb `?` operator
    has to be written as `jsonb_exists()`.
    """
    result, idx, i = [], 1, 0
    n = len(sql)
    quoted = False
    while i < n:
      ch = sql[i]
      if quoted:
        if ch == "'" and i + 1 < n and sql[i+1] == "'":
          result.append("''"); i += 2; continue
        if ch == "'": quoted = False
        result.append(ch)
      elif ch == "'":
        quoted = True
        result.append(ch)
      elif ch == "?":
        result.append(f"${idx}")
        idx += 1
      elif ch == "%" and i + 1 < n and sql[i+1] == "s":
        result.append(f"${idx}")
        idx += 1
        i += 1
      else:
        result.append(ch)
      i += 1
    return "".join(result)

  async def conn(self):
    """Standalone connection, outside the pool."""
    import asyncpg
    return await asyncpg.connect(
      host=self.host, port=self.port,
      user=self.user, password=self.password,
      database=self.db_name,
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
  async def _connect(self):
    """Acquire connection from pool."""
    pool = await self._ensure_pool()
    async with pool.acquire() as conn:
      yield conn

  @property
  def pool(self):
    """Raw asyncpg pool for COPY protocol, etc."""
    return self._pool

  async def start(self):
    """Eagerly create connection pool."""
    await self._ensure_pool()

  async def close(self):
    """Close connection pool."""
    if self._pool:
      await self._pool.close()
      self._pool = None

  #------------------------------------------------------------------------------------ Transaction

  @asynccontextmanager
  async def transaction(self):
    if self._conn is not None: raise RuntimeError("Transaction already active")
    pool = await self._ensure_pool()
    conn = await pool.acquire()
    self._conn = conn
    tr = conn.transaction()
    await tr.start()
    try:
      yield self
      await tr.commit()
    except Exception:
      await tr.rollback()
      raise
    finally:
      self._conn = None
      await pool.release(conn)

  #---------------------------------------------------------------------------------------- Execute

  async def exec(self, sql:str, params=None) -> int:
    import asyncpg
    sql2 = self._pg(sql)
    p = serialize_params(params)
    if self.debug: self._debug("exec", sql2, p)
    if self.in_transaction():
      try:
        result = await self._conn.execute(sql2, *p)
        return self._parse_status(result)
      except asyncpg.PostgresError as e:
        self._err("exec", e, sql2, p)
    try:
      async with self._connect() as conn:
        result = await conn.execute(sql2, *p)
        return self._parse_status(result)
    except asyncpg.PostgresError as e:
      self._err("exec", e, sql2, p)

  def _parse_status(self, status:str) -> int:
    """Parse asyncpg status string like `INSERT 0 1` or `UPDATE 5`."""
    if not status: return 0
    parts = status.split()
    if parts and parts[-1].isdigit(): return int(parts[-1])
    return 0

  async def exec_many(self, sql:str, params_list:list) -> int:
    """Execute once per parameter tuple, returning their count: asyncpg reports no row counts."""
    import asyncpg
    sql2 = self._pg(sql)
    pl = [serialize_params(p) for p in params_list]
    if self.in_transaction():
      try:
        await self._conn.executemany(sql2, pl)
        return len(pl)
      except asyncpg.PostgresError as e:
        self._err("exec_many", e, sql2, tuple(pl))
    try:
      async with self._connect() as conn:
        await conn.executemany(sql2, pl)
        return len(pl)
    except asyncpg.PostgresError as e:
      self._err("exec_many", e, sql2, tuple(pl))

  async def exec_batch(self, sqls:list[tuple[str, Any]]|list[str]|str) -> int:
    import asyncpg

    async def run(conn) -> int:
      total = 0
      if isinstance(sqls, str):
        for s in split_sql(sqls):
          result = await conn.execute(self._pg(s))
          total += self._parse_status(result)
      elif sqls and isinstance(sqls[0], tuple):
        for sql, params in sqls:
          p = serialize_params(params)
          result = await conn.execute(self._pg(sql), *p)
          total += self._parse_status(result)
      else:
        for sql in sqls:
          result = await conn.execute(self._pg(sql))
          total += self._parse_status(result)
      return total

    if self.in_transaction():
      try: return await run(self._conn)
      except asyncpg.PostgresError as e: self._err("exec_batch", e)
    try:
      async with self._connect() as conn:
        async with conn.transaction():
          return await run(conn)
    except asyncpg.PostgresError as e:
      self._err("exec_batch", e)

  #------------------------------------------------------------------------------------------ Query

  async def get_rows(self, sql:str, params=None, json:list[int]|None=None) -> list[list]:
    import asyncpg
    sql2 = self._pg(sql)
    p = serialize_params(params)
    jset = set(json) if json else None

    def process(rows):
      result = [list(r.values()) for r in rows]
      if jset: return [parse_row(r, jset) for r in result]
      return result

    if self.in_transaction():
      try:
        rows = await self._conn.fetch(sql2, *p)
        return process(rows)
      except asyncpg.PostgresError as e:
        self._err("get_rows", e, sql2, p)
    try:
      async with self._connect() as conn:
        rows = await conn.fetch(sql2, *p)
        return process(rows)
    except asyncpg.PostgresError as e:
      self._err("get_rows", e, sql2, p)

  async def get_dicts(
    self,
    sql:str,
    params=None,
    cols:list[str]|None = None,
    json:list[str]|None = None,
  ) -> list[dict]:
    import asyncpg
    sql2 = self._pg(sql)
    p = serialize_params(params)
    jset = set(json) if json else None

    def convert(rows):
      if cols: result = [dict(zip(cols, r.values())) for r in rows]
      else: result = [dict(r) for r in rows]
      if jset:
        for d in result:
          for k in jset:
            if k in d: d[k] = parse_json(d[k])
      return result

    if self.in_transaction():
      try:
        rows = await self._conn.fetch(sql2, *p)
        return convert(rows)
      except asyncpg.PostgresError as e:
        self._err("get_dicts", e, sql2, p)
    try:
      async with self._connect() as conn:
        rows = await conn.fetch(sql2, *p)
        return convert(rows)
    except asyncpg.PostgresError as e:
      self._err("get_dicts", e, sql2, p)

  async def _insert_returning(self, table:str, data:dict, ret:str) -> Any:
    import asyncpg
    sql, params = _insert_sql(table, data, self.ph)
    sql = f"{sql} RETURNING {ident(ret)}"
    if self.in_transaction():
      try:
        row = await self._conn.fetchrow(sql, *params)
        return row[0] if row else None
      except asyncpg.PostgresError as e:
        self._err("insert", e, sql, params)
    try:
      async with self._connect() as conn:
        row = await conn.fetchrow(sql, *params)
        return row[0] if row else None
    except asyncpg.PostgresError as e:
      self._err("insert", e, sql, params)

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
    name = name or self.db_name
    if not name: return False
    backup, self.db_name = self.db_name, "postgres"
    try:
      return await self.get_value("SELECT 1 FROM pg_database WHERE datname=?", name) is not None
    finally:
      self.db_name = backup

  #----------------------------------------------------------------------------------------- Upsert

  async def upsert(
    self,
    table:str,
    data:dict,
    on:str|list[str],
    update:list[str]|None = None,
  ) -> int:
    """INSERT ON CONFLICT (PostgreSQL 9.5+). `on` must be a UNIQUE or PRIMARY KEY column set."""
    sql, params = _upsert_sql(table, data, on, update, self.ph, "EXCLUDED")
    return await self.exec(sql, params)

  #---------------------------------------------------------------------------- Database Management

  async def create_database(self, name:str|None=None) -> bool:
    """Create database. Returns `False` if it already exists."""
    if self.in_transaction(): raise RuntimeError("create_database() not allowed in transaction")
    import asyncpg
    name = name or self.db_name
    self._valid_db(name)
    if await self.has_database(name): return False
    backup, self.db_name = self.db_name, "postgres"
    conn = None
    try:
      conn = await self.conn()
      await conn.execute(f'CREATE DATABASE "{name}"')
      return True
    except asyncpg.PostgresError as e:
      self._err("create_database", e)
    finally:
      if conn: await conn.close()
      self.db_name = backup

  async def drop_database(self, name:str|None=None) -> bool:
    """Drop database and everything in it. Returns `False` if it does not exist."""
    if self.in_transaction(): raise RuntimeError("drop_database() not allowed in transaction")
    import asyncpg
    name = name or self.db_name
    self._valid_db(name)
    if not await self.has_database(name): return False
    backup, self.db_name = self.db_name, "postgres"
    conn = None
    try:
      conn = await self.conn()
      await conn.execute(f'DROP DATABASE "{name}"')
      return True
    except asyncpg.PostgresError as e:
      self._err("drop_database", e)
    finally:
      if conn: await conn.close()
      self.db_name = backup