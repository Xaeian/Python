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
| `strict`     | `False`     | SFTP only: reject unknown keys |
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
r.ls("/srv/data")          # → list[Attrs | SFTPAttributes]

# Batch
r.put_dir("./dist", "/srv/app", filter=lambda p: not p.endswith(".pyc"))
r.get_dir("/srv/data", "./backup")

# Sync (skip unchanged)
actions = r.sync_push("./dist", "/srv/app", delete=True, dry_run=True)
actions = r.sync_push("./dist", "/srv/app", delete=True)
actions = r.sync_pull("/srv/data", "./local")
# actions → [("put"|"get"|"skip"|"delete", rel_path), ...]
```

`sync_pull` refuses to `delete` on an incomplete remote listing.

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

Host keys are checked against `~/.ssh/known_hosts`; `strict=True` also rejects unknown hosts.

## FTP notes

Skip strategy depends on server capabilities detected at connect:
- `sync_push` → **mtime + size** with MFMT, **size only** without
- `sync_pull` → **mtime + size** with MLSD or MDTM, **size only** without

`preserve_mtime` on upload needs MFMT — without it the remote mtime is left as-is.

FTP is cleartext: prefer SFTP when confidentiality matters.