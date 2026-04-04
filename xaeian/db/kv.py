# xaeian/db/kv.py

"""Sync key-value config store over any database backend."""

from .utils import ident
from .abstract import AbstractDatabase

class KeyValue:
  """Key-value store backed by database table.

  Example:
    >>> from xaeian.db import Database, KeyValue
    >>> db = Database("sqlite", "app.db")
    >>> kv = KeyValue(db)
    >>> kv.set("active_table", "pilot")
    >>> kv.get("active_table")
    'pilot'
  """
  def __init__(self, db:AbstractDatabase, table:str="_config"):
    self.db = db
    self.table = table
    self._ready = False

  def _init(self):
    if self._ready: return
    self.db.exec(
      f"CREATE TABLE IF NOT EXISTS {ident(self.table)} "
      f"({ident('key')} VARCHAR(64) PRIMARY KEY, {ident('value')} TEXT)")
    self._ready = True

  def get(self, key:str) -> str|None:
    """Get value by key. Returns None if not found."""
    self._init()
    return self.db.get_value(
      f"SELECT {ident('value')} FROM {ident(self.table)} "
      f"WHERE {ident('key')} = {self.db.ph}", key)

  def set(self, key:str, value:str):
    """Set value (upsert)."""
    self._init()
    self.db.upsert(self.table, {"key": key, "value": value}, on="key")

  def all(self) -> dict[str, str]:
    """Get all entries as dict."""
    self._init()
    rows = self.db.get_dicts(
      f"SELECT {ident('key')}, {ident('value')} FROM {ident(self.table)}")
    return {r["key"]: r["value"] for r in rows}

  def delete(self, key:str):
    """Delete entry by key."""
    self._init()
    self.db.delete(self.table, f"{ident('key')} = {self.db.ph}", key)