# `xaeian.net`

Network clients: SFTP and FTP with unified interface.

SFTP requires `pip install xaeian[sftp]`. FTP uses stdlib only.

## Quick start

```py
from xaeian.net import Remote
from xaeian import Print

# SFTP
with Remote("sftp", "10.0.0.1", "pi", key="~/.ssh/id_rsa", log=Print()) as r:
  r.sync_push("./data", "/srv/data")

# FTP
with Remote("ftp", "10.0.0.1", "user", password="pass") as r:
  r.sync_pull("/srv/data", "./data")
```

## `Remote(type, host, user, ...)`

Factory — returns `SFTP` or `FTP` instance.

| Param        | Default     | Notes                          |
| ------------ | ----------- | ------------------------------ |
| `type`       | —           | `"sftp"` or `"ftp"`            |
| `host`       | —           | Hostname or IP                 |
| `user`       | —           | Username                       |
| `port`       | `22` / `21` | Override if non-standard       |
| `password`   | `None`      | SFTP: optional if `key` set    |
| `key`        | `None`      | SFTP only: path to private key |
| `passphrase` | `None`      | SFTP only: key passphrase      |
| `agent`      | `False`     | SFTP only: use SSH agent       |
| `log`        | `None`      | `Print`, `Logger`, or `None`   |

## Interface

Both: `SFTP` and `FTP`

```py
# Single file
r.put("local/file.json", "/srv/file.json")
r.get("/srv/file.json", "local/file.json")
r.remove("/srv/old.json")
r.rename("/srv/tmp.json", "/srv/file.json")
r.stat("/srv/file.json")   # → Attrs | SFTPAttributes | None
r.exists("/srv/file.json") # → bool

# Directories
r.mkdir("/srv/new/dir")    # recursive, idempotent
r.rmdir("/srv/old")        # recursive
r.ls("/srv/data")          # → list[Attrs]

# Batch
r.put_dir("./dist", "/srv/app", filter=lambda p: not p.endswith(".pyc"))
r.get_dir("/srv/data", "./backup")

# Sync (skip unchanged)
actions = r.sync_push("./dist", "/srv/app", delete=True, dry_run=True)
actions = r.sync_push("./dist", "/srv/app", delete=True)
actions = r.sync_pull("/srv/data", "./local")
# actions → [("put"|"get"|"skip"|"delete", rel_path), ...]
```

## SFTP extras

```py
from xaeian.net import SFTP

with SFTP("host", "user", key="~/.ssh/id_rsa") as s:
  s.exec("systemctl restart app")  # → (stdout, stderr)

# Auth priority: key > password > agent
SFTP("host", "user", key="~/.ssh/id_rsa", passphrase="secret")
SFTP("host", "user", password="pass")
SFTP("host", "user", agent=True)
```

## FTP notes

Skip strategy depends on server capabilities detected at connect:
- MLSD available → skip by **mtime + size**
- MLSD unavailable (vsftpd, IIS) → skip by **size only**

`preserve_mtime` on upload uses MFMT — silent no-op if server lacks it.