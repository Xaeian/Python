# xaeian/db/abstract.py

"""Driver-independent sync implementation behind `Database`."""
from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import contextmanager
from typing import NoReturn, Iterator, Any
from ..log import Logger, Print

from .errors import DatabaseError
from .utils import (
  listify, to_dicts, ident, serialize_params, split_sql, parse_json, parse_row,
  _insert_sql, _insert_many_sql, _update_sql, _find_sql,
)

class AbstractDatabase(ABC):
  """
  Auto-commits per call unless inside `transaction()`; driver errors raise `DatabaseError`.

  Every call outside a transaction opens and closes its own connection. A transaction pins one
  connection to the instance, so an instance must not be shared across threads while it runs.
  """
  def __init__(self):
    self.db_name: str|None = None
    self.log: Logger|Print|None = None
    self.debug: bool = False
    self.ph = "?"
    self._conn = None
    self._cur = None

  def __repr__(self):
    return f"<{self.__class__.__name__} db={self.db_name!r}>"

  def in_transaction(self) -> bool:
    """Check if transaction is active."""
    return self._conn is not None

  def ping(self) -> bool:
    """Check if database is reachable."""
    try:
      self.get_value("SELECT 1")
      return True
    except DatabaseError:
      return False

  @abstractmethod
  def conn(self):
    """Create new database connection."""
    raise NotImplementedError

  #------------------------------------------------------------------------------------ Transaction

  @contextmanager
  def transaction(self):
    """Commit on exit, roll back on exception. Nesting raises `RuntimeError`."""
    if self._conn is not None: raise RuntimeError("Transaction already active")
    conn = self.conn()
    cur = None
    try:
      cur = conn.cursor()
      self._conn, self._cur = conn, cur
      yield self
      conn.commit()
    except Exception:
      conn.rollback()
      raise
    finally:
      self._conn = None
      self._cur = None
      try:
        if cur is not None: cur.close()
      finally:
        conn.close()

  def _cursor(self) -> tuple:
    """Get `(conn, cur, owned)`; `owned` is `False` inside a transaction, which owns cleanup."""
    if self._conn is not None: return self._conn, self._cur, False
    conn = self.conn()
    return conn, conn.cursor(), True

  @contextmanager
  def _scope(self) -> Iterator[tuple]:
    """Yield `(conn, cur, owned)`, committing and closing only outside a transaction."""
    conn, cur, owned = self._cursor()
    try:
      yield conn, cur, owned
      if owned: conn.commit()
    except Exception:
      if owned:
        try: conn.rollback()
        except Exception: pass
      raise
    finally:
      if owned:
        try: cur.close()
        finally: conn.close()

  def _err(self, op:str, exc:Exception, sql:str|None=None, params:tuple|None=None) -> NoReturn:
    err = DatabaseError(op, exc, sql=sql, params=params)
    if self.log: self.log.error(f"[{self.db_name or 'db'}] {err}")
    raise err from exc

  def _debug(self, op:str, sql:str, params:tuple):
    s = " ".join(sql.split())[:100]
    print(f"[{self.db_name or 'db'}] {op}: {s} {params or ''}")

  def _rowcount(self, cur) -> int:
    """Row count clamped to 0, since drivers report -1 when it is unknown."""
    return max(0, cur.rowcount) if cur.rowcount is not None else 0

  #---------------------------------------------------------------------------------------- Execute

  def exec(self, sql:str, params=None) -> int:
    """Execute SQL statement. Returns affected row count."""
    p = serialize_params(params)
    if self.debug: self._debug("exec", sql, p)
    try:
      with self._scope() as (_, cur, __):
        cur.execute(sql, p)
        return self._rowcount(cur)
    except Exception as e:
      self._err("exec", e, sql, p)

  def exec_many(self, sql:str, params_list:list) -> int:
    """Execute the statement once per parameter tuple. Returns affected row count."""
    pl = [serialize_params(p) for p in params_list]
    try:
      with self._scope() as (_, cur, __):
        cur.executemany(sql, pl)
        return self._rowcount(cur)
    except Exception as e:
      self._err("exec_many", e, sql, tuple(pl))

  def exec_batch(self, sqls:list[tuple[str, Any]]|list[str]|str) -> int:
    """
    Execute multiple statements in one transaction, returning total affected rows.

    `sqls`: semicolon-separated string, list of statements, or list of `(sql, params)` tuples.
    """
    if not self.in_transaction():
      with self.transaction():
        return self.exec_batch(sqls)
    total = 0
    try:
      with self._scope() as (_, cur, __):
        if isinstance(sqls, str):
          for s in split_sql(sqls):
            cur.execute(s)
            total += self._rowcount(cur)
        elif sqls and isinstance(sqls[0], tuple):
          for sql, params in sqls:
            cur.execute(sql, serialize_params(params))
            total += self._rowcount(cur)
        else:
          for sql in sqls:
            cur.execute(sql)
            total += self._rowcount(cur)
      return total
    except Exception as e:
      self._err("exec_batch", e)

  #------------------------------------------------------------------------------------------ Query

  def get_rows(self, sql:str, params=None, json:list[int]|None=None) -> list[list]:
    """Fetch all rows as lists, parsing the column indices listed in `json`."""
    p = serialize_params(params)
    try:
      with self._scope() as (_, cur, __):
        cur.execute(sql, p)
        rows = listify(cur.fetchall())
        if json:
          jset = set(json)
          return [parse_row(r, jset) for r in rows]
        return rows
    except Exception as e:
      self._err("get_rows", e, sql, p)

  def get_dicts(
    self,
    sql:str,
    params=None,
    cols:list[str]|None = None,
    json:list[str]|None = None,
  ) -> list[dict]:
    """Fetch all rows as dicts, `cols` overriding cursor names, `json` naming JSON columns."""
    p = serialize_params(params)
    try:
      with self._scope() as (_, cur, __):
        cur.execute(sql, p)
        rows = listify(cur.fetchall())
        columns = cols or [c[0] for c in cur.description]
        return to_dicts(rows, columns, json)
    except Exception as e:
      self._err("get_dicts", e, sql, p)

  def get_row(self, sql:str, params=None, json:list[int]|None=None) -> list|None:
    """Fetch single row as list."""
    rows = self.get_rows(sql, params, json=json)
    return rows[0] if rows else None

  def get_dict(self, sql:str, params=None, json:list[str]|None=None) -> dict|None:
    """Fetch single row as dict."""
    rows = self.get_dicts(sql, params, json=json)
    return rows[0] if rows else None

  def get_column(self, sql:str, params=None, json:bool=False) -> list:
    """Fetch first column of all rows, `json=True` parsing each value as JSON."""
    rows = self.get_rows(sql, params)
    if not rows: return []
    col = [r[0] for r in rows]
    return [parse_json(v) for v in col] if json else col

  def get_value(self, sql:str, params=None, json:bool=False) -> Any:
    """Fetch first value of first row, `None` when no row; `json=True` parses it as JSON."""
    row = self.get_row(sql, params)
    if not row: return None
    return parse_json(row[0]) if json else row[0]

  #------------------------------------------------------------------------------------------- CRUD

  def insert(self, table:str, data:dict, returning:str|None=None) -> int|Any:
    """Insert single row. With `returning` yields that column's value instead of the row count."""
    sql, params = _insert_sql(table, data, self.ph)
    if returning:
      sql = f"{sql} RETURNING {ident(returning)}"
      try:
        with self._scope() as (_, cur, __):
          cur.execute(sql, params)
          row = cur.fetchone()
          return row[0] if row else None
      except Exception as e:
        self._err("insert", e, sql, params)
    return self.exec(sql, params)

  def insert_many(self, table:str, rows:list[dict]) -> int:
    """Insert multiple rows. Returns affected row count."""
    if not rows: return 0
    sql, params_list = _insert_many_sql(table, rows, self.ph)
    return self.exec_many(sql, params_list)

  def update(self, table:str, data:dict, where:str, params=None) -> int:
    """Update rows matching WHERE clause. Returns affected row count."""
    sql, p = _update_sql(table, data, where, params, self.ph)
    return self.exec(sql, p)

  def delete(self, table:str, where:str, params=None) -> int:
    """Delete rows matching WHERE clause. Returns affected row count."""
    return self.exec(f"DELETE FROM {ident(table)} WHERE {where}", params)

  def count(self, table:str, where:str="1=1", params=None) -> int:
    """Count rows matching WHERE clause."""
    return self.get_value(f"SELECT COUNT(*) FROM {ident(table)} WHERE {where}", params) or 0

  def exists(self, table:str, where:str, params=None) -> bool:
    """Check if any row matches WHERE clause."""
    return self.get_value(
      f"SELECT 1 FROM {ident(table)} WHERE {where} LIMIT 1", params
    ) is not None

  #---------------------------------------------------------------------------------- Query Builder

  def find(
    self,
    table:str,
    order:str|None = None,
    limit:int|None = None,
    json:list[str]|None = None,
    **where,
  ) -> list[dict]:
    """
    Query builder, `**where` being `column=value` conditions joined with AND.

    `order` is raw SQL appended after ORDER BY, never place user input there.
    """
    sql, params = _find_sql(table, order, limit, self.ph, where)
    return self.get_dicts(sql, params, json=json)

  def find_one(self, table:str, json:list[str]|None=None, **where) -> dict|None:
    """Find single row by conditions."""
    rows = self.find(table, limit=1, json=json, **where)
    return rows[0] if rows else None

  def paginate(
    self,
    sql:str,
    params=None,
    page:int = 1,
    per_page:int = 20,
    json:list[str]|None = None,
  ) -> dict:
    """
    Paginate a SELECT written without LIMIT/OFFSET.

    `page` is 1-based. Returns `{"items", "total", "page", "pages"}`.
    """
    offset = (page - 1) * per_page
    items = self.get_dicts(f"{sql} LIMIT {per_page} OFFSET {offset}", params, json=json)
    total = self.get_value(f"SELECT COUNT(*) FROM ({sql}) _c", params) or 0
    pages = (total + per_page - 1) // per_page if total else 0
    return {"items": items, "total": total, "page": page, "pages": pages}

  def upsert(self, table:str, data:dict, on:str|list[str], update:list[str]|None=None) -> int:
    """
    Insert, or update the columns in `update` when `on` conflicts.

    Dialect-specific: every backend overrides this, the base raises `NotImplementedError`.
    `update` defaults to every column of `data` except those named in `on`.
    """
    raise NotImplementedError(f"upsert not implemented for {self.__class__.__name__}")

  #----------------------------------------------------------------------------------------- Schema

  @abstractmethod
  def has_table(self, name:str) -> bool:
    """Check if table exists."""
    raise NotImplementedError

  @abstractmethod
  def tables(self) -> list[str]:
    """List all tables."""
    raise NotImplementedError

  @abstractmethod
  def has_database(self, name:str|None=None) -> bool:
    """Check if database exists."""
    raise NotImplementedError

  def drop_table(self, *names:str) -> int:
    """Drop one or more tables."""
    if len(names) == 1: return self.exec(f"DROP TABLE IF EXISTS {ident(names[0])}")
    return self.exec_batch([(f"DROP TABLE IF EXISTS {ident(n)}", None) for n in names])

  def _valid_db(self, name:str):
    if not name or not name.replace("_", "").isalnum():
      raise ValueError(f"Invalid database name: {name!r}")
