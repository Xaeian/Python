# xaeian/files/config.py

"""Core configuration and context management for file operations."""

import os, sys
from typing import Any
from dataclasses import dataclass, replace
from contextlib import contextmanager
from contextvars import ContextVar

#-------------------------------------------------------------------------------------- Core config

def _default_root_path() -> str:
  if getattr(sys, "frozen", False): return os.path.dirname(sys.executable)
  return os.getcwd()

@dataclass
class Config:
  """
  Path and IO configuration.

  Attributes:
    bundle: Use PyInstaller bundle (`_MEIPASS`) when available.
    root_path: Base for relative paths, defaults to the executable dir when frozen, else cwd.
    auto_resolve: Join relative paths with `root_path` when `True`.
    posix_slash: Normalize backslashes to `"/"` when `True`.
    clean: Collapse `"//"` and `"/./"` segments when `True`.
    encoding: Text encoding for reads and writes, ignored in binary mode.
  """
  bundle: bool = False
  root_path: str|None = None
  auto_resolve: bool = True
  posix_slash: bool = True
  clean: bool = True
  encoding: str = "utf-8"

  def __post_init__(self):
    if self.root_path is None:
      self.root_path = _default_root_path()
    elif not os.path.isabs(self.root_path):
      self.root_path = os.path.abspath(self.root_path)

# The default Config is built at import, so its `root_path` snapshots the cwd at import time.
_context: ContextVar[Config] = ContextVar("xaeian_files_config", default=Config())

def get_context() -> Config:
  """Configuration active for this context/thread."""
  return _context.get()

def set_context(**overrides) -> Config:
  """Apply config overrides to this context/thread; `file_context()` scopes them to a block."""
  cfg = get_context()
  new_cfg = replace(cfg, **overrides)
  _context.set(new_cfg)
  return new_cfg

@contextmanager
def file_context(**overrides:Any):
  """Temporarily override configuration within a block."""
  cfg = get_context()
  new_cfg = replace(cfg, **overrides) if overrides else cfg
  token = _context.set(new_cfg)
  try:
    yield new_cfg
  finally:
    _context.reset(token)
