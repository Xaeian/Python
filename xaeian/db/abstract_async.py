# xaeian/db/abstract_async.py

"""Async database base class."""
from __future__ import annotations

from abc import ABC, abstractmethod
from logging import Logger
from typing import NoReturn, Any

from .errors import DatabaseError
from .utils import ident, ph, ph_list, renum_ph, serialize_params, serialize_dict, parse_json, parse_row

class AbstractAsyncDatabase(ABC):
  """
  Async database base class.

  Auto-commits per call, or batch operations in `transaction()`.

  Example:
    >>> await db.exec("INSERT INTO users (name) VALUES (?)", ("Jan",))
    >>> async with db.transaction():
    ...   await db.insert("orders", {"user_id": 1, "total": 99.50})
    ...   await db.update("users", {"balance": 0}, "id = ?", user_id)
  """

  def __init__(self):
    self.db_name: str|None = None
    self.log: Logger|None = None
    self.debug: bool = False
    self.ph = "?"
    self._conn = None

  def __repr__(self):
    return f"<{self.__class__.__name__} db={self.db_name!r}>"

  def in_transaction(self) -> bool:
    """Check if transaction is active."""
    return self._conn is not None

  async def ping(self) -> bool:
    """Check if database is reachable."""
    try:
      await self.get_value("SELECT 1")
      return True
    except DatabaseError:
      return False

  def _debug(self, op:str, sql:str, params:tuple):
    s = " ".join(sql.split())[:100]
    print(f"[{self.db_name or 'db'}] {op}: {s} {params if params else ''}")

  def _err(self, op:str, exc:Exception, sql:str|None=None, params:tuple|None=None) -> NoReturn:
    err = DatabaseError(op, exc, sql=sql, params=params)
    if self.log: self.log.error(f"[{self.db_name or 'db'}] {err}")
    raise err from exc

  @abstractmethod
  async def conn(self):
    """Create new database connection."""
    raise NotImplementedError

  @abstractmethod
  def transaction(self):
    """Transaction context manager."""
    raise NotImplementedError

  #------------------------------------------------------------------------------------ Execute

  @abstractmethod
  async def exec(self, sql:str, params=None) -> int:
    """Execute SQL statement. Returns affected row count."""
    raise NotImplementedError

  @abstractmethod
  async def exec_many(self, sql:str, params_list:list) -> int:
    """Execute statement with multiple parameter sets."""
    raise NotImplementedError

  @abstractmethod
  async def exec_batch(self, sqls:list[tuple[str, Any]]|list[str]|str) -> int:
    """Execute multiple statements in one transaction."""
    raise NotImplementedError

  #-------------------------------------------------------------------------------------- Query

  @abstractmethod
  async def get_rows(self, sql:str, params=None, json:list[int]|None=None) -> list[list]:
    """Fetch all rows as lists."""
    raise NotImplementedError

  @abstractmethod
  async def get_dicts(self, sql:str, params=None, cols:list[str]|None=None, json:list[str]|None=None) -> list[dict]:
    """Fetch all rows as dicts."""
    raise NotImplementedError

  async def get_row(self, sql:str, params=None, json:list[int]|None=None) -> list|None:
    """Fetch single row as list."""
    rows = await self.get_rows(sql, params, json=json)
    return rows[0] if rows else None

  async def get_dict(self, sql:str, params=None, json:list[str]|None=None) -> dict|None:
    """Fetch single row as dict."""
    rows = await self.get_dicts(sql, params, json=json)
    return rows[0] if rows else None

  async def get_column(self, sql:str, params=None, json:bool=False) -> list:
    """Fetch first column of all rows."""
    rows = await self.get_rows(sql, params)
    if not rows: return []
    col = [r[0] for r in rows]
    return [parse_json(v) for v in col] if json else col

  async def get_value(self, sql:str, params=None, json:bool=False) -> Any:
    """Fetch single value."""
    row = await self.get_row(sql, params)
    if not row: return None
    return parse_json(row[0]) if json else row[0]

  #--------------------------------------------------------------------------------------- CRUD

  async def insert(self, table:str, data:dict, returning:str|None=None) -> int|Any:
    """Insert single row. Returns row count or returned column value."""
    d = serialize_dict(data)
    t = ident(table)
    cols = ", ".join(ident(k) for k in d.keys())
    vals = ph(len(d), self.ph)
    if returning: return await self._insert_returning(table, data, returning)
    return await self.exec(f"INSERT INTO {t} ({cols}) VALUES {vals}", tuple(d.values()))

  @abstractmethod
  async def _insert_returning(self, table:str, data:dict, ret:str) -> Any:
    raise NotImplementedError

  async def insert_many(self, table:str, rows:list[dict]) -> int:
    """Insert multiple rows. Returns affected row count."""
    if not rows: return 0
    rows2 = [serialize_dict(r) for r in rows]
    t = ident(table)
    cols = ", ".join(ident(k) for k in rows2[0].keys())
    vals = ph(len(rows2[0]), self.ph)
    return await self.exec_many(
      f"INSERT INTO {t} ({cols}) VALUES {vals}",
      [tuple(r.values()) for r in rows2],
    )

  async def update(self, table:str, data:dict, where:str, params=None) -> int:
    """Update rows matching WHERE clause. Returns affected row count."""
    d = serialize_dict(data)
    t, n = ident(table), len(d)
    phs = ph_list(n, self.ph)
    sets = ", ".join(f"{ident(k)} = {phs[i]}" for i, k in enumerate(d.keys()))
    p = tuple(d.values()) + serialize_params(params)
    return await self.exec(f"UPDATE {t} SET {sets} WHERE {renum_ph(where, n)}", p)

  async def delete(self, table:str, where:str, params=None) -> int:
    """Delete rows matching WHERE clause. Returns affected row count."""
    return await self.exec(f"DELETE FROM {ident(table)} WHERE {where}", params)

  async def count(self, table:str, where:str="1=1", params=None) -> int:
    """Count rows matching WHERE clause."""
    return await self.get_value(f"SELECT COUNT(*) FROM {ident(table)} WHERE {where}", params) or 0

  async def exists(self, table:str, where:str, params=None) -> bool:
    """Check if any row matches WHERE clause."""
    return await self.get_value(f"SELECT 1 FROM {ident(table)} WHERE {where} LIMIT 1", params) is not None

  #------------------------------------------------------------------------------ Query Builder

  async def find(self, table:str, order:str|None=None, limit:int|None=None, json:list[str]|None=None, **where) -> list[dict]:
    """Simple query builder with kwargs."""
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
    return await self.get_dicts(sql, params, json=json)

  async def find_one(self, table:str, json:list[str]|None=None, **where) -> dict|None:
    """Find single row by conditions."""
    rows = await self.find(table, limit=1, json=json, **where)
    return rows[0] if rows else None

  async def paginate(self, sql:str, params=None, page:int=1, per_page:int=20, json:list[str]|None=None) -> dict:
    """Paginate query results."""
    offset = (page - 1) * per_page
    items = await self.get_dicts(f"{sql} LIMIT {per_page} OFFSET {offset}", params, json=json)
    total = await self.get_value(f"SELECT COUNT(*) FROM ({sql}) _c", params) or 0
    pages = (total + per_page - 1) // per_page if total else 0
    return {"items": items, "total": total, "page": page, "pages": pages}

  async def upsert(self, table:str, data:dict, on:str|list[str], update:list[str]|None=None) -> int:
    """Insert or update on conflict. Override in subclasses."""
    raise NotImplementedError(f"upsert not implemented for {self.__class__.__name__}")

  #------------------------------------------------------------------------------------- Schema

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

  def _valid_db(self, name:str):
    if not name or not name.replace("_", "").isalnum():
      raise ValueError(f"Invalid database name: {name!r}")
