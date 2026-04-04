# xaeian/files/file.py

"""File read/write operations."""

import os, hashlib
from typing import Iterator, Sequence
from .config import get_context
from .path import PATH
from .dir import DIR

#------------------------------------------------------------------------------- FILE namespace

class FILE:
  """
  File read/write operations.

  Example:
    >>> FILE.save("data/log.txt", "Hello!")
    >>> content = FILE.load("data/log.txt")
  """

  @staticmethod
  def exists(path:str|Sequence[str]) -> bool:
    """Check if file(s) exist."""
    if isinstance(path, str): path = [path]
    for p in path:
      p = PATH.resolve(p, read=True)
      if not os.path.isfile(p): return False
    return True

  @staticmethod
  def remove(path:str|Sequence[str], missing_ok:bool=True) -> bool:
    """Remove file(s)."""
    if isinstance(path, str): path = [path]
    success = True
    for p in path:
      p = PATH.resolve(p, read=False)
      try:
        os.remove(p)
      except FileNotFoundError:
        if not missing_ok: raise
        success = False
    return success

  @staticmethod
  def load(path:str, binary:bool=False) -> str|bytes:
    """Load entire file content."""
    cfg = get_context()
    path = PATH.resolve(path, read=True)
    mode = "rb" if binary else "r"
    encoding = None if binary else cfg.encoding
    with open(path, mode, encoding=encoding) as file:
      return file.read()

  @staticmethod
  def load_lines(path:str) -> list[str]:
    """Load text file as list of lines."""
    cfg = get_context()
    path = PATH.resolve(path, read=True)
    with open(path, "r", encoding=cfg.encoding) as file:
      return file.readlines()

  @staticmethod
  def iter_lines(path:str, strip:bool=False) -> Iterator[str]:
    """
    Iterate lines from text file without loading entire content.

    Args:
      path: File path.
      strip: Strip whitespace from each line when True.

    Yields:
      Lines from file.

    Example:
      >>> for line in FILE.iter_lines("big.log", strip=True):
      ...   if "ERROR" in line: print(line)
    """
    cfg = get_context()
    path = PATH.resolve(path, read=True)
    with open(path, "r", encoding=cfg.encoding) as file:
      for line in file:
        yield line.strip() if strip else line

  @staticmethod
  def save(path:str, content:str|bytes):
    """Save whole content to file (overwrite)."""
    cfg = get_context()
    path = PATH.resolve(path, read=False)
    DIR.ensure(path, is_file=True)
    mode = "wb" if isinstance(content, bytes) else "w"
    encoding = None if mode == "wb" else cfg.encoding
    with open(path, mode, encoding=encoding) as file:
      file.write(content)

  @staticmethod
  def save_lines(path:str, lines:list[str]):
    """Save list of lines to text file."""
    FILE.save(path, "".join(lines))

  @staticmethod
  def append(path:str, content:str|bytes):
    """Append content to file, creating it if needed."""
    cfg = get_context()
    path = PATH.resolve(path, read=False)
    DIR.ensure(path, is_file=True)
    mode = "ab" if isinstance(content, bytes) else "a"
    encoding = None if mode == "ab" else cfg.encoding
    with open(path, mode, encoding=encoding) as file:
      file.write(content)

  @staticmethod
  def append_line(path:str, line:str, newline:str="\n"):
    """Append single text line to file."""
    FILE.append(path, line + newline)

  @staticmethod
  def hash(path:str, algo:str="sha256", chunk_size:int=8192) -> str:
    """
    Calculate file hash.

    Args:
      path: File path.
      algo: Hash algorithm (md5, sha1, sha256, sha512).
      chunk_size: Read buffer size.

    Example:
      >>> FILE.hash("data.bin", algo="md5")
      'd41d8cd98f00b204e9800998ecf8427e'
    """
    path = PATH.resolve(path, read=True)
    h = hashlib.new(algo)
    with open(path, "rb") as f:
      while chunk := f.read(chunk_size):
        h.update(chunk)
    return h.hexdigest()

  @staticmethod
  def size(path:str) -> int:
    """Return file size in bytes."""
    return os.path.getsize(PATH.resolve(path))

  @staticmethod
  def mtime(path:str) -> float:
    """Return file modification time as Unix timestamp."""
    return os.path.getmtime(PATH.resolve(path))