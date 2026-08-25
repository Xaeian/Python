# xaeian/db/abstract_async.py

"""Driver-independent async implementation behind `AsyncDatabase`."""
from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import Any, AsyncIterator
from .common import DatabaseCore
from .errors import DatabaseError
from .utils import (
  Params, listify, to_dicts, ident, serialize_params, split_sql, parse_json, parse_row,
  _insert_sql, _insert_many_sql, _update_sql, _find_sql,
)

class AbstractAsyncDatabase(DatabaseCore, ABC):
  """
  Auto-commits per call unless inside `transaction()`; failures raise `DatabaseError`.

  A transaction belongs to the task that opened it: the connection lives in a `ContextVar`,
  so a second task sharing this object keeps auto-committing on its own connection
  instead of being swept into someone else's transaction.

  A backend contributes connectivity and dialect only: `_exclusive()` lends a connection,
  `_begin()` opens a transaction on it, `_run`/`_run_many`/`_fetch` speak to its driver,
  and the schema queries know its catalog. Placeholder translation, serialization,
  JSON parsing, transaction framing and error wrapping live here, once.

  The `json=` selector takes the shape of the result it acts on:
  column indices for list rows (`get_rows`), column names for dict rows (`get_dicts`, `find`),
  `True` for a single value (`get_column`, `get_value`).
  """
  def __init__(self) -> None:
    super().__init__()
    self._tx: ContextVar = ContextVar("xaeian_db_tx", default=None)

  @property
  def _conn(self):
    """Connection of the transaction running in this task, `None` outside one."""
    return self._tx.get()

  def in_transaction(self) -> bool:
    """Check if a transaction is active in this task."""
    return self._tx.get() is not None

  async def ping(self) -> bool:
    """Check if database is reachable."""
    try:
      await self.get_value("SELECT 1")
      return True
    except DatabaseError:
      return False

  #----------------------------------------------------------------------------- Backend Primitives

  @abstractmethod
  async def conn(self) -> Any:
    """Create new connection outside the pool or persistent connection."""
    raise NotImplementedError

  @abstractmethod
  def _exclusive(self):
    """Async context manager lending one connection for the caller's whole span."""
    raise NotImplementedError

  def _connect(self):
    """One call's connection outside a transaction; SQLite adds a rollback when the call fails."""
    return self._exclusive()

  @abstractmethod
  async def _begin(self, conn):
    """Open a transaction on `conn`. Returns the handle carrying `commit()` and `rollback()`."""
    raise NotImplementedError

  @abstractmethod
  async def _run(self, conn, sql:str, params:tuple) -> int:
    """Execute one statement on `conn`. Returns affected row count."""
    raise NotImplementedError

  @abstractmethod
  async def _run_many(self, conn, sql:str, params_list:list[tuple]) -> int:
    """
    Execute the statement on `conn` once per tuple.

    Returns the affected row count, or the number of tuples where the driver reports none.
    """
    raise NotImplementedError

  @abstractmethod
  async def _fetch(self, conn, sql:str, params:tuple) -> tuple[list, list[str]]:
    """Run a query on `conn`. Returns `(rows, column names)`."""
    raise NotImplementedError

  @asynccontextmanager
  async def _scope(self):
    """The task's transaction connection, or one handed out for the span of a single call."""
    conn = self._conn
    if conn is not None:
      yield conn
      return
    async with self._connect() as conn:
      yield conn

  #------------------------------------------------------------------------------------ Transaction

  @asynccontextmanager
  async def transaction(self) -> AsyncIterator[AbstractAsyncDatabase]:
    """
    Commit on exit, roll back on exception. Nesting in one task raises `RuntimeError`.

    Ordering is the invariant: the connection is lent first, `_begin` runs second,
    the `ContextVar` is set last.
    A `_begin` that raises therefore strands neither the token nor the connection.
    """
    if self.in_transaction(): raise RuntimeError("Transaction already active")
    async with self._exclusive() as conn:
      tx = await self._begin(conn)
      token = self._tx.set(conn)
      try:
        yield self
      except BaseException: # cancellation is not an Exception, and it must still roll back
        await tx.rollback()
        raise
      else:
        await tx.commit()
      finally:
        self._tx.reset(token)

  #-------------------------------------------------------------------------------------- Lifecycle

  @property
  def pool(self) -> Any:
    """Raw connection pool. None for backends without pooling."""
    return None

  async def start(self) -> None:
    """
    Initialize connection pool or persistent connection.

    Happens lazily on the first query; call it, or use `async with db:`,
    for eager setup in a FastAPI lifespan.
    """
    pass

  async def close(self) -> None:
    """Close connection pool or persistent connection."""
    pass

  async def __aenter__(self) -> AbstractAsyncDatabase:
    await self.start()
    return self

  async def __aexit__(self, *exc) -> None:
    await self.close()

  #---------------------------------------------------------------------------------------- Execute

  async def exec(self, sql:str, params:Params=None) -> int:
    """Execute SQL statement. Returns affected row count."""
    sql = self._sql(sql)
    p = serialize_params(params)
    if self.debug: self._debug("exec", sql, p)
    try:
      async with self._scope() as conn:
        return await self._run(conn, sql, p)
    except Exception as e:
      self._err("exec", e, sql, p)

  async def exec_many(self, sql:str, params_list:list) -> int:
    """
    Execute the statement once per tuple, in one transaction.

    Returns the affected row count; asyncpg reports none, so there it is the tuple count.
    """
    if not self.in_transaction():
      async with self.transaction():
        return await self.exec_many(sql, params_list)
    sql = self._sql(sql)
    pl = [serialize_params(p) for p in params_list]
    if self.debug: self._debug("exec_many", sql, tuple(pl))
    try:
      return await self._run_many(self._conn, sql, pl)
    except Exception as e:
      self._err("exec_many", e, sql, tuple(pl))

  async def exec_batch(self, sqls:list[tuple[str, Any]]|list[str]|str) -> int:
    """
    Execute multiple statements in one transaction, returning total affected rows.

    A `sqls` string is split on semicolons.
    """
    if not self.in_transaction():
      async with self.transaction():
        return await self.exec_batch(sqls)
    if isinstance(sqls, str): pairs = [(s, None) for s in split_sql(sqls)]
    elif sqls and isinstance(sqls[0], tuple): pairs = sqls
    else: pairs = [(s, None) for s in sqls]
    total = 0
    try:
      for sql, params in pairs:
        total += await self._run(self._conn, self._sql(sql), serialize_params(params))
      return total
    except Exception as e:
      self._err("exec_batch", e)

  #------------------------------------------------------------------------------------------ Query

  async def get_rows(
    self,
    sql:str,
    params:Params = None,
    json:list[int]|None = None,
  ) -> list[list[Any]]:
    """Fetch all rows as lists, parsing the column indices listed in `json`."""
    sql = self._sql(sql)
    p = serialize_params(params)
    if self.debug: self._debug("get_rows", sql, p)
    try:
      async with self._scope() as conn:
        rows, _ = await self._fetch(conn, sql, p)
        rows = listify(rows)
        if json:
          jset = set(json)
          return [parse_row(r, jset) for r in rows]
        return rows
    except Exception as e:
      self._err("get_rows", e, sql, p)

  async def get_dicts(
    self,
    sql:str,
    params:Params = None,
    cols:list[str]|None = None,
    json:list[str]|None = None,
  ) -> list[dict[str, Any]]:
    """Fetch all rows as dicts, `cols` overriding cursor names, `json` naming JSON columns."""
    sql = self._sql(sql)
    p = serialize_params(params)
    if self.debug: self._debug("get_dicts", sql, p)
    try:
      async with self._scope() as conn:
        rows, columns = await self._fetch(conn, sql, p)
        return to_dicts(listify(rows), cols or columns, json)
    except Exception as e:
      self._err("get_dicts", e, sql, p)

  async def get_row(self, sql:str, params:Params=None, json:list[int]|None=None) -> list[Any]|None:
    """Fetch single row as list."""
    rows = await self.get_rows(sql, params, json=json)
    return rows[0] if rows else None

  async def get_dict(
    self,
    sql:str,
    params:Params = None,
    json:list[str]|None = None,
  ) -> dict[str, Any]|None:
    """Fetch single row as dict."""
    rows = await self.get_dicts(sql, params, json=json)
    return rows[0] if rows else None

  async def get_column(self, sql:str, params:Params=None, json:bool=False) -> list[Any]:
    """Fetch first column of all rows, `json=True` parsing each value as JSON."""
    rows = await self.get_rows(sql, params)
    if not rows: return []
    col = [r[0] for r in rows]
    return [parse_json(v) for v in col] if json else col

  async def get_value(self, sql:str, params:Params=None, json:bool=False) -> Any:
    """Fetch first value of first row, `None` when no row; `json=True` parses it as JSON."""
    row = await self.get_row(sql, params)
    if not row: return None
    return parse_json(row[0]) if json else row[0]

  #------------------------------------------------------------------------------------------- CRUD

  async def insert(self, table:str, data:dict, returning:str|None=None) -> Any:
    """Insert single row. With `returning` yields that column's value instead of the row count."""
    if returning: return await self._insert_returning(table, data, returning)
    sql, params = _insert_sql(table, data)
    return await self.exec(sql, params)

  async def _insert_returning(self, table:str, data:dict, ret:str) -> Any:
    sql, params = _insert_sql(table, data)
    sql = self._sql(f"{sql} RETURNING {ident(ret)}")
    try:
      async with self._scope() as conn:
        rows, _ = await self._fetch(conn, sql, params)
        return rows[0][0] if rows else None
    except Exception as e:
      self._err("insert", e, sql, params)

  async def insert_many(self, table:str, rows:list[dict]) -> int:
    """Insert multiple rows. Returns affected row count."""
    if not rows: return 0
    sql, params_list = _insert_many_sql(table, rows)
    return await self.exec_many(sql, params_list)

  async def update(self, table:str, data:dict, where:str, params:Params=None) -> int:
    """Update rows matching WHERE clause. Returns affected row count."""
    sql, p = _update_sql(table, data, where, params)
    return await self.exec(sql, p)

  async def delete(self, table:str, where:str, params:Params=None) -> int:
    """Delete rows matching WHERE clause. Returns affected row count."""
    return await self.exec(f"DELETE FROM {ident(table)} WHERE {where}", params)

  async def count(self, table:str, where:str="1=1", params:Params=None) -> int:
    """Count rows matching WHERE clause."""
    return await self.get_value(f"SELECT COUNT(*) FROM {ident(table)} WHERE {where}", params) or 0

  async def exists(self, table:str, where:str, params:Params=None) -> bool:
    """Check if any row matches WHERE clause."""
    return await self.get_value(
      f"SELECT 1 FROM {ident(table)} WHERE {where} LIMIT 1", params
    ) is not None

  #---------------------------------------------------------------------------------- Query Builder

  async def find(
    self,
    table:str,
    order:str|None = None,
    limit:int|None = None,
    json:list[str]|None = None,
    **where,
  ) -> list[dict[str, Any]]:
    """
    Query builder, `**where` being `column=value` conditions joined with AND.

    `order` is raw SQL appended after ORDER BY, never place user input there.
    """
    sql, params = _find_sql(table, order, limit, where)
    return await self.get_dicts(sql, params, json=json)

  async def find_one(self, table:str, json:list[str]|None=None, **where) -> dict[str, Any]|None:
    """Find single row by conditions."""
    rows = await self.find(table, limit=1, json=json, **where)
    return rows[0] if rows else None

  async def paginate(
    self,
    sql:str,
    params:Params = None,
    page:int = 1,
    per_page:int = 20,
    json:list[str]|None = None,
  ) -> dict[str, Any]:
    """
    Paginate a SELECT written without LIMIT/OFFSET.

    `page` is 1-based. Returns `{"items", "total", "page", "pages"}`.
    """
    if page < 1: raise ValueError(f"page is 1-based, got {page}")
    if per_page < 1: raise ValueError(f"per_page must be at least 1, got {per_page}")
    offset = (page - 1) * per_page
    items = await self.get_dicts(f"{sql} LIMIT {per_page} OFFSET {offset}", params, json=json)
    total = await self.get_value(f"SELECT COUNT(*) FROM ({sql}) _c", params) or 0
    pages = (total + per_page - 1) // per_page if total else 0
    return {"items": items, "total": total, "page": page, "pages": pages}

  async def upsert(
    self,
    table:str,
    data:dict,
    on:str|list[str],
    update:list[str]|None = None,
  ) -> int:
    """
    Insert, or update the columns in `update` when `on` conflicts.

    Dialect-specific: every backend overrides this.
    `update` defaults to every column of `data` except those named in `on`.
    """
    raise NotImplementedError(f"upsert not implemented for {self.__class__.__name__}")

  #----------------------------------------------------------------------------------------- Schema

  @abstractmethod
  async def has_table(self, name:str) -> bool:
    """Check if table exists."""
    raise NotImplementedError

  @abstractmethod
  async def tables(self) -> list[str]:
    """List all tables."""
    raise NotImplementedError

  @abstractmethod
  async def has_database(self, name:str|None=None) -> bool:
    """Check if database exists."""
    raise NotImplementedError

  async def drop_table(self, *names:str) -> int:
    """Drop one or more tables."""
    if len(names) == 1: return await self.exec(f"DROP TABLE IF EXISTS {ident(names[0])}")
    return await self.exec_batch([(f"DROP TABLE IF EXISTS {ident(n)}", None) for n in names])
