# xaeian/db/postgres.py

"""PostgreSQL sync implementation."""
from __future__ import annotations

from logging import Logger

from .abstract import AbstractDatabase
from .utils import serialize_dict, ident, ph

class PostgresDatabase(AbstractDatabase):
  """
  PostgreSQL database (psycopg2).

  Uses `RETURNING` clause.

  Args:
    db_name: Database name.
    host: Server hostname.
    user: Username.
    password: Password.
    port: Server port.
    log: Logger instance.

  Example:
    >>> db = PostgresDatabase("mydb", user="postgres", password="secret")
    >>> user_id = db.insert("users", {"name": "Jan"}, returning="id")
  """
  def __init__(
    self,
    db_name: str|None = None,
    host: str = "localhost",
    user: str = "postgres",
    password: str = "",
    port: int = 5432,
    log: Logger|None = None,
  ):
    super().__init__()
    self.host = host
    self.port = port
    self.user = user
    self.password = password
    self.db_name = db_name
    self.log = log
    self.ph = "$"

  def conn(self):
    import psycopg2
    return psycopg2.connect(
      host=self.host, port=self.port,
      user=self.user, password=self.password,
      dbname=self.db_name
    )

  #------------------------------------------------------------------------------------- Schema

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
    name = name or self.db_name
    if not name: return False
    backup, self.db_name = self.db_name, "postgres"
    try:
      return self.get_value("SELECT 1 FROM pg_database WHERE datname=%s", name) is not None
    finally:
      self.db_name = backup

  #------------------------------------------------------------------------------------- Upsert

  def upsert(self, table:str, data:dict, on:str|list[str], update:list[str]|None=None) -> int:
    """INSERT ON CONFLICT (PostgreSQL 9.5+)."""
    d = serialize_dict(data)
    t = ident(table)
    cols = ", ".join(ident(k) for k in d.keys())
    vals = ph(len(d), self.ph)
    conf = on if isinstance(on, str) else ", ".join(on)
    upd_cols = update or [k for k in d.keys() if k not in (on if isinstance(on, list) else [on])]
    sets = ", ".join(f"{ident(k)} = EXCLUDED.{ident(k)}" for k in upd_cols)
    sql = f"INSERT INTO {t} ({cols}) VALUES {vals} ON CONFLICT ({conf}) DO UPDATE SET {sets}"
    return self.exec(sql, tuple(d.values()))

  #------------------------------------------------------------------------ Database Management

  def create_database(self, name:str|None=None) -> bool:
    if self.in_transaction(): raise RuntimeError("create_database() not allowed in transaction")
    import psycopg2
    from psycopg2 import sql as psql
    name = name or self.db_name
    self._valid_db(name)
    if self.has_database(name): return False
    backup, self.db_name = self.db_name, "postgres"
    conn = self.conn()
    conn.autocommit = True
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
    if self.in_transaction(): raise RuntimeError("drop_database() not allowed in transaction")
    import psycopg2
    from psycopg2 import sql as psql
    name = name or self.db_name
    self._valid_db(name)
    if not self.has_database(name): return False
    backup, self.db_name = self.db_name, "postgres"
    conn = self.conn()
    conn.autocommit = True
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
