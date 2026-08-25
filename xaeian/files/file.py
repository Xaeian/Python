# xaeian/files/file.py

"""File read/write operations."""

import os, hashlib, itertools
from typing import Iterator, Sequence
from .config import get_context
from .path import PATH
from .dir import DIR

_tmp_seq = itertools.count()
"""Serial number for temporary files: the PID alone lets two threads share one temp."""

#----------------------------------------------------------------------------------- FILE namespace

class FILE:
  """Static file helpers; paths resolve and text encodes per the active `Config`."""
  @staticmethod
  def exists(path:str|Sequence[str]) -> bool:
    """Check that every given path is an existing file."""
    if isinstance(path, str): path = [path]
    for p in path:
      p = PATH.resolve(p, read=True)
      if not os.path.isfile(p): return False
    return True

  @staticmethod
  def remove(path:str|Sequence[str], missing_ok:bool=True) -> bool:
    """Remove file(s). Missing ones give `False`, or raise when `missing_ok=False`."""
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
    """Load text file as list of lines, line endings kept."""
    cfg = get_context()
    path = PATH.resolve(path, read=True)
    with open(path, "r", encoding=cfg.encoding) as file:
      return file.readlines()

  @staticmethod
  def iter_lines(path:str, strip:bool=False) -> Iterator[str]:
    """Iterate lines from text file without loading it whole; line ends kept unless `strip`."""
    cfg = get_context()
    path = PATH.resolve(path, read=True)
    with open(path, "r", encoding=cfg.encoding) as file:
      for line in file:
        yield line.strip() if strip else line

  @staticmethod
  def save(path:str, content:str|bytes, chmod:int|None=None) -> None:
    """
    Save whole content to file, atomically replacing any previous version.

    The content goes to a temporary file beside the target, swapped in with `os.replace`.
    An interrupted or failing write leaves the previous file untouched,
    and a reader sees the old content or the new, never a partial mix.
    The swap gives the target a new inode,
    so a hardlink or an already-open reader keeps the old content.

    `chmod` is a POSIX mode, e.g. `0o600` for secrets.
    The temporary file is created with it, so the content is never briefly readable by others.
    On Windows only the read-only bit carries over.

    Two threads saving one path each get their own temporary file,
    so the target holds one writer's complete content, never a blend.
    They do not both succeed: on Windows the losing `os.replace` raises `PermissionError`,
    so serialize the writers if every save matters.
    """
    cfg = get_context()
    path = PATH.resolve(path, read=False)
    DIR.ensure(path, is_file=True)
    binary = isinstance(content, bytes)
    mode = "wb" if binary else "w"
    encoding = None if binary else cfg.encoding
    newline = None if binary else ""
    tmp = f"{path}.{os.getpid()}.{next(_tmp_seq)}.tmp"
    try:
      if chmod is None:
        with open(tmp, mode, encoding=encoding, newline=newline) as file:
          file.write(content)
      else:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, chmod)
        with os.fdopen(fd, mode, encoding=encoding, newline=newline) as file:
          file.write(content)
      os.replace(tmp, path)
    except BaseException: # so Ctrl+C leaves no stray temporary behind
      if os.path.exists(tmp): os.remove(tmp)
      raise

  @staticmethod
  def save_lines(path:str, lines:list[str]) -> None:
    """Save list of lines to text file, joined as-is; the lines carry their own line ends."""
    FILE.save(path, "".join(lines))

  @staticmethod
  def append(path:str, content:str|bytes) -> None:
    """Append content to file, creating it if needed; text is written verbatim, as `save` does."""
    cfg = get_context()
    path = PATH.resolve(path, read=False)
    DIR.ensure(path, is_file=True)
    binary = isinstance(content, bytes)
    mode = "ab" if binary else "a"
    encoding = None if binary else cfg.encoding
    with open(path, mode, encoding=encoding, newline=None if binary else "") as file:
      file.write(content)

  @staticmethod
  def append_line(path:str, line:str, newline:str="\n") -> None:
    """Append single text line to file."""
    FILE.append(path, line + newline)

  @staticmethod
  def hash(path:str, algo:str="sha256", chunk_size:int=8192) -> str:
    """Hex digest of file content, read in chunks. `algo`: any `hashlib` name (md5, sha256)."""
    path = PATH.resolve(path, read=True)
    h = hashlib.new(algo)
    with open(path, "rb") as file:
      while chunk := file.read(chunk_size):
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
