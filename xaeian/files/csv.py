# xaeian/files/csv.py

"""CSV file operations."""

import os, csv
from typing import Any
from .config import get_context
from .path import PATH
from .dir import DIR
from ..xstring import ensure_suffix

#-------------------------------------------------------------------------------- CSV namespace

class CSV:
  """CSV file operations."""

  @staticmethod
  def _cast(value:str, ctype:type) -> Any:
    """Cast CSV string value to target type."""
    if value in (None, ""): return None
    try:
      return ctype(value)
    except (ValueError, TypeError):
      return None

  @staticmethod
  def load(
    path: str,
    delimiter: str = ",",
    types: dict[str, type]|None = None,
  ) -> list[dict[str, Any]]:
    """Load CSV file as list of dicts."""
    cfg = get_context()
    path = ensure_suffix(path, ".csv")
    path = PATH.resolve(path, read=True)
    if not os.path.exists(path): return []
    rows: list[dict[str, Any]] = []
    with open(path, "r", encoding=cfg.encoding, newline="") as file:
      reader = csv.DictReader(file, delimiter=delimiter)
      for row in reader:
        if types:
          for col, ctype in types.items():
            if col in row:
              row[col] = CSV._cast(row[col], ctype)
        rows.append(row)
    return rows

  @staticmethod
  def load_raw(
    path: str,
    delimiter: str = ",",
    types: dict[str, type]|None = None,
    include_header: bool = True,
  ) -> list[list[Any]]:
    """Load CSV file as list of lists."""
    cfg = get_context()
    path = ensure_suffix(path, ".csv")
    path = PATH.resolve(path, read=True)
    if not os.path.exists(path): return []
    with open(path, "r", encoding=cfg.encoding, newline="") as file:
      reader = csv.reader(file, delimiter=delimiter)
      rows: list[list[Any]] = [r for r in reader]
    if not rows: return []
    if types:
      header = rows[0]
      idx_map: dict[int, type] = {
        i: types[name]
        for i, name in enumerate(header) if name in types
      }
      for r in rows[1:]:
        for i, ctype in idx_map.items():
          if i < len(r):
            r[i] = CSV._cast(r[i], ctype)
    return rows if include_header else rows[1:]

  @staticmethod
  def load_vectors(
    path: str,
    delimiter: str = ",",
    types: dict[str, type]|None = None,
    group_by: str|None = None,
  ) -> dict[str, list[Any]] | dict[Any, dict[str, list[Any]]]:
    """
    Load CSV as dict of column vectors.

    Args:
      path: CSV file path.
      types: Optional `{column: type}` for casting.
      group_by: Column to group by.

    Returns:
      `{column: [values...]}` or `{group: {column: [values...]}}`
    """
    rows = CSV.load(path, delimiter=delimiter, types=types)
    if not rows: return {}
    columns = list(rows[0].keys())
    if group_by is None:
      result: dict[str, list[Any]] = {col: [] for col in columns}
      for row in rows:
        for col in columns:
          result[col].append(row.get(col))
      return result
    if group_by not in columns:
      raise ValueError(f"group_by column '{group_by}' not found")
    other_cols = [c for c in columns if c != group_by]
    grouped: dict[Any, dict[str, list[Any]]] = {}
    for row in rows:
      key = row.get(group_by)
      if key not in grouped:
        grouped[key] = {col: [] for col in other_cols}
      for col in other_cols:
        grouped[key][col].append(row.get(col))
    return grouped

  @staticmethod
  def add_row(path:str, datarow:dict[str, Any]|list[Any],
              delimiter:str=","):
    """Append single row to CSV file."""
    if datarow is None: raise ValueError("datarow must not be None")
    cfg = get_context()
    path = ensure_suffix(path, ".csv")
    path = PATH.resolve(path, read=False)
    DIR.ensure(path, is_file=True)
    file_exists = os.path.isfile(path)
    with open(path, "a", newline="", encoding=cfg.encoding) as csv_file:
      if isinstance(datarow, dict):
        field_names = list(datarow.keys())
        writer = csv.DictWriter(
          csv_file, fieldnames=field_names, delimiter=delimiter,
        )
        if not file_exists: writer.writeheader()
        writer.writerow(datarow)
      elif isinstance(datarow, list):
        writer = csv.writer(csv_file, delimiter=delimiter)
        writer.writerow(datarow)
      else:
        raise ValueError("datarow must be dict or list")

  @staticmethod
  def save(
    path: str,
    data: list[dict[str, Any]]|list[list[Any]],
    field_names: list[str]|None = None,
    delimiter: str = ",",
  ) -> None:
    """Save whole CSV file from list of dicts or list of lists."""
    if not data: return
    cfg = get_context()
    path = ensure_suffix(path, ".csv")
    path = PATH.resolve(path, read=False)
    DIR.ensure(path, is_file=True)
    with open(path, "w", newline="", encoding=cfg.encoding) as csv_file:
      if all(isinstance(row, dict) for row in data):
        field_names = field_names or list(data[0].keys())
        writer = csv.DictWriter(
          csv_file, fieldnames=field_names, delimiter=delimiter,
        )
        writer.writeheader()
        writer.writerows(data)
      elif all(isinstance(row, list) for row in data):
        if not field_names:
          raise ValueError("field_names required for list rows")
        writer = csv.writer(csv_file, delimiter=delimiter)
        writer.writerow(field_names)
        writer.writerows(data)
      else:
        raise ValueError("data must be list of dicts or list of lists")

  @staticmethod
  def save_vectors(
    path: str,
    *columns: list[Any],
    header: list[str]|None = None,
    delimiter: str = ",",
  ) -> None:
    """Save multiple equal-length vectors as CSV columns."""
    if not columns: raise ValueError("No data vectors provided")
    vector_lengths = {len(col) for col in columns}
    if len(vector_lengths) > 1:
      raise ValueError("All vectors must have same length")
    if header and len(header) != len(columns):
      raise ValueError("Header length must match number of vectors")
    cfg = get_context()
    path = ensure_suffix(path, ".csv")
    path = PATH.resolve(path, read=False)
    DIR.ensure(path, is_file=True)
    with open(path, "w", newline="", encoding=cfg.encoding) as file:
      writer = csv.writer(file, delimiter=delimiter)
      if header: writer.writerow(header)
      for values in zip(*columns): writer.writerow(values)
