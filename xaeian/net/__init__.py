# xaeian/net/__init__.py

"""
Network clients: SFTP and FTP with unified interface.

`xaeian.net.ftp` runs on stdlib `ftplib`.
`xaeian.net.sftp` needs `paramiko`, so `SFTP` is exported only where that extra is installed.

Example:
  >>> from xaeian.net import Remote
  >>> with Remote("sftp", "10.0.0.1", "pi", key="~/.ssh/id_rsa") as r:
  ...   r.sync_push("./data", "/srv/data")
  >>> with Remote("ftp", "10.0.0.1", "user", password="pass") as r:
  ...   r.sync_pull("/srv/data", "./data")
"""

from ..extras import MissingExtra
from .ftp import FTP

__all__ = ["Remote", "FTP"]

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
    backend: `"sftp"` or `"ftp"`.
    port: Defaults to 22 for SFTP, 21 for FTP.
    password: Optional for SFTP when `key` is set.
    key: SSH private key path.
    strict: Reject an unknown host key instead of trusting it on first use.
    log: `Print`, `Logger`, or `None`.
  """
  name = backend.lower()
  if name not in _PORTS: raise ValueError(f"Unknown remote type: {backend!r}")
  port = port or _PORTS[name]
  if name == "ftp": return FTP(host, user, port, password=password, log=log)
  from .sftp import SFTP
  return SFTP(host, user, port, password=password, key=key,
    passphrase=passphrase, agent=agent, strict=strict, log=log)
