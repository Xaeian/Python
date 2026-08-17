# xaeian/db/kv_async.py

"""Async key-value config store with JSON-canonical values."""

import asyncio
from typing import Any
from .abstract_async import AbstractAsyncDatabase
from .kv_common import (
  JsonValue, KvEntry, check_key, check_table, dumps, loads, now_ms,
  sql_create, sql_get_value, sql_get_meta, sql_read_all, sql_read_all_meta, where_key,
)
from .utils import ph_list

#------------------------------------------------------------------------------------ AsyncKeyValue

class AsyncKeyValue:
  """
  JSON-canonical async key-value store backed by a database table.

  Values are stored as canonical JSON text, reads return native Python types. `None` is a
  legitimate value (JSON `null`), so use `has()` to tell a missing key from a stored `None`.

  The table is created on the first operation, under an `asyncio.Lock` so concurrent tasks
  create it once. Its existence is then assumed for the life of the instance: a table dropped
  afterwards is never recreated.

  Example:
    >>> db = AsyncDatabase("postgres", "app", user="postgres", password="pass")
    >>> kv = AsyncKeyValue(db, table="vars")
    >>> async with db:
    ...   await kv.set("maintenance", True)
  """
  def __init__(self, db:AbstractAsyncDatabase, table:str="_config"):
    check_table(table)
    self.db = db
    self.table = table
    self._ready = False
    self._lock = asyncio.Lock()
    ph = ph_list(1, db.ph)[0]
    self._sql_get = sql_get_value(table, ph)
    self._sql_meta = sql_get_meta(table, ph)
    self._sql_all = sql_read_all(table)
    self._sql_all_meta = sql_read_all_meta(table)
    self._where = where_key(ph)

  async def _ensure(self):
    """Create the table once, double-checked so later calls skip the lock."""
    if self._ready: return
    async with self._lock:
      if self._ready: return
      await self.db.exec(sql_create(self.table))
      self._ready = True

  #------------------------------------------------------------------------------------------- Read

  async def has(self, key:str) -> bool:
    """Check if key exists. Distinct from `get(key) is None`."""
    check_key(key)
    await self._ensure()
    return await self.db.exists(self.table, self._where, key)

  async def get(self, key:str, default:Any=None) -> Any:
    """Get value by key, `default` when the key is missing."""
    check_key(key)
    await self._ensure()
    raw = await self.db.get_value(self._sql_get, key)
    return default if raw is None else loads(raw, key)

  async def meta(self, key:str) -> KvEntry|None:
    """Get value with its `updated_at` epoch milliseconds."""
    check_key(key)
    await self._ensure()
    row = await self.db.get_dict(self._sql_meta, key)
    if not row: return None
    return {"value": loads(row["value"], key), "updated_at": int(row["updated_at"])}

  async def read_all(self) -> dict[str, JsonValue]:
    """Load entire table as `{key: value}`, ordered by key. Use only for small stores."""
    await self._ensure()
    rows = await self.db.get_dicts(self._sql_all)
    return {r["key"]: loads(r["value"], r["key"]) for r in rows}

  async def read_all_meta(self) -> dict[str, KvEntry]:
    """Load entire table with `updated_at`, ordered by key. Use only for small stores."""
    await self._ensure()
    rows = await self.db.get_dicts(self._sql_all_meta)
    return {
      r["key"]: {
        "value": loads(r["value"], r["key"]),
        "updated_at": int(r["updated_at"]),
      }
      for r in rows
    }

  #------------------------------------------------------------------------------------------ Write

  async def set(self, key:str, value:JsonValue) -> int:
    """Upsert value, returning the write timestamp in epoch milliseconds."""
    check_key(key)
    await self._ensure()
    serialized = dumps(value)
    ts = now_ms()
    await self.db.upsert(self.table, {
      "key": key,
      "value": serialized,
      "updated_at": ts,
    }, on="key")
    return ts

  async def delete(self, key:str) -> bool:
    """Delete entry, `True` when a row was actually removed."""
    check_key(key)
    await self._ensure()
    return await self.db.delete(self.table, self._where, key) > 0
