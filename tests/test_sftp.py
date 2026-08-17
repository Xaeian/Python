# tests/test_sftp.py

"""SFTP client: host-key policy, symlink handling, and destructive-action guards."""

import stat as statmod
import threading
import pytest

paramiko = pytest.importorskip("paramiko", reason="SFTP needs the [sftp] extra")

from xaeian.net import sftp as sftpmod
from xaeian.net.sftp import SFTP

EPOCH = 1_700_000_000.0
DIR = statmod.S_IFDIR | 0o755
LNK = statmod.S_IFLNK | 0o777
REG = statmod.S_IFREG | 0o644

class Attr:
  """Stand-in for the SFTPAttributes that listdir_attr returns (lstat semantics)."""
  def __init__(self, filename, size=3, mtime=EPOCH, mode=REG):
    self.filename, self.st_size, self.st_mtime = filename, size, mtime
    self.st_mode, self.st_atime = mode, mtime

class Client:
  """Fake paramiko.SFTPClient over a scripted tree."""
  def __init__(self, tree=None, targets=None, missing=(), nostat=(),
               put_fails=False, close_fails=False, utime_fails=False):
    self.tree = tree or {}
    self.targets = targets or {}
    self.missing, self.nostat = set(missing), set(nostat)
    self.put_fails, self.close_fails, self.utime_fails = put_fails, close_fails, utime_fails
    self.files, self.removed = {}, []

  def listdir_attr(self, remote):
    if remote in self.missing or remote not in self.tree: raise FileNotFoundError(remote)
    return list(self.tree[remote])

  def stat(self, path):
    if path in self.nostat: raise FileNotFoundError(path)
    if path in self.targets: return self.targets[path]
    if path in self.files: return Attr(path)
    listed = {f"{d}/{a.filename}" for d, entries in self.tree.items() for a in entries}
    if path in listed: return Attr(path)
    raise FileNotFoundError(path)

  def get(self, remote, local, callback=None):
    with open(local, "wb") as handle: handle.write(b"xxx")

  def put(self, local, remote, callback=None):
    self.files[remote] = True  # bytes already landed on the wire
    if self.put_fails: raise OSError("link dropped mid-transfer")

  def posix_rename(self, src, dst): self.files[dst] = self.files.pop(src)
  def rename(self, src, dst): self.files[dst] = self.files.pop(src)

  def remove(self, path):
    self.removed.append(path)
    if path not in self.files: raise FileNotFoundError(path)
    del self.files[path]

  def rmdir(self, path): pass
  def mkdir(self, path): pass

  def utime(self, path, times):
    if self.utime_fails: raise OSError("SETSTAT denied")

  def close(self):
    if self.close_fails: raise OSError("dead channel")

class Ssh:
  def __init__(self): self.closed = False
  def close(self): self.closed = True

@pytest.fixture
def client():
  def build(**kw):
    session = SFTP("host", "user")
    session._sftp = Client(**kw)
    session._ssh = Ssh()
    return session
  return build

#--------------------------------------------------------------------------------- Connection

def connect_loads_known_hosts_and_honours_strict(monkeypatch, tmp_path):
  class Recorder:
    def __init__(self): self.loaded, self.own, self.policy = False, None, None
    def load_system_host_keys(self): self.loaded = True
    def load_host_keys(self, path): self.own = path
    def set_missing_host_key_policy(self, policy): self.policy = policy
    def connect(self, **kw): pass
    def open_sftp(self): return Client()
    def close(self): pass
  made = []
  def factory():
    made.append(Recorder())
    return made[-1]
  monkeypatch.setattr(sftpmod.paramiko, "SSHClient", factory)
  monkeypatch.setattr(sftpmod, "_known_hosts", lambda: str(tmp_path / "kh"))
  SFTP("host", "user").connect()
  assert made[-1].loaded is True  # system known_hosts honored, read-only
  assert made[-1].own.endswith("kh")  # writable store: arms persistence and the key check
  assert isinstance(made[-1].policy, sftpmod._RecordPolicy)
  SFTP("host", "user", strict=True).connect()
  assert isinstance(made[-1].policy, paramiko.RejectPolicy)

def forget_drops_only_the_given_host(monkeypatch, tmp_path):
  store = tmp_path / "kh"
  lines = ["a.example ssh-ed25519 AAAA1", "[b.example]:2222 ssh-ed25519 AAAA2", ""]
  store.write_text("\n".join(lines), encoding="utf-8")
  monkeypatch.setattr(sftpmod, "_known_hosts", lambda: str(store))
  assert SFTP.forget("a.example") is True
  assert SFTP.forget("a.example") is False # already gone
  left = store.read_text(encoding="utf-8")
  assert "b.example" in left and "a.example" not in left
  assert SFTP.forget("b.example", port=2222) is True
  assert store.read_text(encoding="utf-8") == ""

def disconnect_closes_the_ssh_session_even_when_the_channel_is_dead(client):
  session = client(close_fails=True)
  ssh = session._ssh
  session.disconnect()
  assert ssh.closed is True
  assert session._sftp is None and session._ssh is None

#-------------------------------------------------------------------------------- Single file

def a_failed_upload_removes_the_partial_tmp_file(client, tmp_path):
  (tmp_path / "a.txt").write_bytes(b"hello")
  session = client(put_fails=True)
  with pytest.raises(OSError):
    session.put(str(tmp_path / "a.txt"), "/r/a.txt")
  assert "/r/a.txt.tmp" not in session._sftp.files

def rename_does_not_destroy_the_target_when_the_source_is_gone(client):
  session = client()
  session._sftp.files["/r/live"] = True
  def unsupported(src, dst): raise IOError("transient failure")
  session._sftp.posix_rename = unsupported
  with pytest.raises(FileNotFoundError):
    session.rename("/r/missing.tmp", "/r/live")
  assert session._sftp.removed == []
  assert "/r/live" in session._sftp.files

def a_server_refusing_setstat_neither_aborts_the_push_nor_loops_forever(client, tmp_path):
  (tmp_path / "a.txt").write_bytes(b"hello")
  session = client(tree={"/r": [Attr("a.txt", size=5, mtime=999_999.0)]}, utime_fails=True)
  session.put(str(tmp_path / "a.txt"), "/r/a.txt", preserve_mtime=True)
  assert session._can_utime is False
  assert ("skip", "a.txt") in session.sync_push(str(tmp_path), "/r")

#------------------------------------------------------------------------------------ Listing

def hostile_names_from_the_server_are_skipped(client):
  session = client(tree={"/r": [Attr("../evil.txt"), Attr(".."), Attr("a/b"), Attr("ok.txt")]})
  assert sorted(session._index_remote("/r")) == ["ok.txt"]
  assert [a.filename for a in session.ls("/r")] == ["ok.txt"]

def rmdir_cannot_be_steered_outside_the_directory(client):
  session = client(tree={"/r": [Attr("../evil.txt"), Attr("ok.txt")]})
  session._sftp.files["/r/ok.txt"] = True
  session.rmdir("/r")
  assert session._sftp.removed == ["/r/ok.txt"]

def file_symlinks_resolve_to_their_target_and_directory_links_are_skipped(client):
  session = client(
    tree={"/r": [Attr("flink", mode=LNK, size=9, mtime=1.0), Attr("dlink", mode=LNK),
      Attr("broken", mode=LNK), Attr("real.txt", size=5, mtime=2.0)]},
    targets={"/r/flink": Attr("flink", size=42, mtime=EPOCH), "/r/dlink": Attr("dlink", mode=DIR)},
    nostat=["/r/broken"],
  )
  idx = session._index_remote("/r")
  assert sorted(idx) == ["flink", "real.txt"]
  assert idx["flink"].st_size == 42  # the target's size, not the link's
  assert idx["flink"].st_mtime == EPOCH

def rmdir_unlinks_a_symlink_instead_of_following_it(client):
  session = client(tree={"/r": [Attr("dlink", mode=LNK)]},
    targets={"/r/dlink": Attr("dlink", mode=DIR)})
  session._sftp.files["/r/dlink"] = True
  session.rmdir("/r")
  assert session._sftp.removed == ["/r/dlink"]

#--------------------------------------------------------------------------------------- Sync

def sync_pull_refuses_to_delete_when_the_remote_root_is_missing(client, tmp_path):
  (tmp_path / "keep.txt").write_bytes(b"precious")
  session = client(missing=["/typo"])
  actions = session.sync_pull("/typo", str(tmp_path), delete=True)
  assert (tmp_path / "keep.txt").exists()
  assert not [a for a in actions if a[0] == "delete"]
  assert session._index_partial is True

def sync_pull_refuses_to_delete_on_a_partially_readable_tree(client, tmp_path):
  (tmp_path / "keep.txt").write_bytes(b"precious")
  session = client(tree={"/r": [Attr("sub", mode=DIR)]}, missing=["/r/sub"])
  session.sync_pull("/r", str(tmp_path), delete=True)
  assert (tmp_path / "keep.txt").exists()
  assert session._index_partial is True

def sync_pull_still_deletes_when_the_remote_listing_is_complete(client, tmp_path):
  (tmp_path / "stale.txt").write_bytes(b"old")
  session = client(tree={"/r": [Attr("new.txt")]})
  session.sync_pull("/r", str(tmp_path), delete=True)
  assert not (tmp_path / "stale.txt").exists()
  assert (tmp_path / "new.txt").exists()
  assert session._index_partial is False

def sync_push_creates_a_remote_root_that_does_not_exist_yet(client, tmp_path):
  (tmp_path / "a.txt").write_bytes(b"hello")
  session = client(missing=["/new"])
  actions = session.sync_push(str(tmp_path), "/new", delete=True)
  assert "/new/a.txt" in session._sftp.files
  assert ("put", "a.txt") in actions

#--------------------------------------------------------------------------------------- Exec

def exec_drains_stderr_concurrently_and_tolerates_non_utf8(client):
  gate = threading.Event()
  class Chan:
    def recv_exit_status(self): return 0
  class Stdout:
    def __init__(self): self.channel = Chan()
    def read(self):
      if not gate.wait(timeout=5): raise TimeoutError("stdout stalled: stderr never drained")
      return b"done\n"
  class Stderr:
    def read(self):
      gate.set()
      return b"\xff\xfe not utf8\n"
  class Remote:
    def exec_command(self, cmd): return None, Stdout(), Stderr()
  session = client()
  session._ssh = Remote()
  out, err = session.exec("build")
  assert out == "done"
  assert "not utf8" in err
