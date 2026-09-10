# tests/test_net_contract.py

"""
One contract, both transports.

`Remote()` promises FTP and SFTP can stand in for each other, so both must answer alike over
one logical tree: a root holding `a.txt` of 3 bytes, and an empty directory `sub`.

Each case seeds its fake server with that tree and hands back the client plus one lens
turning a listing entry into `(name, is_dir)`. No test body branches on the transport.
"""

import pytest

import test_ftp
import test_sftp
from xaeian.net.ftp import FTP
from xaeian.net.sftp import SFTP, _is_dir as sftp_is_dir

EPOCH = 1_700_000_000.0

@pytest.fixture(params=["ftp", "sftp"])
def remote(request):
  """A connected client over the shared tree, and a lens turning an entry into (name, is_dir)."""
  if request.param == "ftp":
    session = FTP("host", "user")
    session._ftp = test_ftp.Server(
      files={"root/a.txt": (3, EPOCH)},
      dirs={"root", "root/sub"},
    )
    session._has_mlsd, session._has_mfmt = True, True
    return session, lambda entry: (entry.filename, entry.is_dir)
  session = SFTP("host", "user")
  session._sftp = test_sftp.Client(
    tree={
      "root": [
        test_sftp.Attr("a.txt", size=3, mtime=EPOCH),
        test_sftp.Attr("sub", mode=test_sftp.DIR),
      ],
      "root/sub": [],
    },
    targets={"root/sub": test_sftp.Attr("sub", mode=test_sftp.DIR)},
  )
  session._ssh = test_sftp.Ssh()
  return session, lambda entry: (entry.filename, sftp_is_dir(entry))

@pytest.fixture(params=["ftp", "sftp"])
def denied(request):
  """
  A connected client over a `root` the server guards: it will not create `denied` inside it,
  and will not delete the `locked.txt` that is already there.
  """
  if request.param == "ftp":
    session = FTP("host", "user")
    session._ftp = test_ftp.Server(
      files={"root/locked.txt": (3, EPOCH)},
      dirs={"root"},
      unwritable={"root/denied", "root/locked.txt"},
    )
    session._has_mlsd, session._has_mfmt = True, True
    return session
  session = SFTP("host", "user")
  session._sftp = test_sftp.Client(
    tree={"root": [test_sftp.Attr("locked.txt", size=3, mtime=EPOCH)]},
    unwritable={"root/denied", "root/locked.txt"},
  )
  session._ssh = test_sftp.Ssh()
  return session

@pytest.fixture(params=["ftp", "sftp"])
def empty(request):
  """A connected client over a bare `root`, and a lens answering what has landed in it."""
  if request.param == "ftp":
    session = FTP("host", "user")
    session._ftp = test_ftp.Server(dirs={"root"})
    session._has_mlsd, session._has_mfmt = True, True
    return session, lambda: set(session._ftp.files)
  session = SFTP("host", "user")
  session._sftp = test_sftp.Client(tree={"root": []})
  session._ssh = test_sftp.Ssh()
  return session, lambda: set(session._sftp.files)

#------------------------------------------------------------------------------------- the contract

def a_file_exists_and_a_missing_path_does_not(remote):
  client, _ = remote
  assert client.exists("root/a.txt") is True
  assert client.exists("root/nope.txt") is False

def a_directory_exists_too(remote):
  """FTP used to answer `False` for a directory that SFTP answered `True` for."""
  client, _ = remote
  assert client.exists("root/sub") is True

def stat_reports_the_size_and_none_for_a_missing_path(remote):
  client, _ = remote
  assert client.stat("root/a.txt").st_size == 3
  assert client.stat("root/nope.txt") is None

def ls_lists_the_same_names_and_kinds(remote):
  client, kind = remote
  assert sorted(kind(e) for e in client.ls("root")) == [("a.txt", False), ("sub", True)]

def ls_of_an_empty_directory_is_empty(remote):
  client, _ = remote
  assert client.ls("root/sub") == []

def a_missing_directory_is_not_an_empty_one(remote):
  """
  FTP answers both with 550, and answering `[]` to either made a directory that vanished
  read as one that was simply empty. Code handed a client by `Remote` cannot tell them apart
  unless both raise.
  """
  client, _ = remote
  with pytest.raises(FileNotFoundError):
    client.ls("root/nope")

def mkdir_says_nothing_about_a_directory_that_is_already_there(remote):
  client, _ = remote
  client.mkdir("root/sub")

def a_missing_file_cannot_be_downloaded(remote, tmp_path):
  client, _ = remote
  with pytest.raises(FileNotFoundError):
    client.get("root/nope.txt", str(tmp_path / "out.txt"))

def a_refused_delete_is_not_a_silent_one(denied):
  """
  Deleting what is already gone is the outcome the caller asked for, so both clients keep
  quiet about it. Being told no is the opposite, and `ftplib.error_perm` is not an `OSError`,
  so code written against `Remote` caught it on one client and missed it on the other.
  """
  with pytest.raises(PermissionError):
    denied.remove("root/locked.txt")

def a_refused_directory_is_not_a_missing_one(denied):
  """
  Both clients swallow the reply to a create and read the answer from the tree instead, and
  both used to read a refusal as "not there". `FileNotFoundError` promises a path nobody
  has; a path this login may not have is a different answer.
  """
  with pytest.raises(PermissionError):
    denied.mkdir("root/denied")

def a_filter_prunes_the_local_side_as_it_prunes_the_remote(empty, tmp_path):
  """
  The remote index prunes per folder, so a local side that did not would send the excluded
  files on every run and never once read one back as unchanged.

  The filter names the folder only. A flat check would be asked about `vendor/x.txt`, which
  it has no opinion on, and would let it through.
  """
  client, landed = empty
  (tmp_path / "keep.txt").write_bytes(b"hello")
  (tmp_path / "vendor").mkdir()
  (tmp_path / "vendor" / "x.txt").write_bytes(b"hello")
  actions = client.sync_push(str(tmp_path), "root",
    filter=lambda p: p not in ("vendor", "vendor/"))
  assert ("put", "keep.txt") in actions
  assert not [a for a in actions if a[1].startswith("vendor")]
  assert not [path for path in landed() if "vendor" in path]
