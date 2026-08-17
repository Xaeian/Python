# xaeian/files/yaml.py

"""
YAML file operations. Requires `pyyaml`.

Loading goes through `safe_load`, so tags that would construct Python objects are rejected.
"""

__extras__ = ("yaml", ["pyyaml"])

import os
from typing import Any
from .config import get_context
from .path import PATH
from .dir import DIR
from .file import FILE

try:
  import yaml
except ImportError:
  raise ImportError("Install with: pip install xaeian[yaml]")

#----------------------------------------------------------------------------------- YAML namespace

class YAML:
  """YAML read/write, auto `.yaml` extension, `.yml` accepted."""
  EXTS = (".yaml", ".yml")

  @staticmethod
  def _ensure_ext(path:str) -> str:
    """Keep an `EXTS` extension, else append `.yaml`."""
    ext = os.path.splitext(path)[1].lower()
    if ext in YAML.EXTS: return path
    return path + ".yaml"

  @staticmethod
  def _resolve_read(path:str) -> str:
    """Explicit YAML extension wins, else try `.yaml` then `.yml`."""
    ext = os.path.splitext(path)[1].lower()
    if ext in YAML.EXTS: return PATH.resolve(path, read=True)
    for e in YAML.EXTS:
      resolved = PATH.resolve(path + e, read=True)
      if os.path.isfile(resolved): return resolved
    return PATH.resolve(path + ".yaml", read=True)

  @staticmethod
  def load(path:str, otherwise:Any=None) -> Any:
    """Load YAML file, `otherwise` when missing or empty."""
    cfg = get_context()
    resolved = YAML._resolve_read(path)
    if not os.path.isfile(resolved): return otherwise
    with open(resolved, "r", encoding=cfg.encoding) as file:
      content = yaml.safe_load(file)
    return content if content is not None else otherwise

  @staticmethod
  def load_all(path:str) -> list[Any]:
    """Load multi-document YAML, `[]` when missing."""
    cfg = get_context()
    resolved = YAML._resolve_read(path)
    if not os.path.isfile(resolved): return []
    with open(resolved, "r", encoding=cfg.encoding) as file:
      return list(yaml.safe_load_all(file))

  @staticmethod
  def save(path:str, content:Any, flow:bool=False) -> None:
    """Save YAML, block style unless `flow`, key order preserved."""
    path = DIR._resolve_write(YAML._ensure_ext(path), "")
    FILE.save(path, yaml.safe_dump(
      content, default_flow_style=flow,
      allow_unicode=True, sort_keys=False,
    ))

  @staticmethod
  def save_pretty(
    path:str,
    content:Any,
    indent:int = 2,
    sort_keys:bool = False,
    flow:bool = False,
  ) -> None:
    """Save YAML with an explicit indent, keys in insertion order unless `sort_keys`."""
    path = DIR._resolve_write(YAML._ensure_ext(path), "")
    FILE.save(path, yaml.safe_dump(
      content, indent=indent, sort_keys=sort_keys,
      default_flow_style=flow, allow_unicode=True,
    ))

  @staticmethod
  def save_all(path:str, documents:list[Any], flow:bool=False) -> None:
    """Save documents separated by `---`."""
    path = DIR._resolve_write(YAML._ensure_ext(path), "")
    FILE.save(path, yaml.safe_dump_all(
      documents, default_flow_style=flow,
      allow_unicode=True, sort_keys=False,
    ))
