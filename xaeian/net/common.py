# xaeian/net/common.py

"""
What every transport shares: the sync vocabulary and the rules behind it.

Each client speaks its own protocol.
What to skip, how one filter prunes a tree, which names to refuse: the same on all of them,
so it lives here once.
"""

import itertools, os, ntpath, errno
from pathlib import Path
from dataclasses import dataclass
from typing import Callable
from ..log import Logger, Print
from ..files import DIR, PATH
from ..colors import Color as c

_tmp_seq = itertools.count()  # numbers the remote `.tmp` a put lands beside its target
CHUNK = 2**20                 # read size for a streamed transfer, download and digest alike
TIMEOUT_S = 30                # to open a connection, on every transport

#-------------------------------------------------------------------------------------------- Types

Filter = Callable[[str], bool]
"""`(rel) → keep`. A folder is asked twice, as `name` and as `name/`."""

Progress = Callable[[str, int, int], None]
"""
`(path, done, total)` in bytes, `total` 0 when unknown.
`path` is the rel path in a sync, the remote path for a single file.
"""

Action = tuple[str, str]
"""`("put"|"get"|"skip"|"delete", rel)`."""

@dataclass
class Attrs:
  """Remote file attributes, named after `paramiko.SFTPAttributes` so sync code is shared."""
  st_size: int = 0
  st_mtime: float|None = None # UTC epoch, `None` when the transport has no timestamp
  filename: str = ""
  is_dir: bool = False
  # content digest, `S3` only: a file protocol never says what is inside
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

  Skipped on the local side, the excluded files go up on every run and never read as unchanged:
  the remote index pruned them, so nothing there matches.
  """
  if filter is None: return False
  parts = rel.split("/")
  for depth in range(1, len(parts)):
    branch = "/".join(parts[:depth])
    if not (filter(branch) and filter(f"{branch}/")): return True
  return not filter(rel)

def unchanged(rs:Attrs, lmtime:float, lsize:int, *, use_mtime:bool=True) -> bool:
  """Same file? `st_size` always; `st_mtime` too, when `use_mtime` and the remote has one."""
  if use_mtime and rs.st_mtime is not None:
    return int(rs.st_mtime) == int(lmtime) and rs.st_size == lsize
  return rs.st_size == lsize

def log_sync(log:Logger|Print|None, op:str, actions:list[Action], dry_run:bool) -> None:
  """One line for a whole sync: counts per action, `(dry)` when nothing moved."""
  if not log: return
  counts = {k: sum(1 for a, _ in actions if a == k) for k in ("put", "get", "skip", "delete")}
  hue = {"put": c.LIME, "skip": c.MAGNTA}
  parts = [f"{k}:{hue.get(k, c.CYAN)}{v}{c.END}" for k, v in counts.items() if v]
  suffix = f" {c.GREY}(dry){c.END}" if dry_run else ""
  log.inf(f"{op} {' '.join(parts)}{suffix}")
