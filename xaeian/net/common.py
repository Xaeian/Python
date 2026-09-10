# xaeian/net/common.py

"""
What every transport shares: the sync vocabulary and the transport-agnostic helpers.

`FTP` and `SFTP` each speak their own protocol; deciding what to skip, keeping a download atomic
and refusing hostile names is the same job on both sides, so it lives here once.
"""

import itertools, os, ntpath, errno
from pathlib import Path
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable, Iterator
from ..files import DIR, PATH
from ..colors import Color as c

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
  # Content digest where the transport carries one, and only `S3` does.
  # A file protocol answers what a file weighs and when it changed, never what is inside it.
  etag: str|None = None

#------------------------------------------------------------------------------------------- Faults

def _gone(remote:str) -> FileNotFoundError:
  """What `SFTP` raises for a path that is not there, so every client reads alike."""
  return FileNotFoundError(errno.ENOENT, "No such file or directory", remote)

def _refused(remote:str) -> PermissionError:
  """Other half of a refusal: the path is there, this login may not have it."""
  return PermissionError(errno.EACCES, "Permission denied", remote)

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

def pruned(rel:str, filter:Filter|None) -> bool:
  """
  Whether `filter` rejects this path, counting the folders above it.

  A flat list of paths carries no directory entries,
  so a filter written to prune a folder would never be asked about one.
  Every ancestor is offered the way a listing offers it, as `name` and as `name/`,
  so one filter prunes one tree on every transport.

  A local side that skipped this would send the excluded files on every run and never read
  one back as unchanged: the remote index pruned them, so nothing over there ever matches.
  """
  if filter is None: return False
  parts = rel.split("/")
  for depth in range(1, len(parts)):
    branch = "/".join(parts[:depth])
    if not (filter(branch) and filter(f"{branch}/")): return True
  return not filter(rel)

def unchanged(rs:Attrs, lmtime:float, lsize:int, *, use_mtime:bool=True) -> bool:
  """Skip check: mtime+size when a trustworthy remote mtime exists, size-only otherwise."""
  if use_mtime and rs.st_mtime is not None:
    return int(rs.st_mtime) == int(lmtime) and rs.st_size == lsize
  return rs.st_size == lsize

def log_sync(log, op:str, actions:list[Action], dry_run:bool) -> None:
  """One line for a whole sync: what it moved, what it left alone, and whether it moved it."""
  if not log: return
  counts = {k: sum(1 for a, _ in actions if a == k) for k in ("put", "get", "skip", "delete")}
  hue = {"put": c.LIME, "skip": c.MAGNTA}
  parts = [f"{k}:{hue.get(k, c.CYAN)}{v}{c.END}" for k, v in counts.items() if v]
  suffix = f" {c.GREY}(dry){c.END}" if dry_run else ""
  log.inf(f"{op} {' '.join(parts)}{suffix}")
