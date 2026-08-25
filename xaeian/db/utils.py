# xaeian/db/utils.py

"""Serialization and SQL utilities."""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, TypeAlias
from ..xstring import scan, split_sql

Params:TypeAlias = Any
"""Query parameters: one value, a `list`/`tuple` of them, or `None` for none at all."""

#-------------------------------------------------------------------------------------------- Regex

ISO_RE = re.compile(
  r"^\d{4}-\d{2}-\d{2}"
  r"([T ]\d{2}:\d{2}(:\d{2})?(\.\d+)?(Z|[+-]\d{2}:?\d{2})?)?$"
)
"""ISO 8601 date, with optional time and timezone."""

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

def norm(params:Any) -> tuple[Any, ...]:
  """Normalize `None` / bare value / `list` / `tuple` params to a tuple."""
  if params is None: return ()
  if isinstance(params, tuple): return params
  if isinstance(params, list): return tuple(params)
  return (params,)

def serialize_params(params:Any) -> tuple[Any, ...]:
  """Normalize and serialize parameters."""
  return tuple(serialize(v) for v in norm(params))

def serialize_dict(data:dict) -> dict[str, Any]:
  """Serialize every value in dict."""
  return {k: serialize(v) for k, v in data.items()}

def listify(data:Any) -> Any:
  """Recursively convert tuples to lists: drivers return tuple rows, the API returns lists."""
  if isinstance(data, (tuple, list)): return [listify(item) for item in data]
  return data

#-------------------------------------------------------------------------------------- SQL Helpers

IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
"""SQL identifier: ASCII letters, digits and `_`, not starting with a digit."""

def ident(name:str) -> str:
  """
  Guard a table/column name before it is interpolated into SQL.

  Stricter than the SQL grammar on purpose: a name that fails here would need quoting.
  Quoting is a decision the caller makes knowingly, as the key-value store does,
  never a default that silently changes how the server case-folds a user's table.
  """
  if not IDENT_RE.match(name):
    raise ValueError(f"Invalid identifier: {name!r}")
  return name

def ph(n:int) -> str:
  """Parenthesized placeholder list: `"(?, ?)"`."""
  return "(" + ", ".join(ph_list(n)) + ")"

def ph_list(n:int) -> list[str]:
  """Placeholders unwrapped: `["?", "?"]`."""
  return ["?"] * n

def to_driver(sql:str, style:str) -> str:
  """
  Rewrite `?` placeholders into the driver's own form.

  `?` is the one dialect the builders emit and the one users write.
  `style` is `"?"` for sqlite3 and aiosqlite, `"%s"` for pymysql and psycopg2,
  and `"$"` for asyncpg, which numbers them from the left.

  Only a `?` that stands as SQL counts: `scan` settles quotes and comments in one pass,
  so a question mark inside `'a literal'`, a `"quoted identifier"`, a backtick name
  or a `--` or `/* */` comment is left alone.
  The jsonb `?` operator is SQL, so it still has to be written as `jsonb_exists()`.
  """
  if style == "?": return sql
  out, idx = [], 1
  for kind, chunk in scan(sql, quotes="'\"`", line="--", block=("/*", "*/")):
    if kind != "text":
      out.append(chunk)
      continue
    for ch in chunk:
      if ch != "?":
        out.append(ch)
        continue
      out.append(f"${idx}" if style == "$" else style)
      idx += 1
  return "".join(out)

#------------------------------------------------------------------------------------- SQL Builders

# Shared by the sync and async implementations.

def _insert_sql(table:str, data:dict) -> tuple[str, tuple]:
  """Build `INSERT INTO ... VALUES (...)` and its params (no RETURNING)."""
  d = serialize_dict(data)
  t = ident(table)
  cols = ", ".join(ident(k) for k in d.keys())
  return f"INSERT INTO {t} ({cols}) VALUES {ph(len(d))}", tuple(d.values())

def _insert_many_sql(table:str, rows:list[dict]) -> tuple[str, list[tuple]]:
  """
  Build INSERT and per-row param tuples for a non-empty row list.

  Columns are taken from the first row and every later row is read by those names,
  so a row spelling its keys in another order still lands in the right columns.
  A row missing one of them raises `KeyError` rather than shifting the values along.
  """
  rows2 = [serialize_dict(r) for r in rows]
  t = ident(table)
  keys = list(rows2[0].keys())
  cols = ", ".join(ident(k) for k in keys)
  sql = f"INSERT INTO {t} ({cols}) VALUES {ph(len(keys))}"
  return sql, [tuple(r[k] for k in keys) for r in rows2]

def _update_sql(table:str, data:dict, where:str, params:Any) -> tuple[str, tuple]:
  """
  Build `UPDATE ... SET ... WHERE ...`.

  The SET list and the caller's WHERE both carry plain `?`.
  Placeholders are numbered in one left-to-right pass, so the two can never collide.
  """
  d = serialize_dict(data)
  t = ident(table)
  sets = ", ".join(f"{ident(k)} = ?" for k in d.keys())
  p = tuple(d.values()) + serialize_params(params)
  return f"UPDATE {t} SET {sets} WHERE {where}", p

def _find_sql(
  table:str,
  order:str|None,
  limit:int|None,
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
    conds = " AND ".join(f"{ident(k)} = ?" for k in where.keys())
    sql += f" WHERE {conds}"
    params = tuple(serialize_dict(where).values())
  if order: sql += f" ORDER BY {order}"
  if limit is not None: # `limit=0` asks for no rows; a falsy test would return the whole table
    if limit < 0: raise ValueError(f"limit cannot be negative: {limit}")
    sql += f" LIMIT {limit}"
  return sql, params

def _upsert_sql(
  table:str,
  data:dict,
  on:str|list[str],
  update:list[str]|None,
  excluded:str|None,
) -> tuple[str, tuple]:
  """
  Build dialect-aware upsert and its params.

  `excluded` is the conflict-row alias for `ON CONFLICT ... DO UPDATE`:
  `"excluded"` in SQLite, `"EXCLUDED"` in PostgreSQL,
  and `None` for MySQL, whose `ON DUPLICATE KEY UPDATE` names no conflict target.
  """
  d = serialize_dict(data)
  t = ident(table)
  cols = ", ".join(ident(k) for k in d.keys())
  vals = ph(len(d))
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

def parse_row(row:list, json_idx:set[int]) -> list[Any]:
  """Parse JSON in the columns whose index is in `json_idx`."""
  return [parse_json(v) if i in json_idx else v for i, v in enumerate(row)]

def to_dicts(rows:list, cols:list[str], json:list[str]|None=None) -> list[dict[str, Any]]:
  """Zip rows against `cols`, parsing the columns named in `json`."""
  if not json: return [dict(zip(cols, row)) for row in rows]
  jset = set(json)
  return [{k: parse_json(v) if k in jset else v for k, v in zip(cols, row)} for row in rows]
