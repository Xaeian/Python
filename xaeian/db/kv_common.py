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

#--------------------------------------------------------------------------------------- Validators

def check_key(key:Any) -> None:
  """Non-empty string within `KEY_MAX`. Naming policy is left to the caller."""
  if not isinstance(key, str):
    raise TypeError(f"key must be string, got {type(key).__name__}")
  if not key:
    raise ValueError("key must be non-empty")
  if len(key) > KEY_MAX:
    raise ValueError(f"key too long ({len(key)} > {KEY_MAX})")

def check_table(table:Any) -> None:
  """Validate table name: `ident` rules, since it is interpolated into DDL, plus a length cap."""
  if not isinstance(table, str):
    raise TypeError(f"table must be string, got {type(table).__name__}")
  if len(table) > KEY_MAX:
    raise ValueError(f"table name too long ({len(table)} > {KEY_MAX})")
  ident(table)

#--------------------------------------------------------------------------------------------- JSON

def dumps(value:JsonValue) -> str:
  """
  Canonical JSON: sorted keys, no whitespace, unicode preserved.

  The `VALUE_MAX_BYTES` cap counts encoded bytes, not characters.
  `allow_nan` stays at the Python default, so `NaN`/`Infinity` serialize as bare literals:
  `json.loads` reads them back, strict RFC 8259 parsers of the same table do not.
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
# Plain SQL accepted by sqlite, mysql and postgres alike.
# `ph` is the single bound placeholder for the key, always `?`;
# the backend rewrites it on the way to its driver.

def quoted(name:str, q:str) -> str:
  """
  Validated identifier wrapped in the driver's quote character.

  The store owns these names, and one of them is `key`, which is reserved in MySQL.
  Quoting is safe here precisely because the schema is ours:
  `ident` has already restricted the name to letters, digits and `_`,
  so nothing can escape the quotes, and no user table has its case-folding changed underneath it.
  """
  return f"{q}{ident(name)}{q}"

def sql_create(table:str, q:str) -> str:
  """Idempotent DDL: `key` primary key, JSON text `value`, `updated_at` in epoch milliseconds."""
  t = quoted(table, q)
  return (
    f"CREATE TABLE IF NOT EXISTS {t} ("
    f"{quoted('key', q)} VARCHAR({KEY_MAX}) PRIMARY KEY, "
    f"{quoted('value', q)} TEXT NOT NULL, "
    f"{quoted('updated_at', q)} BIGINT NOT NULL)"
  )

def sql_get_value(table:str, ph:str, q:str) -> str:
  """Select the JSON text of one key."""
  return (
    f"SELECT {quoted('value', q)} FROM {quoted(table, q)} "
    f"WHERE {quoted('key', q)} = {ph}"
  )

def sql_get_meta(table:str, ph:str, q:str) -> str:
  """Select the JSON text and `updated_at` of one key."""
  return (
    f"SELECT {quoted('value', q)}, {quoted('updated_at', q)} FROM {quoted(table, q)} "
    f"WHERE {quoted('key', q)} = {ph}"
  )

def sql_read_all(table:str, q:str) -> str:
  """Select every key with its JSON text, ordered by key."""
  return (
    f"SELECT {quoted('key', q)}, {quoted('value', q)} FROM {quoted(table, q)} "
    f"ORDER BY {quoted('key', q)}"
  )

def sql_read_all_meta(table:str, q:str) -> str:
  """Select every key with its JSON text and `updated_at`, ordered by key."""
  return (
    f"SELECT {quoted('key', q)}, {quoted('value', q)}, {quoted('updated_at', q)} "
    f"FROM {quoted(table, q)} ORDER BY {quoted('key', q)}"
  )

def sql_upsert(table:str, ph:str, q:str, excluded:str|None) -> str:
  """
  Insert-or-replace one entry, every identifier quoted.

  The generic `upsert` builder leaves identifiers bare, which is right for a user's table
  but fatal here: `key` is a reserved word in MySQL.
  `excluded` is the conflict-row alias, or `None` for MySQL,
  whose `ON DUPLICATE KEY UPDATE` names no conflict target.
  """
  t, k, v, u = quoted(table, q), quoted("key", q), quoted("value", q), quoted("updated_at", q)
  head = f"INSERT INTO {t} ({k}, {v}, {u}) VALUES ({ph}, {ph}, {ph})"
  if excluded is None:
    return f"{head} ON DUPLICATE KEY UPDATE {v} = VALUES({v}), {u} = VALUES({u})"
  return (
    f"{head} ON CONFLICT ({k}) DO UPDATE SET "
    f"{v} = {excluded}.{v}, {u} = {excluded}.{u}"
  )

def where_key(ph:str, q:str) -> str:
  """WHERE fragment for one key, in the form `db.exists()` and `db.delete()` take."""
  return f"{quoted('key', q)} = {ph}"
