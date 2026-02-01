# xaeian/files_async.py

"""
Async wrappers for file operations.

Provides async versions of `DIR`, `FILE`, `INI`, `CSV`, `JSON` classes
using `asyncio.to_thread()` for non-blocking file I/O.

Same API as sync versions — just `await` the calls.

Example:
  >>> from xaeian.files_async import FILE, JSON
  >>> async def main():
  ...   data = await JSON.load("config")
  ...   await FILE.save("log.txt", "done")
"""

import asyncio
from .files import (
  PATH,
  DIR as _DIR,
  FILE as _FILE,
  INI as _INI,
  CSV as _CSV,
  JSON as _JSON,
  get_context, set_context, files_context,
)

__all__ = [
  "PATH", "DIR", "FILE", "INI", "CSV", "JSON",
  "get_context", "set_context", "files_context",
]

class DIR:
  """Async directory operations. Same API as `files.DIR`."""
  ensure = staticmethod(_DIR.ensure)

  @staticmethod
  async def remove(path, force=False):
    return await asyncio.to_thread(_DIR.remove, path, force)

  @staticmethod
  async def remove_empty(path, force=False):
    return await asyncio.to_thread(_DIR.remove_empty, path, force)

  @staticmethod
  async def move(src, dst):
    return await asyncio.to_thread(_DIR.move, src, dst)

  @staticmethod
  async def copy(src, dst):
    return await asyncio.to_thread(_DIR.copy, src, dst)

  @staticmethod
  async def folder_list(path, deep=False, basename=False):
    return await asyncio.to_thread(_DIR.folder_list, path, deep, basename)

  @staticmethod
  async def file_list(path, exts=None, blacklist=None, basename=False):
    return await asyncio.to_thread(_DIR.file_list, path, exts, blacklist, basename)

  @staticmethod
  async def zip(path, zip_output=None):
    return await asyncio.to_thread(_DIR.zip, path, zip_output)

class FILE:
  """Async file read/write operations. Same API as `files.FILE`."""

  @staticmethod
  async def exists(path):
    return await asyncio.to_thread(_FILE.exists, path)

  @staticmethod
  async def remove(path):
    return await asyncio.to_thread(_FILE.remove, path)

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

class INI:
  """Async INI file operations."""
  format = staticmethod(_INI.format)
  parse = staticmethod(_INI.parse)

  @staticmethod
  async def load(path, otherwise=None):
    return await asyncio.to_thread(_INI.load, path, otherwise)

  @staticmethod
  async def save_raw(path, data):
    return await asyncio.to_thread(_INI.save_raw, path, data)

  @staticmethod
  async def save(path, data):
    return await asyncio.to_thread(_INI.save, path, data)

class CSV:
  """Async CSV file operations."""
  
  @staticmethod
  async def load(path, delimiter=",", types=None):
    return await asyncio.to_thread(_CSV.load, path, delimiter, types)

  @staticmethod
  async def load_vectors(path, delimiter=",", header=True):
    return await asyncio.to_thread(_CSV.load_vectors, path, delimiter, header)

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
