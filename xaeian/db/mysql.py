# xaeian/db/mysql.py

"""MySQL sync implementation."""
from __future__ import annotations

from typing import Any
from logging import Logger

from .abstract import AbstractDatabase
from .utils import ident, ph, serialize_dict


class MysqlDatabase(AbstractDatabase):
  """
  MySQL database (pymysql).

  Uses `lastrowid` for `insert(..., returning=)`.

  Args:
    db_name: Database name.
    host: Server hostname.
    user: Username.
    password: Password.
    port: Server port.
    log: Logger instance.

  Example:
    >>> db = MysqlDatabase("mydb", user="root", password="secret")
    >>> db.insert("users", {"name": "Jan"})
  """
  def __init__(
    self,
    db_name: str|None = None,
    host: str = "localhost",
    user: str = "root",
    password: str = "",
    port: int = 3306,
    log: Logger|None = None,
  ):
    super().__init__()
    self.host = host
    self.port = port
    self.user = user
    self.password = password
    self.db_name = db_name
    self.ph = "%s"
    self.log = log

  def conn(self):
    import pymysql
    return pymysql.connect(
      host=self.host, port=self.port,
      user=self.user, password=self.password,
      database=self.db_name
    )

  #------------------------------------------------------------------------------------- Insert

  def insert(self, table:str, data:dict, returning:str|None=None) -> int|Any:
    """Insert row. MySQL uses `lastrowid` for returning (ignores column name)."""
    d = serialize_dict(data)
    t = ident(table)
    cols = ", ".join(ident(k) for k in d.keys())
    vals = ph(len(d), self.ph)
    sql = f"INSERT INTO {t} ({cols}) VALUES {vals}"
    if returning:
      try:
        with self._scope(commit=True) as (_, cur, __):
          cur.execute(sql, tuple(d.values()))
          return cur.lastrowid
      except Exception as e:
        self._err("insert", e, sql, tuple(d.values()))
    return self.exec(sql, tuple(d.values()))

  #------------------------------------------------------------------------------------- Schema

  def has_table(self, name:str) -> bool:
    return self.get_value(
      "SELECT 1 FROM information_schema.tables WHERE table_name=%s AND table_schema=%s",
      (name, self.db_name),
    ) is not None

  def tables(self) -> list[str]:
    return self.get_column(
      "SELECT table_name FROM information_schema.tables WHERE table_schema=%s",
      self.db_name,
    )

  def has_database(self, name:str|None=None) -> bool:
    name = name or self.db_name
    if not name: return False
    return name in self.get_column("SHOW DATABASES")

  #------------------------------------------------------------------------------------- Upsert

  def upsert(self, table:str, data:dict, on:str|list[str], update:list[str]|None=None) -> int:
    """INSERT ON DUPLICATE KEY UPDATE. `on` param ignored — uses table's unique keys."""
    d = serialize_dict(data)
    t = ident(table)
    cols = ", ".join(ident(k) for k in d.keys())
    vals = ph(len(d), self.ph)
    upd_cols = update or [k for k in d.keys() if k not in (on if isinstance(on, list) else [on])]
    sets = ", ".join(f"{ident(k)} = VALUES({ident(k)})" for k in upd_cols)
    sql = f"INSERT INTO {t} ({cols}) VALUES {vals} ON DUPLICATE KEY UPDATE {sets}"
    return self.exec(sql, tuple(d.values()))

  #------------------------------------------------------------------------ Database Management

  def create_database(self, name:str|None=None) -> bool:
    if self.in_transaction(): raise RuntimeError("create_database() not allowed in transaction")
    name = name or self.db_name
    self._valid_db(name)
    if self.has_database(name): return False
    backup, self.db_name = self.db_name, None
    try:
      self.exec(f"CREATE DATABASE `{name}`")
      return True
    finally:
      self.db_name = backup

  def drop_database(self, name:str|None=None) -> bool:
    if self.in_transaction(): raise RuntimeError("drop_database() not allowed in transaction")
    name = name or self.db_name
    self._valid_db(name)
    if not self.has_database(name): return False
    backup, self.db_name = self.db_name, None
    try:
      self.exec(f"DROP DATABASE `{name}`")
      return True
    finally:
      self.db_name = backup
