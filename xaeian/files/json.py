# xaeian/files/json.py

"""JSON file operations."""

import os, json
from typing import Any
from .config import get_context
from .path import PATH
from .dir import DIR
from .file import FILE
from ..xstring import ensure_suffix

#----------------------------------------------------------------------------------- JSON namespace

class JSON:
  """JSON read/write, auto `.json` extension."""
  @staticmethod
  def load(path:str, otherwise:Any=None) -> Any:
    """Load JSON file, `otherwise` when missing or empty."""
    cfg = get_context()
    path = ensure_suffix(path, ".json")
    path = PATH.resolve(path, read=True)
    if not os.path.isfile(path): return otherwise
    with open(path, "r", encoding=cfg.encoding) as file:
      content = file.read()
    if not content: return otherwise
    return json.loads(content)

  @staticmethod
  def save(path:str, content:Any, ensure_ascii:bool=False) -> None:
    """Save JSON in compact form, no whitespace."""
    path = DIR._resolve_write(path, ".json")
    FILE.save(path, json.dumps(content, separators=(",", ":"), ensure_ascii=ensure_ascii))

  @staticmethod
  def save_pretty(
    path:str,
    content:Any,
    indent:int = 2,
    sort_keys:bool = False,
    ensure_ascii:bool = False,
  ) -> None:
    """Save JSON indented, LF line ends, trailing newline."""
    path = DIR._resolve_write(path, ".json")
    text = json.dumps(content, indent=indent, ensure_ascii=ensure_ascii, sort_keys=sort_keys)
    FILE.save(path, text + "\n")

  @staticmethod
  def smart(
    obj:Any,
    indent:int = 2,
    max_line:int = 100,
    array_wrap:int = 10,
    compact_dict:bool = True,
    ensure_ascii:bool = False,
  ) -> str:
    """
    Format JSON for reading: a value stays on one line while its compact form fits `max_line`.

    Numeric arrays wrap every `array_wrap` values, 2D numeric arrays get one row per line, and
    `compact_dict` packs flat dicts several entries per line instead of one key per line.
    """
    def _dumps(v, **kw):
      return json.dumps(v, ensure_ascii=ensure_ascii, **kw)
    def dump_key(k):
      if not isinstance(k, str): k = _dumps(k) # `json.dumps` quotes non-string keys, so do that
      return _dumps(k)
    def is_primitive(v):
      return v is None or isinstance(v, (bool, int, float, str))
    def is_numeric_array(v):
      return isinstance(v, list) and v and all(isinstance(x, (int, float)) for x in v)
    def is_2d_numeric(v):
      return isinstance(v, list) and v and all(is_numeric_array(row) for row in v)
    def is_flat_dict(v):
      return isinstance(v, dict) and v and all(is_primitive(val) for val in v.values())
    def compact(v):
      return _dumps(v, separators=(",", ":"))
    def fits_line(v):
      return len(compact(v)) <= max_line
    def format_numeric_array(arr, depth):
      if len(arr) <= array_wrap and fits_line(arr): return _dumps(arr)
      pad = " " * (depth * indent)
      pad_inner = " " * ((depth + 1) * indent)
      chunks = [arr[i:i + array_wrap] for i in range(0, len(arr), array_wrap)]
      lines = [_dumps(chunk)[1:-1] for chunk in chunks]
      return "[\n" + pad_inner + (",\n" + pad_inner).join(lines) + "\n" + pad + "]"
    def format_numeric_row(arr, base_indent):
      if fits_line(arr): return _dumps(arr)
      chunks = [arr[i:i + array_wrap] for i in range(0, len(arr), array_wrap)]
      if len(chunks) == 1: return "[ " + _dumps(chunks[0])[1:-1] + " ]"
      lines = []
      for i, chunk in enumerate(chunks):
        line = _dumps(chunk)[1:-1]
        if i == 0: lines.append("[ " + line + ",")
        elif i == len(chunks) - 1: lines.append("  " + line + " ]")
        else: lines.append("  " + line + ",")
      return ("\n" + base_indent).join(lines)
    def format_2d_numeric(arr, depth):
      pad = " " * (depth * indent)
      pad_inner = " " * ((depth + 1) * indent)
      rows = [format_numeric_row(row, pad_inner) for row in arr]
      return "[\n" + pad_inner + (",\n" + pad_inner).join(rows) + "\n" + pad + "]"
    def format_flat_dict(d, depth):
      pad = " " * (depth * indent)
      pad_inner = " " * ((depth + 1) * indent)
      entries = [f"{dump_key(k)}: {_dumps(v)}" for k, v in d.items()]
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
      return "{\n" + pad_inner + (",\n" + pad_inner).join(lines) + "\n" + pad + "}"
    def fmt(v, depth=0):
      pad = " " * (depth * indent)
      pad_inner = " " * ((depth + 1) * indent)
      if is_primitive(v): return _dumps(v)
      if is_2d_numeric(v): return format_2d_numeric(v, depth)
      if is_numeric_array(v): return format_numeric_array(v, depth)
      if isinstance(v, list):
        if not v: return "[]"
        if fits_line(v): return _dumps(v)
        items = [fmt(x, depth + 1) for x in v]
        return "[\n" + pad_inner + (",\n" + pad_inner).join(items) + "\n" + pad + "]"
      if isinstance(v, dict):
        if not v: return "{}"
        if fits_line(v): return _dumps(v)
        if compact_dict and is_flat_dict(v):
          return format_flat_dict(v, depth)
        items = []
        for key, val in v.items():
          formatted_val = fmt(val, depth + 1)
          items.append(f"{dump_key(key)}: {formatted_val}")
        return "{\n" + pad_inner + (",\n" + pad_inner).join(items) + "\n" + pad + "}"
      return _dumps(v)
    return fmt(obj)

  @staticmethod
  def save_smart(
    path:str,
    content:Any,
    max_line:int = 100,
    array_wrap:int = 10,
    compact_dict:bool = True,
    ensure_ascii:bool = False,
  ) -> None:
    """Save JSON formatted by `smart`, LF line ends, trailing newline."""
    path = DIR._resolve_write(path, ".json")
    text = JSON.smart(
      content, max_line=max_line, array_wrap=array_wrap,
      compact_dict=compact_dict, ensure_ascii=ensure_ascii,
    )
    FILE.save(path, text + "\n")
