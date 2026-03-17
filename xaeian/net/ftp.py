# xaeian/net/ftp.py

"""FTP client with same interface as SFTP."""

import os, ftplib, datetime
from pathlib import Path
from dataclasses import dataclass
from typing import Callable
from ..log import Logger, Print
from ..colors import Color as c

Filter   = Callable[[str], bool]
Progress = Callable[[str, int, int], None]
Action   = tuple[str, str]

#------------------------------------------------------------------------------------------ Types

@dataclass
class Attrs:
  """Remote file attributes (mirrors paramiko.SFTPAttributes for sync compatibility)."""
  st_size:  int        = 0
  st_mtime: float|None = None  # UTC epoch; None if server lacks MLSD/MDTM
  filename: str        = ""
  is_dir:   bool       = False

def _parse_mtime(s: str) -> float|None:
  """Parse MLSD/MDTM timestamp `YYYYMMDDHHmmss` → UTC epoch."""
  try:
    dt = datetime.datetime.strptime(s.strip()[:14], "%Y%m%d%H%M%S")
    return dt.replace(tzinfo=datetime.timezone.utc).timestamp()
  except Exception: return None

#-------------------------------------------------------------------------------------------- FTP

class FTP:
  """
  FTP client: push/pull sync, matching SFTP interface.

  Capability detection on connect: MLSD (mtime+size skip) and MFMT (preserve mtime).
  Degrades gracefully: no MLSD → size-only skip; no MFMT → preserve_mtime is no-op.

  Example:
    >>> with FTP("host", "user", password="pass", log=Print()) as f:
    ...   f.sync_push("./data", "/home/user/data")
    ...   f.sync_pull("/home/user/data", "./data")
  """
  def __init__(
    self,
    host: str,
    user: str,
    port: int = 21,
    *,
    password: str = "",
    log: Logger|Print|None = None,
  ):
    self.host = host
    self.user = user
    self.port = port
    self._password = password
    self.log = log
    self._ftp: ftplib.FTP|None = None
    self._has_mlsd = False
    self._has_mfmt = False

  def __enter__(self): self.connect(); return self
  def __exit__(self, *_): self.disconnect()

  #----------------------------------------------------------------------------------- Connection

  def connect(self):
    """Open FTP session and detect server capabilities (MLSD, MFMT)."""
    self._ftp = ftplib.FTP()
    self._ftp.connect(self.host, self.port, timeout=30)
    self._ftp.login(self.user, self._password)
    try:
      feat = self._ftp.sendcmd("FEAT")
      self._has_mlsd = "MLST" in feat
      self._has_mfmt = "MFMT" in feat
    except Exception:
      self._has_mlsd = False
      self._has_mfmt = False
    if self.log:
      caps = f"mlsd:{c.CYAN}{self._has_mlsd}{c.END} mfmt:{c.CYAN}{self._has_mfmt}{c.END}"
      self.log.inf(
        f"connected {c.TURQUS}{self.host}{c.END} user:{c.CYAN}{self.user}{c.END} {caps}"
      )

  def disconnect(self):
    """Close FTP session."""
    if self._ftp:
      try: self._ftp.quit()
      except Exception: pass
      self._ftp = None

  def _require_connected(self):
    if not self._ftp: raise RuntimeError("FTP not connected: call connect() first")

  #---------------------------------------------------------------------------------- Single file

  def stat(self, remote: str) -> Attrs|None:
    """Remote file attributes, or `None` if not found."""
    self._require_connected()
    try:
      size = self._ftp.size(remote)
      if size is None: return None
      mtime = None
      try:
        resp = self._ftp.sendcmd(f"MDTM {remote}")
        mtime = _parse_mtime(resp[4:])
      except Exception: pass
      return Attrs(st_size=size, st_mtime=mtime)
    except Exception: return None

  def exists(self, remote: str) -> bool:
    """Check if remote path exists."""
    return self.stat(remote) is not None

  def put(
    self,
    local: str,
    remote: str,
    *,
    atomic: bool = True,
    preserve_mtime: bool = False,
    callback: Progress|None = None,
    _label: str|None = None,
  ):
    """
    Upload single file.

    Args:
      local: Local source path.
      remote: Remote destination path.
      atomic: Upload to `{remote}.tmp`, rename on completion.
      preserve_mtime: Set remote mtime via MFMT (no-op if server lacks MFMT).
      callback: `(path, bytes_done, total_bytes)` progress hook.
    """
    self._require_connected()
    self.mkdir(os.path.dirname(remote))
    label = _label or remote
    dst = f"{remote}.tmp" if atomic else remote
    with open(local, "rb") as f:
      if callback:
        total = os.path.getsize(local)
        sent = [0]
        def _cb(block): sent[0] += len(block); callback(label, sent[0], total)
        self._ftp.storbinary(f"STOR {dst}", f, callback=_cb)
      else:
        self._ftp.storbinary(f"STOR {dst}", f)
    if atomic: self._ftp.rename(dst, remote)
    if preserve_mtime and self._has_mfmt:
      ts = datetime.datetime.fromtimestamp(
        Path(local).stat().st_mtime, tz=datetime.timezone.utc
      ).strftime("%Y%m%d%H%M%S")
      try: self._ftp.sendcmd(f"MFMT {ts} {remote}")
      except Exception: pass
    if self.log: self.log.item(f"{c.GREY}{local}{c.END} -> {c.GREY}{remote}{c.END}")

  def get(
    self,
    remote: str,
    local: str,
    *,
    preserve_mtime: bool = False,
    callback: Progress|None = None,
    _label: str|None = None,
  ):
    """
    Download single file.

    Args:
      remote: Remote source path.
      local: Local destination path.
      preserve_mtime: Set local mtime from remote via MDTM.
      callback: `(path, bytes_done, total_bytes)` progress hook.
    """
    self._require_connected()
    Path(local).parent.mkdir(parents=True, exist_ok=True)
    label = _label or remote
    with open(local, "wb") as f:
      if callback:
        try: total = self._ftp.size(remote) or 0
        except Exception: total = 0
        recv = [0]
        def _write(block): f.write(block); recv[0] += len(block); callback(label, recv[0], total)
        self._ftp.retrbinary(f"RETR {remote}", _write)
      else:
        self._ftp.retrbinary(f"RETR {remote}", f.write)
    if preserve_mtime:
      try:
        resp = self._ftp.sendcmd(f"MDTM {remote}")
        mtime = _parse_mtime(resp[4:])
        if mtime: os.utime(local, (mtime, mtime))
      except Exception: pass
    if self.log: self.log.item(f"{c.GREY}{remote}{c.END} -> {c.GREY}{local}{c.END}")

  def remove(self, remote: str):
    """Delete remote file. Silent if not found."""
    self._require_connected()
    try: self._ftp.delete(remote)
    except ftplib.error_perm: pass

  def rename(self, src: str, dst: str):
    """Rename/move remote file."""
    self._require_connected()
    self._ftp.rename(src, dst)

  #--------------------------------------------------------------------------------- Directories

  def mkdir(self, remote: str):
    """Create remote directory recursively, idempotent."""
    self._require_connected()
    if not remote or remote == "/": return
    parts = [p for p in remote.replace("\\", "/").split("/") if p]
    prefix = "/" if remote.startswith("/") else ""
    cur = ""
    for p in parts:
      cur = f"{prefix}{p}" if not cur else f"{cur}/{p}"
      try: self._ftp.mkd(cur)
      except ftplib.error_perm: pass

  def ls(self, remote: str) -> list[Attrs]:
    """List remote directory with attributes."""
    self._require_connected()
    result = []
    if self._has_mlsd:
      for name, facts in self._ftp.mlsd(remote, facts=["size", "modify", "type"]):
        if name in (".", ".."): continue
        ftype = facts.get("type", "file")
        result.append(Attrs(
          st_size=int(facts.get("size", 0)),
          st_mtime=_parse_mtime(facts["modify"]) if "modify" in facts else None,
          filename=name,
          is_dir=ftype in ("dir", "cdir", "pdir"),
        ))
    else:
      for path in self._ftp.nlst(remote):
        name = os.path.basename(path) or path
        try:
          size = self._ftp.size(path)
          result.append(Attrs(st_size=size or 0, st_mtime=None, filename=name, is_dir=size is None))
        except ftplib.error_perm:
          result.append(Attrs(st_size=0, st_mtime=None, filename=name, is_dir=True))
    return result

  def rmdir(self, remote: str):
    """Remove remote directory recursively."""
    self._require_connected()
    for attr in self.ls(remote):
      path = f"{remote}/{attr.filename}"
      if attr.is_dir: self.rmdir(path)
      else: self.remove(path)
    self._ftp.rmd(remote)

  #------------------------------------------------------------------------------ Batch transfer

  def put_dir(
    self,
    local: str,
    remote: str,
    *,
    filter: Filter|None = None,
    atomic: bool = True,
    callback: Progress|None = None,
  ):
    """
    Upload directory recursively.

    Args:
      local: Local source directory.
      remote: Remote destination directory.
      filter: `(rel_path) -> bool`: return `False` to skip.
      atomic: Atomic upload per file.
      callback: Per-file progress hook.
    """
    self._require_connected()
    root = Path(local)
    files = [f for f in root.rglob("*") if f.is_file()]
    if self.log: self.log.inf(f"put_dir {c.CYAN}{len(files)}{c.END} files -> {c.SKY}{remote}{c.END}")
    for f in files:
      rel = f.relative_to(root).as_posix()
      if filter and not filter(rel): continue
      self.put(str(f), f"{remote}/{rel}", atomic=atomic, callback=callback, _label=rel)

  def get_dir(
    self,
    remote: str,
    local: str,
    *,
    filter: Filter|None = None,
    callback: Progress|None = None,
  ):
    """
    Download directory recursively.

    Args:
      remote: Remote source directory.
      local: Local destination directory.
      filter: `(rel_path) -> bool`: return `False` to skip.
      callback: Per-file progress hook.
    """
    self._require_connected()
    self._get_dir_rec(remote, remote, Path(local), filter, callback)

  #---------------------------------------------------------------------------------------- Sync

  def sync_push(
    self,
    local: str,
    remote: str,
    *,
    delete: bool = False,
    dry_run: bool = False,
    filter: Filter|None = None,
    callback: Progress|None = None,
  ) -> list[Action]:
    """
    Push local -> remote, skipping unchanged files.

    Skip strategy: mtime+size if MLSD available, size-only otherwise.

    Args:
      local: Local source directory.
      remote: Remote destination directory.
      delete: Remove remote files absent locally.
      dry_run: Plan actions without executing.
      filter: `(rel_path) -> bool`: return `False` to skip.
      callback: Per-file progress hook.

    Returns:
      List of `("put"|"skip"|"delete", rel_path)` actions.
    """
    self._require_connected()
    root = Path(local)
    local_files = {
      f.relative_to(root).as_posix(): f
      for f in root.rglob("*") if f.is_file()
    }
    remote_idx = self._index_remote(remote)
    actions: list[Action] = []
    for rel, lpath in local_files.items():
      if filter and not filter(rel): continue
      ls = lpath.stat()
      rs = remote_idx.get(rel)
      if rs and _unchanged(rs, ls.st_mtime, ls.st_size):
        actions.append(("skip", rel)); continue
      actions.append(("put", rel))
      if not dry_run:
        self.put(str(lpath), f"{remote}/{rel}", atomic=True,
          preserve_mtime=True, callback=callback, _label=rel)
    if delete:
      for rel in remote_idx:
        if rel not in local_files and not (filter and not filter(rel)):
          actions.append(("delete", rel))
          if not dry_run: self.remove(f"{remote}/{rel}")
    self._log_sync("sync_push", actions, dry_run)
    return actions

  def sync_pull(
    self,
    remote: str,
    local: str,
    *,
    delete: bool = False,
    dry_run: bool = False,
    filter: Filter|None = None,
    callback: Progress|None = None,
  ) -> list[Action]:
    """
    Pull remote -> local, skipping unchanged files.

    Skip strategy: mtime+size if MLSD available, size-only otherwise.

    Args:
      remote: Remote source directory.
      local: Local destination directory.
      delete: Remove local files absent remotely.
      dry_run: Plan actions without executing.
      filter: `(rel_path) -> bool`: return `False` to skip.
      callback: Per-file progress hook.

    Returns:
      List of `("get"|"skip"|"delete", rel_path)` actions.
    """
    self._require_connected()
    root = Path(local)
    local_idx = (
      {f.relative_to(root).as_posix(): f for f in root.rglob("*") if f.is_file()}
      if root.exists() else {}
    )
    remote_idx = self._index_remote(remote)
    actions: list[Action] = []
    for rel, rs in remote_idx.items():
      if filter and not filter(rel): continue
      lpath = root / rel
      if lpath.exists():
        ls = lpath.stat()
        if _unchanged(rs, ls.st_mtime, ls.st_size):
          actions.append(("skip", rel)); continue
      actions.append(("get", rel))
      if not dry_run:
        self.get(f"{remote}/{rel}", str(lpath), preserve_mtime=True,
          callback=callback, _label=rel)
    if delete:
      for rel in local_idx:
        if rel not in remote_idx and not (filter and not filter(rel)):
          actions.append(("delete", rel))
          if not dry_run: (root / rel).unlink(missing_ok=True)
    self._log_sync("sync_pull", actions, dry_run)
    return actions

  #------------------------------------------------------------------------------------- Helpers

  def _index_remote(self, remote: str, _rel: str = "") -> dict[str, Attrs]:
    """Recursively build `{rel_path: Attrs}` for remote dir."""
    idx: dict = {}
    if self._has_mlsd:
      try: entries = list(self._ftp.mlsd(remote, facts=["size", "modify", "type"]))
      except ftplib.error_perm: return idx
      for name, facts in entries:
        if name in (".", ".."): continue
        rel = f"{_rel}/{name}" if _rel else name
        if facts.get("type", "file") in ("dir", "cdir", "pdir"):
          idx.update(self._index_remote(f"{remote}/{name}", rel))
        else:
          idx[rel] = Attrs(
            st_size=int(facts.get("size", 0)),
            st_mtime=_parse_mtime(facts["modify"]) if "modify" in facts else None,
            filename=name,
          )
    else:
      try: paths = self._ftp.nlst(remote)
      except ftplib.error_perm: return idx
      for path in paths:
        name = os.path.basename(path) or path
        rel = f"{_rel}/{name}" if _rel else name
        try:
          size = self._ftp.size(path)
          if size is not None: idx[rel] = Attrs(st_size=size, st_mtime=None, filename=name)
          else: idx.update(self._index_remote(path, rel))
        except ftplib.error_perm:
          idx.update(self._index_remote(path, rel))
    return idx

  def _get_dir_rec(
    self,
    remote_root: str,
    remote: str,
    local: Path,
    filter: Filter|None,
    callback: Progress|None,
  ):
    for attr in self.ls(remote):
      rpath = f"{remote}/{attr.filename}"
      rel = rpath[len(remote_root):].lstrip("/")
      if attr.is_dir:
        self._get_dir_rec(remote_root, rpath, local, filter, callback)
      else:
        if filter and not filter(rel): continue
        self.get(rpath, str(local / rel), callback=callback, _label=rel)

  def _log_sync(self, op: str, actions: list[Action], dry_run: bool):
    if not self.log: return
    counts = {k: sum(1 for a, _ in actions if a == k) for k in ("put", "get", "skip", "delete")}
    parts = [f"{k}:{c.CYAN}{v}{c.END}" for k, v in counts.items() if v]
    suffix = f" {c.GREY}(dry){c.END}" if dry_run else ""
    self.log.inf(f"{op} {' '.join(parts)}{suffix}")

#---------------------------------------------------------------------------------------- Helpers

def _unchanged(rs: Attrs, lmtime: float, lsize: int) -> bool:
  """Skip check: mtime+size if available, size-only otherwise."""
  if rs.st_mtime is not None:
    return int(rs.st_mtime) == int(lmtime) and rs.st_size == lsize
  return rs.st_size == lsize