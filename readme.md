# `xaeian`

Python utilities for files, strings, time, serial, structs, and database.
Zero dependencies for core modules. Optional extras for time, serial, and database backends.

## Install

```bash
pip install xaeian            # core
pip install xaeian[time]      # + pytz, tzlocal
pip install xaeian[serial]    # + pyserial
pip install xaeian[db]        # + pymysql, psycopg2
pip install xaeian[db-async]  # + aiomysql, asyncpg, aiosqlite
pip install xaeian[all]       # everything
```

## Modules

| Module        | Description                                      | Docs                                                  |
| ------------- | ------------------------------------------------ | ----------------------------------------------------- |
| `files`       | FILE, DIR, PATH, JSON, CSV, INI                  | [xaeian/files.py](xaeian/readme.md#files)             |
| `files_async` | Async wrappers via `asyncio.to_thread()`         | [xaeian/files_async.py](xaeian/readme.md#files_async) |
| `xstring`     | split, replace, strip comments, passwords        | [xaeian/xstring.py](xaeian/readme.md#xstring)         |
| `xtime`       | Datetime parsing, arithmetic, rounding           | [xaeian/xtime.py](xaeian/readme.md#xtime)             |
| `colors`      | ANSI 256-color terminal codes                    | [xaeian/colors.py](xaeian/readme.md#colors)           |
| `log`         | Colored logging with file rotation               | [xaeian/log.py](xaeian/readme.md#log)                 |
| `crc`         | CRC-8/16/32 with predefined variants             | [xaeian/crc.py](xaeian/readme.md#crc)                 |
| `cstruct`     | Binary struct serialization (C-like)             | [xaeian/cstruct.py](xaeian/readme.md#cstruct)         |
| `serial_port` | Serial communication with colored output         | [xaeian/serial_port.py](xaeian/readme.md#serial_port) |
| `cbash`       | Embedded device console protocol                 | [xaeian/cbash.py](xaeian/readme.md#cbash)             |
| `db`          | Database abstraction (SQLite, MySQL, PostgreSQL) | [xaeian/db/](xaeian/db/readme.md)                     |

## Quick Start

```python
from xaeian import FILE, JSON, CSV, logger, generate_password
from xaeian.xtime import Time
from xaeian.crc import crc16_modbus

# File operations
config = JSON.load("config")
CSV.save("export", [{"name": "Jan", "score": 95}, {"name": "Anna", "score": 88}])
# Time arithmetic
deadline = Time("2025-03-01") + "2w" # + 2 weeks
if Time() > deadline:
  print("Overdue!")
# CRC protection
frame = crc16_modbus.encode(b"\x01\x03\x00\x00\x00\x0A")
if crc16_modbus.decode(frame):
  print("Valid Modbus frame")
# Colored logging
log = logger("app", file="app.log", color=True)
log.info(f"New password: {generate_password(16)}")
```

**Database example:**

```python
from xaeian.db import Database

db = Database("sqlite", "app.db")
db.insert("users", {"name": "Jan", "email": "jan@example.com"})
user = db.find_one("users", name="Jan")
users = db.find("users", order="name", limit=10)
with db.transaction():
  db.update("users", {"verified": True}, "id = ?", user["id"])
  db.insert("logs", {"action": "verify", "user_id": user["id"]})
```

## License

MIT