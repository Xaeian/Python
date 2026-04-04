# xaeian/db/kv_async.py

"""Async key-value config store over any database backend."""

from .utils import ident
from .abstract_async import AbstractAsyncDatabase

class AsyncKeyValue:
  """Async key-value store backed by database table.

  Example:
    >>> from xaeian.db import AsyncDatabase, AsyncKeyValue
    >>> db = AsyncDatabase("postgres", "app", user="postgres", password="pass")
    >>> kv = AsyncKeyValue(db)
    >>> await kv.set("active_table", "pilot")
    >>> await kv.get("active_table")
    'pilot'
  """
  def __init__(self, db:AbstractAsyncDatabase, table:str="_config"):
    self.db = db
    self.table = table
    self._ready = False

  async def _init(self):
    if self._ready: return
    await self.db.exec(
      f"CREATE TABLE IF NOT EXISTS {ident(self.table)} "
      f"({ident('key')} VARCHAR(64) PRIMARY KEY, {ident('value')} TEXT)")
    self._ready = True

  async def get(self, key:str) -> str|None:
    """Get value by key. Returns None if not found."""
    await self._init()
    return await self.db.get_value(
      f"SELECT {ident('value')} FROM {ident(self.table)} "
      f"WHERE {ident('key')} = {self.db.ph}", key)

  async def set(self, key:str, value:str):
    """Set value (upsert)."""
    await self._init()
    await self.db.upsert(
      self.table, {"key": key, "value": value}, on="key")

  async def all(self) -> dict[str, str]:
    """Get all entries as dict."""
    await self._init()
    rows = await self.db.get_dicts(
      f"SELECT {ident('key')}, {ident('value')} FROM {ident(self.table)}")
    return {r["key"]: r["value"] for r in rows}

  async def delete(self, key:str):
    """Delete entry by key."""
    await self._init()
    await self.db.delete(self.table, f"{ident('key')} = {self.db.ph}", key)