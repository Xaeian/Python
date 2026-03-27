# xaeian/files/config.py

"""Core configuration and context management for file operations."""

import os, sys
from typing import Any
from dataclasses import dataclass, replace
from contextlib import contextmanager
from contextvars import ContextVar

#---------------------------------------------------------------------------------- Core config

def _default_root_path() -> str:
  if getattr(sys, "frozen", False): return os.path.dirname(sys.executable)
  return os.getcwd()

@dataclass
class Config:
  """
  Global path and IO configuration.

  Attributes:
    bundle: Use PyInstaller bundle (`_MEIPASS`) when available.
    root_path: Base directory for resolving relative paths.
    auto_resolve: Join relative paths with `root_path` when `True`.
    posix_slash: Normalize backslashes to `"/"` when `True`.
    clean: Collapse `"//"` and `"/./"` segments when `True`.
    encoding: Default text encoding for file operations.
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

_context: ContextVar[Config] = ContextVar(
  "xaeian_files_config", default=Config()
)

def get_context() -> Config:
  """Get current configuration for this context/thread."""
  return _context.get()

def set_context(**overrides) -> Config:
  """Set global file context configuration."""
  cfg = get_context()
  new_cfg = replace(cfg, **overrides)
  if new_cfg.root_path is None:
    new_cfg = replace(new_cfg, root_path=_default_root_path())
  _context.set(new_cfg)
  return new_cfg

@contextmanager
def file_context(**overrides:Any):
  """Temporarily override configuration within a block."""
  cfg = get_context()
  if overrides:
    new_cfg = replace(cfg, **overrides)
    if new_cfg.root_path is None:
      new_cfg = replace(new_cfg, root_path=_default_root_path())
  else:
    new_cfg = cfg
  token = _context.set(new_cfg)
  try:
    yield new_cfg
  finally:
    _context.reset(token)
