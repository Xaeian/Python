# xaeian/db/__init__.py

"""
Lightweight database abstraction layer.

Supports SQLite, MySQL, PostgreSQL with sync and async interfaces.
Auto-converts: `dict`/`list` → JSON, ISO datetime → `datetime` object.
All driver/SQL errors raise `DatabaseError`.

Example:
  >>> from xaeian.db import Database
  >>> db = Database("sqlite", "app.db")
  >>> db.exec("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
  >>> db.insert("users", {"name": "Jan"})
  >>> user = db.find_one("users", name="Jan")

Transaction:
  >>> with db.transaction():
  ...   db.insert("orders", {"user_id": 1, "total": 99.50})
  ...   db.update("users", {"balance": 0}, "id = ?", user_id)

Async:
  >>> from xaeian.db import AsyncDatabase
  >>> db = AsyncDatabase("postgres", "app", user="postgres", password="pass")
  >>> async with db.transaction():
  ...   await db.insert("users", {"name": "Jan"})
"""
from __future__ import annotations

import importlib
from enum import Enum
from typing import TYPE_CHECKING
from logging import Logger

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

def _load(mapping:dict, t:str):
  mod_name, cls_name = mapping[t]
  mod = importlib.import_module(mod_name, __name__)
  return getattr(mod, cls_name)

#-------------------------------------------------------------------------------------- Factory

def Database(
  type: str|DatabaseType,
  db_name: str|None = None,
  host: str = "localhost",
  user: str = "root",
  password: str = "",
  port: int|None = None,
  log: Logger|None = None,
):
  """
  Create sync database instance.

  Args:
    type: Database type (`"sqlite"`, `"mysql"`, `"postgres"`).
    db_name: Database name or file path (SQLite).
    host: Server hostname (ignored for SQLite).
    user: Username (ignored for SQLite).
    password: Password (ignored for SQLite).
    port: Server port (default: 3306 for MySQL, 5432 for PostgreSQL).
    log: Logger for error logging.

  Returns:
    Database instance (`SqliteDatabase`, `MysqlDatabase`, `PostgresDatabase`).

  Example:
    >>> db = Database("sqlite", "app.db")
    >>> db = Database("mysql", "mydb", user="root", password="secret")
    >>> db = Database("postgres", "mydb", user="postgres", password="secret")
  """
  t = _norm(type)
  if t not in _SYNC: raise ValueError(f"Unknown database type: {type!r}")
  cls = _load(_SYNC, t)
  if t == "sqlite": return cls(db_name or ":memory:")
  return cls(db_name, host, user, password, port or _PORTS[t], log=log)

def AsyncDatabase(
  type: str|DatabaseType,
  db_name: str|None = None,
  host: str = "localhost",
  user: str = "root",
  password: str = "",
  port: int|None = None,
  log: Logger|None = None,
):
  """
  Create async database instance.

  Args:
    type: Database type (`"sqlite"`, `"mysql"`, `"postgres"`).
    db_name: Database name or file path (SQLite).
    host: Server hostname (ignored for SQLite).
    user: Username (ignored for SQLite).
    password: Password (ignored for SQLite).
    port: Server port (default: 3306 for MySQL, 5432 for PostgreSQL).
    log: Logger for error logging.

  Returns:
    Async database instance.

  Example:
    >>> db = AsyncDatabase("postgres", "mydb", user="postgres", password="secret")
    >>> users = await db.get_dicts("SELECT * FROM users")
  """
  t = _norm(type)
  if t not in _ASYNC: raise ValueError(f"Unknown database type: {type!r}")
  cls = _load(_ASYNC, t)
  if t == "sqlite": return cls(db_name or ":memory:")
  return cls(db_name, host, user, password, port or _PORTS[t], log=log)

#-------------------------------------------------------------------------------------- Exports

from .errors import DatabaseError
from .utils import (
  ident, ph, to_dicts, serialize, serialize_params, serialize_dict,
  split_sql, norm, parse_json, parse_row
)

__all__ = [
  "Database", "AsyncDatabase", "DatabaseType", "DatabaseError",
  "ident", "ph", "to_dicts", "serialize", "serialize_params", "serialize_dict",
  "split_sql", "norm", "parse_json", "parse_row",
]

#--------------------------------------------------------------------------------- Lazy Imports

_LAZY = {
  "PostgresDatabase": (".postgres", "PostgresDatabase"),
  "PostgresAsyncDatabase": (".postgres_async", "PostgresAsyncDatabase"),
  "MysqlDatabase": (".mysql", "MysqlDatabase"),
  "MysqlAsyncDatabase": (".mysql_async", "MysqlAsyncDatabase"),
  "SqliteDatabase": (".sqlite", "SqliteDatabase"),
  "SqliteAsyncDatabase": (".sqlite_async", "SqliteAsyncDatabase"),
}

if TYPE_CHECKING:
  from .postgres import PostgresDatabase
  from .postgres_async import PostgresAsyncDatabase
  from .mysql import MysqlDatabase
  from .mysql_async import MysqlAsyncDatabase
  from .sqlite import SqliteDatabase
  from .sqlite_async import SqliteAsyncDatabase

def __getattr__(name:str):
  if name not in _LAZY:
    raise AttributeError(f"module 'xaeian.db' has no attribute {name!r}")
  mod_name, cls_name = _LAZY[name]
  mod = importlib.import_module(mod_name, __name__)
  return getattr(mod, cls_name)

__all__ += list(_LAZY.keys())
