# xaeian/db/mysql.py

"""MySQL sync implementation."""
from __future__ import annotations

from typing import Any
from ..log import Logger, Print

from .abstract import AbstractDatabase
from .utils import _insert_sql, _upsert_sql

class MysqlDatabase(AbstractDatabase):
  """MySQL database (pymysql)."""
  style = "%s"
  quote = "`"
  excluded = None

  def __init__(
    self,
    db_name:str|None = None,
    host:str = "localhost",
    user:str = "root",
    password:str = "",
    port:int = 3306,
    log:Logger|Print|None = None,
  ) -> None:
    super().__init__()
    self.host = host
    self.port = port
    self.user = user
    self.password = password
    self.db_name = db_name
    self.log = log

  def conn(self) -> Any:
    import pymysql
    return pymysql.connect(
      host=self.host, port=self.port,
      user=self.user, password=self.password,
      database=self.db_name,
    )

  #----------------------------------------------------------------------------------------- Insert

  def insert(self, table:str, data:dict, returning:str|None=None) -> Any:
    """
    Insert single row.

    MySQL has no RETURNING: any truthy `returning` yields `lastrowid`, its column name ignored.
    """
    sql, params = _insert_sql(table, data)
    if returning:
      try:
        with self._scope() as (_, cur, __):
          cur.execute(self._sql(sql), params)
          return cur.lastrowid
      except Exception as e:
        self._err("insert", e, sql, params)
    return self.exec(sql, params)

  def _admin_conn(self):
    """
    Standalone connection bound to no database, for `CREATE`/`DROP DATABASE`.

    Admin work never borrows `self.db_name`, so a failure cannot leave the object aimed elsewhere.
    """
    import pymysql
    return pymysql.connect(
      host=self.host, port=self.port,
      user=self.user, password=self.password,
    )

  #----------------------------------------------------------------------------------------- Schema

  def has_table(self, name:str) -> bool:
    return self.get_value(
      "SELECT 1 FROM information_schema.tables WHERE table_name=? AND table_schema=?",
      (name, self.db_name),
    ) is not None

  def tables(self) -> list[str]:
    return self.get_column(
      "SELECT table_name FROM information_schema.tables WHERE table_schema=?",
      self.db_name,
    )

  def has_database(self, name:str|None=None) -> bool:
    """Check if database exists, asked over a connection bound to no database."""
    import pymysql
    name = name or self.db_name
    if not name: return False
    conn = self._admin_conn()
    try:
      with conn.cursor() as cur:
        cur.execute("SHOW DATABASES")
        return name in [row[0] for row in cur.fetchall()]
    except pymysql.Error as e:
      self._err("has_database", e)
    finally:
      conn.close()

  #----------------------------------------------------------------------------------------- Upsert

  def upsert(self, table:str, data:dict, on:str|list[str], update:list[str]|None=None) -> int:
    """
    INSERT ON DUPLICATE KEY UPDATE.

    MySQL matches on the table's own unique keys, so `on` names no conflict target here.
    It only decides which columns the default `update` list leaves alone.
    """
    sql, params = _upsert_sql(table, data, on, update, self.excluded)
    return self.exec(sql, params)

  #---------------------------------------------------------------------------- Database Management

  def create_database(self, name:str|None=None) -> bool:
    """Create database. Returns `False` if it already exists."""
    if self.in_transaction(): raise RuntimeError("create_database() not allowed in transaction")
    name = name or self.db_name
    name = self._valid_db(name)
    if self.has_database(name): return False
    import pymysql
    conn = self._admin_conn()
    try:
      with conn.cursor() as cur:
        cur.execute(f"CREATE DATABASE `{name}`")
      conn.commit()
      return True
    except pymysql.Error as e:
      self._err("create_database", e)
    finally:
      conn.close()

  def drop_database(self, name:str|None=None) -> bool:
    """Drop database and everything in it. Returns `False` if it does not exist."""
    if self.in_transaction(): raise RuntimeError("drop_database() not allowed in transaction")
    name = name or self.db_name
    name = self._valid_db(name)
    if not self.has_database(name): return False
    import pymysql
    conn = self._admin_conn()
    try:
      with conn.cursor() as cur:
        cur.execute(f"DROP DATABASE `{name}`")
      conn.commit()
      return True
    except pymysql.Error as e:
      self._err("drop_database", e)
    finally:
      conn.close()