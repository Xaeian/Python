# xaeian/db/utils.py

"""Serialization and SQL utilities."""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

#---------------------------------------------------------------------------------------- Regex

ISO_RE = re.compile(
  r"^\d{4}-\d{2}-\d{2}"
  r"([T ]\d{2}:\d{2}(:\d{2})?(\.\d+)?(Z|[+-]\d{2}:?\d{2})?)?$"
)
"""ISO 8601 datetime pattern."""

PH_RE = re.compile(r"\$(\d+)")
"""PostgreSQL placeholder pattern ($1, $2, ...)."""

#-------------------------------------------------------------------------------- Serialization

def serialize(val:Any) -> Any:
  """
  Serialize value for database storage.

  Converts `dict`/`list` to JSON string, ISO datetime string to `datetime`.

  Args:
    val: Value to serialize.

  Returns:
    Serialized value ready for database.

  Example:
    >>> serialize({"key": "value"})
    '{"key": "value"}'
    >>> serialize("2024-01-15T10:30:00Z")
    datetime(2024, 1, 15, 10, 30, tzinfo=...)
  """
  if val is None: return None
  if isinstance(val, (dict, list)):
    return json.dumps(val, ensure_ascii=False, default=str)
  if isinstance(val, str) and ISO_RE.match(val):
    try: return datetime.fromisoformat(val.replace("Z", "+00:00"))
    except ValueError: return val
  return val

def norm(params:Any) -> tuple:
  """
  Normalize parameters to tuple.

  Args:
    params: `None`, single value, `list`, or `tuple`.

  Returns:
    Tuple of parameters.

  Example:
    >>> norm(None)
    ()
    >>> norm(42)
    (42,)
    >>> norm([1, 2, 3])
    (1, 2, 3)
  """
  if params is None: return ()
  if isinstance(params, tuple): return params
  if isinstance(params, list): return tuple(params)
  return (params,)

def serialize_params(params:Any) -> tuple:
  """
  Normalize and serialize parameters.

  Args:
    params: Raw parameters.

  Returns:
    Tuple of serialized values.
  """
  return tuple(serialize(v) for v in norm(params))

def serialize_dict(data:dict) -> dict:
  """
  Serialize all values in dict.

  Args:
    data: Dict with raw values.

  Returns:
    Dict with serialized values.
  """
  return {k: serialize(v) for k, v in data.items()}

def listify(data:Any) -> Any:
  """
  Recursively convert tuples to lists.

  Args:
    data: Data structure with tuples.

  Returns:
    Same structure with lists instead of tuples.
  """
  if isinstance(data, (tuple, list)): return [listify(item) for item in data]
  return data

#---------------------------------------------------------------------------------- SQL Helpers

def ident(name:str) -> str:
  """
  Validate SQL identifier.

  Args:
    name: Table or column name.

  Returns:
    Validated identifier.

  Raises:
    ValueError: When name contains invalid characters.

  Example:
    >>> ident("users")
    'users'
    >>> ident("user_id")
    'user_id'
  """
  if not name.replace("_", "").isalnum():
    raise ValueError(f"Invalid identifier: {name!r}")
  return name

def ph(n:int, style:str="?", offset:int=0) -> str:
  """
  Generate placeholder tuple string.

  Args:
    n: Number of placeholders.
    style: `"?"` for SQLite/MySQL, `"%s"` for MySQL, `"$"` for PostgreSQL.
    offset: Starting number for `$N` style.

  Returns:
    Placeholder tuple like `"(?, ?)"` or `"($1, $2)"`.

  Example:
    >>> ph(3)
    '(?, ?, ?)'
    >>> ph(3, "$")
    '($1, $2, $3)'
  """
  if style == "$": phs = [f"${i + offset + 1}" for i in range(n)]
  else: phs = [style] * n
  return "(" + ", ".join(phs) + ")"

def ph_list(n:int, style:str="?", offset:int=0) -> list[str]:
  """
  Generate placeholder list.

  Args:
    n: Number of placeholders.
    style: Placeholder style.
    offset: Starting number for `$N` style.

  Returns:
    List of placeholders.

  Example:
    >>> ph_list(3)
    ['?', '?', '?']
    >>> ph_list(3, "$")
    ['$1', '$2', '$3']
  """
  if style == "$": return [f"${i + offset + 1}" for i in range(n)]
  return [style] * n

def renum_ph(where:str, offset:int) -> str:
  """
  Renumber `$N` placeholders by offset.

  Args:
    where: SQL WHERE clause with `$N` placeholders.
    offset: Number to add to each placeholder.

  Returns:
    WHERE clause with renumbered placeholders.

  Example:
    >>> renum_ph("id = $1 AND status = $2", 3)
    'id = $4 AND status = $5'
  """
  if not offset: return where
  if PH_RE.search(where):
    return PH_RE.sub(lambda m: f"${int(m.group(1)) + offset}", where)
  return where

#--------------------------------------------------------------------------------- JSON Parsing

def parse_json(val:Any) -> Any:
  """
  Parse JSON string to dict/list.

  Args:
    val: Value to parse.

  Returns:
    Parsed JSON or original value on failure.

  Example:
    >>> parse_json('{"key": "value"}')
    {'key': 'value'}
    >>> parse_json('not json')
    'not json'
  """
  if val is None: return None
  if isinstance(val, (dict, list)): return val
  if isinstance(val, str):
    try: return json.loads(val)
    except (json.JSONDecodeError, TypeError): return val
  return val

def parse_row(row:list, json_idx:set[int]) -> list:
  """
  Parse JSON at specified indices in row.

  Args:
    row: Row as list of values.
    json_idx: Set of column indices to parse as JSON.

  Returns:
    Row with JSON columns parsed.
  """
  return [parse_json(v) if i in json_idx else v for i, v in enumerate(row)]

def to_dicts(rows:list, cols:list[str], json:list[str]|None=None) -> list[dict]:
  """
  Convert rows to dicts.

  Args:
    rows: List of row tuples/lists.
    cols: Column names.
    json: Column names to parse as JSON.

  Returns:
    List of dicts.
  """
  if not json: return [dict(zip(cols, row)) for row in rows]
  jset = set(json)
  result = []
  for row in rows:
    d = {}
    for k, v in zip(cols, row):
      d[k] = parse_json(v) if k in jset else v
    result.append(d)
  return result

def split_sql(sql:str) -> list[str]:
  """
  Split SQL by semicolons, respecting quotes.

  Args:
    sql: Multi-statement SQL string.

  Returns:
    List of individual statements.

  Example:
    >>> split_sql("SELECT 1; SELECT 'a;b'")
    ['SELECT 1;', "SELECT 'a;b'"]
  """
  from ..xstring import split_sql as _split_sql
  return _split_sql(sql)
