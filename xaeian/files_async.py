# xaeian/files_async.py

"""
Async wrappers for file operations.

Provides async versions of `DIR`, `FILE`, `INI`, `CSV`, `JSON` classes
using `asyncio.to_thread()` for non-blocking file I/O.

Same API as sync versions — just `await` the calls.
Object-oriented access via `AsyncFiles(root_path=...)`.

Example:
  >>> from xaeian.files_async import FILE, JSON, AsyncFiles
  >>> async def main():
  ...   data = await JSON.load("config")
  ...   await FILE.save("log.txt", "done")
  ...   fs = AsyncFiles(root_path="/data")
  ...   await fs.FILE.load("test.txt")
"""

import asyncio
from .files import (
  PATH,
  DIR as _DIR,
  FILE as _FILE,
  INI as _INI,
  CSV as _CSV,
  JSON as _JSON,
  Config, Files,
  get_context, file_context,
  _BoundNamespace,
)

__all__ = [
  "PATH", "DIR", "FILE", "INI", "CSV", "JSON",
  "AsyncFiles",
  "get_context", "file_context",
]

#----------------------------------------------------------------------------- Async namespaces

class DIR:
  """Async directory operations. Same API as `files.DIR`."""

  @staticmethod
  async def ensure(path, is_file=None):
    return await asyncio.to_thread(_DIR.ensure, path, is_file)

  @staticmethod
  async def remove(path, force=False):
    return await asyncio.to_thread(_DIR.remove, path, force)

  @staticmethod
  async def move(src, dst):
    return await asyncio.to_thread(_DIR.move, src, dst)

  @staticmethod
  async def copy(src, dst):
    return await asyncio.to_thread(_DIR.copy, src, dst)

  @staticmethod
  async def folder_list(path, deep=False, basename=False, blacklist=None):
    return await asyncio.to_thread(_DIR.folder_list, path, deep, basename, blacklist)

  @staticmethod
  async def file_list(path, exts=None, match=None, blacklist=None, basename=False, local=False):
    return await asyncio.to_thread(
      _DIR.file_list, path, exts, match, blacklist, basename, local
    )

  @staticmethod
  async def zip(path, zip_output=None, blacklist=None):
    return await asyncio.to_thread(_DIR.zip, path, zip_output, blacklist)

class FILE:
  """Async file read/write operations. Same API as `files.FILE`."""

  @staticmethod
  async def exists(path):
    return await asyncio.to_thread(_FILE.exists, path)

  @staticmethod
  async def remove(path, missing_ok=True):
    return await asyncio.to_thread(_FILE.remove, path, missing_ok)

  @staticmethod
  async def load(path, binary=False):
    return await asyncio.to_thread(_FILE.load, path, binary)

  @staticmethod
  async def load_lines(path):
    return await asyncio.to_thread(_FILE.load_lines, path)

  @staticmethod
  async def save(path, content):
    return await asyncio.to_thread(_FILE.save, path, content)

  @staticmethod
  async def save_lines(path, lines):
    return await asyncio.to_thread(_FILE.save_lines, path, lines)

  @staticmethod
  async def append(path, content):
    return await asyncio.to_thread(_FILE.append, path, content)

  @staticmethod
  async def append_line(path, line, newline="\n"):
    return await asyncio.to_thread(_FILE.append_line, path, line, newline)

  @staticmethod
  async def hash(path, algo="sha256", chunk_size=8192):
    return await asyncio.to_thread(_FILE.hash, path, algo, chunk_size)

  @staticmethod
  async def size(path):
    return await asyncio.to_thread(_FILE.size, path)

  @staticmethod
  async def mtime(path):
    return await asyncio.to_thread(_FILE.mtime, path)

class INI:
  """Async INI file operations."""
  format = staticmethod(_INI.format)
  parse = staticmethod(_INI.parse)

  @staticmethod
  async def load(path):
    return await asyncio.to_thread(_INI.load, path)

  @staticmethod
  async def save(path, data, comment_section=None, comment_field=None,
                 comment_section_char="# ", comment_field_char=" # "):
    return await asyncio.to_thread(
      _INI.save, path, data, comment_section, comment_field,
      comment_section_char, comment_field_char
    )

class CSV:
  """Async CSV file operations."""

  @staticmethod
  async def load(path, delimiter=",", types=None):
    return await asyncio.to_thread(_CSV.load, path, delimiter, types)

  @staticmethod
  async def load_raw(path, delimiter=",", types=None, include_header=True):
    return await asyncio.to_thread(_CSV.load_raw, path, delimiter, types, include_header)

  @staticmethod
  async def load_vectors(path, delimiter=",", types=None, group_by=None):
    return await asyncio.to_thread(_CSV.load_vectors, path, delimiter, types, group_by)

  @staticmethod
  async def add_row(path, datarow, delimiter=","):
    return await asyncio.to_thread(_CSV.add_row, path, datarow, delimiter)

  @staticmethod
  async def save(path, data, field_names=None, delimiter=","):
    return await asyncio.to_thread(_CSV.save, path, data, field_names, delimiter)

  @staticmethod
  async def save_vectors(path, *columns, header=None, delimiter=","):
    return await asyncio.to_thread(
      _CSV.save_vectors, path, *columns, header=header, delimiter=delimiter
    )

class JSON:
  """Async JSON file operations."""
  smart = staticmethod(_JSON.smart)

  @staticmethod
  async def load(path, otherwise=None):
    return await asyncio.to_thread(_JSON.load, path, otherwise)

  @staticmethod
  async def save(path, content):
    return await asyncio.to_thread(_JSON.save, path, content)

  @staticmethod
  async def save_pretty(path, content, indent=2, sort_keys=False):
    return await asyncio.to_thread(_JSON.save_pretty, path, content, indent, sort_keys)

  @staticmethod
  async def save_smart(path, content, max_line=100, array_wrap=10):
    return await asyncio.to_thread(_JSON.save_smart, path, content, max_line, array_wrap)

#---------------------------------------------------------------------- AsyncFiles (bound context)

class _AsyncBoundNamespace:
  """Async proxy that wraps `_BoundNamespace` methods with `asyncio.to_thread`."""

  # Pure computation — no syscalls, no async needed
  _SYNC_ONLY = frozenset({
    "normalize", "expand", "resolve", "local",
    "basename", "dirname", "stem", "ext", "with_suffix", "ensure_suffix",
    "is_under", "join", "match",
    "format", "parse", "_strip_inline_comment", "_cast",
    "smart",
  })

  def __init__(self, bound_ns: _BoundNamespace):
    self._bound = bound_ns
    self._cache: dict = {}

  def __getattr__(self, name: str):
    cached = self._cache.get(name)
    if cached is not None: return cached
    method = getattr(self._bound, name)
    if not callable(method) or name in self._SYNC_ONLY:
      self._cache[name] = method
      return method
    async def wrapper(*args, **kwargs):
      return await asyncio.to_thread(method, *args, **kwargs)
    self._cache[name] = wrapper
    return wrapper

class AsyncFiles:
  """
  Async object-oriented access to file operations with own config context.

  Example:
    >>> fs = AsyncFiles(root_path="/data/project")
    >>> await fs.FILE.load("test.txt")
    >>> await fs.JSON.save("cfg", {"a": 1})
    >>> fs.PATH.resolve("sub/file.txt")  # sync — no IO
  """

  def __init__(self, root_path: str|None = None, **kwargs):
    sync = Files(root_path=root_path, **kwargs)
    self.PATH = sync.PATH  # PATH is all non-IO
    self.DIR = _AsyncBoundNamespace(sync.DIR)
    self.FILE = _AsyncBoundNamespace(sync.FILE)
    self.INI = _AsyncBoundNamespace(sync.INI)
    self.CSV = _AsyncBoundNamespace(sync.CSV)
    self.JSON = _AsyncBoundNamespace(sync.JSON)