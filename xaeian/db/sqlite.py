# xaeian/db/sqlite.py

"""SQLite sync implementation."""
from __future__ import annotations

import os, sqlite3
from contextlib import contextmanager
from typing import Iterator
from ..log import Logger, Print

from .abstract import AbstractDatabase
from .utils import Params, iso_text, _upsert_sql

class SqliteDatabase(AbstractDatabase):
  """
  SQLite database. `db_name` is a file path or `":memory:"`.

  `insert(..., returning=)` needs SQLite 3.35+ for the `RETURNING` clause.
  Every call outside a transaction opens its own connection,
  so `":memory:"` starts empty each time and keeps data only for the span of one `transaction()`.
  Foreign keys are enforced on every connection, as MySQL and PostgreSQL enforce them,
  and a `datetime` is stored as ISO text.
  """
  def __init__(self, db_name:str, log:Logger|Print|None=None) -> None:
    super().__init__()
    self.db_name:str = db_name
    self.log = log

  def conn(self) -> sqlite3.Connection:
    conn = sqlite3.connect(self.db_name)
    conn.execute("PRAGMA foreign_keys = ON") # off by default, per connection
    return conn

  def _params(self, params:Params) -> tuple:
    """Dates as ISO text: sqlite3 deprecated its own date adapter in Python 3.12."""
    return tuple(iso_text(v) for v in super()._params(params))

  #------------------------------------------------------------------------------------ Transaction

  @contextmanager
  def transaction(self) -> Iterator[SqliteDatabase]:
    with super().transaction():
      self._cur.execute("BEGIN") # driver opens one only for DML, leaving DDL outside
      yield self

  #----------------------------------------------------------------------------------------- Schema

  def has_table(self, name:str) -> bool:
    return self.get_value(
      "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", name,
    ) is not None

  def tables(self) -> list[str]:
    return self.get_column("SELECT name FROM sqlite_master WHERE type='table'")

  def has_database(self, name:str|None=None) -> bool:
    """Check the database file exists on disk; `":memory:"` is never a file, so `False`."""
    n = name or self.db_name
    return os.path.isfile(n) if n else False

  #----------------------------------------------------------------------------------------- Upsert

  def upsert(self, table:str, data:dict, on:str|list[str], update:list[str]|None=None) -> int:
    """INSERT ON CONFLICT (SQLite 3.24+). `on` must be a UNIQUE or PRIMARY KEY column set."""
    sql, params = _upsert_sql(table, data, on, update, self.excluded)
    return self.exec(sql, params)

  #---------------------------------------------------------------------------- Database Management

  def create_database(self, name:str|None=None) -> bool:
    """Create database file. Returns `False` if it already exists."""
    if self.in_transaction(): raise RuntimeError("create_database() not allowed in transaction")
    n = name or self.db_name
    if not n: raise ValueError("db_name required")
    if self.has_database(n): return False
    sqlite3.connect(n).close()
    return True

  def drop_database(self, name:str|None=None) -> bool:
    """Delete database file. Returns `False` if it does not exist."""
    if self.in_transaction(): raise RuntimeError("drop_database() not allowed in transaction")
    n = name or self.db_name
    if not n: raise ValueError("db_name required")
    if not self.has_database(n): return False
    try:
      os.remove(n)
      return True
    except OSError as e:
      self._err("drop_database", e)