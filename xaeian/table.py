"""
Lightweight tabular operations on `list[dict]`: pandas-free.

Zero dependencies. Works with data from `CSV.load()`, `JSON.load()`
or any other source that produces `list[dict]`.

Filtering and lookup:
  `where`, `first`, `take`

Column operations:
  `select`, `exclude`, `rename`, `add_column`, `pluck`, `set_defaults`

Sorting and deduplication:
  `sort_by`, `unique`

Grouping and aggregation:
  `group_by`, `count_by`, `aggregate`

Joining and combining:
  `join`, `concat`

Value mapping:
  `replace_values`, `map_column`

Inspection:
  `columns`, `describe`

Example:
  >>> from xaeian.table import where, select, sort_by, aggregate
  >>> rows = CSV.load("data")
  >>> active = where(rows, lambda r: r["status"] == "active")
  >>> summary = aggregate(active, "dept", {"salary": "sum"})
"""

from typing import Any, Callable, Literal
from collections import Counter

Rows = list[dict[str, Any]]
Key = str | Callable[[dict], Any]

def _all_cols(rows:Rows) -> set[str]:
  """Collect all keys across all rows."""
  out: set[str] = set()
  for r in rows:
    out.update(r.keys())
  return out

def _safe_sort_key(v:Any) -> Any:
  """Wrap value so mixed types compare by type name first, then by value."""
  if isinstance(v, tuple):
    return tuple(_safe_sort_key(x) for x in v)
  return (type(v).__name__, v)

def _getter(key:Key) -> Callable[[dict], Any]:
  """Resolve string key to row accessor."""
  if isinstance(key, str):
    k = key
    return lambda r: r.get(k)
  return key

#----------------------------------------------------------------------------- Filtering lookup

def where(rows:Rows, predicate:Callable[[dict], bool]) -> Rows:
  """
  Filter rows by predicate function.

  Example:
    >>> where(rows, lambda r: r["age"] > 30)
  """
  return [r for r in rows if predicate(r)]

def first(rows:Rows, predicate:Callable[[dict], bool]) -> dict | None:
  """Return first row matching predicate, or `None`."""
  for r in rows:
    if predicate(r): return r
  return None

def take(rows:Rows, n:int, *, offset:int=0) -> Rows:
  """
  Return up to `n` rows starting from `offset`.

  Example:
    >>> take(rows, 10, offset=20)  # rows 20..29
  """
  return rows[offset:offset + n]

#---------------------------------------------------------------------------- Column operations

def columns(rows:Rows) -> list[str]:
  """Extract ordered column names from first row."""
  if not rows: return []
  return list(rows[0].keys())

def select(rows:Rows, *cols:str) -> Rows:
  """
  Keep only specified columns.

  Example:
    >>> select(rows, "name", "age", "email")
  """
  return [{k: r.get(k) for k in cols} for r in rows]

def exclude(rows:Rows, *cols:str) -> Rows:
  """Drop specified columns, keep everything else."""
  drop = set(cols)
  return [{k: v for k, v in r.items() if k not in drop} for r in rows]

def rename(rows:Rows, mapping:dict[str, str]) -> Rows:
  """
  Rename columns. `mapping` is `{old_name: new_name}`.

  Example:
    >>> rename(rows, {"Ref": "Designator", "Pacage": "Footprint"})
  """
  return [{mapping.get(k, k): v for k, v in r.items()} for r in rows]

def add_column(rows:Rows, name:str, fn:Callable[[dict], Any]) -> Rows:
  """
  Add computed column to each row (in-place, returns same list).

  Example:
    >>> add_column(rows, "full", lambda r: f'{r["first"]} {r["last"]}')
  """
  for r in rows:
    r[name] = fn(r)
  return rows

def pluck(rows:Rows, col:str) -> list[Any]:
  """
  Extract single column as flat list.

  Example:
    >>> pluck(rows, "email")
    ['a@b.com', 'c@d.com', ...]
  """
  return [r.get(col) for r in rows]

def set_defaults(rows:Rows, **defaults:Any) -> Rows:
  """
  Fill missing keys with default values (in-place).

  Example:
    >>> set_defaults(rows, Count=1, DNP=False, Code="")
  """
  for r in rows:
    for k, v in defaults.items():
      if k not in r: r[k] = v
  return rows

#-------------------------------------------------------------------- Sorting and deduplication

def sort_by(rows:Rows, key:Key, *, reverse:bool=False) -> Rows:
  """
  Sort rows by column or callable. `None` values always sort last.

  For multi-key: `sort_by(rows, lambda r: (r["dept"], -r["salary"]))`
  """
  fn = _getter(key)
  has = [r for r in rows if fn(r) is not None]
  nah = [r for r in rows if fn(r) is None]
  try:
    return sorted(has, key=fn, reverse=reverse) + nah
  except TypeError:
    return sorted(has, key=lambda r: _safe_sort_key(fn(r)), reverse=reverse) + nah

def unique(rows:Rows, key:Key|None=None) -> Rows:
  """
  Deduplicate rows, keeping first occurrence.

  Args:
    key: Column or callable to deduplicate on.
      `None` deduplicates on full row content.

  Example:
    >>> unique(rows, "id")
  """
  seen = set()
  result = []
  fn = _getter(key) if key else lambda r: tuple(sorted(r.items()))
  for r in rows:
    k = fn(r)
    try:
      h = k
      hash(h)
    except TypeError:
      h = repr(k)
    if h not in seen:
      seen.add(h)
      result.append(r)
  return result

#--------------------------------------------------------------------- Grouping and aggregation

def group_by(rows:Rows, key:Key) -> dict[Any, Rows]:
  """
  Group rows by column or callable. No pre-sorting required.

  Example:
    >>> groups = group_by(rows, "dept")
    >>> groups["engineering"]
    [{"dept": "engineering", "name": "Alice"}, ...]
  """
  fn = _getter(key)
  groups: dict[Any, Rows] = {}
  for r in rows:
    k = fn(r)
    groups.setdefault(k, []).append(r)
  return groups

def count_by(rows:Rows, key:Key) -> dict[Any, int]:
  """
  Count occurrences per key value (like `value_counts`).

  Example:
    >>> count_by(rows, "status")
    {"active": 42, "inactive": 7}
  """
  fn = _getter(key)
  return dict(Counter(fn(r) for r in rows))

def aggregate(
  rows:Rows,
  keys:str|list[str],
  agg:dict[str, str|Callable],
) -> Rows:
  """
  Group rows by keys and aggregate columns.

  Args:
    keys: Column name(s) to group by.
    agg: `{column: aggregation}` where aggregation is one of:
      `"first"`, `"last"`, `"sum"`, `"count"`,
      `"min"`, `"max"`, `"mean"`,
      `"join"` or `"join:<sep>"`,
      or `callable(values_list) -> value`.

  Example:
    >>> aggregate(rows, ["Manufacturer", "Code"], {
    ...   "Value": "first",
    ...   "Count": "sum",
    ...   "Reference": "join",
    ... })
  """
  if isinstance(keys, str): keys = [keys]
  groups: dict[tuple, Rows] = {}
  for row in rows:
    k = tuple(row.get(c) for c in keys)
    groups.setdefault(k, []).append(row)
  result = []
  for key_vals, group in groups.items():
    out = dict(zip(keys, key_vals))
    for col, func in agg.items():
      values = [r.get(col) for r in group]
      if callable(func):
        out[col] = func(values)
      elif not isinstance(func, str):
        raise ValueError(f"Aggregation must be string or callable, got: {type(func).__name__}")
      elif func == "first":
        out[col] = values[0] if values else None
      elif func == "last":
        out[col] = values[-1] if values else None
      elif func == "sum":
        out[col] = sum(v for v in values if v is not None)
      elif func == "count":
        out[col] = len(values)
      elif func == "min":
        clean = [v for v in values if v is not None]
        try:
          out[col] = min(clean) if clean else None
        except TypeError:
          out[col] = None
      elif func == "max":
        clean = [v for v in values if v is not None]
        try:
          out[col] = max(clean) if clean else None
        except TypeError:
          out[col] = None
      elif func == "mean":
        nums = [v for v in values if isinstance(v, (int, float))]
        out[col] = (sum(nums) / len(nums)) if nums else None
      elif func.startswith("join"):
        sep = func.split(":", 1)[1] if ":" in func else ","
        out[col] = sep.join(str(v) for v in values if v is not None)
      else:
        raise ValueError(f"Unknown aggregation: {func}")
    result.append(out)
  return result

#------------------------------------------------------------------------ Joining and combining

def join(
  left:Rows,
  right:Rows,
  on:str, *,
  right_on:str|None = None,
  how:Literal["inner", "left", "right", "outer"] = "inner",
  lsuffix:str = "_l",
  rsuffix:str = "_r",
) -> Rows:
  """
  Join two tables on key column(s). Hash-based, O(n+m).

  Args:
    on: Key column in left table.
    right_on: Key column in right table (defaults to `on`).
    how: Join type: `"inner"`, `"left"`, `"right"`, `"outer"`.
    lsuffix: Suffix for overlapping left columns.
    rsuffix: Suffix for overlapping right columns.

  Example:
    >>> join(orders, products, on="product_id", how="left")
  """
  rk = right_on or on
  index: dict[Any, list[dict]] = {}
  for r in right:
    k = r.get(rk)
    index.setdefault(k, []).append(r)
  left_cols = _all_cols(left) if left else set()
  right_cols = _all_cols(right) if right else set()
  overlap = (left_cols & right_cols) - {on, rk}
  def _merge(lr:dict|None, rr:dict|None) -> dict:
    out = {}
    if lr:
      for k, v in lr.items():
        out[k + lsuffix if k in overlap else k] = v
    if rr:
      for k, v in rr.items():
        if k == rk and on in out: continue
        out[k + rsuffix if k in overlap else k] = v
    return out
  result = []
  matched_right_keys = set()
  for lr in left:
    lk = lr.get(on)
    matches = index.get(lk)
    if matches:
      matched_right_keys.add(lk)
      for rr in matches:
        result.append(_merge(lr, rr))
    elif how in ("left", "outer"):
      result.append(_merge(lr, None))
  if how in ("right", "outer"):
    for rr in right:
      if rr.get(rk) not in matched_right_keys:
        result.append(_merge(None, rr))
  return result

def concat(*tables:Rows) -> Rows:
  """
  Vertically stack tables. Missing columns filled with `None`.

  Example:
    >>> concat(batch_1, batch_2, batch_3)
  """
  if not tables: return []
  all_cols: list[str] = []
  seen: set[str] = set()
  for t in tables:
    for r in t:
      for col in r.keys():
        if col not in seen:
          all_cols.append(col)
          seen.add(col)
  result = []
  for t in tables:
    for r in t:
      result.append({c: r.get(c) for c in all_cols})
  return result

#-------------------------------------------------------------------------------- Value mapping

def replace_values(rows:Rows, column:str, mapping:dict) -> Rows:
  """
  Replace values in column by mapping (in-place).

  Example:
    >>> replace_values(rows, "Side", {"top": "T", "bottom": "B"})
  """
  for r in rows:
    if column in r and r[column] in mapping:
      r[column] = mapping[r[column]]
  return rows

def map_column(rows:Rows, column:str, fn:Callable[[Any], Any]) -> Rows:
  """
  Apply function to every value in column (in-place).

  Example:
    >>> map_column(rows, "price", lambda v: round(v, 2))
  """
  for r in rows:
    if column in r:
      r[column] = fn(r[column])
  return rows

#------------------------------------------------------------------------------- Inspection

def describe(rows:Rows, col:str) -> dict[str, Any]:
  """
  Summary statistics for a single column.

  Returns:
    Dict with `count`, `nulls`, `unique`, `min`, `max`,
    and `mean` (for numeric columns, else `None`).

  Example:
    >>> describe(rows, "salary")
    {"count": 50, "nulls": 2, "unique": 45, ...}
  """
  values = pluck(rows, col)
  non_null = [v for v in values if v is not None]
  nums = [v for v in non_null if isinstance(v, (int, float))]
  try:
    uniq = len(set(non_null))
  except TypeError:
    uniq = len({repr(v) for v in non_null})
  try:
    vmin = min(non_null) if non_null else None
    vmax = max(non_null) if non_null else None
  except TypeError:
    vmin = vmax = None
  return {
    "count": len(values),
    "nulls": len(values) - len(non_null),
    "unique": uniq,
    "min": vmin,
    "max": vmax,
    "mean": (sum(nums) / len(nums)) if nums else None,
  }
  
#------------------------------------------------------------------------------------- Markdown

def _md_esc(v:Any) -> str:
  """Escape value for markdown cell."""
  if v is None: return ""
  return str(v).replace("|", r"\|").replace("\n", "<br>")

def _md_auto_aligns(data:list[list[str]], ncols:int) -> list[str]:
  """Auto-detect column alignment: >=70% numeric → right, else left."""
  aligns = []
  for col in range(ncols):
    vals = [r[col] for r in data if col < len(r) and r[col]]
    if not vals:
      aligns.append("<")
      continue
    num = 0
    for v in vals:
      try:
        float(v.replace(" ", "").replace(",", "."))
        num += 1
      except ValueError:
        pass
    aligns.append(">" if num / len(vals) >= 0.7 else "<")
  return aligns

_MD_ALIGN = {
  "<": "<", "l": "<", "left": "<",
  "^": "^", "c": "^", "center": "^",
  ">": ">", "r": ">", "right": ">",
}

def _md_render(hdr:list[str], data:list[list[str]], aligns:list[str]|None) -> str:
  """Render markdown table from escaped header + data cells."""
  if not hdr: return ""
  ncols = len(hdr)
  for r in data:
    while len(r) < ncols: r.append("")
  if aligns is None:
    aligns = _md_auto_aligns(data, ncols)
  else:
    aligns = [_MD_ALIGN.get(str(a).strip().lower(), "<") for a in aligns]
    while len(aligns) < ncols: aligns.append("<")
    aligns = aligns[:ncols]
  widths = [max(3, len(h)) for h in hdr]
  for r in data:
    for i in range(ncols):
      widths[i] = max(widths[i], len(r[i]))
  def fmt(i, txt):
    a, w = aligns[i], widths[i]
    if a == ">": return txt.rjust(w)
    if a == "^": return txt.center(w)
    return txt.ljust(w)
  def sep(i):
    a, w = aligns[i], widths[i]
    if a == "<": return ":" + "-" * (w - 1)
    if a == "^": return ":" + "-" * (w - 2) + ":"
    if a == ">": return "-" * (w - 1) + ":"
    return "-" * w
  lines = [
    "| " + " | ".join(fmt(i, hdr[i]) for i in range(ncols)) + " |",
    "| " + " | ".join(sep(i) for i in range(ncols)) + " |",
  ]
  for r in data:
    lines.append("| " + " | ".join(fmt(i, r[i]) for i in range(ncols)) + " |")
  return "\n".join(lines)

def markdown(
  rows: Rows,
  cols: list[str]|None = None,
  header: list[str]|None = None,
  aligns: list[str]|None = None,
  exclude: list[str]|None = None,
) -> str:
  """
  Render `list[dict]` as markdown table.

  Args:
    rows: Row dicts.
    cols: Column keys to include (default: all from first row).
    header: Display names for columns (default: same as `cols`).
    aligns: Per-column alignment: `"<"`/`">"`/`"^"` or
      `"left"`/`"right"`/`"center"`. `None` = auto-detect.
    exclude: Column keys to drop.

  Returns:
    Markdown table string.

  Example:
    >>> rows = [{"name": "R1", "value": 10}, {"name": "R2", "value": 22}]
    >>> print(markdown(rows))
    | name | value |
    | :--- | ----: |
    | R1   |    10 |
    | R2   |    22 |
    >>> print(markdown(rows, cols=["value", "name"], header=["Val", "Ref"]))
    |  Val | Ref |
    | ---: | :-- |
    |   10 | R1  |
    |   22 | R2  |
  """
  if not rows: return ""
  if cols is None: cols = list(rows[0].keys())
  if exclude:
    drop = set(exclude)
    cols = [c for c in cols if c not in drop]
  hdr = [_md_esc(h) for h in (header if header else cols)]
  while len(hdr) < len(cols): hdr.append("")
  data = [[_md_esc(r.get(c)) for c in cols] for r in rows]
  return _md_render(hdr[:len(cols)], data, aligns)

def markdown_raw(
  rows: list[list],
  header: bool = True,
  aligns: list[str]|None = None,
) -> str:
  """
  Render `list[list]` as markdown table.

  For raw data from `CSV.load_raw()` or similar sources.

  Args:
    rows: List of rows (each row is a list of values).
    header: When `True`, first row is used as column headers.
    aligns: Per-column alignment (see `markdown`). `None` = auto-detect.

  Returns:
    Markdown table string.

  Example:
    >>> raw = [["Name", "Ohm"], ["R1", "10k"], ["R2", "22k"]]
    >>> print(markdown_raw(raw))
    | Name | Ohm |
    | :--- | :-- |
    | R1   | 10k |
    | R2   | 22k |
  """
  if not rows: return ""
  if header:
    hdr = [_md_esc(c) for c in rows[0]]
    data = [[_md_esc(c) for c in r] for r in rows[1:]]
  else:
    ncols = max(len(r) for r in rows)
    hdr = [_md_esc(str(i)) for i in range(ncols)]
    data = [[_md_esc(c) for c in r] for r in rows]
  return _md_render(hdr, data, aligns)