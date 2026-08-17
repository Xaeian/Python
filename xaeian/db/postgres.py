# xaeian/db/postgres.py

"""PostgreSQL sync implementation."""
from __future__ import annotations

from ..log import Logger, Print

from .abstract import AbstractDatabase
from .utils import _upsert_sql

class PostgresDatabase(AbstractDatabase):
  """PostgreSQL database (psycopg2). `insert(..., returning=)` uses a `RETURNING` clause."""
  def __init__(
    self,
    db_name:str|None = None,
    host:str = "localhost",
    user:str = "postgres",
    password:str = "",
    port:int = 5432,
    log:Logger|Print|None = None,
  ):
    super().__init__()
    self.host = host
    self.port = port
    self.user = user
    self.password = password
    self.db_name = db_name
    self.log = log
    self.ph = "%s"

  def conn(self):
    import psycopg2
    return psycopg2.connect(
      host=self.host, port=self.port,
      user=self.user, password=self.password,
      dbname=self.db_name,
    )

  #----------------------------------------------------------------------------------------- Schema

  def has_table(self, name:str) -> bool:
    return self.get_value(
      "SELECT 1 FROM information_schema.tables WHERE table_name=%s AND table_schema='public'",
      name,
    ) is not None

  def tables(self) -> list[str]:
    return self.get_column(
      "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
    )

  def has_database(self, name:str|None=None) -> bool:
    """Check if database exists. Queries through the `postgres` maintenance database."""
    name = name or self.db_name
    if not name: return False
    backup, self.db_name = self.db_name, "postgres"
    try:
      return self.get_value("SELECT 1 FROM pg_database WHERE datname=%s", name) is not None
    finally:
      self.db_name = backup

  #----------------------------------------------------------------------------------------- Upsert

  def upsert(self, table:str, data:dict, on:str|list[str], update:list[str]|None=None) -> int:
    """INSERT ON CONFLICT (PostgreSQL 9.5+). `on` must be a UNIQUE or PRIMARY KEY column set."""
    sql, params = _upsert_sql(table, data, on, update, self.ph, "EXCLUDED")
    return self.exec(sql, params)

  #---------------------------------------------------------------------------- Database Management

  def create_database(self, name:str|None=None) -> bool:
    """Create database. Returns `False` if it already exists."""
    if self.in_transaction(): raise RuntimeError("create_database() not allowed in transaction")
    import psycopg2
    from psycopg2 import sql as psql
    name = name or self.db_name
    self._valid_db(name)
    if self.has_database(name): return False
    backup, self.db_name = self.db_name, "postgres"
    conn = self.conn()
    conn.autocommit = True # CREATE DATABASE cannot run inside a transaction block
    try:
      cur = conn.cursor()
      cur.execute(psql.SQL("CREATE DATABASE {}").format(psql.Identifier(name)))
      cur.close()
      return True
    except psycopg2.Error as e:
      self._err("create_database", e)
    finally:
      conn.close()
      self.db_name = backup

  def drop_database(self, name:str|None=None) -> bool:
    """Drop database and everything in it. Returns `False` if it does not exist."""
    if self.in_transaction(): raise RuntimeError("drop_database() not allowed in transaction")
    import psycopg2
    from psycopg2 import sql as psql
    name = name or self.db_name
    self._valid_db(name)
    if not self.has_database(name): return False
    backup, self.db_name = self.db_name, "postgres"
    conn = self.conn()
    conn.autocommit = True # DROP DATABASE cannot run inside a transaction block
    try:
      cur = conn.cursor()
      cur.execute(psql.SQL("DROP DATABASE {}").format(psql.Identifier(name)))
      cur.close()
      return True
    except psycopg2.Error as e:
      self._err("drop_database", e)
    finally:
      conn.close()
      self.db_name = backup