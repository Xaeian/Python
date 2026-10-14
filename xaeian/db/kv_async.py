# xaeian/db/kv_async.py

"""Async key-value store in one database table."""

import asyncio
from typing import Any
from .abstract_async import AbstractAsyncDatabase
from .kv_common import (
  JsonValue, KvEntry, check_key, check_table, dumps, loads, entry, now_ms,
  sql_create, sql_upsert, sql_get_value, sql_get_meta, sql_read_all, sql_read_all_meta, where_key,
)
from .utils import ph_list

#------------------------------------------------------------------------------------ AsyncKeyValue

class AsyncKeyValue:
  """
  JSON values by key, read back as stored, dict key order included.

  `None` is a value (JSON `null`): `has()` tells it from a missing key.
  The first call creates the table, once under concurrent tasks;
  a table dropped later is not recreated.

  Example:
    >>> db = AsyncDatabase("postgres", "app", user="postgres", password="pass")
    >>> kv = AsyncKeyValue(db, table="vars")
    >>> async with db:
    ...   await kv.set("maintenance", True)
  """
  def __init__(self, db:AbstractAsyncDatabase, table:str="_config") -> None:
    check_table(table)
    self.db = db
    self.table = table
    self._ready = False
    self._lock = asyncio.Lock()
    ph, q = ph_list(1)[0], db.quote
    self._sql_get = sql_get_value(table, ph, q)
    self._sql_meta = sql_get_meta(table, ph, q)
    self._sql_all = sql_read_all(table, q)
    self._sql_all_meta = sql_read_all_meta(table, q)
    self._where = where_key(ph, q)
    self._sql_create = sql_create(table, q)
    self._sql_set = sql_upsert(table, ph, q, db.excluded)

  async def _ensure(self):
    """Create the table once, double-checked so later calls skip the lock."""
    if self._ready: return
    async with self._lock:
      if self._ready: return
      await self.db.exec(self._sql_create)
      self._ready = True

  #------------------------------------------------------------------------------------------- Read

  async def has(self, key:str) -> bool:
    """`True` for a stored key, its value `None` included."""
    check_key(key)
    await self._ensure()
    return await self.db.exists(self.table, self._where, key)

  async def get(self, key:str, default:Any=None) -> Any:
    """Value of `key`, `default` when missing."""
    check_key(key)
    await self._ensure()
    raw = await self.db.get_value(self._sql_get, key)
    return default if raw is None else loads(raw, key)

  async def meta(self, key:str) -> KvEntry|None:
    """Value with `created_at` and `updated_at` in epoch ms, `None` when missing."""
    check_key(key)
    await self._ensure()
    row = await self.db.get_dict(self._sql_meta, key)
    return entry(row, key) if row else None

  async def read_all(self) -> dict[str, JsonValue]:
    """Whole table as `{key: value}`, ordered by key; for small stores."""
    await self._ensure()
    rows = await self.db.get_dicts(self._sql_all)
    return {r["key"]: loads(r["value"], r["key"]) for r in rows}

  async def read_all_meta(self) -> dict[str, KvEntry]:
    """Whole table as `{key: KvEntry}`, ordered by key; for small stores."""
    await self._ensure()
    rows = await self.db.get_dicts(self._sql_all_meta)
    return {r["key"]: entry(r, r["key"]) for r in rows}

  #------------------------------------------------------------------------------------------ Write

  async def set(self, key:str, value:JsonValue) -> int:
    """Store `value`, returning its write time in epoch ms."""
    check_key(key)
    await self._ensure()
    serialized = dumps(value)
    ts = now_ms()
    await self.db.exec(self._sql_set, (key, serialized, ts, ts))
    return ts

  async def delete(self, key:str) -> bool:
    """`True` when the key existed."""
    check_key(key)
    await self._ensure()
    return await self.db.delete(self.table, self._where, key) > 0
