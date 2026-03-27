# xaeian/files/json.py

"""JSON file operations."""

import os, json
from typing import Any
from .config import get_context
from .path import PATH
from .dir import DIR
from ..xstring import ensure_suffix

#------------------------------------------------------------------------------- JSON namespace

class JSON:
  """JSON file operations."""

  @staticmethod
  def load(path:str, otherwise:Any=None) -> Any:
    """Load JSON file."""
    cfg = get_context()
    path = ensure_suffix(path, ".json")
    path = PATH.resolve(path, read=True)
    if not os.path.isfile(path): return otherwise
    with open(path, "r", encoding=cfg.encoding) as file:
      content = file.read()
    if not content: return otherwise
    return json.loads(content)

  @staticmethod
  def save(path:str, content:Any) -> None:
    """Save JSON to file in compact form."""
    cfg = get_context()
    path = ensure_suffix(path, ".json")
    path = PATH.resolve(path, read=False)
    DIR.ensure(path, is_file=True)
    with open(path, "w", encoding=cfg.encoding) as file:
      json.dump(content, file, separators=(",", ":"))

  @staticmethod
  def save_pretty(path:str, content:Any, indent:int=2,
                  sort_keys:bool=False) -> None:
    """Save JSON in pretty-printed form."""
    cfg = get_context()
    path = ensure_suffix(path, ".json")
    path = PATH.resolve(path, read=False)
    DIR.ensure(path, is_file=True)
    with open(path, "w", encoding=cfg.encoding, newline="\n") as file:
      json.dump(content, file, indent=indent, ensure_ascii=False,
                sort_keys=sort_keys)
      file.write("\n")

  @staticmethod
  def smart(
    obj: Any,
    indent: int = 2,
    max_line: int = 100,
    array_wrap: int = 10,
    compact_dict: bool = True,
  ) -> str:
    """Format JSON with smart inline/multiline decisions."""
    def is_primitive(v):
      return v is None or isinstance(v, (bool, int, float, str))
    def is_numeric_array(v):
      return (isinstance(v, list) and v
              and all(isinstance(x, (int, float)) for x in v))
    def is_2d_numeric(v):
      return (isinstance(v, list) and v
              and all(is_numeric_array(row) for row in v))
    def is_flat_dict(v):
      return (isinstance(v, dict) and v
              and all(is_primitive(val) for val in v.values()))
    def compact(v):
      return json.dumps(v, separators=(",", ":"))
    def fits_line(v):
      return len(compact(v)) <= max_line
    def format_numeric_array(arr, depth):
      if len(arr) <= array_wrap and fits_line(arr):
        return json.dumps(arr)
      pad = " " * (depth * indent)
      pad_inner = " " * ((depth + 1) * indent)
      chunks = [
        arr[i:i + array_wrap]
        for i in range(0, len(arr), array_wrap)
      ]
      lines = [json.dumps(chunk)[1:-1] for chunk in chunks]
      return ("[\n" + pad_inner
              + (",\n" + pad_inner).join(lines)
              + "\n" + pad + "]")
    def format_numeric_row(arr, base_indent):
      if fits_line(arr): return json.dumps(arr)
      chunks = [
        arr[i:i + array_wrap]
        for i in range(0, len(arr), array_wrap)
      ]
      if len(chunks) == 1:
        return "[ " + json.dumps(chunks[0])[1:-1] + " ]"
      lines = []
      for i, chunk in enumerate(chunks):
        line = json.dumps(chunk)[1:-1]
        if i == 0: lines.append("[ " + line + ",")
        elif i == len(chunks) - 1: lines.append("  " + line + " ]")
        else: lines.append("  " + line + ",")
      return ("\n" + base_indent).join(lines)
    def format_2d_numeric(arr, depth):
      pad = " " * (depth * indent)
      pad_inner = " " * ((depth + 1) * indent)
      rows = [format_numeric_row(row, pad_inner) for row in arr]
      return ("[\n" + pad_inner
              + (",\n" + pad_inner).join(rows)
              + "\n" + pad + "]")
    def format_flat_dict(d, depth):
      pad = " " * (depth * indent)
      pad_inner = " " * ((depth + 1) * indent)
      entries = [
        f"{json.dumps(k)}: {json.dumps(v)}" for k, v in d.items()
      ]
      lines, current, length = [], [], 0
      for entry in entries:
        added = len(entry) + (2 if current else 0)
        if current and length + added > max_line:
          lines.append(", ".join(current))
          current, length = [entry], len(entry)
        else:
          current.append(entry)
          length += added
      if current: lines.append(", ".join(current))
      return ("{\n" + pad_inner
              + (",\n" + pad_inner).join(lines)
              + "\n" + pad + "}")
    def fmt(v, depth=0):
      pad = " " * (depth * indent)
      pad_inner = " " * ((depth + 1) * indent)
      if is_primitive(v): return json.dumps(v)
      if is_2d_numeric(v): return format_2d_numeric(v, depth)
      if is_numeric_array(v): return format_numeric_array(v, depth)
      if isinstance(v, list):
        if not v: return "[]"
        if fits_line(v): return json.dumps(v)
        items = [fmt(x, depth + 1) for x in v]
        return ("[\n" + pad_inner
                + (",\n" + pad_inner).join(items)
                + "\n" + pad + "]")
      if isinstance(v, dict):
        if not v: return "{}"
        if fits_line(v): return json.dumps(v)
        if compact_dict and is_flat_dict(v):
          return format_flat_dict(v, depth)
        items = []
        for key, val in v.items():
          formatted_val = fmt(val, depth + 1)
          items.append(f"{json.dumps(key)}: {formatted_val}")
        return ("{\n" + pad_inner
                + (",\n" + pad_inner).join(items)
                + "\n" + pad + "}")
      return json.dumps(v)
    return fmt(obj)

  @staticmethod
  def save_smart(
    path: str,
    content: Any,
    max_line: int = 100,
    array_wrap: int = 10,
    compact_dict: bool = True,
  ) -> None:
    """Save JSON with smart formatting."""
    cfg = get_context()
    path = ensure_suffix(path, ".json")
    path = PATH.resolve(path, read=False)
    DIR.ensure(path, is_file=True)
    with open(path, "w", encoding=cfg.encoding) as file:
      file.write(JSON.smart(
        content, max_line=max_line,
        array_wrap=array_wrap, compact_dict=compact_dict,
      ))
      file.write("\n")
