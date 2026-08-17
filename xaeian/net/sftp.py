# xaeian/net/sftp.py

"""
SFTP/SSH client for deployment and data collection.

Auth priority: key file, then password, then SSH agent.

Example:
  >>> with SFTP("10.0.0.1", "pi", key="~/.ssh/id_rsa") as s:
  ...   s.sync_push("./dist", "/srv/app")
  ...   s.exec("systemctl restart app")
"""

__extras__ = ("sftp", ["paramiko"])

import os, stat, threading
from pathlib import Path
from typing import Callable
from ..log import Logger, Print
from ..colors import Color as c
from .ftp import Filter, Progress, Action, _atomic_local, _unchanged, _safe_name # documented there

try:
  import paramiko
except ImportError:
  raise ImportError("Install with: pip install xaeian[sftp]")

def _known_hosts() -> str:
  """
  The library's own trust store for first-contact host keys.

  Kept apart from the user's `known_hosts`: paramiko saving would rewrite that file and drop
  entries it cannot parse (`@cert-authority`, `@revoked`, foreign key types). This file it owns
  outright, so recording a key cannot damage anything.
  """
  path = Path.home() / ".ssh" / "known_hosts.xaeian"
  if not path.is_file():
    path.parent.mkdir(mode=0o700, exist_ok=True)
    path.touch(mode=0o600)
  return str(path)

#--------------------------------------------------------------------------------------------- SFTP

class SFTP:
  """
  SFTP/SSH client: push/pull sync, atomic transfers, remote exec.

  Accepts `Print`, `Logger`, or any object with `inf/wrn/err/run/gap/item` as `log`.

  Host keys are checked against `~/.ssh/known_hosts`: a changed key aborts.
  An unknown host is trusted on first use unless `strict=True`.
  """
  def __init__(
    self,
    host:str,
    user:str,
    port:int = 22,
    *,
    password:str|None = None,
    key:str|None = None,
    passphrase:str|None = None,
    agent:bool = False,
    strict:bool = False,
    log:Logger|Print|None = None,
  ):
    self.host = host
    self.user = user
    self.port = port
    self._password = password
    self._key = key
    self._passphrase = passphrase
    self._agent = agent
    self._strict = strict
    self.log: Logger|Print|None = log
    self._ssh: paramiko.SSHClient|None = None
    self._sftp: paramiko.SFTPClient|None = None
    self._index_partial = False # a listing failed: delete must stand down
    self._can_utime = True # cleared when the server refuses SETSTAT

  def __enter__(self): self.connect(); return self
  def __exit__(self, *_): self.disconnect()

  #------------------------------------------------------------------------------------- Connection

  def connect(self):
    """
    Open SSH + SFTP session.

    Host identity: the system `known_hosts` is honored read-only, and a host accepted on first
    contact is recorded in `~/.ssh/known_hosts.xaeian` - from then on a changed server key is
    refused instead of silently trusted. `strict=True` refuses unknown hosts outright.
    """
    self._can_utime = True
    self._ssh = paramiko.SSHClient()
    self._ssh.load_system_host_keys()
    # writable store: gives AutoAddPolicy a place to persist, which is what arms the key check
    self._ssh.load_host_keys(_known_hosts())
    self._ssh.set_missing_host_key_policy(
      paramiko.RejectPolicy() if self._strict else paramiko.AutoAddPolicy()
    )
    kw: dict = {
      "hostname": self.host, "port": self.port, "username": self.user,
      "allow_agent": False, "look_for_keys": False,
    }
    if self._key:
      kw["key_filename"] = str(Path(self._key).expanduser())
      if self._passphrase: kw["passphrase"] = self._passphrase
    elif self._password: kw["password"] = self._password
    elif self._agent: kw["allow_agent"] = True
    try:
      self._ssh.connect(**kw)
      self._sftp = self._ssh.open_sftp()
      if self.log:
        self.log.inf(f"connected {c.TURQUS}{self.host}{c.END} user:{c.VIOLET}{self.user}{c.END}")
    except Exception as e:
      if self.log: self.log.err(f"connect failed {c.TURQUS}{self.host}{c.END} | {e}")
      raise ConnectionError(f"SFTP connect failed host:{self.host} | {e}") from e

  def disconnect(self):
    """Close SFTP and SSH sessions."""
    if self._sftp:
      try: self._sftp.close()
      except Exception: pass # a dead channel must not strand the ssh session
      self._sftp = None
    if self._ssh: self._ssh.close(); self._ssh = None

  def _require_connected(self):
    if not self._sftp: raise RuntimeError("SFTP not connected: call connect() first")

  #------------------------------------------------------------------------------------ Single file

  def stat(self, remote:str) -> "paramiko.SFTPAttributes|None":
    """Remote attributes, or `None` if not found. Follows symlinks."""
    self._require_connected()
    try: return self._sftp.stat(remote)
    except FileNotFoundError: return None

  def exists(self, remote:str) -> bool:
    """Check if a remote path exists, directories included."""
    return self.stat(remote) is not None

  def put(
    self,
    local:str,
    remote:str,
    *,
    atomic:bool = True,
    preserve_mtime:bool = False,
    callback:Progress|None = None,
    _label:str|None = None,
  ):
    """
    Upload single file, creating the missing remote parent directories.

    Args:
      atomic: Upload to `{remote}.tmp`, rename on completion.
      preserve_mtime: Set remote mtime to match local, which `sync_push` relies on to skip.
    """
    self._require_connected()
    self.mkdir(os.path.dirname(remote))
    label = _label or remote
    cb = (lambda done, total: callback(label, done, total)) if callback else None
    dst = f"{remote}.tmp" if atomic else remote
    try: self._sftp.put(local, dst, callback=cb)
    except Exception:
      if atomic:
        try: self._sftp.remove(dst) # drop the partial .tmp
        except Exception: pass
      raise
    if atomic: self._posix_rename(dst, remote)
    if preserve_mtime:
      mtime = Path(local).stat().st_mtime
      try: self._sftp.utime(remote, (mtime, mtime))
      except Exception:
        self._can_utime = False # SETSTAT refused: sync_push falls back to size-only skip
        if self.log: self.log.wrn(f"utime failed {c.GREY}{remote}{c.END}: mtime not preserved")
    if self.log: self.log.item(f"{c.GREY}{local}{c.END} → {c.GREY}{remote}{c.END}")

  def get(
    self,
    remote:str,
    local:str,
    *,
    preserve_mtime:bool = False,
    callback:Progress|None = None,
    _label:str|None = None,
  ):
    """
    Download single file, creating the missing local parent directories.

    The bytes land beside the target and are swapped in on completion,
    so a failed transfer leaves the previous local file untouched.

    Args:
      preserve_mtime: Set local mtime to match remote, which `sync_pull` relies on to skip.
    """
    self._require_connected()
    label = _label or remote
    cb = (lambda done, total: callback(label, done, total)) if callback else None
    with _atomic_local(local) as tmp:
      self._sftp.get(remote, tmp, callback=cb)
    if preserve_mtime:
      rstat = self._sftp.stat(remote)
      if rstat.st_mtime is not None:
        atime = rstat.st_atime if rstat.st_atime is not None else rstat.st_mtime
        os.utime(local, (atime, rstat.st_mtime))
      elif self.log: self.log.wrn(f"mtime unavailable {c.GREY}{remote}{c.END}: not preserved")
    if self.log: self.log.item(f"{c.GREY}{remote}{c.END} → {c.GREY}{local}{c.END}")

  def remove(self, remote:str):
    """Delete remote file. Silent if not found."""
    self._require_connected()
    try: self._sftp.remove(remote)
    except FileNotFoundError: pass

  def rename(self, src:str, dst:str):
    """Rename/move remote file: overwrites target."""
    self._require_connected()
    self._posix_rename(src, dst)

  #------------------------------------------------------------------------------------ Directories

  def mkdir(self, remote:str):
    """Create remote directory recursively, idempotent."""
    self._require_connected()
    if not remote or remote == "/": return
    parts = [p for p in remote.replace("\\", "/").split("/") if p]
    prefix = "/" if remote.startswith("/") else ""
    current = ""
    for part in parts:
      current = f"{prefix}{part}" if not current else f"{current}/{part}"
      try: self._sftp.stat(current)
      except FileNotFoundError:
        try: self._sftp.mkdir(current)
        except OSError: self._sftp.stat(current) # lost a concurrent create: fine if it exists now

  def ls(self, remote:str) -> list["paramiko.SFTPAttributes"]:
    """List remote directory with attributes. Symlinks are reported as links, not resolved."""
    self._require_connected()
    return [a for a in self._sftp.listdir_attr(remote) if _safe_name(a.filename)]

  def rmdir(self, remote:str):
    """Remove remote directory recursively."""
    self._require_connected()
    for attr in self.ls(remote):
      path = f"{remote}/{attr.filename}"
      if _is_dir(attr): self.rmdir(path)
      else: self._sftp.remove(path)
    self._sftp.rmdir(remote)

  #--------------------------------------------------------------------------------- Batch transfer

  def put_dir(
    self,
    local:str,
    remote:str,
    *,
    filter:Filter|None = None,
    atomic:bool = True,
    callback:Progress|None = None,
  ):
    """
    Upload every file recursively. No skip check: `sync_push` transfers only what changed.

    Walks files, so an empty local directory has no remote counterpart afterwards.
    """
    self._require_connected()
    root = Path(local)
    files = [f for f in root.rglob("*") if f.is_file()]
    if self.log:
      self.log.inf(f"put_dir {c.CYAN}{len(files)}{c.END} files → {c.SKY}{remote}{c.END}")
    for f in files:
      rel = f.relative_to(root).as_posix()
      if filter and not filter(rel): continue
      self.put(str(f), f"{remote}/{rel}", atomic=atomic, callback=callback, _label=rel)

  def get_dir(
    self,
    remote:str,
    local:str,
    *,
    filter:Filter|None = None,
    callback:Progress|None = None,
  ):
    """Download every file recursively. No skip check: `sync_pull` transfers only what changed."""
    self._require_connected()
    self._get_dir_rec(remote, remote, Path(local), filter, callback)

  #------------------------------------------------------------------------------------------- Sync

  def sync_push(
    self,
    local:str,
    remote:str,
    *,
    delete:bool = False,
    dry_run:bool = False,
    filter:Filter|None = None,
    callback:Progress|None = None,
  ) -> list[Action]:
    """
    Push local → remote, skipping unchanged files.

    Skip strategy: mtime+size, falling back to size-only for the rest
    of the session once the server refuses to set a remote mtime.

    `delete` is refused when the local source is not a directory,
    so a missing source can never wipe the remote.

    Args:
      delete: Remove remote files absent locally, `filter` respected.
      dry_run: Plan actions without executing, the returned list is still complete.

    Returns:
      `("put"|"skip"|"delete", rel_path)` per file.
    """
    self._require_connected()
    root = Path(local)
    local_files = {f.relative_to(root).as_posix(): f for f in root.rglob("*") if f.is_file()}
    remote_idx = self._index_remote(remote, filter=filter)
    actions: list[Action] = []
    for rel, lpath in local_files.items():
      if filter and not filter(rel): continue
      ls = lpath.stat()
      rs = remote_idx.get(rel)
      if rs and _unchanged(rs, ls.st_mtime, ls.st_size, use_mtime=self._can_utime):
        actions.append(("skip", rel)); continue
      actions.append(("put", rel))
      if not dry_run:
        self.put(str(lpath), f"{remote}/{rel}", atomic=True,
          preserve_mtime=True, callback=callback, _label=rel)
    if delete:
      if not root.is_dir(): # a missing source would make every remote file look deleted
        if self.log: self.log.wrn("delete skipped: local source is not a directory")
      else:
        for rel in remote_idx:
          if rel not in local_files and not (filter and not filter(rel)):
            actions.append(("delete", rel))
            if not dry_run: self.remove(f"{remote}/{rel}")
    self._log_sync("sync_push", actions, dry_run)
    return actions

  def sync_pull(
    self,
    remote:str,
    local:str,
    *,
    delete:bool = False,
    dry_run:bool = False,
    filter:Filter|None = None,
    callback:Progress|None = None,
  ) -> list[Action]:
    """
    Pull remote → local, skipping unchanged files (mtime + size).

    `delete` is refused on an incomplete remote listing,
    so an unreadable remote can never wipe local files.

    Args:
      delete: Remove local files absent remotely, `filter` respected.
      dry_run: Plan actions without executing, the returned list is still complete.

    Returns:
      `("get"|"skip"|"delete", rel_path)` per file.
    """
    self._require_connected()
    root = Path(local)
    local_idx = (
      {f.relative_to(root).as_posix(): f for f in root.rglob("*") if f.is_file()}
      if root.exists() else {}
    )
    remote_idx = self._index_remote(remote, filter=filter)
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
      if self._index_partial: # a partial view would make present files look deleted
        if self.log: self.log.wrn("delete skipped: remote listing incomplete")
      else:
        for rel in local_idx:
          if rel not in remote_idx and not (filter and not filter(rel)):
            actions.append(("delete", rel))
            if not dry_run: (root / rel).unlink(missing_ok=True)
    self._log_sync("sync_pull", actions, dry_run)
    return actions

  #------------------------------------------------------------------------------------------- Exec

  def exec(self, cmd:str, *, check:bool=False) -> tuple[str, str]:
    """
    Run command on remote host, blocking until it exits.

    The exit status is never returned - `check=True` raises `RuntimeError` on non-zero.

    Returns:
      `(stdout, stderr)`, decoded with `errors="replace"` and stripped.
    """
    self._require_connected()
    if self.log: self.log.run(f"{c.SILVER}{cmd}{c.END}")
    _, stdout, stderr = self._ssh.exec_command(cmd)
    err_buf: list[bytes] = []
    drain = threading.Thread(target=lambda: err_buf.append(stderr.read()), daemon=True)
    drain.start() # stderr must drain in parallel: a full channel window would stall stdout
    out = stdout.read().decode(errors="replace").strip()
    drain.join()
    err = err_buf[0].decode(errors="replace").strip()
    rc = stdout.channel.recv_exit_status()
    if self.log:
      for line in out.splitlines(): self.log.gap(f"{c.GREY}{line}{c.END}")
      for line in err.splitlines(): self.log.wrn(line)
    if check and rc != 0:
      raise RuntimeError(f"remote command failed (rc={rc}): {cmd}" + (f"\n{err}" if err else ""))
    return out, err

  #---------------------------------------------------------------------------------------- Helpers

  def _posix_rename(self, src:str, dst:str):
    """Atomic overwrite where the server supports it, delete-then-rename otherwise."""
    try: self._sftp.posix_rename(src, dst)
    except (AttributeError, IOError):
      self._sftp.stat(src) # src is gone: fail before dst gets destroyed
      try: self._sftp.remove(dst)
      except FileNotFoundError: pass
      self._sftp.rename(src, dst)

  def _resolve(self, path:str, attr:"paramiko.SFTPAttributes"):
    """
    Follow a symlink: a listing describes the link, but `get()` reads its target.

    Returns `None` for a broken link, or a link to a directory: it may close a cycle.
    """
    if not stat.S_ISLNK(attr.st_mode or 0): return attr
    try: target = self._sftp.stat(path)
    except OSError: target = None
    if target is None or _is_dir(target):
      if self.log: self.log.wrn(f"symlink skipped {c.GREY}{path}{c.END}")
      return None
    target.filename = attr.filename
    return target

  def _index_remote(
    self,
    remote:str,
    _rel:str = "",
    filter:Filter|None = None,
  ) -> dict[str, "paramiko.SFTPAttributes"]:
    """
    Recursively build `{rel_path: SFTPAttributes}` for remote dir, pruning filtered paths.

    Sets `_index_partial` when a listing fails, so callers can refuse to delete on a partial view.
    A missing root yields `{}`: a push then creates it.
    """
    if not _rel: self._index_partial = False
    idx: dict = {}
    try: entries = self._sftp.listdir_attr(remote)
    except FileNotFoundError:
      self._index_partial = True; return idx
    for attr in entries:
      if not _safe_name(attr.filename): continue
      rel = f"{_rel}/{attr.filename}" if _rel else attr.filename
      path = f"{remote}/{attr.filename}"
      attr = self._resolve(path, attr)
      if attr is None: continue
      if _is_dir(attr):
        if filter and not (filter(rel) and filter(f"{rel}/")): continue
        idx.update(self._index_remote(path, rel, filter))
      else:
        if filter and not filter(rel): continue
        idx[rel] = attr
    return idx

  def _get_dir_rec(
    self,
    remote_root:str,
    remote:str,
    local:Path,
    filter:Filter|None,
    callback:Progress|None,
  ):
    for attr in self.ls(remote):
      rpath = f"{remote}/{attr.filename}"
      rel = rpath[len(remote_root):].lstrip("/")
      lpath = local / rel
      attr = self._resolve(rpath, attr)
      if attr is None: continue
      if _is_dir(attr):
        self._get_dir_rec(remote_root, rpath, local, filter, callback)
      else:
        if filter and not filter(rel): continue
        self.get(rpath, str(lpath), callback=callback, _label=rel)

  def _log_sync(self, op:str, actions:list[Action], dry_run:bool):
    if not self.log: return
    counts = {k: sum(1 for a, _ in actions if a == k) for k in ("put", "get", "skip", "delete")}
    hue = {"put": c.LIME, "skip": c.MAGNTA}
    parts = [f"{k}:{hue.get(k, c.CYAN)}{v}{c.END}" for k, v in counts.items() if v]
    suffix = f" {c.GREY}(dry){c.END}" if dry_run else ""
    self.log.inf(f"{op} {' '.join(parts)}{suffix}")

#------------------------------------------------------------------------------------------ Helpers

def _is_dir(attr:"paramiko.SFTPAttributes") -> bool:
  return stat.S_ISDIR(attr.st_mode or 0)