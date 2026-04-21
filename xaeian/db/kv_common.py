# xaeian/db/kv_common.py

"""Shared internals for sync/async KeyValue stores. Not part of public API."""

import json
import re
import time
from typing import Any, TypeAlias, TypedDict, Union
from .utils import ident

#---------------------------------------------------------------------------------- Types

JsonValue: TypeAlias = Union[
  None, bool, int, float, str,
  list["JsonValue"], dict[str, "JsonValue"],
]

class KvEntry(TypedDict):
  """Single key-value entry with metadata.

  Fields:
    value: Decoded JSON value (`JsonValue`, including `None`).
      Note: `NaN`/`Infinity`/`-Infinity` are accepted as floats; this
      is a Python json extension, not RFC 8259 canonical JSON.
    updated_at: Last write time as epoch milliseconds (`int`).
  """
  value: JsonValue
  updated_at: int

#-------------------------------------------------------------------------------- Constants

KEY_MAX = 256
VALUE_MAX_BYTES = 1_000_000  # library-level cap on canonical JSON utf-8 size

# Table name policy: classic SQL identifier (letters, digits, underscore;
# no leading digit). Required because table names are interpolated into
# DDL via ident(), unlike keys which go through bound parameters.
_TABLE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

#-------------------------------------------------------------------------------- Validators

def check_key(key:Any):
  """Minimal sanity check for key. Library leaves naming policy to caller.

  Raises:
    TypeError: When key is not a string.
    ValueError: When key is empty or exceeds `KEY_MAX`.
  """
  if not isinstance(key, str):
    raise TypeError(f"key must be string, got {type(key).__name__}")
  if not key:
    raise ValueError("key must be non-empty")
  if len(key) > KEY_MAX:
    raise ValueError(f"key too long ({len(key)} > {KEY_MAX})")

def check_table(table:Any):
  """Validate table name as a SQL identifier.

  Stricter than `check_key()` because the value is interpolated into
  DDL/DML via `ident()`, not bound as a parameter.

  Raises:
    TypeError: When table is not a string.
    ValueError: When table is empty, too long, or not a valid identifier.
  """
  if not isinstance(table, str):
    raise TypeError(f"table must be string, got {type(table).__name__}")
  if not table:
    raise ValueError("table must be non-empty")
  if len(table) > KEY_MAX:
    raise ValueError(f"table name too long ({len(table)} > {KEY_MAX})")
  if not _TABLE_RE.match(table):
    raise ValueError(
      f"table {table!r} must match [A-Za-z_][A-Za-z0-9_]* "
      f"(SQL identifier rules)"
    )

#---------------------------------------------------------------------------------- JSON

def dumps(value:JsonValue) -> str:
  """Canonical JSON: sorted keys, no whitespace, unicode preserved.

  Note: `allow_nan` is left at Python default (`True`); `NaN`/`Infinity`/
  `-Infinity` round-trip cleanly through `json.loads`. This is a Python
  extension to JSON, not RFC 8259 compliant. Acceptable here because
  the store is internal, not exchanged with external systems.

  Raises:
    TypeError: When value contains non-JSON-serializable types.
    ValueError: When serialized form exceeds `VALUE_MAX_BYTES`.
  """
  text = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
  if len(text.encode("utf-8")) > VALUE_MAX_BYTES:
    raise ValueError(f"value too large (> {VALUE_MAX_BYTES} bytes serialized)")
  return text

def loads(raw:Any, key:str) -> JsonValue:
  """Parse JSON from DB row, wrapping all errors with key context."""
  if not isinstance(raw, str):
    raise ValueError(
      f"corrupted entry for key {key!r}: expected string, got {type(raw).__name__}"
    )
  try:
    return json.loads(raw)
  except json.JSONDecodeError as e:
    raise ValueError(f"corrupted JSON for key {key!r}: {e}") from e

#---------------------------------------------------------------------------------- Time

def now_ms() -> int:
  """Current time as epoch milliseconds."""
  return time.time_ns() // 1_000_000

#---------------------------------------------------------------------------- SQL builders
# Note: assumes mainstream SQL dialect (sqlite, mysql, postgres).
# Exotic backends may need overrides at AbstractDatabase level.

def sql_create(table:str) -> str:
  t = ident(table)
  return (
    f"CREATE TABLE IF NOT EXISTS {t} ("
    f"{ident('key')} VARCHAR({KEY_MAX}) PRIMARY KEY, "
    f"{ident('value')} TEXT NOT NULL, "
    f"{ident('updated_at')} INTEGER NOT NULL)"
  )

def sql_get_value(table:str, ph:str) -> str:
  return (
    f"SELECT {ident('value')} FROM {ident(table)} "
    f"WHERE {ident('key')} = {ph}"
  )

def sql_get_meta(table:str, ph:str) -> str:
  return (
    f"SELECT {ident('value')}, {ident('updated_at')} FROM {ident(table)} "
    f"WHERE {ident('key')} = {ph}"
  )

def sql_read_all(table:str) -> str:
  return (
    f"SELECT {ident('key')}, {ident('value')} FROM {ident(table)} "
    f"ORDER BY {ident('key')}"
  )

def sql_read_all_meta(table:str) -> str:
  return (
    f"SELECT {ident('key')}, {ident('value')}, {ident('updated_at')} "
    f"FROM {ident(table)} ORDER BY {ident('key')}"
  )

def where_key(ph:str) -> str:
  return f"{ident('key')} = {ph}"