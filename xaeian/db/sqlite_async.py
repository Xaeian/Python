# xaeian/db/sqlite_async.py

"""SQLite async implementation."""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any
from logging import Logger

from .abstract_async import AbstractAsyncDatabase
from .utils import listify, to_dicts, ident, ph, serialize_params, serialize_dict, split_sql, parse_row

class SqliteAsyncDatabase(AbstractAsyncDatabase):
  """
  SQLite async database (aiosqlite).

  Uses `RETURNING` clause (SQLite 3.35+).

  Args:
    db_name: Database file path or `":memory:"`.
    log: Logger instance for error logging.

  Example:
    >>> db = SqliteAsyncDatabase("app.db")
    >>> await db.insert("users", {"name": "Jan"})
  """
  def __init__(self, db_name:str, log:Logger|None=None):
    super().__init__()
    self.db_name = db_name
    self.log = log

  async def conn(self):
    import aiosqlite
    return await aiosqlite.connect(self.db_name)

  #-------------------------------------------------------------------------------- Transaction

  @asynccontextmanager
  async def transaction(self):
    if self._conn is not None: raise RuntimeError("Transaction already active")
    self._conn = await self.conn()
    try:
      yield self
      await self._conn.commit()
    except Exception:
      await self._conn.rollback()
      raise
    finally:
      await self._conn.close()
      self._conn = None

  def _rowcount(self, cur) -> int:
    return max(0, cur.rowcount) if cur.rowcount is not None else 0

  #------------------------------------------------------------------------------------ Execute

  async def exec(self, sql:str, params=None) -> int:
    import aiosqlite
    p = serialize_params(params)
    if self.debug: self._debug("exec", sql, p)
    if self.in_transaction():
      try:
        cur = await self._conn.execute(sql, p)
        rc = self._rowcount(cur)
        await cur.close()
        return rc
      except aiosqlite.Error as e:
        self._err("exec", e, sql, p)
    conn = None
    try:
      conn = await self.conn()
      cur = await conn.execute(sql, p)
      rc = self._rowcount(cur)
      await cur.close()
      await conn.commit()
      return rc
    except aiosqlite.Error as e:
      self._err("exec", e, sql, p)
    finally:
      if conn: await conn.close()

  async def exec_many(self, sql:str, params_list:list) -> int:
    import aiosqlite
    pl = [serialize_params(p) for p in params_list]
    if self.in_transaction():
      try:
        cur = await self._conn.executemany(sql, pl)
        rc = self._rowcount(cur)
        await cur.close()
        return rc
      except aiosqlite.Error as e:
        self._err("exec_many", e, sql, tuple(pl))
    conn = None
    try:
      conn = await self.conn()
      cur = await conn.executemany(sql, pl)
      rc = self._rowcount(cur)
      await cur.close()
      await conn.commit()
      return rc
    except aiosqlite.Error as e:
      self._err("exec_many", e, sql, tuple(pl))
    finally:
      if conn: await conn.close()

  async def exec_batch(self, sqls:list[tuple[str, Any]]|list[str]|str) -> int:
    import aiosqlite

    async def run(conn) -> int:
      total = 0
      if isinstance(sqls, str):
        for s in split_sql(sqls):
          cur = await conn.execute(s)
          total += self._rowcount(cur)
          await cur.close()
      elif sqls and isinstance(sqls[0], tuple):
        for sql, params in sqls:
          cur = await conn.execute(sql, serialize_params(params))
          total += self._rowcount(cur)
          await cur.close()
      else:
        for sql in sqls:
          cur = await conn.execute(sql)
          total += self._rowcount(cur)
          await cur.close()
      return total

    if self.in_transaction():
      try: return await run(self._conn)
      except aiosqlite.Error as e: self._err("exec_batch", e)
    conn = None
    try:
      conn = await self.conn()
      total = await run(conn)
      await conn.commit()
      return total
    except aiosqlite.Error as e:
      self._err("exec_batch", e)
    finally:
      if conn: await conn.close()

  #-------------------------------------------------------------------------------------- Query

  async def get_rows(self, sql:str, params=None, json:list[int]|None=None) -> list[list]:
    import aiosqlite
    p = serialize_params(params)
    jset = set(json) if json else None

    def process(rows):
      rows = listify(rows)
      if jset: return [parse_row(r, jset) for r in rows]
      return rows

    if self.in_transaction():
      try:
        cur = await self._conn.execute(sql, p)
        rows = await cur.fetchall()
        await cur.close()
        return process(rows)
      except aiosqlite.Error as e:
        self._err("get_rows", e, sql, p)
    conn = None
    try:
      conn = await self.conn()
      cur = await conn.execute(sql, p)
      rows = await cur.fetchall()
      await cur.close()
      return process(rows)
    except aiosqlite.Error as e:
      self._err("get_rows", e, sql, p)
    finally:
      if conn: await conn.close()

  async def get_dicts(self, sql:str, params=None, cols:list[str]|None=None, json:list[str]|None=None) -> list[dict]:
    import aiosqlite
    p = serialize_params(params)
    if self.in_transaction():
      try:
        cur = await self._conn.execute(sql, p)
        rows = await cur.fetchall()
        columns = cols or [c[0] for c in cur.description]
        await cur.close()
        return to_dicts(rows, columns, json)
      except aiosqlite.Error as e:
        self._err("get_dicts", e, sql, p)
    conn = None
    try:
      conn = await self.conn()
      cur = await conn.execute(sql, p)
      rows = await cur.fetchall()
      columns = cols or [c[0] for c in cur.description]
      await cur.close()
      return to_dicts(rows, columns, json)
    except aiosqlite.Error as e:
      self._err("get_dicts", e, sql, p)
    finally:
      if conn: await conn.close()

  async def _insert_returning(self, table:str, data:dict, ret:str) -> Any:
    import aiosqlite
    d = serialize_dict(data)
    t = ident(table)
    cols = ", ".join(ident(k) for k in d.keys())
    vals = ph(len(d), self.ph)
    sql = f"INSERT INTO {t} ({cols}) VALUES {vals} RETURNING {ident(ret)}"
    if self.in_transaction():
      try:
        cur = await self._conn.execute(sql, tuple(d.values()))
        row = await cur.fetchone()
        await cur.close()
        return row[0] if row else None
      except aiosqlite.Error as e:
        self._err("insert", e, sql, tuple(d.values()))
    conn = None
    try:
      conn = await self.conn()
      cur = await conn.execute(sql, tuple(d.values()))
      row = await cur.fetchone()
      await cur.close()
      await conn.commit()
      return row[0] if row else None
    except aiosqlite.Error as e:
      self._err("insert", e, sql, tuple(d.values()))
    finally:
      if conn: await conn.close()

  #------------------------------------------------------------------------------------- Schema

  async def has_table(self, name:str) -> bool:
    return await self.get_value(
      "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", name
    ) is not None

  async def tables(self) -> list[str]:
    return await self.get_column("SELECT name FROM sqlite_master WHERE type='table'")

  async def has_database(self, name:str|None=None) -> bool:
    n = name or self.db_name
    return os.path.isfile(n) if n else False

  #------------------------------------------------------------------------------------- Upsert

  async def upsert(self, table:str, data:dict, on:str|list[str], update:list[str]|None=None) -> int:
    """INSERT ON CONFLICT (SQLite 3.24+)."""
    d = serialize_dict(data)
    t = ident(table)
    cols = ", ".join(ident(k) for k in d.keys())
    vals = ph(len(d), self.ph)
    conf = on if isinstance(on, str) else ", ".join(on)
    upd_cols = update or [k for k in d.keys() if k not in (on if isinstance(on, list) else [on])]
    sets = ", ".join(f"{ident(k)} = excluded.{ident(k)}" for k in upd_cols)
    sql = f"INSERT INTO {t} ({cols}) VALUES {vals} ON CONFLICT ({conf}) DO UPDATE SET {sets}"
    return await self.exec(sql, tuple(d.values()))

  #------------------------------------------------------------------------ Database Management

  async def create_database(self, name:str|None=None) -> bool:
    if self.in_transaction(): raise RuntimeError("create_database() not allowed in transaction")
    import aiosqlite
    n = name or self.db_name
    if not n: raise ValueError("db_name required")
    if await self.has_database(n): return False
    conn = await aiosqlite.connect(n)
    await conn.close()
    return True

  async def drop_database(self, name:str|None=None) -> bool:
    if self.in_transaction(): raise RuntimeError("drop_database() not allowed in transaction")
    n = name or self.db_name
    if not n: raise ValueError("db_name required")
    if not await self.has_database(n): return False
    try:
      os.remove(n)
      return True
    except OSError as e:
      self._err("drop_database", e)
