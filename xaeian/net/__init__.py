# xaeian/net/__init__.py

"""
Network clients: SFTP and FTP with unified interface.

`xaeian.net.ftp` runs on stdlib `ftplib`, `xaeian.net.sftp` needs `paramiko`.

Example:
  >>> from xaeian.net import Remote
  >>> with Remote("sftp", "10.0.0.1", "pi", key="~/.ssh/id_rsa") as r:
  ...   r.sync_push("./data", "/srv/data")
  >>> with Remote("ftp", "10.0.0.1", "user", password="pass") as r:
  ...   r.sync_pull("/srv/data", "./data")
"""

from .ftp import FTP
try:
  from .sftp import SFTP
except ImportError:
  SFTP = None

_PORTS = {"sftp": 22, "ftp": 21}

def Remote(
  type:str,
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
) -> "SFTP|FTP": # type: ignore
  """
  Build a remote client. Not connected yet: use `with` or call `connect()`.

  `key`, `passphrase`, `agent` and `strict` are SFTP-only.

  Args:
    type: `"sftp"` or `"ftp"`.
    port: Defaults to 22 for SFTP, 21 for FTP.
    password: Optional for SFTP when `key` is set.
    key: SSH private key path.
    strict: Reject an unknown host key instead of trusting it on first use.
    log: `Print`, `Logger`, or `None`.
  """
  t = type.lower()
  if t not in _PORTS: raise ValueError(f"Unknown remote type: {type!r}")
  p = port or _PORTS[t]
  if t == "sftp":
    if SFTP is None: raise ImportError("Install with: pip install xaeian[sftp]")
    return SFTP(host, user, p, password=password, key=key,
      passphrase=passphrase, agent=agent, strict=strict, log=log)
  return FTP(host, user, p, password=password, log=log)

__all__ = ["Remote", "FTP", "SFTP"]