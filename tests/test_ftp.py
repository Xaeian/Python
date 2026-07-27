# tests/test_ftp.py

"""FTP client: binary-mode quirks, listing fallbacks, and destructive-action guards."""

import datetime
import pytest
from xaeian.net import ftp as ftpmod
from xaeian.net.ftp import FTP, Attrs, _leaf, _safe_name, _unchanged

PERM = ftpmod.ftplib.error_perm
EPOCH = 1_700_000_000.0

class Server:
  """
  Deliberately strict FTP server.

  SIZE answers only in binary, NLST resets TYPE to ASCII (as ftplib's retrlines does),
  and RNTO refuses an existing target.
  """
  def __init__(self, files=None, dirs=(), mlsd=True, mfmt=True,
               unlistable=(), strict_rename=True, store_fail=False):
    self.files = dict(files or {})
    self.dirs = set(dirs)
    self.mlsd_ok, self.mfmt_ok = mlsd, mfmt
    self.unlistable = set(unlistable)
    self.strict_rename, self.store_fail = strict_rename, store_fail
    self.binary = False
    self.closed = False

  @staticmethod
  def stamp(epoch: float) -> str:
    return datetime.datetime.fromtimestamp(
      epoch, tz=datetime.timezone.utc).strftime("%Y%m%d%H%M%S")

  def _children(self, remote):
    dirs = sorted(d for d in self.dirs if d != remote and d.rsplit("/", 1)[0] == remote)
    files = sorted(p for p in self.files if p.rsplit("/", 1)[0] == remote)
    return dirs, files  # dirs first: a file after a subdir catches a lost TYPE I

  def connect(self, host, port, timeout=0): pass
  def login(self, user, password): pass
  def set_pasv(self, on): pass
  def quit(self): raise OSError("half-dead link")
  def close(self): self.closed = True

  def voidcmd(self, cmd):
    if cmd != "TYPE I": raise PERM("500")
    self.binary = True
    return "200"

  def sendcmd(self, cmd):
    if cmd == "FEAT":  # lowercase on purpose: FEAT casing is not guaranteed
      feat = ["211-Extensions:"]
      if self.mlsd_ok: feat.append(" mlst")
      if self.mfmt_ok: feat.append(" mfmt")
      return "\n".join(feat + ["211 End"])
    if cmd.startswith("MDTM "):
      path = cmd[5:]
      if path not in self.files: raise PERM("550")
      return "213 " + self.stamp(self.files[path][1])
    if cmd.startswith("MFMT "):
      if not self.mfmt_ok: raise PERM("500")
      _, when, path = cmd.split(" ", 2)
      moment = datetime.datetime.strptime(when, "%Y%m%d%H%M%S")
      self.files[path] = (self.files[path][0],
        moment.replace(tzinfo=datetime.timezone.utc).timestamp())
      return "213"
    raise PERM("500")

  def nlst(self, remote):
    self.binary = False  # retrlines sends TYPE A
    if remote in self.unlistable or remote not in self.dirs: raise PERM("550")
    dirs, files = self._children(remote)
    return dirs + files

  def mlsd(self, remote, facts=()):
    self.binary = False
    if remote in self.unlistable or remote not in self.dirs: raise PERM("550")
    dirs, files = self._children(remote)
    out = [(d.rsplit("/", 1)[-1], {"type": "DIR"}) for d in dirs]
    return out + [(p.rsplit("/", 1)[-1], {
      "type": "FILE", "size": str(self.files[p][0]), "modify": self.stamp(self.files[p][1]),
    }) for p in files]

  def size(self, path):
    if not self.binary: raise PERM("550 SIZE not allowed in ASCII mode")
    if path in self.dirs: raise PERM("550 is a directory")
    if path not in self.files: raise PERM("550 no such file")
    return self.files[path][0]

  def storbinary(self, cmd, handle, callback=None):
    self.binary = True
    path = cmd[5:]
    if self.store_fail:
      self.files[path] = (1, 1_000_000.0)  # a partial file already landed on the server
      raise OSError("transfer aborted")
    self.files[path] = (len(handle.read()), 1_000_000.0)

  def retrbinary(self, cmd, callback):
    self.binary = True
    path = cmd[5:]
    if path not in self.files: raise PERM("550")
    callback(b"x" * self.files[path][0])

  def rename(self, src, dst):
    if src not in self.files: raise PERM("550 no such source")
    if self.strict_rename and dst in self.files: raise PERM("550 target exists")
    self.files[dst] = self.files.pop(src)

  def delete(self, path):
    if path not in self.files: raise PERM("550")
    del self.files[path]

  def mkd(self, path):
    if path in self.dirs: raise PERM("550 exists")
    self.dirs.add(path)

  def rmd(self, path): self.dirs.discard(path)

@pytest.fixture
def client():
  def build(**kw):
    session = FTP("host", "user")
    session._ftp = Server(**kw)
    session._has_mlsd, session._has_mfmt = session._ftp.mlsd_ok, session._ftp.mfmt_ok
    return session
  return build

#--------------------------------------------------------------------------------- Connection

def connect_reports_failure_as_connection_error(monkeypatch):
  class Refusing(Server):
    def login(self, user, password): raise OSError("530 auth failed")
  monkeypatch.setattr(ftpmod.ftplib, "FTP", Refusing)
  with pytest.raises(ConnectionError):
    FTP("host", "user").connect()

def connect_detects_capabilities_from_a_lowercase_feat_reply(monkeypatch):
  monkeypatch.setattr(ftpmod.ftplib, "FTP", Server)
  session = FTP("host", "user")
  session.connect()
  assert session._has_mlsd and session._has_mfmt
  assert session._ftp.binary is True

def disconnect_frees_the_socket_when_quit_cannot_round_trip(client):
  session = client(dirs=["/r"])
  server = session._ftp
  session.disconnect()
  assert server.closed is True
  assert session._ftp is None

#-------------------------------------------------------------------------------- Single file

def stat_forces_binary_because_strict_servers_reject_size_in_ascii(client):
  session = client(files={"/d/a.txt": (10, EPOCH)}, dirs=["/d"])
  attrs = session.stat("/d/a.txt")
  assert attrs.st_size == 10
  assert attrs.st_mtime == EPOCH

def stat_returns_none_for_a_missing_path(client):
  session = client(dirs=["/d"])
  assert session.stat("/d/nope") is None
  assert session.exists("/d/nope") is False

def stat_does_not_disguise_a_dead_connection_as_a_missing_file(client):
  session = client(dirs=["/d"])
  def dead(path): raise OSError("connection reset")
  session._ftp.size = dead
  with pytest.raises(OSError):
    session.stat("/d/a.txt")

def atomic_put_overwrites_a_target_on_a_server_that_refuses_rnto(client, tmp_path):
  (tmp_path / "a.txt").write_bytes(b"hello")
  session = client(files={"/r/a.txt": (2, 1.0)}, dirs=["/r"])
  session.put(str(tmp_path / "a.txt"), "/r/a.txt")
  assert session._ftp.files["/r/a.txt"][0] == 5
  assert "/r/a.txt.tmp" not in session._ftp.files

def a_failed_upload_removes_the_partial_tmp_file(client, tmp_path):
  (tmp_path / "a.txt").write_bytes(b"hello")
  session = client(dirs=["/r"], store_fail=True)
  with pytest.raises(OSError):
    session.put(str(tmp_path / "a.txt"), "/r/a.txt")
  assert not [p for p in session._ftp.files if p.endswith(".tmp")]

def rename_does_not_destroy_the_target_when_the_source_is_gone(client):
  session = client(files={"/r/live.txt": (5, 1.0)}, dirs=["/r"])
  with pytest.raises(PERM):
    session.rename("/r/missing.tmp", "/r/live.txt")
  assert "/r/live.txt" in session._ftp.files

#------------------------------------------------------------------------------------ Listing

def index_walks_nested_directories_without_mlsd(client):
  session = client(files={"/r/sub/x.txt": (1, EPOCH), "/r/b.txt": (7, EPOCH)},
    dirs=["/r", "/r/sub"], mlsd=False)
  idx = session._index_remote("/r")
  assert sorted(idx) == ["b.txt", "sub/x.txt"]
  assert session._index_partial is False

def index_reasserts_binary_after_a_failed_nested_listing(client):
  # the nested NLST sends TYPE A and then fails, so it returns without restoring binary
  session = client(files={"/r/b.txt": (7, EPOCH)}, dirs=["/r", "/r/sub"],
    mlsd=False, unlistable=["/r/sub"])
  idx = session._index_remote("/r")
  assert "b.txt" in idx  # a file after the failed subdir must not be read as a directory
  assert session._index_partial is True

def index_without_mlsd_carries_mtime_from_mdtm(client):
  session = client(files={"/r/a.txt": (3, EPOCH)}, dirs=["/r"], mlsd=False)
  assert session._index_remote("/r")["a.txt"].st_mtime == EPOCH

def hostile_names_from_the_server_are_skipped(client):
  session = client(dirs=["/r"])
  session._ftp.mlsd = lambda remote, facts=(): [
    ("..", {"type": "FILE", "size": "1"}),
    ("a/b", {"type": "FILE", "size": "1"}),
    ("ok.txt", {"type": "FILE", "size": "1"}),
  ]
  assert sorted(session._index_remote("/r")) == ["ok.txt"]
  assert [a.filename for a in session.ls("/r")] == ["ok.txt"]

#--------------------------------------------------------------------------------------- Sync

def sync_pull_refuses_to_delete_when_the_remote_listing_failed(client, tmp_path):
  (tmp_path / "keep.txt").write_bytes(b"precious")
  session = client(unlistable=["/remote"])
  actions = session.sync_pull("/remote", str(tmp_path), delete=True)
  assert (tmp_path / "keep.txt").exists()
  assert not [a for a in actions if a[0] == "delete"]
  assert session._index_partial is True

def sync_pull_still_deletes_when_the_remote_listing_is_complete(client, tmp_path):
  (tmp_path / "stale.txt").write_bytes(b"old")
  session = client(files={"/r/new.txt": (3, EPOCH)}, dirs=["/r"])
  session.sync_pull("/r", str(tmp_path), delete=True)
  assert not (tmp_path / "stale.txt").exists()
  assert (tmp_path / "new.txt").exists()
  assert session._index_partial is False

def sync_push_creates_a_remote_root_that_does_not_exist_yet(client, tmp_path):
  (tmp_path / "a.txt").write_bytes(b"hello")
  session = client()
  actions = session.sync_push(str(tmp_path), "/new", delete=True)
  assert "/new/a.txt" in session._ftp.files
  assert ("put", "a.txt") in actions

def push_falls_back_to_size_only_when_the_server_cannot_set_mtime(client, tmp_path):
  (tmp_path / "a.txt").write_bytes(b"hello")
  session = client(files={"/r/a.txt": (5, 999_999.0)}, dirs=["/r"], mfmt=False)
  assert ("skip", "a.txt") in session.sync_push(str(tmp_path), "/r")

def push_compares_mtime_when_the_server_supports_mfmt(client, tmp_path):
  (tmp_path / "a.txt").write_bytes(b"hello")
  session = client(files={"/r/a.txt": (5, 999_999.0)}, dirs=["/r"], mfmt=True)
  assert ("put", "a.txt") in session.sync_push(str(tmp_path), "/r")

#------------------------------------------------------------------------------------ Helpers

def leaf_takes_the_last_segment_of_any_nlst_answer():
  assert _leaf("a.txt") == "a.txt"
  assert _leaf("dir/a.txt") == "a.txt"
  assert _leaf("/srv/dir/a.txt") == "a.txt"

def safe_name_rejects_traversal_and_separators():
  assert _safe_name("ok.txt")
  assert not any(_safe_name(n) for n in ("", ".", "..", "a/b", "a\\b"))

def unchanged_compares_mtime_only_when_it_can_be_trusted():
  attrs = Attrs(st_size=5, st_mtime=999.0)
  assert not _unchanged(attrs, 111.0, 5)
  assert _unchanged(attrs, 111.0, 5, use_mtime=False)
  assert _unchanged(Attrs(st_size=5, st_mtime=111.0), 111.0, 5)
