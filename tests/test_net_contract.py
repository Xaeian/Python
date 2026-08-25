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
