# xaeian/db/mysql.py

"""MySQL sync implementation."""
from __future__ import annotations

from typing import Any
from ..log import Logger, Print

from .abstract import AbstractDatabase
from .utils import _insert_sql, _upsert_sql

class MysqlDatabase(AbstractDatabase):
  """MySQL database (pymysql)."""
  def __init__(
    self,
    db_name:str|None = None,
    host:str = "localhost",
    user:str = "root",
    password:str = "",
    port:int = 3306,
    log:Logger|Print|None = None,
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
      database=self.db_name,
    )

  #----------------------------------------------------------------------------------------- Insert

  def insert(self, table:str, data:dict, returning:str|None=None) -> int|Any:
    """
    Insert single row.

    MySQL has no RETURNING: any truthy `returning` yields `lastrowid`, its column name ignored.
    """
    sql, params = _insert_sql(table, data, self.ph)
    if returning:
      try:
        with self._scope() as (_, cur, __):
          cur.execute(sql, params)
          return cur.lastrowid
      except Exception as e:
        self._err("insert", e, sql, params)
    return self.exec(sql, params)

  #----------------------------------------------------------------------------------------- Schema

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

  #----------------------------------------------------------------------------------------- Upsert

  def upsert(self, table:str, data:dict, on:str|list[str], update:list[str]|None=None) -> int:
    """
    INSERT ON DUPLICATE KEY UPDATE.

    MySQL matches on the table's own unique keys, so `on` names no conflict target here and
    only decides which columns the default `update` list leaves alone.
    """
    sql, params = _upsert_sql(table, data, on, update, self.ph, None)
    return self.exec(sql, params)

  #---------------------------------------------------------------------------- Database Management

  def create_database(self, name:str|None=None) -> bool:
    """Create database. Returns `False` if it already exists."""
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
    """Drop database and everything in it. Returns `False` if it does not exist."""
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