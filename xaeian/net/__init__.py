# xaeian/net/__init__.py

"""
Network clients: SFTP and FTP with unified interface.

Modules:
  - `xaeian.net.ftp`: FTP client (stdlib `ftplib`, no extra deps)
  - `xaeian.net.sftp`: SFTP client (requires `paramiko`)

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
  type: str,
  host: str,
  user: str,
  port: int|None = None,
  *,
  password: str|None = None,
  key: str|None = None,
  passphrase: str|None = None,
  agent: bool = False,
  log=None,
) -> "SFTP|FTP": # type: ignore
  """
  Create remote client instance.

  Args:
    type: Protocol (`"sftp"` or `"ftp"`).
    host: Remote hostname or IP.
    user: Username.
    port: Port (default: 22 for SFTP, 21 for FTP).
    password: Password (SFTP: optional if `key` set).
    key: SSH private key path (SFTP only).
    passphrase: Key passphrase (SFTP only).
    agent: Use SSH agent (SFTP only).
    log: `Print`, `Logger`, or `None`.

  Returns:
    `SFTP` or `FTP` instance (use as context manager).

  Example:
    >>> with Remote("sftp", "host", "pi", key="~/.ssh/id_rsa", log=Print()) as r:
    ...   r.sync_push("./dist", "/srv/app")
    >>> with Remote("ftp", "host", "user", password="pass") as r:
    ...   r.sync_pull("/srv/data", "./data")
  """
  t = type.lower()
  if t not in _PORTS: raise ValueError(f"Unknown remote type: {type!r}")
  p = port or _PORTS[t]
  if t == "sftp":
    if SFTP is None: raise ImportError("Install with: pip install xaeian[sftp]")
    return SFTP(host, user, p, password=password, key=key,
      passphrase=passphrase, agent=agent, log=log)
  return FTP(host, user, p, password=password or "", log=log)

__all__ = ["Remote", "FTP", "SFTP"]