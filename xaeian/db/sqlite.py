# xaeian/db/sqlite.py

"""SQLite sync implementation."""
from __future__ import annotations

import os
import sqlite3
from logging import Logger

from .abstract import AbstractDatabase
from .utils import serialize_dict, ident, ph

class SqliteDatabase(AbstractDatabase):
  """
  SQLite database.

  Uses `RETURNING` clause (SQLite 3.35+).

  Args:
    db_name: Database file path or `":memory:"`.
    log: Logger instance for error logging.

  Example:
    >>> db = SqliteDatabase("app.db")
    >>> db = SqliteDatabase(":memory:")
  """
  def __init__(self, db_name:str, log:Logger|None=None):
    super().__init__()
    self.db_name = db_name
    self.log = log

  def conn(self):
    return sqlite3.connect(self.db_name)

  #------------------------------------------------------------------------------------- Schema

  def has_table(self, name:str) -> bool:
    return self.get_value(
      "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", name
    ) is not None

  def tables(self) -> list[str]:
    return self.get_column("SELECT name FROM sqlite_master WHERE type='table'")

  def has_database(self, name:str|None=None) -> bool:
    n = name or self.db_name
    return os.path.isfile(n) if n else False

  #------------------------------------------------------------------------------------- Upsert

  def upsert(self, table:str, data:dict, on:str|list[str], update:list[str]|None=None) -> int:
    """
    INSERT ON CONFLICT (SQLite 3.24+).

    Args:
      table: Table name.
      data: Column-value dict.
      on: Conflict column(s).
      update: Columns to update on conflict (default: all except `on`).

    Returns:
      Affected row count.
    """
    d = serialize_dict(data)
    t = ident(table)
    cols = ", ".join(ident(k) for k in d.keys())
    vals = ph(len(d), self.ph)
    conf = on if isinstance(on, str) else ", ".join(on)
    upd_cols = update or [k for k in d.keys() if k not in (on if isinstance(on, list) else [on])]
    sets = ", ".join(f"{ident(k)} = excluded.{ident(k)}" for k in upd_cols)
    sql = f"INSERT INTO {t} ({cols}) VALUES {vals} ON CONFLICT ({conf}) DO UPDATE SET {sets}"
    return self.exec(sql, tuple(d.values()))

  #------------------------------------------------------------------------ Database Management

  def create_database(self, name:str|None=None) -> bool:
    """Create database file. Returns `False` if already exists."""
    if self.in_transaction(): raise RuntimeError("create_database() not allowed in transaction")
    n = name or self.db_name
    if not n: raise ValueError("db_name required")
    if self.has_database(n): return False
    sqlite3.connect(n).close()
    return True

  def drop_database(self, name:str|None=None) -> bool:
    """Delete database file. Returns `False` if not exists."""
    if self.in_transaction(): raise RuntimeError("drop_database() not allowed in transaction")
    n = name or self.db_name
    if not n: raise ValueError("db_name required")
    if not self.has_database(n): return False
    try:
      os.remove(n)
      return True
    except OSError as e:
      self._err("drop_database", e)
