# xaeian/table.py

"""
Lightweight tabular operations on `list[dict]`: pandas-free, zero dependencies.

Takes anything that produces `list[dict]`, such as `CSV.load()` or `JSON.load()`. Filter
(`where`, `first`, `take`), shape (`select`, `exclude`, `rename`, `add_column`, `pluck`,
`set_defaults`), order (`sort_by`, `unique`), group (`group_by`, `count_by`, `aggregate`),
combine (`join`, `concat`), map (`replace_values`, `map_column`), inspect (`columns`,
`describe`), render (`markdown`, `markdown_raw`).

Example:
  >>> from xaeian.table import where, aggregate
  >>> rows = CSV.load("data")
  >>> active = where(rows, lambda r: r["status"] == "active")
  >>> summary = aggregate(active, "dept", {"salary": "sum"})
"""

from typing import Any, Callable, Literal
from collections import Counter

Rows = list[dict[str, Any]]
Key = str | Callable[[dict], Any]

def _all_cols(rows:Rows) -> set[str]:
  out: set[str] = set()
  for r in rows:
    out.update(r.keys())
  return out

def _safe_sort_key(v:Any) -> Any:
  """Wrap value so mixed types compare by type name first, then by value."""
  if isinstance(v, (tuple, list)):
    return tuple(_safe_sort_key(x) for x in v)
  return (type(v).__name__, v)

def _getter(key:Key) -> Callable[[dict], Any]:
  if isinstance(key, str):
    k = key
    return lambda r: r.get(k)
  return key

#--------------------------------------------------------------------------------- Filtering lookup

def where(rows:Rows, predicate:Callable[[dict], bool]) -> Rows:
  """Filter rows by predicate."""
  return [r for r in rows if predicate(r)]

def first(rows:Rows, predicate:Callable[[dict], bool]) -> dict|None:
  """Return first row matching predicate, or `None`."""
  for r in rows:
    if predicate(r): return r
  return None

def take(rows:Rows, n:int, *, offset:int=0) -> Rows:
  """Return up to `n` rows starting from `offset`."""
  return rows[offset:offset + n]

#-------------------------------------------------------------------------------- Column operations

def columns(rows:Rows) -> list[str]:
  """Extract ordered column names from first row."""
  if not rows: return []
  return list(rows[0].keys())

def select(rows:Rows, *cols:str) -> Rows:
  """Keep only the given columns, missing ones become `None`."""
  return [{k: r.get(k) for k in cols} for r in rows]

def exclude(rows:Rows, *cols:str) -> Rows:
  """Drop the given columns."""
  drop = set(cols)
  return [{k: v for k, v in r.items() if k not in drop} for r in rows]

def rename(rows:Rows, mapping:dict[str, str]) -> Rows:
  """Rename columns, `mapping` is `{old: new}`."""
  return [{mapping.get(k, k): v for k, v in r.items()} for r in rows]

def add_column(rows:Rows, name:str, fn:Callable[[dict], Any]) -> Rows:
  """Add a computed column to each row, in-place."""
  for r in rows:
    r[name] = fn(r)
  return rows

def pluck(rows:Rows, col:str) -> list[Any]:
  """Extract a single column as a flat list."""
  return [r.get(col) for r in rows]

def set_defaults(rows:Rows, **defaults:Any) -> Rows:
  """Fill missing keys with default values, in-place."""
  for r in rows:
    for k, v in defaults.items():
      if k not in r: r[k] = v
  return rows

#------------------------------------------------------------------------ Sorting and deduplication

def sort_by(rows:Rows, key:Key, *, reverse:bool=False) -> Rows:
  """
  Sort rows by column or callable, `None` values always land last.

  Multi-key: `sort_by(rows, lambda r: (r["dept"], -r["salary"]))`
  """
  fn = _getter(key)
  has = [r for r in rows if fn(r) is not None]
  nah = [r for r in rows if fn(r) is None]
  try:
    return sorted(has, key=fn, reverse=reverse) + nah
  except TypeError:
    return sorted(has, key=lambda r: _safe_sort_key(fn(r)), reverse=reverse) + nah

def unique(rows:Rows, key:Key|None=None) -> Rows:
  """Deduplicate rows keeping first occurrence, `key=None` compares the full row."""
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

#------------------------------------------------------------------------- Grouping and aggregation

def group_by(rows:Rows, key:Key) -> dict[Any, Rows]:
  """Group rows by column or callable, no pre-sorting required."""
  fn = _getter(key)
  groups: dict[Any, Rows] = {}
  for r in rows:
    k = fn(r)
    groups.setdefault(k, []).append(r)
  return groups

def count_by(rows:Rows, key:Key) -> dict[Any, int]:
  """Count occurrences per key value, like pandas `value_counts`."""
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
    agg: `{column: aggregation}`, aggregation being `"first"`, `"last"`, `"sum"`, `"count"`,
      `"min"`, `"max"`, `"mean"`, `"join"`/`"join:<sep>"` (default separator `,`),
      or `callable(values) → value`.
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

#---------------------------------------------------------------------------- Joining and combining

def join(
  left:Rows,
  right:Rows,
  on:str,
  *,
  right_on:str|None = None,
  how:Literal["inner", "left", "right", "outer"] = "inner",
  lsuffix:str = "_l",
  rsuffix:str = "_r",
) -> Rows:
  """
  Join two tables on a key column. Hash-based, O(n+m).

  `on` names the left key, `right_on` the right one and defaults to `on`. `lsuffix`/`rsuffix`
  rename only the columns present in both tables. A key value repeated on both sides yields
  every pair, so rows can multiply. Matched rows carry the left key column, right-only rows
  from a `right`/`outer` join carry `right_on`.
  """
  rk = right_on or on
  index: dict[Any, list[dict]] = {}
  for r in right:
    k = r.get(rk)
    index.setdefault(k, []).append(r)
  left_cols = _all_cols(left) if left else set()
  right_cols = _all_cols(right) if right else set()
  overlap = (left_cols & right_cols) - ({on} if on == rk else set())
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
  """Vertically stack tables, missing columns filled with `None`."""
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

#------------------------------------------------------------------------------------ Value mapping

def replace_values(rows:Rows, column:str, mapping:dict) -> Rows:
  """Replace values in a column through `mapping`, in-place."""
  for r in rows:
    if column in r and r[column] in mapping:
      r[column] = mapping[r[column]]
  return rows

def map_column(rows:Rows, column:str, fn:Callable[[Any], Any]) -> Rows:
  """Apply a function to every value in a column, in-place."""
  for r in rows:
    if column in r:
      r[column] = fn(r[column])
  return rows

#--------------------------------------------------------------------------------------- Inspection

def describe(rows:Rows, col:str) -> dict[str, Any]:
  """
  Summary statistics for a single column.

  Keys: `count` (all rows, nulls included), `nulls`, `unique` (distinct non-null values),
  `min`, `max`, `mean`. `mean` is `None` for non-numeric columns, `min`/`max` are `None` when
  the values cannot be compared with each other.
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

#----------------------------------------------------------------------------------------- Markdown

def _md_esc(v:Any) -> str:
  if v is None: return ""
  return str(v).replace("|", r"\|").replace("\n", "<br>")

def _md_auto_aligns(data:list[list[str]], ncols:int) -> list[str]:
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
  """Render markdown table, cells must already be escaped."""
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
  rows:Rows,
  cols:list[str]|None = None,
  header:list[str]|None = None,
  aligns:list[str]|None = None,
  exclude:list[str]|None = None,
) -> str:
  """
  Render `list[dict]` as markdown table.

  Cells escape `|` and turn newlines into `<br>`, `None` renders as an empty cell.

  Args:
    cols: Keys to include, default all keys of the first row.
    header: Display names, default `cols`; must line up with what is left after `exclude`.
    aligns: Per column `"<"`/`"^"`/`">"` or `"left"`/`"center"`/`"right"`, `None` right-aligns
      columns whose values are at least 70% numeric and left-aligns the rest.
    exclude: Keys to drop, applied after `cols` is resolved.

  Example:
    >>> print(markdown([{"name": "R1", "value": 10}, {"name": "R2", "value": 22}]))
    | name | value |
    | :--- | ----: |
    | R1   |    10 |
    | R2   |    22 |
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
  rows:list[list],
  header:bool = True,
  aligns:list[str]|None = None,
) -> str:
  """
  Render `list[list]` as markdown table, for raw data from `CSV.load_raw()`.

  `header=True` takes the first row as column names, `False` numbers them from `0`.
  `aligns` as in `markdown`.
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
