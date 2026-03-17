# xaeian/net/sftp.py

"""
SFTP/SSH client for deployment and data collection.

Accepts `Print` or `Logger` as `log`: or `None` for silence.
Auth: key file takes priority, then password, then SSH agent.

Example:
  >>> with SFTP("10.0.0.1", "pi", key="~/.ssh/id_rsa") as s:
  ...   s.sync_push("./dist", "/srv/app")
  ...   s.exec("systemctl restart app")
"""

import os, stat
from pathlib import Path
from typing import Callable
from ..log import Logger, Print
from ..colors import Color as c

try:
  import paramiko
except ImportError:
  raise ImportError("Install with: pip install xaeian[sftp]")

__extras__ = ("sftp", ["paramiko"])

#------------------------------------------------------------------------------------------- Types

# (rel_path) → include?
Filter   = Callable[[str], bool]
# (path, done, total): rel for sync/dir, remote for single
Progress = Callable[[str, int, int], None]
# ("put"|"get"|"skip"|"delete", rel_path)
Action   = tuple[str, str]

#-------------------------------------------------------------------------------------------- SFTP

class SFTP:
  """
  SFTP/SSH client: push/pull sync, atomic uploads, remote exec.

  Accepts `Print`, `Logger`, or any object with `inf/wrn/err/gap/item` as `log`.

  Example:
    >>> s = SFTP("host", "user", password="pass", log=Print())
    >>> with s:
    ...   actions = s.sync_push("./data", "/home/user/data", dry_run=True)
    ...   s.sync_push("./data", "/home/user/data")
    ...   s.exec("python3 process.py")
  """
  def __init__(
    self,
    host: str,
    user: str,
    port: int = 22,
    *,
    password: str|None = None,
    key: str|None = None,
    passphrase: str|None = None,
    agent: bool = False,
    log: Logger|Print|None = None,
  ):
    self.host = host
    self.user = user
    self.port = port
    self._password = password
    self._key = key
    self._passphrase = passphrase
    self._agent = agent
    self.log: Logger|Print|None = log
    self._ssh:  paramiko.SSHClient|None  = None
    self._sftp: paramiko.SFTPClient|None = None

  def __enter__(self): self.connect(); return self
  def __exit__(self, *_): self.disconnect()

  #----------------------------------------------------------------------------------- Connection

  def connect(self):
    """Open SSH + SFTP session."""
    self._ssh = paramiko.SSHClient()
    self._ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    kw: dict = {
      "hostname": self.host, "port": self.port, "username": self.user,
      "allow_agent": False, "look_for_keys": False,
    }
    if self._key:
      kw["key_filename"] = str(Path(self._key).expanduser())
      if self._passphrase: kw["passphrase"] = self._passphrase
    elif self._password: kw["password"] = self._password
    elif self._agent:    kw["allow_agent"] = True
    try:
      self._ssh.connect(**kw)
      self._sftp = self._ssh.open_sftp()
      if self.log: self.log.inf(f"connected {c.TURQUS}{self.host}{c.END} user:{c.CYAN}{self.user}{c.END}")
    except Exception as e:
      if self.log: self.log.err(f"connect failed {c.TURQUS}{self.host}{c.END} | {e}")
      raise ConnectionError(f"SFTP connect failed host:{self.host} | {e}") from e

  def disconnect(self):
    """Close SFTP and SSH sessions."""
    if self._sftp: self._sftp.close(); self._sftp = None
    if self._ssh:  self._ssh.close();  self._ssh  = None

  def _require_connected(self):
    if not self._sftp: raise RuntimeError("SFTP not connected: call connect() first")

  #---------------------------------------------------------------------------------- Single file

  def stat(self, remote: str) -> "paramiko.SFTPAttributes|None":
    """Remote file attributes, or `None` if not found."""
    self._require_connected()
    try: return self._sftp.stat(remote)
    except FileNotFoundError: return None

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
      preserve_mtime: Set remote mtime to match local (required for sync).
      callback: `(remote, bytes_done, total_bytes)` progress hook.
    """
    self._require_connected()
    self.mkdir(os.path.dirname(remote))
    label = _label or remote
    cb = (lambda done, total: callback(label, done, total)) if callback else None
    dst = f"{remote}.tmp" if atomic else remote
    self._sftp.put(local, dst, callback=cb)
    if atomic: self._posix_rename(dst, remote)
    if preserve_mtime:
      mtime = Path(local).stat().st_mtime
      self._sftp.utime(remote, (mtime, mtime))
    if self.log: self.log.item(f"{c.GREY}{local}{c.END} → {c.GREY}{remote}{c.END}")

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
      preserve_mtime: Set local mtime to match remote (required for sync).
      callback: `(remote, bytes_done, total_bytes)` progress hook.
    """
    self._require_connected()
    Path(local).parent.mkdir(parents=True, exist_ok=True)
    label = _label or remote
    cb = (lambda done, total: callback(label, done, total)) if callback else None
    self._sftp.get(remote, local, callback=cb)
    if preserve_mtime:
      rstat = self._sftp.stat(remote)
      os.utime(local, (rstat.st_atime or rstat.st_mtime, rstat.st_mtime))
    if self.log: self.log.item(f"{c.GREY}{remote}{c.END} → {c.GREY}{local}{c.END}")

  def remove(self, remote: str):
    """Delete remote file. Silent if not found."""
    self._require_connected()
    try: self._sftp.remove(remote)
    except FileNotFoundError: pass

  def rename(self, src: str, dst: str):
    """Atomic remote rename: overwrites target (posix_rename)."""
    self._require_connected()
    self._posix_rename(src, dst)

  #--------------------------------------------------------------------------------- Directories

  def mkdir(self, remote: str):
    """Create remote directory recursively, idempotent."""
    self._require_connected()
    if not remote or remote == "/": return
    parts = [p for p in remote.split("/") if p]
    prefix = "/" if remote.startswith("/") else ""
    current = ""
    for part in parts:
      current = f"{prefix}{part}" if not current else f"{current}/{part}"
      try: self._sftp.stat(current)
      except FileNotFoundError: self._sftp.mkdir(current)

  def ls(self, remote: str) -> list["paramiko.SFTPAttributes"]:
    """List remote directory with attributes."""
    self._require_connected()
    return self._sftp.listdir_attr(remote)

  def rmdir(self, remote: str):
    """Remove remote directory recursively."""
    self._require_connected()
    for attr in self._sftp.listdir_attr(remote):
      path = f"{remote}/{attr.filename}"
      if _is_dir(attr): self.rmdir(path)
      else: self._sftp.remove(path)
    self._sftp.rmdir(remote)

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
      filter: `(rel_path) → bool`: return `False` to skip.
      atomic: Atomic upload per file.
      callback: Per-file progress hook.
    """
    self._require_connected()
    root = Path(local)
    files = [f for f in root.rglob("*") if f.is_file()]
    if self.log: self.log.inf(f"put_dir {c.CYAN}{len(files)}{c.END} files → {c.SKY}{remote}{c.END}")
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
      filter: `(rel_path) → bool`: return `False` to skip.
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
    Push local → remote, skipping unchanged files (mtime + size).

    Args:
      local: Local source directory.
      remote: Remote destination directory.
      delete: Remove remote files absent locally (respects filter).
      dry_run: Plan actions without executing.
      filter: `(rel_path) → bool`: return `False` to skip.
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
      if rs and int(rs.st_mtime) == int(ls.st_mtime) and rs.st_size == ls.st_size:
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
    Pull remote → local, skipping unchanged files (mtime + size).

    Args:
      remote: Remote source directory.
      local: Local destination directory.
      delete: Remove local files absent remotely (respects filter).
      dry_run: Plan actions without executing.
      filter: `(rel_path) → bool`: return `False` to skip.
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
        if int(rs.st_mtime) == int(ls.st_mtime) and rs.st_size == ls.st_size:
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

  #---------------------------------------------------------------------------------------- Exec

  def exec(self, cmd: str) -> tuple[str, str]:
    """
    Run command on remote host.

    Returns:
      `(stdout, stderr)` as stripped strings.
    """
    self._require_connected()
    if self.log: self.log.run(f"{c.SILVER}{cmd}{c.END}")
    _, stdout, stderr = self._ssh.exec_command(cmd)
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    if self.log:
      for line in out.splitlines(): self.log.gap(f"{c.GREY}{line}{c.END}")
      for line in err.splitlines(): self.log.wrn(line)
    return out, err

  #------------------------------------------------------------------------------------- Helpers

  def _posix_rename(self, src: str, dst: str):
    try: self._sftp.posix_rename(src, dst)
    except (AttributeError, IOError):
      try: self._sftp.remove(dst)
      except FileNotFoundError: pass
      self._sftp.rename(src, dst)

  def _index_remote(
    self, remote: str, _rel: str = ""
  ) -> dict[str, "paramiko.SFTPAttributes"]:
    """Recursively build `{rel_path: SFTPAttributes}` for remote dir."""
    idx: dict = {}
    try: entries = self._sftp.listdir_attr(remote)
    except FileNotFoundError: return idx
    for attr in entries:
      rel = f"{_rel}/{attr.filename}" if _rel else attr.filename
      path = f"{remote}/{attr.filename}"
      if _is_dir(attr): idx.update(self._index_remote(path, rel))
      else: idx[rel] = attr
    return idx

  def _get_dir_rec(
    self,
    remote_root: str,
    remote: str,
    local: Path,
    filter: Filter|None,
    callback: Progress|None,
  ):
    for attr in self._sftp.listdir_attr(remote):
      rpath = f"{remote}/{attr.filename}"
      rel = rpath[len(remote_root):].lstrip("/")
      lpath = local / rel
      if _is_dir(attr):
        self._get_dir_rec(remote_root, rpath, local, filter, callback)
      else:
        if filter and not filter(rel): continue
        self.get(rpath, str(lpath), callback=callback, _label=rel)

  def _log_sync(self, op: str, actions: list[Action], dry_run: bool):
    if not self.log: return
    counts = {k: sum(1 for a, _ in actions if a == k) for k in ("put", "get", "skip", "delete")}
    parts = [f"{k}:{c.CYAN}{v}{c.END}" for k, v in counts.items() if v]
    suffix = f" {c.GREY}(dry){c.END}" if dry_run else ""
    self.log.inf(f"{op} {' '.join(parts)}{suffix}")

#---------------------------------------------------------------------------------------- Helpers

def _is_dir(attr: "paramiko.SFTPAttributes") -> bool:
  return stat.S_ISDIR(attr.st_mode or 0)