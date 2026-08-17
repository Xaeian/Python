# xaeian/db/__init__.py

"""
Lightweight database abstraction layer.

SQLite, MySQL, PostgreSQL behind one sync and one async interface.
Auto-converts: `dict`/`list` → JSON, ISO datetime → `datetime` object.
All driver/SQL errors raise `DatabaseError`.

Example:
  >>> db = Database("sqlite", "app.db")
  >>> db.insert("users", {"name": "Jan"})
  >>> user = db.find_one("users", name="Jan")
  >>> with db.transaction():
  ...   db.update("users", {"balance": 0}, "id = ?", user["id"])

Async:
  >>> db = AsyncDatabase("postgres", "app", user="postgres", password="pass")
  >>> async with db.transaction():
  ...   await db.insert("users", {"name": "Jan"})
"""

from __future__ import annotations

__extras__ = {
  "db": ["pymysql", "psycopg2-binary"],
  "db-async": ["aiomysql", "asyncpg", "aiosqlite"],
}

import importlib
from enum import Enum
from typing import TYPE_CHECKING
from ..log import Logger, Print

class DatabaseType(str, Enum):
  """Supported database types."""
  sqlite = "sqlite"
  mysql = "mysql"
  postgres = "postgres"

_SYNC = {
  "sqlite": (".sqlite", "SqliteDatabase"),
  "mysql": (".mysql", "MysqlDatabase"),
  "postgres": (".postgres", "PostgresDatabase"),
}

_ASYNC = {
  "sqlite": (".sqlite_async", "SqliteAsyncDatabase"),
  "mysql": (".mysql_async", "MysqlAsyncDatabase"),
  "postgres": (".postgres_async", "PostgresAsyncDatabase"),
}

_PORTS = {"mysql": 3306, "postgres": 5432}

def _norm(t:str|DatabaseType) -> str:
  return t.value if isinstance(t, DatabaseType) else str(t).strip().lower()

def _load(mapping:dict, key:str):
  mod_name, cls_name = mapping[key]
  mod = importlib.import_module(mod_name, __name__)
  return getattr(mod, cls_name)

#------------------------------------------------------------------------------------------ Factory

def Database(
  type:str|DatabaseType,
  db_name:str|None = None,
  host:str = "localhost",
  user:str|None = None,
  password:str = "",
  port:int|None = None,
  log:Logger|Print|None = None,
):
  """
  Create sync database instance.

  For SQLite `db_name` is the file path and host/user/password are ignored; when omitted it is
  `":memory:"`, which only holds data for the span of one `transaction()`. Default port 3306
  MySQL / 5432 PostgreSQL, default user `root` / `postgres`.
  """
  t = _norm(type)
  if t not in _SYNC: raise ValueError(f"Unknown database type: {type!r}")
  cls = _load(_SYNC, t)
  if t == "sqlite": return cls(db_name or ":memory:", log=log)
  user = user or ("postgres" if t == "postgres" else "root")
  return cls(db_name, host, user, password, port or _PORTS[t], log=log)

def AsyncDatabase(
  type:str|DatabaseType,
  db_name:str|None = None,
  host:str = "localhost",
  user:str|None = None,
  password:str = "",
  port:int|None = None,
  log:Logger|Print|None = None,
):
  """Create async database instance, arguments as in `Database`."""
  t = _norm(type)
  if t not in _ASYNC: raise ValueError(f"Unknown database type: {type!r}")
  cls = _load(_ASYNC, t)
  if t == "sqlite": return cls(db_name or ":memory:", log=log)
  user = user or ("postgres" if t == "postgres" else "root")
  return cls(db_name, host, user, password, port or _PORTS[t], log=log)

#------------------------------------------------------------------------------------------ Exports

from .errors import DatabaseError
from .utils import (
  ident, ph, to_dicts, serialize, serialize_params, serialize_dict,
  split_sql, norm, parse_json, parse_row,
)
from .kv_common import KvEntry

__all__ = [
  "Database", "AsyncDatabase", "DatabaseType", "DatabaseError",
  "ident", "ph", "to_dicts", "serialize", "serialize_params", "serialize_dict",
  "split_sql", "norm", "parse_json", "parse_row", "KvEntry",
]

#------------------------------------------------------------------------------------- Lazy Imports

_LAZY = {
  "PostgresDatabase": (".postgres", "PostgresDatabase"),
  "PostgresAsyncDatabase": (".postgres_async", "PostgresAsyncDatabase"),
  "MysqlDatabase": (".mysql", "MysqlDatabase"),
  "MysqlAsyncDatabase": (".mysql_async", "MysqlAsyncDatabase"),
  "SqliteDatabase": (".sqlite", "SqliteDatabase"),
  "SqliteAsyncDatabase": (".sqlite_async", "SqliteAsyncDatabase"),
  "KeyValue": (".kv", "KeyValue"),
  "AsyncKeyValue": (".kv_async", "AsyncKeyValue"),
}

if TYPE_CHECKING:
  from .postgres import PostgresDatabase
  from .postgres_async import PostgresAsyncDatabase
  from .mysql import MysqlDatabase
  from .mysql_async import MysqlAsyncDatabase
  from .sqlite import SqliteDatabase
  from .sqlite_async import SqliteAsyncDatabase
  from .kv import KeyValue
  from .kv_async import AsyncKeyValue

def __getattr__(name:str):
  if name not in _LAZY: raise AttributeError(f"module 'xaeian.db' has no attribute {name!r}")
  return _load(_LAZY, name)

__all__ += list(_LAZY.keys())