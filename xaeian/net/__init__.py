# xaeian/net/__init__.py

"""
Network clients: SFTP, FTP and S3 over one vocabulary, plus a plain HTTP `download`.

`xaeian.net.ftp`, `xaeian.net.s3` and `xaeian.net.http` run on the stdlib.
`xaeian.net.sftp` needs `paramiko`, so `SFTP` is exported only where that extra is installed.

`Remote` builds the two that address a box by host and login. `S3` is constructed on its own,
because an access key is not a user and a secret is not a password, and a factory pretending
otherwise would be lying in its own signature.

Example:
  >>> from xaeian.net import Remote, S3
  >>> with Remote("sftp", "10.0.0.1", "pi", key="~/.ssh/id_rsa") as r:
  ...   r.sync_push("./data", "/srv/data")
  >>> with Remote("ftp", "10.0.0.1", "user", password="pass") as r:
  ...   r.sync_pull("/srv/data", "./data")
  >>> with S3("<account>.r2.cloudflarestorage.com", key_id, secret, "assets") as s3:
  ...   s3.sync_push("./dist", "cdn", delete=True)
"""

from ..extras import MissingExtra
from .ftp import FTP
from .s3 import S3
from .http import download

__all__ = ["Remote", "FTP", "S3", "download"]

try:
  from .sftp import SFTP
  __all__ += ["SFTP"]
except MissingExtra:
  pass

_PORTS = {"sftp": 22, "ftp": 21}

def Remote(
  backend:str,
  host:str,
  user:str,
  port:int|None = None,
  *,
  password:str|None = None,
  key:str|None = None,
  passphrase:str|None = None,
  agent:bool = False,
  strict:bool = False,
  log = None,
) -> "FTP|SFTP":
  """
  Build a remote client. Not connected yet: use `with` or call `connect()`.

  `key`, `passphrase`, `agent` and `strict` are SFTP-only.
  Asking for `"sftp"` without `paramiko` raises `MissingExtra`.

  Args:
    backend: `"sftp"` or `"ftp"`. S3 is its own class, not a backend here.
    port: Defaults to 22 for SFTP, 21 for FTP.
    password: Optional for SFTP when `key` is set.
    key: SSH private key path.
    strict: Reject an unknown host key instead of trusting it on first use.
    log: `Print`, `Logger`, or `None`.
  """
  name = backend.lower()
  if name in ("s3", "r2"):
    raise ValueError("S3 is not a Remote backend, its credentials are a different shape: "
      "build it directly with S3(endpoint, key_id, secret, bucket)")
  if name not in _PORTS: raise ValueError(f"Unknown remote type: {backend!r}")
  port = port or _PORTS[name]
  if name == "ftp": return FTP(host, user, port, password=password, log=log)
  from .sftp import SFTP
  return SFTP(host, user, port, password=password, key=key,
    passphrase=passphrase, agent=agent, strict=strict, log=log)
