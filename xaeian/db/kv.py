# xaeian/db/kv.py

"""Sync key-value config store with JSON-canonical values."""

import threading
from typing import Any
from .abstract import AbstractDatabase
from .kv_common import (
  JsonValue, KvEntry, check_key, check_table, dumps, loads, now_ms,
  sql_create, sql_get_value, sql_get_meta, sql_read_all, sql_read_all_meta, where_key,
)
from .utils import ph_list

#----------------------------------------------------------------------------------------- KeyValue

class KeyValue:
  """
  JSON-canonical sync key-value store backed by a database table.

  Values are stored as canonical JSON text, reads return native Python types. `None` is a
  legitimate value (JSON `null`), so use `has()` to tell a missing key from a stored `None`.

  The table is created on the first operation, under a lock so concurrent threads create it
  once. Its existence is then assumed for the life of the instance: a table dropped afterwards
  is never recreated.

  Example:
    >>> kv = KeyValue(Database("sqlite", "app.db"), table="vars")
    >>> kv.set("limits", {"max": 100, "min": 1})
    >>> kv.get("limits")
    {'max': 100, 'min': 1}
    >>> kv.set("nothing", None)
    >>> kv.has("nothing"), kv.has("missing")
    (True, False)
  """
  def __init__(self, db:AbstractDatabase, table:str="_config"):
    check_table(table)
    self.db = db
    self.table = table
    self._ready = False
    self._lock = threading.Lock()
    ph = ph_list(1, db.ph)[0]
    self._sql_get = sql_get_value(table, ph)
    self._sql_meta = sql_get_meta(table, ph)
    self._sql_all = sql_read_all(table)
    self._sql_all_meta = sql_read_all_meta(table)
    self._where = where_key(ph)

  def _ensure(self):
    """Create the table once, double-checked so later calls skip the lock."""
    if self._ready: return
    with self._lock:
      if self._ready: return
      self.db.exec(sql_create(self.table))
      self._ready = True

  #------------------------------------------------------------------------------------------- Read

  def has(self, key:str) -> bool:
    """Check if key exists. Distinct from `get(key) is None`."""
    check_key(key)
    self._ensure()
    return self.db.exists(self.table, self._where, key)

  def get(self, key:str, default:Any=None) -> Any:
    """Get value by key, `default` when the key is missing."""
    check_key(key)
    self._ensure()
    raw = self.db.get_value(self._sql_get, key)
    return default if raw is None else loads(raw, key)

  def meta(self, key:str) -> KvEntry|None:
    """Get value with its `updated_at` epoch milliseconds."""
    check_key(key)
    self._ensure()
    row = self.db.get_dict(self._sql_meta, key)
    if not row: return None
    return {"value": loads(row["value"], key), "updated_at": int(row["updated_at"])}

  def read_all(self) -> dict[str, JsonValue]:
    """Load entire table as `{key: value}`, ordered by key. Use only for small stores."""
    self._ensure()
    rows = self.db.get_dicts(self._sql_all)
    return {r["key"]: loads(r["value"], r["key"]) for r in rows}

  def read_all_meta(self) -> dict[str, KvEntry]:
    """Load entire table with `updated_at`, ordered by key. Use only for small stores."""
    self._ensure()
    rows = self.db.get_dicts(self._sql_all_meta)
    return {
      r["key"]: {
        "value": loads(r["value"], r["key"]),
        "updated_at": int(r["updated_at"]),
      }
      for r in rows
    }

  #------------------------------------------------------------------------------------------ Write

  def set(self, key:str, value:JsonValue) -> int:
    """Upsert value, returning the write timestamp in epoch milliseconds."""
    check_key(key)
    self._ensure()
    serialized = dumps(value)
    ts = now_ms()
    self.db.upsert(self.table, {
      "key": key,
      "value": serialized,
      "updated_at": ts,
    }, on="key")
    return ts

  def delete(self, key:str) -> bool:
    """Delete entry, `True` when a row was actually removed."""
    check_key(key)
    self._ensure()
    return self.db.delete(self.table, self._where, key) > 0
