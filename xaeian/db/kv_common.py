# xaeian/db/kv_common.py

"""Internals of `KeyValue` and `AsyncKeyValue`, not public API."""

import json, time
from typing import Any, TypeAlias, TypedDict
from .utils import ident

#-------------------------------------------------------------------------------------------- Types

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]

class KvEntry(TypedDict):
  """Value with its first and last write time in epoch ms."""
  value: JsonValue
  created_at: int
  updated_at: int

#---------------------------------------------------------------------------------------- Constants

KEY_MAX = 256 # longest key and table name, the VARCHAR width too
VALUE_MAX_BYTES = 1_000_000 # longest JSON of a value, in utf-8 bytes

#--------------------------------------------------------------------------------------- Validators

def check_key(key:Any) -> None:
  """Non-empty string within `KEY_MAX`; any naming rule is the caller's."""
  if not isinstance(key, str): raise TypeError(f"key must be string, got {type(key).__name__}")
  if not key: raise ValueError("key must be non-empty")
  if len(key) > KEY_MAX: raise ValueError(f"key too long ({len(key)} > {KEY_MAX})")

def check_table(table:Any) -> None:
  """`ident` rules within `KEY_MAX`: the name goes into SQL as it is."""
  if not isinstance(table, str):
    raise TypeError(f"table must be string, got {type(table).__name__}")
  if len(table) > KEY_MAX: raise ValueError(f"table name too long ({len(table)} > {KEY_MAX})")
  ident(table)

#--------------------------------------------------------------------------------------------- JSON

def dumps(value:JsonValue) -> str:
  """
  Compact JSON, keys in the order given, unicode kept.

  The `VALUE_MAX_BYTES` cap counts encoded bytes, not characters.
  `NaN` and `Infinity` go out bare: `json.loads` reads them back, strict parsers do not.
  """
  text = json.dumps(value, separators=(",", ":"), ensure_ascii=False)
  if len(text.encode("utf-8")) > VALUE_MAX_BYTES:
    raise ValueError(f"value too large (> {VALUE_MAX_BYTES} bytes serialized)")
  return text

def loads(raw:Any, key:str) -> JsonValue:
  """Decoded JSON of a row; every error names `key`."""
  if not isinstance(raw, str):
    raise ValueError(f"corrupted entry for key {key!r}: expected string, got {type(raw).__name__}")
  try:
    return json.loads(raw)
  except json.JSONDecodeError as e:
    raise ValueError(f"corrupted JSON for key {key!r}: {e}") from e

def entry(row:dict, key:str) -> KvEntry:
  """Meta row as `KvEntry`, its times `int` whatever the driver returns."""
  return {
    "value": loads(row["value"], key),
    "created_at": int(row["created_at"]),
    "updated_at": int(row["updated_at"]),
  }

#--------------------------------------------------------------------------------------------- Time

def now_ms() -> int:
  """Current time as epoch milliseconds."""
  return time.time_ns() // 1_000_000

#------------------------------------------------------------------------------------- SQL Builders
# Plain SQL for SQLite, MySQL and PostgreSQL alike.
# `ph` is the placeholder of the key, always `?`; the backend rewrites it for its driver.

def quoted(name:str, q:str) -> str:
  """
  Name checked by `ident`, in the quotes of the driver.

  `key` is reserved in MySQL, so every name of the store is quoted.
  `ident` allows letters, digits and `_` only: nothing escapes the quotes.
  The schema is the store's own, so no user table changes its case-folding.
  """
  return f"{q}{ident(name)}{q}"

def sql_create(table:str, q:str) -> str:
  """Table of the store: `key` primary key, JSON `value`, both times in epoch ms."""
  t = quoted(table, q)
  return (
    f"CREATE TABLE IF NOT EXISTS {t} ("
    f"{quoted('key', q)} VARCHAR({KEY_MAX}) PRIMARY KEY, "
    f"{quoted('value', q)} TEXT NOT NULL, "
    f"{quoted('created_at', q)} BIGINT NOT NULL, "
    f"{quoted('updated_at', q)} BIGINT NOT NULL)"
  )

def sql_get_value(table:str, ph:str, q:str) -> str:
  """Select the JSON text of one key."""
  return (
    f"SELECT {quoted('value', q)} FROM {quoted(table, q)} "
    f"WHERE {quoted('key', q)} = {ph}"
  )

def sql_get_meta(table:str, ph:str, q:str) -> str:
  """Select the JSON text, `created_at` and `updated_at` of one key."""
  return (
    f"SELECT {quoted('value', q)}, {quoted('created_at', q)}, {quoted('updated_at', q)} "
    f"FROM {quoted(table, q)} WHERE {quoted('key', q)} = {ph}"
  )

def sql_read_all(table:str, q:str) -> str:
  """Select every key with its JSON text, ordered by key."""
  return (
    f"SELECT {quoted('key', q)}, {quoted('value', q)} FROM {quoted(table, q)} "
    f"ORDER BY {quoted('key', q)}"
  )

def sql_read_all_meta(table:str, q:str) -> str:
  """Select every key with its JSON text, `created_at` and `updated_at`, ordered by key."""
  return (
    f"SELECT {quoted('key', q)}, {quoted('value', q)}, "
    f"{quoted('created_at', q)}, {quoted('updated_at', q)} "
    f"FROM {quoted(table, q)} ORDER BY {quoted('key', q)}"
  )

def sql_upsert(table:str, ph:str, q:str, excluded:str|None) -> str:
  """
  Insert or update one entry; an update leaves `created_at` as it is.

  Not the generic `upsert`: it leaves names bare, and `key` is reserved in MySQL.
  `excluded` is the alias of the conflict row; `None` for MySQL,
  whose `ON DUPLICATE KEY UPDATE` names no conflict target.
  """
  t, k, v = quoted(table, q), quoted("key", q), quoted("value", q)
  c, u = quoted("created_at", q), quoted("updated_at", q)
  head = f"INSERT INTO {t} ({k}, {v}, {c}, {u}) VALUES ({ph}, {ph}, {ph}, {ph})"
  if excluded is None:
    return f"{head} ON DUPLICATE KEY UPDATE {v} = VALUES({v}), {u} = VALUES({u})"
  return (
    f"{head} ON CONFLICT ({k}) DO UPDATE SET "
    f"{v} = {excluded}.{v}, {u} = {excluded}.{u}"
  )

def where_key(ph:str, q:str) -> str:
  """WHERE fragment for one key, in the form `db.exists()` and `db.delete()` take."""
  return f"{quoted('key', q)} = {ph}"
