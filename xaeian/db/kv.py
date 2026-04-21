# xaeian/db/kv.py

"""Sync key-value config store with JSON-canonical values."""

import threading
from typing import Any
from .abstract import AbstractDatabase
from .kv_common import (
  JsonValue, KvEntry, check_key, check_table, dumps, loads, now_ms,
  sql_create, sql_get_value, sql_get_meta, sql_read_all, sql_read_all_meta, where_key,
)

#--------------------------------------------------------------------------------- KeyValue

class KeyValue:
  """JSON-canonical sync key-value store backed by database table.

  Values are stored as canonical JSON text. Reads return native Python
  types. `None` is a legitimate value (stored as JSON `null`); use
  `has()` to distinguish missing keys from `None` values.

  Key naming policy is left to the caller. The library only enforces
  that keys are non-empty strings within `KEY_MAX`.

  Initialization is lazy: the table is created on first operation,
  thread-safe via internal lock.

  Caveats:
    - The instance assumes exclusive ownership of its table for its
      lifetime. External schema changes (e.g. another connection
      dropping the table) are not detected; `_ready` does not retry.
    - Constructing two `KeyValue` instances against the same `(db, table)`
      and calling them concurrently before either has finished init
      may run `CREATE TABLE IF NOT EXISTS` in parallel. The DDL is
      idempotent so this is harmless, but it is your responsibility
      not to construct duplicate instances for the same table.

  Example:
    >>> from xaeian.db import Database, KeyValue
    >>> db = Database("sqlite", "app.db")
    >>> kv = KeyValue(db, table="vars")
    >>> kv.set("maintenance", True)
    >>> kv.get("maintenance")
    True
    >>> kv.set("limits", {"max": 100, "min": 1})
    >>> kv.get("limits")
    {'max': 100, 'min': 1}
    >>> kv.set("nothing", None)
    >>> kv.has("nothing"), kv.get("nothing")
    (True, None)
    >>> kv.has("missing"), kv.get("missing")
    (False, None)
  """
  def __init__(self, db:AbstractDatabase, table:str="_config"):
    check_table(table)
    self.db = db
    self.table = table
    self._ready = False
    self._lock = threading.Lock()
    ph = db.ph
    self._sql_get = sql_get_value(table, ph)
    self._sql_meta = sql_get_meta(table, ph)
    self._sql_all = sql_read_all(table)
    self._sql_all_meta = sql_read_all_meta(table)
    self._where = where_key(ph)

  def _ensure(self):
    if self._ready: return
    with self._lock:
      if self._ready: return
      self.db.exec(sql_create(self.table))
      self._ready = True

  #------------------------------------------------------------------------------ Read

  def has(self, key:str) -> bool:
    """Check if key exists. Distinct from `get(key) is None`."""
    check_key(key)
    self._ensure()
    return self.db.exists(self.table, self._where, key)

  def get(self, key:str, default:Any=None) -> Any:
    """Get value by key. Returns `default` if key not found."""
    check_key(key)
    self._ensure()
    raw = self.db.get_value(self._sql_get, key)
    return default if raw is None else loads(raw, key)

  def meta(self, key:str) -> KvEntry|None:
    """Get value with metadata. Returns `None` if key not found.

    Metadata `updated_at` is epoch milliseconds.
    """
    check_key(key)
    self._ensure()
    row = self.db.get_dict(self._sql_meta, key)
    if not row: return None
    return {"value": loads(row["value"], key), "updated_at": int(row["updated_at"])}

  def read_all(self) -> dict[str, JsonValue]:
    """Load entire table into memory as `{key: value}`. Use only for small stores."""
    self._ensure()
    rows = self.db.get_dicts(self._sql_all)
    return {r["key"]: loads(r["value"], r["key"]) for r in rows}

  def read_all_meta(self) -> dict[str, KvEntry]:
    """Load entire table into memory with metadata. Use only for small stores."""
    self._ensure()
    rows = self.db.get_dicts(self._sql_all_meta)
    return {
      r["key"]: {
        "value": loads(r["value"], r["key"]),
        "updated_at": int(r["updated_at"]),
      }
      for r in rows
    }

  #----------------------------------------------------------------------------- Write

  def set(self, key:str, value:JsonValue) -> int:
    """Upsert value. Returns the write timestamp (epoch milliseconds).

    Raises:
      TypeError: When value contains non-JSON-serializable types.
      ValueError: When serialized value exceeds `VALUE_MAX_BYTES`.
    """
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
    """Delete entry by key. Returns `True` if a row was removed."""
    check_key(key)
    self._ensure()
    return self.db.delete(self.table, self._where, key) > 0