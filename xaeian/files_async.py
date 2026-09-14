# xaeian/files_async.py

"""
Async wrappers for file operations.

`DIR`, `FILE`, `INI`, `CSV`, `JSON` and `YAML` offloaded to `asyncio.to_thread()`.
Same API as the sync versions, just `await` the calls.

Called directly, not awaited: the pure helpers `INI.format`, `INI.parse` and `JSON.smart`,
which never touch the filesystem, and the generators `DIR.iter_files` and `FILE.iter_lines`,
which the caller drives. `PATH` is sync throughout.

Each name is listed once here and takes its signature from the sync method it wraps,
so the class reads as a method list and a type checker still sees every parameter.

Example:
  >>> await FILE.save("config.json", "{}")
  >>> fs = AsyncFiles(root_path="/data")
  >>> await fs.JSON.load("state")
"""

import asyncio
from functools import wraps
from inspect import isgeneratorfunction
from typing import Any, Awaitable, Callable, ParamSpec, TypeVar
from .files import (
  PATH, DIR as _DIR, FILE as _FILE, INI as _INI, CSV as _CSV, JSON as _JSON,
  Files, get_context, set_context, file_context, _BoundNamespace,
)

__all__ = [
  "PATH", "DIR", "FILE", "INI", "CSV", "JSON", "YAML",
  "AsyncFiles",
  "get_context", "set_context", "file_context",
]

#------------------------------------------------------------------------------------------ Offload

P = ParamSpec("P")
R = TypeVar("R")

PURE = frozenset({"format", "parse", "smart"})
"""Helpers that only shape text. A worker thread would cost more than the call itself."""

def _stays_sync(name:str, method) -> bool:
  """A generator is driven by the caller, and a pure helper has no IO to wait for."""
  return name in PURE or isgeneratorfunction(method)

def _offload(method:Callable[P, R]) -> Callable[P, Awaitable[R]]:
  """
  Same call, run in a worker thread.

  `ParamSpec` is what carries the wrapped signature through to the awaited twin.
  """
  @wraps(method)
  async def wrapper(*args:P.args, **kwargs:P.kwargs) -> R:
    return await asyncio.to_thread(method, *args, **kwargs)
  return wrapper

#--------------------------------------------------------------------------------- Async namespaces

class DIR:
  """Async directory operations."""
  exists = _offload(_DIR.exists)
  ensure = _offload(_DIR.ensure)
  remove = _offload(_DIR.remove)
  move = _offload(_DIR.move)
  copy = _offload(_DIR.copy)
  folder_list = _offload(_DIR.folder_list)
  file_list = _offload(_DIR.file_list)
  mtime = _offload(_DIR.mtime)
  zip = _offload(_DIR.zip)
  unzip = _offload(_DIR.unzip)
  unzip_bytes = _offload(_DIR.unzip_bytes)
  iter_files = _DIR.iter_files # generator: the caller drives it

class FILE:
  """Async file operations."""
  load = _offload(_FILE.load)
  save = _offload(_FILE.save)
  append = _offload(_FILE.append)
  load_lines = _offload(_FILE.load_lines)
  save_lines = _offload(_FILE.save_lines)
  append_line = _offload(_FILE.append_line)
  exists = _offload(_FILE.exists)
  remove = _offload(_FILE.remove)
  size = _offload(_FILE.size)
  mtime = _offload(_FILE.mtime)
  hash = _offload(_FILE.hash)
  iter_lines = _FILE.iter_lines # generator: the caller drives it
  atomic = _FILE.atomic # context manager: the caller drives it

class INI:
  """Async INI operations."""
  EXTS = _INI.EXTS
  load = _offload(_INI.load)
  save = _offload(_INI.save)
  format = _INI.format # pure: no IO to wait for
  parse = _INI.parse # pure: no IO to wait for

class CSV:
  """Async CSV operations."""
  load = _offload(_CSV.load)
  load_raw = _offload(_CSV.load_raw)
  load_vectors = _offload(_CSV.load_vectors)
  save = _offload(_CSV.save)
  save_vectors = _offload(_CSV.save_vectors)
  add_row = _offload(_CSV.add_row)

class JSON:
  """Async JSON operations."""
  load = _offload(_JSON.load)
  save = _offload(_JSON.save)
  save_pretty = _offload(_JSON.save_pretty)
  save_smart = _offload(_JSON.save_smart)
  smart = _JSON.smart # pure: no IO to wait for

def __getattr__(name:str) -> Any:
  """`YAML` is built on first use, mirroring the sync side."""
  if name != "YAML": raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
  from .files.yaml import YAML as _YAML
  class YAML:
    """Async YAML operations."""
    EXTS = _YAML.EXTS
    load = _offload(_YAML.load)
    load_all = _offload(_YAML.load_all)
    save = _offload(_YAML.save)
    save_all = _offload(_YAML.save_all)
    save_pretty = _offload(_YAML.save_pretty)
  globals()[name] = YAML
  return YAML

#----------------------------------------------------------------------- AsyncFiles (bound context)

class _AsyncBoundNamespace:
  """Async proxy over `_BoundNamespace`, offloading by the same rule as the namespaces above."""
  def __init__(self, bound_ns:_BoundNamespace) -> None:
    self._bound = bound_ns
    self._cache: dict = {}

  def __getattr__(self, name:str) -> Any:
    cached = self._cache.get(name)
    if cached is not None: return cached
    method = getattr(self._bound, name)
    if callable(method) and not _stays_sync(name, getattr(self._bound._cls, name, method)):
      method = _offload(method)
    self._cache[name] = method
    return method

class AsyncFiles:
  """
  Async object-oriented access to file operations with own config context.

  `PATH`, the pure helpers and the generators stay sync, every other call is awaited.

  Example:
    >>> fs = AsyncFiles(root_path="/data/project")
    >>> await fs.FILE.load("test.txt")
  """
  def __init__(self, root_path:str|None=None, **kwargs) -> None:
    sync = Files(root_path=root_path, **kwargs)
    self.PATH = sync.PATH
    self.DIR = _AsyncBoundNamespace(sync.DIR)
    self.FILE = _AsyncBoundNamespace(sync.FILE)
    self.INI = _AsyncBoundNamespace(sync.INI)
    self.CSV = _AsyncBoundNamespace(sync.CSV)
    self.JSON = _AsyncBoundNamespace(sync.JSON)
    self._sync = sync

  def __getattr__(self, name:str) -> _AsyncBoundNamespace:
    """`YAML` binds on first use, as it does on `Files`: the twins keep one surface."""
    if name != "YAML": raise AttributeError(name)
    bound = _AsyncBoundNamespace(self._sync.YAML)
    setattr(self, name, bound)
    return bound
