# xaeian/net/common.py

"""
What every transport shares: the sync vocabulary and the transport-agnostic helpers.

`FTP` and `SFTP` each speak their own protocol; deciding what to skip, keeping a download atomic
and refusing hostile names is the same job on both sides, so it lives here once.
"""

import itertools, os, ntpath
from pathlib import Path
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable, Iterator
from ..files import DIR, PATH

_tmp_seq = itertools.count()

#-------------------------------------------------------------------------------------------- Types

# (rel_path) → keep? `False` skips it; a directory must pass both `rel` and `rel/`
Filter = Callable[[str], bool]
# (path, bytes_done, bytes_total): rel path for sync/dir, remote path for a single file
Progress = Callable[[str, int, int], None]
# ("put"|"get"|"skip"|"delete", rel_path)
Action = tuple[str, str]

@dataclass
class Attrs:
  """Remote file attributes, named after `paramiko.SFTPAttributes` so sync code is shared."""
  st_size: int = 0
  st_mtime: float|None = None # UTC epoch; None if server lacks MLSD/MDTM
  filename: str = ""
  is_dir: bool = False

#------------------------------------------------------------------------------------------ Helpers

def local_index(root:str) -> dict[str, Path]:
  """
  Every file under `root`, keyed by its path relative to it.

  The walk stops at a linked directory.
  Following one would upload a file from beside the tree as though it came from inside.
  """
  base = PATH.resolve(root)
  return {PATH.normalize(os.path.relpath(f, base)): Path(f) for f in DIR.iter_files(root)}

@contextmanager
def atomic_local(local:str) -> Iterator[str]:
  """
  Yield a temp path beside `local`, swapped in only once the block completes.

  Creates the missing parent directories, so a download never has to.
  A failed transfer must not eat the file it was refreshing.
  """
  Path(local).parent.mkdir(parents=True, exist_ok=True)
  # pid and counter: a remote `X.tmp` cannot collide with `X`'s temp, nor two transfers
  tmp = f"{local}.{os.getpid()}.{next(_tmp_seq)}.tmp"
  try:
    yield tmp
    os.replace(tmp, local)
  except BaseException: # Ctrl+C must leave no stray temporary behind
    Path(tmp).unlink(missing_ok=True)
    raise

def safe_name(name:str) -> bool:
  """Reject empty, `.`, `..`, separators and drives: a server must not write outside the root."""
  return bool(name) and name not in (".", "..") and ntpath.basename(name) == name

def unchanged(rs:Attrs, lmtime:float, lsize:int, *, use_mtime:bool=True) -> bool:
  """Skip check: mtime+size when a trustworthy remote mtime exists, size-only otherwise."""
  if use_mtime and rs.st_mtime is not None:
    return int(rs.st_mtime) == int(lmtime) and rs.st_size == lsize
  return rs.st_size == lsize
