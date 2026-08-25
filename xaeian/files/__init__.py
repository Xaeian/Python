# xaeian/files/__init__.py

"""
File operations with context-based path resolution.

Namespace classes `PATH`, `DIR`, `FILE`, `INI`, `CSV`, `JSON` and `YAML` (needs `pyyaml`).
Paths resolve against the global context set by `file_context()`,
or against an isolated root held by an instance of `Files(root_path=...)`.
"""

from importlib import import_module
from typing import TYPE_CHECKING, Any
from .config import Config, get_context, set_context, file_context
from .path import PATH
from .dir import DIR
from .file import FILE
from .ini import INI
from .csv import CSV
from .json import JSON
from .bound import _BoundNamespace, Files

__all__ = [
  "Config", "get_context", "set_context", "file_context",
  "PATH", "DIR", "FILE", "INI", "CSV", "JSON",
  "Files", "YAML",
]

if TYPE_CHECKING: # so a checker and an editor see the real type
  from .yaml import YAML

def __getattr__(name:str) -> Any:
  """`YAML` loads on first use; importing it eagerly pulls `pyyaml` into every `import xaeian`."""
  if name != "YAML": raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
  globals()[name] = value = import_module(".yaml", __name__).YAML
  return value

def __dir__() -> list[str]:
  return sorted(set(globals()) | set(__all__))
