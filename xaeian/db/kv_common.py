# xaeian/db/kv_common.py

"""Shared internals for sync/async KeyValue stores. Not part of public API."""

import json
import re
import time
from typing import Any, TypeAlias, TypedDict, Union
from .utils import ident

#-------------------------------------------------------------------------------------------- Types

JsonValue: TypeAlias = Union[
  None, bool, int, float, str,
  list["JsonValue"], dict[str, "JsonValue"],
]

class KvEntry(TypedDict):
  """Single entry: decoded value and its last write time in epoch milliseconds."""
  value: JsonValue
  updated_at: int

#---------------------------------------------------------------------------------------- Constants

KEY_MAX = 256 # key and table name length, also the VARCHAR width in DDL
VALUE_MAX_BYTES = 1_000_000 # cap on canonical JSON utf-8 byte size

_TABLE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

#--------------------------------------------------------------------------------------- Validators

def check_key(key:Any):
  """Non-empty string within `KEY_MAX`. Naming policy is left to the caller."""
  if not isinstance(key, str):
    raise TypeError(f"key must be string, got {type(key).__name__}")
  if not key:
    raise ValueError("key must be non-empty")
  if len(key) > KEY_MAX:
    raise ValueError(f"key too long ({len(key)} > {KEY_MAX})")

def check_table(table:Any):
  """Validate table name as a SQL identifier: it is interpolated into DDL, not bound."""
  if not isinstance(table, str):
    raise TypeError(f"table must be string, got {type(table).__name__}")
  if not table:
    raise ValueError("table must be non-empty")
  if len(table) > KEY_MAX:
    raise ValueError(f"table name too long ({len(table)} > {KEY_MAX})")
  if not _TABLE_RE.match(table):
    raise ValueError(f"table {table!r} must match [A-Za-z_][A-Za-z0-9_]* (SQL identifier rules)")

#--------------------------------------------------------------------------------------------- JSON

def dumps(value:JsonValue) -> str:
  """
  Canonical JSON: sorted keys, no whitespace, unicode preserved.

  The `VALUE_MAX_BYTES` cap counts encoded bytes, not characters. `allow_nan` stays at the
  Python default, so `NaN`/`Infinity` serialize as bare literals: `json.loads` reads them back,
  strict RFC 8259 parsers of the same table do not.
  """
  text = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
  if len(text.encode("utf-8")) > VALUE_MAX_BYTES:
    raise ValueError(f"value too large (> {VALUE_MAX_BYTES} bytes serialized)")
  return text

def loads(raw:Any, key:str) -> JsonValue:
  """Parse JSON from a DB row, `key` naming the entry in every error raised."""
  if not isinstance(raw, str):
    raise ValueError(f"corrupted entry for key {key!r}: expected string, got {type(raw).__name__}")
  try:
    return json.loads(raw)
  except json.JSONDecodeError as e:
    raise ValueError(f"corrupted JSON for key {key!r}: {e}") from e

#--------------------------------------------------------------------------------------------- Time

def now_ms() -> int:
  """Current time as epoch milliseconds."""
  return time.time_ns() // 1_000_000

#------------------------------------------------------------------------------------- SQL Builders
# Plain SQL accepted by sqlite, mysql and postgres alike. `ph` is the single bound placeholder
# for the key, in the driver's style: "?", "%s" or "$1".

def sql_create(table:str) -> str:
  """Idempotent DDL: `key` primary key, JSON text `value`, `updated_at` in epoch milliseconds."""
  t = ident(table)
  return (
    f"CREATE TABLE IF NOT EXISTS {t} ("
    f"{ident('key')} VARCHAR({KEY_MAX}) PRIMARY KEY, "
    f"{ident('value')} TEXT NOT NULL, "
    f"{ident('updated_at')} BIGINT NOT NULL)"
  )

def sql_get_value(table:str, ph:str) -> str:
  """Select the JSON text of one key."""
  return (
    f"SELECT {ident('value')} FROM {ident(table)} "
    f"WHERE {ident('key')} = {ph}"
  )

def sql_get_meta(table:str, ph:str) -> str:
  """Select the JSON text and `updated_at` of one key."""
  return (
    f"SELECT {ident('value')}, {ident('updated_at')} FROM {ident(table)} "
    f"WHERE {ident('key')} = {ph}"
  )

def sql_read_all(table:str) -> str:
  """Select every key with its JSON text, ordered by key."""
  return (
    f"SELECT {ident('key')}, {ident('value')} FROM {ident(table)} "
    f"ORDER BY {ident('key')}"
  )

def sql_read_all_meta(table:str) -> str:
  """Select every key with its JSON text and `updated_at`, ordered by key."""
  return (
    f"SELECT {ident('key')}, {ident('value')}, {ident('updated_at')} "
    f"FROM {ident(table)} ORDER BY {ident('key')}"
  )

def where_key(ph:str) -> str:
  """WHERE fragment for one key, in the form `db.exists()` and `db.delete()` take."""
  return f"{ident('key')} = {ph}"
