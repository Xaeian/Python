# xaeian/files/yaml.py

"""
YAML file operations.

Requires: `pyyaml`

Example:
  >>> from xaeian import YAML
  >>> YAML.save("config", {"debug": True, "port": 8080})
  >>> data = YAML.load("config")
"""

__extras__ = ("yaml", ["pyyaml"])

import os
from typing import Any
from .config import get_context
from .path import PATH
from .dir import DIR
from ..xstring import ensure_suffix

try:
  import yaml
except ImportError:
  raise ImportError("Install with: pip install xaeian[yaml]")

#------------------------------------------------------------------------------- YAML namespace

class YAML:
  """YAML file operations. Auto-adds `.yaml`, accepts `.yml` on load."""

  @staticmethod
  def _resolve_read(path:str) -> str:
    """Try `.yaml` then `.yml`: return first existing."""
    for ext in (".yaml", ".yml"):
      resolved = PATH.resolve(ensure_suffix(path, ext), read=True)
      if os.path.isfile(resolved): return resolved
    return PATH.resolve(ensure_suffix(path, ".yaml"), read=True)

  @staticmethod
  def load(path:str, otherwise:Any=None) -> Any:
    """Load YAML file. Tries `.yaml` then `.yml`."""
    cfg = get_context()
    resolved = YAML._resolve_read(path)
    if not os.path.isfile(resolved): return otherwise
    with open(resolved, "r", encoding=cfg.encoding) as file:
      content = yaml.safe_load(file)
    return content if content is not None else otherwise

  @staticmethod
  def load_all(path:str) -> list[Any]:
    """Load multi-document YAML file."""
    cfg = get_context()
    resolved = YAML._resolve_read(path)
    if not os.path.isfile(resolved): return []
    with open(resolved, "r", encoding=cfg.encoding) as file:
      return list(yaml.safe_load_all(file))

  @staticmethod
  def save(path:str, content:Any, flow:bool=False) -> None:
    """Save data to YAML file (block style by default)."""
    cfg = get_context()
    path = ensure_suffix(path, ".yaml")
    path = PATH.resolve(path, read=False)
    DIR.ensure(path, is_file=True)
    with open(path, "w", encoding=cfg.encoding) as file:
      yaml.safe_dump(
        content, file, default_flow_style=flow,
        allow_unicode=True, sort_keys=False,
      )

  @staticmethod
  def save_pretty(path:str, content:Any, indent:int=2,
                  sort_keys:bool=False, flow:bool=False) -> None:
    """Save YAML with explicit formatting options."""
    cfg = get_context()
    path = ensure_suffix(path, ".yaml")
    path = PATH.resolve(path, read=False)
    DIR.ensure(path, is_file=True)
    with open(path, "w", encoding=cfg.encoding) as file:
      yaml.safe_dump(
        content, file, indent=indent, sort_keys=sort_keys,
        default_flow_style=flow, allow_unicode=True,
      )

  @staticmethod
  def save_all(path:str, documents:list[Any],
               flow:bool=False) -> None:
    """Save multiple documents to YAML file (separated by `---`)."""
    cfg = get_context()
    path = ensure_suffix(path, ".yaml")
    path = PATH.resolve(path, read=False)
    DIR.ensure(path, is_file=True)
    with open(path, "w", encoding=cfg.encoding) as file:
      yaml.safe_dump_all(
        documents, file, default_flow_style=flow,
        allow_unicode=True, sort_keys=False,
      )