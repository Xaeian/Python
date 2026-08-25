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

from enum import Enum
from ..log import Logger, Print
from .errors import DatabaseError
from .abstract import AbstractDatabase
from .abstract_async import AbstractAsyncDatabase
from .sqlite import SqliteDatabase
from .mysql import MysqlDatabase
from .postgres import PostgresDatabase
from .sqlite_async import SqliteAsyncDatabase
from .mysql_async import MysqlAsyncDatabase
from .postgres_async import PostgresAsyncDatabase
from .kv import KeyValue
from .kv_async import AsyncKeyValue
from .kv_common import KvEntry
from .utils import (
  ident, ph, to_dicts, serialize, serialize_params, serialize_dict,
  split_sql, norm, parse_json, parse_row,
)

class DatabaseType(str, Enum):
  """Supported database types."""
  sqlite = "sqlite"
  mysql = "mysql"
  postgres = "postgres"

# A backend module pulls in no driver: every one of them imports its driver inside `conn()`,
# so a missing psycopg2 surfaces on connect, not on `import xaeian.db`.
_SYNC = {
  "sqlite": SqliteDatabase,
  "mysql": MysqlDatabase,
  "postgres": PostgresDatabase,
}

_ASYNC = {
  "sqlite": SqliteAsyncDatabase,
  "mysql": MysqlAsyncDatabase,
  "postgres": PostgresAsyncDatabase,
}

_PORTS = {"mysql": 3306, "postgres": 5432}
_USERS = {"mysql": "root", "postgres": "postgres"}

def _norm(backend:str|DatabaseType) -> str:
  return backend.value if isinstance(backend, DatabaseType) else str(backend).strip().lower()

#------------------------------------------------------------------------------------------ Factory

def Database(
  backend:str|DatabaseType,
  db_name:str|None = None,
  host:str = "localhost",
  user:str|None = None,
  password:str = "",
  port:int|None = None,
  log:Logger|Print|None = None,
) -> AbstractDatabase:
  """
  Create sync database instance.

  For SQLite `db_name` is the file path and host/user/password are ignored;
  when omitted it is `":memory:"`, which only holds data for the span of one `transaction()`.
  Default port 3306 MySQL / 5432 PostgreSQL, default user `root` / `postgres`.
  """
  name = _norm(backend)
  if name not in _SYNC: raise ValueError(f"Unknown database type: {backend!r}")
  cls = _SYNC[name]
  if name == "sqlite": return cls(db_name or ":memory:", log=log)
  return cls(db_name, host, user or _USERS[name], password, port or _PORTS[name], log=log)

def AsyncDatabase(
  backend:str|DatabaseType,
  db_name:str|None = None,
  host:str = "localhost",
  user:str|None = None,
  password:str = "",
  port:int|None = None,
  log:Logger|Print|None = None,
) -> AbstractAsyncDatabase:
  """Create async database instance, arguments as in `Database`."""
  name = _norm(backend)
  if name not in _ASYNC: raise ValueError(f"Unknown database type: {backend!r}")
  cls = _ASYNC[name]
  if name == "sqlite": return cls(db_name or ":memory:", log=log)
  return cls(db_name, host, user or _USERS[name], password, port or _PORTS[name], log=log)

#------------------------------------------------------------------------------------------ Exports

__all__ = [
  "Database", "AsyncDatabase", "DatabaseType", "DatabaseError",
  "AbstractDatabase", "AbstractAsyncDatabase",
  "SqliteDatabase", "MysqlDatabase", "PostgresDatabase",
  "SqliteAsyncDatabase", "MysqlAsyncDatabase", "PostgresAsyncDatabase",
  "KeyValue", "AsyncKeyValue", "KvEntry",
  "ident", "ph", "to_dicts", "serialize", "serialize_params", "serialize_dict",
  "split_sql", "norm", "parse_json", "parse_row",
]
