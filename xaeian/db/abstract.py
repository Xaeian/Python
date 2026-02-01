# xaeian/db/abstract.py

"""Sync database base class."""
from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import contextmanager
from logging import Logger
from typing import NoReturn, Iterator, Any

from .errors import DatabaseError
from .utils import (
  listify, to_dicts, ident, ph, ph_list, renum_ph,
  serialize_params, serialize_dict, split_sql, parse_json, parse_row
)

class AbstractDatabase(ABC):
  """
  Sync database base class.

  Auto-commits per call, or batch operations in `transaction()`.

  Example:
    >>> db.exec("INSERT INTO users (name) VALUES (?)", ("Jan",))
    >>> with db.transaction():
    ...   db.insert("orders", {"user_id": 1, "total": 99.50})
    ...   db.update("users", {"balance": 0}, "id = ?", user_id)
  """

  def __init__(self):
    self.db_name: str|None = None
    self.log: Logger|None = None
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

  #-------------------------------------------------------------------------------- Transaction

  @contextmanager
  def transaction(self):
    """
    Transaction context manager.

    Commits on success, rolls back on exception.

    Example:
      >>> with db.transaction():
      ...   db.insert("users", {"name": "Jan"})
      ...   db.update("accounts", {"balance": 0}, "user_id = ?", 1)

    Raises:
      RuntimeError: When transaction already active.
    """
    if self._conn is not None: raise RuntimeError("Transaction already active")
    self._conn = self.conn()
    self._cur = self._conn.cursor()
    try:
      yield self
      self._conn.commit()
    except Exception:
      self._conn.rollback()
      raise
    finally:
      try: self._cur.close()
      finally: self._conn.close()
      self._conn = None
      self._cur = None

  def _cursor(self) -> tuple:
    if self._conn is not None: return self._conn, self._cur, False
    conn = self.conn()
    return conn, conn.cursor(), True

  @contextmanager
  def _scope(self, commit:bool=False) -> Iterator[tuple]:
    conn, cur, owned = self._cursor()
    try:
      yield conn, cur, owned
      if commit and owned: conn.commit()
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
    print(f"[{self.db_name or 'db'}] {op}: {s} {params if params else ''}")

  def _rowcount(self, cur) -> int:
    return max(0, cur.rowcount) if cur.rowcount is not None else 0

  #------------------------------------------------------------------------------------ Execute

  def exec(self, sql:str, params=None) -> int:
    """
    Execute SQL statement.

    Args:
      sql: SQL statement with placeholders.
      params: Parameters for placeholders.

    Returns:
      Affected row count.

    Raises:
      DatabaseError: On SQL or driver error.
    """
    p = serialize_params(params)
    if self.debug: self._debug("exec", sql, p)
    try:
      with self._scope(commit=True) as (_, cur, __):
        cur.execute(sql, p)
        return self._rowcount(cur)
    except Exception as e:
      self._err("exec", e, sql, p)

  def exec_many(self, sql:str, params_list:list) -> int:
    """
    Execute statement with multiple parameter sets.

    Args:
      sql: SQL statement with placeholders.
      params_list: List of parameter tuples.

    Returns:
      Affected row count.
    """
    pl = [serialize_params(p) for p in params_list]
    try:
      with self._scope(commit=True) as (_, cur, __):
        cur.executemany(sql, pl)
        return self._rowcount(cur)
    except Exception as e:
      self._err("exec_many", e, sql, tuple(pl))

  def exec_batch(self, sqls:list[tuple[str, Any]]|list[str]|str) -> int:
    """
    Execute multiple statements in one transaction.

    Args:
      sqls: SQL string with semicolons, list of SQL strings,
            or list of `(sql, params)` tuples.

    Returns:
      Total affected rows.
    """
    total = 0
    try:
      with self._scope(commit=True) as (_, cur, __):
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

  #-------------------------------------------------------------------------------------- Query

  def get_rows(self, sql:str, params=None, json:list[int]|None=None) -> list[list]:
    """
    Fetch all rows as lists.

    Args:
      sql: SELECT statement.
      params: Query parameters.
      json: Column indices to parse as JSON.

    Returns:
      List of row lists.
    """
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

  def get_dicts(self, sql:str, params=None, cols:list[str]|None=None, json:list[str]|None=None) -> list[dict]:
    """
    Fetch all rows as dicts.

    Args:
      sql: SELECT statement.
      params: Query parameters.
      cols: Override column names.
      json: Column names to parse as JSON.

    Returns:
      List of row dicts.
    """
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
    """Fetch first column of all rows."""
    rows = self.get_rows(sql, params)
    if not rows: return []
    col = [r[0] for r in rows]
    return [parse_json(v) for v in col] if json else col

  def get_value(self, sql:str, params=None, json:bool=False) -> Any:
    """Fetch single value."""
    row = self.get_row(sql, params)
    if not row: return None
    return parse_json(row[0]) if json else row[0]

  #--------------------------------------------------------------------------------------- CRUD

  def insert(self, table:str, data:dict, returning:str|None=None) -> int|Any:
    """
    Insert single row.

    Args:
      table: Table name.
      data: Column-value dict.
      returning: Column to return (e.g., `"id"`).

    Returns:
      Row count, or returned column value if `returning` specified.
    """
    d = serialize_dict(data)
    t = ident(table)
    cols = ", ".join(ident(k) for k in d.keys())
    vals = ph(len(d), self.ph)
    if returning:
      sql = f"INSERT INTO {t} ({cols}) VALUES {vals} RETURNING {ident(returning)}"
      try:
        with self._scope(commit=True) as (_, cur, __):
          cur.execute(sql, tuple(d.values()))
          row = cur.fetchone()
          return row[0] if row else None
      except Exception as e:
        self._err("insert", e, sql, tuple(d.values()))
    return self.exec(f"INSERT INTO {t} ({cols}) VALUES {vals}", tuple(d.values()))

  def insert_many(self, table:str, rows:list[dict]) -> int:
    """Insert multiple rows. Returns affected row count."""
    if not rows: return 0
    rows2 = [serialize_dict(r) for r in rows]
    t = ident(table)
    cols = ", ".join(ident(k) for k in rows2[0].keys())
    vals = ph(len(rows2[0]), self.ph)
    return self.exec_many(
      f"INSERT INTO {t} ({cols}) VALUES {vals}",
      [tuple(r.values()) for r in rows2],
    )

  def update(self, table:str, data:dict, where:str, params=None) -> int:
    """Update rows matching WHERE clause. Returns affected row count."""
    d = serialize_dict(data)
    t, n = ident(table), len(d)
    phs = ph_list(n, self.ph)
    sets = ", ".join(f"{ident(k)} = {phs[i]}" for i, k in enumerate(d.keys()))
    p = tuple(d.values()) + serialize_params(params)
    return self.exec(f"UPDATE {t} SET {sets} WHERE {renum_ph(where, n)}", p)

  def delete(self, table:str, where:str, params=None) -> int:
    """Delete rows matching WHERE clause. Returns affected row count."""
    return self.exec(f"DELETE FROM {ident(table)} WHERE {where}", params)

  def count(self, table:str, where:str="1=1", params=None) -> int:
    """Count rows matching WHERE clause."""
    return self.get_value(f"SELECT COUNT(*) FROM {ident(table)} WHERE {where}", params) or 0

  def exists(self, table:str, where:str, params=None) -> bool:
    """Check if any row matches WHERE clause."""
    return self.get_value(f"SELECT 1 FROM {ident(table)} WHERE {where} LIMIT 1", params) is not None

  #------------------------------------------------------------------------------ Query Builder

  def find(self, table:str, order:str|None=None, limit:int|None=None, json:list[str]|None=None, **where) -> list[dict]:
    """
    Simple query builder with kwargs.

    Args:
      table: Table name.
      order: ORDER BY clause.
      limit: Max rows to return.
      json: Column names to parse as JSON.
      **where: Column=value conditions (AND).

    Returns:
      List of matching rows as dicts.

    Example:
      >>> db.find("users", active=True, role="admin")
      >>> db.find("users", order="created DESC", limit=10)
    """
    t = ident(table)
    sql = f"SELECT * FROM {t}"
    params = ()
    if where:
      phs = ph_list(len(where), self.ph)
      conds = " AND ".join(f"{ident(k)} = {phs[i]}" for i, k in enumerate(where.keys()))
      sql += f" WHERE {conds}"
      params = tuple(serialize_dict(where).values())
    if order: sql += f" ORDER BY {order}"
    if limit: sql += f" LIMIT {limit}"
    return self.get_dicts(sql, params, json=json)

  def find_one(self, table:str, json:list[str]|None=None, **where) -> dict|None:
    """Find single row by conditions."""
    rows = self.find(table, limit=1, json=json, **where)
    return rows[0] if rows else None

  def paginate(self, sql:str, params=None, page:int=1, per_page:int=20, json:list[str]|None=None) -> dict:
    """
    Paginate query results.

    Args:
      sql: Base SELECT statement (without LIMIT/OFFSET).
      params: Query parameters.
      page: Page number (1-based).
      per_page: Items per page.
      json: Column names to parse as JSON.

    Returns:
      Dict with `items`, `total`, `page`, `pages`.
    """
    offset = (page - 1) * per_page
    items = self.get_dicts(f"{sql} LIMIT {per_page} OFFSET {offset}", params, json=json)
    total = self.get_value(f"SELECT COUNT(*) FROM ({sql}) _c", params) or 0
    pages = (total + per_page - 1) // per_page if total else 0
    return {"items": items, "total": total, "page": page, "pages": pages}

  def upsert(self, table:str, data:dict, on:str|list[str], update:list[str]|None=None) -> int:
    """Insert or update on conflict. Override in subclasses."""
    raise NotImplementedError(f"upsert not implemented for {self.__class__.__name__}")

  #------------------------------------------------------------------------------------- Schema

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
