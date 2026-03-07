# `xaeian`

Python utilities. Zero dependencies for core. Optional extras for time, serial, media, database.

## Install

```bash
pip install xaeian            # core
pip install xaeian[time]      # + pytz, tzlocal
pip install xaeian[serial]    # + pyserial
pip install xaeian[mf]        # + pypdf, PyMuPDF, Pillow
pip install xaeian[db]        # + pymysql, psycopg2
pip install xaeian[db-async]  # + aiomysql, asyncpg, aiosqlite
pip install xaeian[all]       # everything
```

## Examples

```python
from xaeian import FILE, JSON, CSV, logger, split_str, generate_password
from xaeian.xtime import Time
from xaeian.crc import crc16_modbus
from xaeian.db import Database

# Files: auto extension, context-based paths
JSON.save("config", {"debug": True, "port": 8080})
CSV.save("users", [{"name": "Jan", "age": 30}, {"name": "Anna", "age": 25}])

# Time: parse anything, arithmetic with strings
t = Time("2025-03-01") + "2w 3d"
t.round("w")  # Monday 00:00
t.to("iso")   # "2025-03-17T00:00:00+01:00"

# CRC: encode/decode with Modbus, ISO, custom
frame = crc16_modbus.encode(b"\x01\x03\x00\x00\x00\x0A")
assert crc16_modbus.decode(frame) is not None

# String tools
split_str('a,"b,c",d', sep=",")  # ['a', '"b,c"', 'd']
generate_password(16)            # 'aB3$xY9!mN2@pQ7&'

# Database: sqlite/mysql/postgres, sync/async
db = Database("sqlite", "app.db")
db.insert("users", {"name": "Jan", "settings": {"theme": "dark"}})
db.find("users", order="name", limit=10)
async with db.transaction():
  db.update("users", {"verified": True}, "id = ?", 42)

# Media: compress, strip metadata
from xaeian.mf.min import compress
compress("report.pdf")            # → report-min.pdf
compress("photos/", max_px=1280)  # → photos-min/ (recursive)

# Logging: colored, rotating
log = logger("app", file="app.log")
log.info("started")  # 2025-03-01 14:32:01 INF started
```

## Modules

| Module        | Description                                        | Docs                                             |
| ------------- | -------------------------------------------------- | ------------------------------------------------ |
| `files`       | FILE, DIR, PATH, JSON, CSV, INI                    | [xaeian/readme.md](xaeian/readme.md#files)       |
| `files_async` | Async wrappers via `asyncio.to_thread()`           | [xaeian/readme.md](xaeian/readme.md#files_async) |
| `table`       | Lightweight tabular ops on `list[dict]`            | [xaeian/readme.md](xaeian/readme.md#table)       |
| `xstring`     | Split, replace, strip comments, passwords          | [xaeian/readme.md](xaeian/readme.md#xstring)     |
| `xtime`       | Datetime parsing, arithmetic, rounding             | [xaeian/readme.md](xaeian/readme.md#xtime)       |
| `colors`      | ANSI 256-color terminal codes                      | [xaeian/readme.md](xaeian/readme.md#colors)      |
| `log`         | Colored logging with file rotation                 | [xaeian/readme.md](xaeian/readme.md#log)         |
| `crc`         | CRC-8/16/32 with predefined variants               | [xaeian/readme.md](xaeian/readme.md#crc)         |
| `cstruct`     | Binary struct serialization _(C-like)_             | [xaeian/readme.md](xaeian/readme.md#cstruct)     |
| `cmd`         | Shell command helpers                              | [xaeian/readme.md](xaeian/readme.md#cmd)         |
| `serial_port` | Serial communication with colored output           | [xaeian/readme.md](xaeian/readme.md#serial_port) |
| `cbash`       | Embedded device console protocol                   | [xaeian/readme.md](xaeian/readme.md#cbash)       |
| `mf`          | Compress, convert, strip metadata _(PDF & images)_ | [xaeian/mf/readme.md](xaeian/mf/readme.md)       |
| `db`          | Database abstraction _(SQLite, MySQL, PostgreSQL)_ | [xaeian/db/readme.md](xaeian/db/readme.md)       |
| `eda`         | E-series, KiCad production export                  | [xaeian/eda/readme.md](xaeian/eda/readme.md)     |
| `cli`         | tree, dupes, wifi scripts                          | [xaeian/cli/readme.md](xaeian/cli/readme.md)     |