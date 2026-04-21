# xaeian/db/kv_async.py

"""Async key-value config store with JSON-canonical values."""

import asyncio
from typing import Any
from .abstract_async import AbstractAsyncDatabase
from .kv_common import (
  JsonValue, KvEntry, check_key, check_table, dumps, loads, now_ms,
  sql_create, sql_get_value, sql_get_meta, sql_read_all, sql_read_all_meta, where_key,
)

#---------------------------------------------------------------------------- AsyncKeyValue

class AsyncKeyValue:
  """JSON-canonical async key-value store backed by database table.

  Values are stored as canonical JSON text. Reads return native Python
  types. `None` is a legitimate value (stored as JSON `null`); use
  `has()` to distinguish missing keys from `None` values.

  Key naming policy is left to the caller. The library only enforces
  that keys are non-empty strings within `KEY_MAX`.

  Initialization is lazy: the table is created on first operation,
  async-safe via `asyncio.Lock`.

  Caveats:
    - The instance assumes exclusive ownership of its table for its
      lifetime. External schema changes (e.g. another connection
      dropping the table) are not detected; `_ready` does not retry.
    - Constructing two `AsyncKeyValue` instances against the same
      `(db, table)` and calling them concurrently before either has
      finished init may run `CREATE TABLE IF NOT EXISTS` in parallel.
      The DDL is idempotent so this is harmless, but it is your
      responsibility not to construct duplicate instances for the
      same table.

  Example:
    >>> from xaeian.db import AsyncDatabase, AsyncKeyValue
    >>> db = AsyncDatabase("postgres", "app", user="postgres", password="pass")
    >>> kv = AsyncKeyValue(db, table="vars")
    >>> async with db:
    ...   await kv.set("maintenance", True)
    ...   await kv.get("maintenance")
    True
  """
  def __init__(self, db:AbstractAsyncDatabase, table:str="_config"):
    check_table(table)
    self.db = db
    self.table = table
    self._ready = False
    self._lock = asyncio.Lock()
    ph = db.ph
    self._sql_get = sql_get_value(table, ph)
    self._sql_meta = sql_get_meta(table, ph)
    self._sql_all = sql_read_all(table)
    self._sql_all_meta = sql_read_all_meta(table)
    self._where = where_key(ph)

  async def _ensure(self):
    if self._ready: return
    async with self._lock:
      if self._ready: return
      await self.db.exec(sql_create(self.table))
      self._ready = True

  #------------------------------------------------------------------------------ Read

  async def has(self, key:str) -> bool:
    """Check if key exists. Distinct from `get(key) is None`."""
    check_key(key)
    await self._ensure()
    return await self.db.exists(self.table, self._where, key)

  async def get(self, key:str, default:Any=None) -> Any:
    """Get value by key. Returns `default` if key not found."""
    check_key(key)
    await self._ensure()
    raw = await self.db.get_value(self._sql_get, key)
    return default if raw is None else loads(raw, key)

  async def meta(self, key:str) -> KvEntry|None:
    """Get value with metadata. Returns `None` if key not found.

    Metadata `updated_at` is epoch milliseconds.
    """
    check_key(key)
    await self._ensure()
    row = await self.db.get_dict(self._sql_meta, key)
    if not row: return None
    return {"value": loads(row["value"], key), "updated_at": int(row["updated_at"])}

  async def read_all(self) -> dict[str, JsonValue]:
    """Load entire table into memory as `{key: value}`. Use only for small stores."""
    await self._ensure()
    rows = await self.db.get_dicts(self._sql_all)
    return {r["key"]: loads(r["value"], r["key"]) for r in rows}

  async def read_all_meta(self) -> dict[str, KvEntry]:
    """Load entire table into memory with metadata. Use only for small stores."""
    await self._ensure()
    rows = await self.db.get_dicts(self._sql_all_meta)
    return {
      r["key"]: {
        "value": loads(r["value"], r["key"]),
        "updated_at": int(r["updated_at"]),
      }
      for r in rows
    }

  #----------------------------------------------------------------------------- Write

  async def set(self, key:str, value:JsonValue) -> int:
    """Upsert value. Returns the write timestamp (epoch milliseconds).

    Raises:
      TypeError: When value contains non-JSON-serializable types.
      ValueError: When serialized value exceeds `VALUE_MAX_BYTES`.
    """
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
    """Delete entry by key. Returns `True` if a row was removed."""
    check_key(key)
    await self._ensure()
    return await self.db.delete(self.table, self._where, key) > 0