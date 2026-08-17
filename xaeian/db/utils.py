# xaeian/db/utils.py

"""Serialization and SQL utilities."""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

#-------------------------------------------------------------------------------------------- Regex

ISO_RE = re.compile(
  r"^\d{4}-\d{2}-\d{2}"
  r"([T ]\d{2}:\d{2}(:\d{2})?(\.\d+)?(Z|[+-]\d{2}:?\d{2})?)?$"
)
"""ISO 8601 date, with optional time and timezone."""

PH_RE = re.compile(r"\$(\d+)")
"""PostgreSQL placeholder pattern ($1, $2, ...)."""

#------------------------------------------------------------------------------------ Serialization

def serialize(val:Any) -> Any:
  """Serialize for storage: `dict`/`list` → JSON, ISO datetime string → `datetime`."""
  if val is None: return None
  if isinstance(val, (dict, list)):
    return json.dumps(val, ensure_ascii=False, default=str)
  if isinstance(val, str) and ISO_RE.match(val):
    try: return datetime.fromisoformat(val.replace("Z", "+00:00"))
    except ValueError: return val
  return val

def norm(params:Any) -> tuple:
  """Normalize `None` / bare value / `list` / `tuple` params to a tuple."""
  if params is None: return ()
  if isinstance(params, tuple): return params
  if isinstance(params, list): return tuple(params)
  return (params,)

def serialize_params(params:Any) -> tuple:
  """Normalize and serialize parameters."""
  return tuple(serialize(v) for v in norm(params))

def serialize_dict(data:dict) -> dict:
  """Serialize every value in dict."""
  return {k: serialize(v) for k, v in data.items()}

def listify(data:Any) -> Any:
  """Recursively convert tuples to lists: drivers return tuple rows, the API returns lists."""
  if isinstance(data, (tuple, list)): return [listify(item) for item in data]
  return data

#-------------------------------------------------------------------------------------- SQL Helpers

def ident(name:str) -> str:
  """Guard a table/column name before it is interpolated into SQL: alphanumeric and `_` only."""
  if not name.replace("_", "").isalnum():
    raise ValueError(f"Invalid identifier: {name!r}")
  return name

def ph(n:int, style:str="?", offset:int=0) -> str:
  """
  Build a parenthesized placeholder list: `"(?, ?)"`, `"($1, $2)"`.

  Style: `"?"` SQLite, `"%s"` MySQL and sync PostgreSQL, `"$"` async PostgreSQL, where
  `offset` is the count of placeholders already numbered before this one.
  """
  return "(" + ", ".join(ph_list(n, style, offset)) + ")"

def ph_list(n:int, style:str="?", offset:int=0) -> list[str]:
  """Placeholders unwrapped: `['$1', '$2']`. Styles as in `ph`."""
  if style == "$": return [f"${i + offset + 1}" for i in range(n)]
  return [style] * n

def renum_ph(where:str, offset:int) -> str:
  """Shift every `$N` in `where` by `offset`, so `$1` with offset 3 → `$4`."""
  if not offset: return where
  return PH_RE.sub(lambda m: f"${int(m.group(1)) + offset}", where)

#------------------------------------------------------------------------------------- SQL Builders

# Shared by the sync and async implementations.

def _insert_sql(table:str, data:dict, style:str) -> tuple[str, tuple]:
  """Build `INSERT INTO ... VALUES (...)` and its params (no RETURNING)."""
  d = serialize_dict(data)
  t = ident(table)
  cols = ", ".join(ident(k) for k in d.keys())
  return f"INSERT INTO {t} ({cols}) VALUES {ph(len(d), style)}", tuple(d.values())

def _insert_many_sql(table:str, rows:list[dict], style:str) -> tuple[str, list[tuple]]:
  """
  Build INSERT and per-row param tuples for a non-empty row list.

  Columns are taken from the first row, so every row must carry the same keys.
  """
  rows2 = [serialize_dict(r) for r in rows]
  t = ident(table)
  cols = ", ".join(ident(k) for k in rows2[0].keys())
  sql = f"INSERT INTO {t} ({cols}) VALUES {ph(len(rows2[0]), style)}"
  return sql, [tuple(r.values()) for r in rows2]

def _update_sql(table:str, data:dict, where:str, params:Any, style:str) -> tuple[str, tuple]:
  """Build `UPDATE ... SET ... WHERE ...` with renumbered placeholders."""
  d = serialize_dict(data)
  t, n = ident(table), len(d)
  phs = ph_list(n, style)
  sets = ", ".join(f"{ident(k)} = {phs[i]}" for i, k in enumerate(d.keys()))
  p = tuple(d.values()) + serialize_params(params)
  return f"UPDATE {t} SET {sets} WHERE {renum_ph(where, n)}", p

def _find_sql(
  table:str,
  order:str|None,
  limit:int|None,
  style:str,
  where:dict,
) -> tuple[str, tuple]:
  """
  Build `SELECT * FROM ...` with kwargs WHERE / ORDER BY / LIMIT.

  `order` and `limit` are interpolated raw, so they must never come from user input.
  """
  t = ident(table)
  sql = f"SELECT * FROM {t}"
  params = ()
  if where:
    phs = ph_list(len(where), style)
    conds = " AND ".join(f"{ident(k)} = {phs[i]}" for i, k in enumerate(where.keys()))
    sql += f" WHERE {conds}"
    params = tuple(serialize_dict(where).values())
  if order: sql += f" ORDER BY {order}"
  if limit: sql += f" LIMIT {limit}"
  return sql, params

def _upsert_sql(
  table:str,
  data:dict,
  on:str|list[str],
  update:list[str]|None,
  style:str,
  excluded:str|None,
) -> tuple[str, tuple]:
  """
  Build dialect-aware upsert and its params.

  `excluded` is the conflict-row alias (`"excluded"`/`"EXCLUDED"`) for `ON CONFLICT ... DO
  UPDATE`, or `None` for MySQL `ON DUPLICATE KEY UPDATE`, which names no conflict target.
  `update` defaults to every column of `data` except those named in `on`.
  """
  d = serialize_dict(data)
  t = ident(table)
  cols = ", ".join(ident(k) for k in d.keys())
  vals = ph(len(d), style)
  upd = update or [k for k in d.keys() if k not in (on if isinstance(on, list) else [on])]
  if excluded is None:
    sets = ", ".join(f"{ident(k)} = VALUES({ident(k)})" for k in upd)
    sql = f"INSERT INTO {t} ({cols}) VALUES {vals} ON DUPLICATE KEY UPDATE {sets}"
  else:
    conf = ident(on) if isinstance(on, str) else ", ".join(ident(x) for x in on)
    sets = ", ".join(f"{ident(k)} = {excluded}.{ident(k)}" for k in upd)
    sql = f"INSERT INTO {t} ({cols}) VALUES {vals} ON CONFLICT ({conf}) DO UPDATE SET {sets}"
  return sql, tuple(d.values())

#------------------------------------------------------------------------------------- JSON Parsing

def parse_json(val:Any) -> Any:
  """Parse a JSON string, returning the value unchanged when it does not parse."""
  if val is None: return None
  if isinstance(val, (dict, list)): return val
  if isinstance(val, str):
    try: return json.loads(val)
    except (json.JSONDecodeError, TypeError): return val
  return val

def parse_row(row:list, json_idx:set[int]) -> list:
  """Parse JSON in the columns whose index is in `json_idx`."""
  return [parse_json(v) if i in json_idx else v for i, v in enumerate(row)]

def to_dicts(rows:list, cols:list[str], json:list[str]|None=None) -> list[dict]:
  """Zip rows against `cols`, parsing the columns named in `json`."""
  if not json: return [dict(zip(cols, row)) for row in rows]
  jset = set(json)
  return [{k: parse_json(v) if k in jset else v for k, v in zip(cols, row)} for row in rows]

def split_sql(sql:str) -> list[str]:
  """Split multi-statement SQL on `;`, protecting `'...'` literals but not `"identifiers"`."""
  from ..xstring import split_sql as _split_sql
  return _split_sql(sql)
