# xaeian/db/postgres_async.py

"""PostgreSQL async implementation."""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any
from logging import Logger

from .abstract_async import AbstractAsyncDatabase
from .utils import ident, serialize_params, serialize_dict, split_sql, parse_json, parse_row

class PostgresAsyncDatabase(AbstractAsyncDatabase):
  """
  PostgreSQL async database (asyncpg).

  Converts `?`/`%s` placeholders to `$1`, `$2`, ...

  Args:
    db_name: Database name.
    host: Server hostname.
    user: Username.
    password: Password.
    port: Server port.
    log: Logger instance.

  Example:
    >>> db = PostgresAsyncDatabase("mydb", user="postgres", password="secret")
    >>> user_id = await db.insert("users", {"name": "Jan"}, returning="id")
  """
  def __init__(
    self,
    db_name: str|None = None,
    host: str = "localhost",
    user: str = "postgres",
    password: str = "",
    port: int = 5432,
    log: Logger|None = None,
  ):
    super().__init__()
    self.host = host
    self.port = port
    self.user = user
    self.password = password
    self.db_name = db_name
    self.log = log
    self.ph = "$"

  def _pg(self, sql:str) -> str:
    """Convert `?` or `%s` placeholders to `$1`, `$2`, ..."""
    result, idx, i = [], 1, 0
    n = len(sql)
    while i < n:
      if sql[i] == "?":
        result.append(f"${idx}")
        idx += 1
      elif i + 1 < n and sql[i:i+2] == "%s":
        result.append(f"${idx}")
        idx += 1
        i += 1
      else:
        result.append(sql[i])
      i += 1
    return "".join(result)

  async def conn(self):
    import asyncpg
    return await asyncpg.connect(
      host=self.host, port=self.port,
      user=self.user, password=self.password,
      database=self.db_name
    )

  #-------------------------------------------------------------------------------- Transaction

  @asynccontextmanager
  async def transaction(self):
    if self._conn is not None: raise RuntimeError("Transaction already active")
    self._conn = await self.conn()
    tr = self._conn.transaction()
    await tr.start()
    try:
      yield self
      await tr.commit()
    except Exception:
      await tr.rollback()
      raise
    finally:
      await self._conn.close()
      self._conn = None

  #------------------------------------------------------------------------------------ Execute

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
    conn = None
    try:
      conn = await self.conn()
      result = await conn.execute(sql2, *p)
      return self._parse_status(result)
    except asyncpg.PostgresError as e:
      self._err("exec", e, sql2, p)
    finally:
      if conn: await conn.close()

  def _parse_status(self, status:str) -> int:
    """Parse asyncpg status string like `INSERT 0 1` or `UPDATE 5`."""
    if not status: return 0
    parts = status.split()
    if parts and parts[-1].isdigit(): return int(parts[-1])
    return 0

  async def exec_many(self, sql:str, params_list:list) -> int:
    import asyncpg
    sql2 = self._pg(sql)
    pl = [serialize_params(p) for p in params_list]
    if self.in_transaction():
      try:
        await self._conn.executemany(sql2, pl)
        return len(pl)
      except asyncpg.PostgresError as e:
        self._err("exec_many", e, sql2, tuple(pl))
    conn = None
    try:
      conn = await self.conn()
      await conn.executemany(sql2, pl)
      return len(pl)
    except asyncpg.PostgresError as e:
      self._err("exec_many", e, sql2, tuple(pl))
    finally:
      if conn: await conn.close()

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
    conn = None
    try:
      conn = await self.conn()
      async with conn.transaction():
        total = await run(conn)
      return total
    except asyncpg.PostgresError as e:
      self._err("exec_batch", e)
    finally:
      if conn: await conn.close()

  #-------------------------------------------------------------------------------------- Query

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
    conn = None
    try:
      conn = await self.conn()
      rows = await conn.fetch(sql2, *p)
      return process(rows)
    except asyncpg.PostgresError as e:
      self._err("get_rows", e, sql2, p)
    finally:
      if conn: await conn.close()

  async def get_dicts(self, sql:str, params=None, cols:list[str]|None=None, json:list[str]|None=None) -> list[dict]:
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
    conn = None
    try:
      conn = await self.conn()
      rows = await conn.fetch(sql2, *p)
      return convert(rows)
    except asyncpg.PostgresError as e:
      self._err("get_dicts", e, sql2, p)
    finally:
      if conn: await conn.close()

  async def _insert_returning(self, table:str, data:dict, ret:str) -> Any:
    import asyncpg
    d = serialize_dict(data)
    t = ident(table)
    cols = ", ".join(ident(k) for k in d.keys())
    vals = ", ".join(f"${i+1}" for i in range(len(d)))
    sql = f"INSERT INTO {t} ({cols}) VALUES ({vals}) RETURNING {ident(ret)}"
    if self.in_transaction():
      try:
        row = await self._conn.fetchrow(sql, *d.values())
        return row[0] if row else None
      except asyncpg.PostgresError as e:
        self._err("insert", e, sql, tuple(d.values()))
    conn = None
    try:
      conn = await self.conn()
      row = await conn.fetchrow(sql, *d.values())
      return row[0] if row else None
    except asyncpg.PostgresError as e:
      self._err("insert", e, sql, tuple(d.values()))
    finally:
      if conn: await conn.close()

  #------------------------------------------------------------------------------------- Schema

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

  #------------------------------------------------------------------------------------- Upsert

  async def upsert(self, table:str, data:dict, on:str|list[str], update:list[str]|None=None) -> int:
    """INSERT ON CONFLICT (PostgreSQL 9.5+)."""
    d = serialize_dict(data)
    t = ident(table)
    cols = ", ".join(ident(k) for k in d.keys())
    vals = ", ".join(f"${i+1}" for i in range(len(d)))
    conf = on if isinstance(on, str) else ", ".join(on)
    upd_cols = update or [k for k in d.keys() if k not in (on if isinstance(on, list) else [on])]
    sets = ", ".join(f"{ident(k)} = EXCLUDED.{ident(k)}" for k in upd_cols)
    sql = f"INSERT INTO {t} ({cols}) VALUES ({vals}) ON CONFLICT ({conf}) DO UPDATE SET {sets}"
    return await self.exec(sql, tuple(d.values()))

  #------------------------------------------------------------------------ Database Management

  async def create_database(self, name:str|None=None) -> bool:
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
