# `xaeian.net`

Network clients: SFTP, FTP and S3 over one vocabulary.

SFTP requires `pip install xaeian[sftp]`. FTP and S3 use stdlib only.

## Quick start

```py
from xaeian.net import Remote, S3
from xaeian import Print

# SFTP
with Remote("sftp", "10.0.0.1", "pi", key="~/.ssh/id_rsa", log=Print()) as r:
  r.sync_push("./data", "/srv/data")

# FTP
with Remote("ftp", "10.0.0.1", "user", password="pass") as r:
  r.sync_pull("/srv/data", "./data")

# S3, its own class: an access key is not a user
with S3("<account>.r2.cloudflarestorage.com", key_id, secret, "assets") as s3:
  s3.sync_push("./dist", "cdn", delete=True)
```

## `Remote(type, host, user, ...)`

Factory, returns an `SFTP` or `FTP` instance.
S3 is not a backend here: its credentials are another shape, so it is built directly.
`Remote("s3", ...)` raises and says so.

| Param        | Default     | Notes                          |
| ------------ | ----------- | ------------------------------ |
| `type`       | -           | `"sftp"` or `"ftp"`            |
| `host`       | -           | Hostname or IP                 |
| `user`       | -           | Username                       |
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
r.stat("/srv/file.json")    # → Attrs | SFTPAttributes | None
r.exists("/srv/file.json")  # → bool

# Directories
r.mkdir("/srv/new/dir")  # recursive, idempotent
r.rmdir("/srv/old")      # recursive
r.ls("/srv/data")        # → list[Attrs | SFTPAttributes]

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

A `filter` is asked about folders as well as files, each as `name` and as `name/`, and a folder
it holds back prunes everything below it. The same on either side of a sync, so what a push
sends is what a pull brings back. Write one as a denylist: an allowlist that only ever matches
file names rejects every folder and so prunes the whole tree.

Failures read alike from either client:
`FileNotFoundError` for a path that is not there,
`PermissionError` for one this login may not have,
`ConnectionError` for a session that cannot be opened.
FTP answers the first two with one code, so it asks the server which it was before raising.

## SFTP extras

```py
from xaeian.net import SFTP

with SFTP("host", "user", key="~/.ssh/id_rsa") as s:
  s.exec("systemctl restart app") # → (stdout, stderr)

# Auth priority: key > password > agent
SFTP("host", "user", key="~/.ssh/id_rsa", passphrase="secret")
SFTP("host", "user", password="pass")
SFTP("host", "user", agent=True)
```

Host keys are checked against `~/.ssh/known_hosts`. An unknown host is trusted on first
contact and its key is pinned to `~/.ssh/known_hosts.xaeian`, so a changed server key aborts
the next connect; `strict=True` rejects unknown hosts outright. `xn host` lists the pinned
keys, `xn host <ip>` shows one, and `xn host <ip> --drop` removes it after a server rebuild.

## FTP notes

Skip strategy depends on server capabilities detected at connect:
- `sync_push` → **mtime + size** with MFMT, **size only** without
- `sync_pull` → **mtime + size** with MLSD or MDTM, **size only** without

`preserve_mtime` on upload needs MFMT - without it the remote mtime is left as-is.

FTP is cleartext: prefer SFTP when confidentiality matters.

## `S3(endpoint, key_id, secret, bucket, ...)`

Its own class, not a `Remote` backend.
An access key is not a user and a secret is not a password,
so a factory taking `host, user, password` would be lying in its own signature.

| Param      | Default  | Notes                                  |
| ---------- | -------- | -------------------------------------- |
| `endpoint` | -        | Host only, no scheme                   |
| `key_id`   | -        | Access key id                          |
| `secret`   | -        | Secret access key                      |
| `bucket`   | -        | The bucket every key lives in          |
| `region`   | `"auto"` | R2 has none; AWS needs the bucket's    |
| `verify`   | `True`   | Ask the bucket on connect              |
| `log`      | `None`   | `Print`, `Logger`, or `None`           |

Cloudflare R2, Backblaze B2, Wasabi, MinIO and AWS itself. SigV4 is signed by hand over stdlib
`http.client`, so the client costs no dependency and holds one TLS connection per context.

```py
from xaeian.net import S3

with S3("<account>.r2.cloudflarestorage.com", key_id, secret, "assets") as s3:
  # Single object
  s3.put("./dist/app.js", "cdn/app.js")
  s3.get("cdn/app.js", "./local/app.js")
  s3.copy("cdn/app.js", "cdn/app.bak.js") # server-side, the bytes never leave the store
  s3.rename("cdn/app.bak.js", "cdn/old/app.js")
  s3.remove("cdn/old/app.js")

  s3.stat("cdn/app.js")    # → Attrs | None
  s3.exists("cdn/app.js")  # → bool

  # Prefixes
  s3.ls("cdn")         # → one level, folders come back as CommonPrefixes
  s3.walk("cdn")       # → every object below, one request per 1000 keys
  s3.rmdir("cdn/old")  # → the whole prefix, 1000 keys per call

  # Batch and sync
  s3.put_dir("./dist", "cdn", filter=lambda p: not p.endswith(".map"))
  s3.get_dir("cdn", "./backup")
  s3.sync_push("./dist", "cdn", delete=True, dry_run=True)
  s3.sync_pull("cdn", "./backup", delete=True)
```

Skip strategy: **size, then ETag**, which for a single-part upload is the object's own MD5. A
same-size edit is caught here, where FTP without MFMT calls it unchanged. A multipart object's
ETag digests the part digests, which no client can reproduce, so those fall back to size alone.

`sync_pull` needs no guard against a partial listing: a listing that fails raises rather than
coming back short, and one short of a page carries the token to the next.

### What an object store does differently

- `mkdir` does nothing. A prefix is there from the moment the first object is written under it
- `ls` of a prefix holding nothing answers `[]`, where the file clients raise `FileNotFoundError`.
  Nothing records a prefix anywhere, only the keys under it, so empty and missing are one state
- `exists` answers `False` for a folder, where `FTP` and `SFTP` answer `True`
- `rename` is a server-side copy followed by a delete.
  `copy` reads the response body, not the status line:
  S3 answers `200` before it knows how the copy went, and reports the failure inside
- `put` over 5 GiB goes up in parts, and takes the upload back down if a part fails
- `atomic` and `preserve_mtime` on `put` are accepted and ignored:
  one request lands the whole object, and `LastModified` is when it landed, which no client sets
- `walk` is S3 only.
  A file protocol needs one listing per folder, which `sync_push` already does for it;
  the store answers the whole subtree in one request

A key holding `..` is stored happily, because keys are literal and nothing resolves them.
It is left out of `walk`, where it would otherwise become a local path and escape the root.

## `download(url, local, ...)`

Plain HTTP(S) into a file, no client, no login: a release, a package, a public asset.
Same shape as `S3.get`: the bytes land beside the target and are swapped in on completion.
`callback` gets `(url, bytes_done, bytes_total)` per chunk,
total `0` when the server does not say.
Errors are the stdlib ones, `urllib.error.HTTPError` and `URLError`.

```py
from xaeian.net import download

download("https://example.com/tool.zip", "tool.zip")
```
