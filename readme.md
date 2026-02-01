# xaeian

Python utilities for files, strings, time, serial, structs, and database.

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

| Module        | Description                                      | Docs                              |
| ------------- | ------------------------------------------------ | --------------------------------- |
| `files`       | FILE, DIR, PATH, JSON, CSV, INI                  | [📖](xaeian/readme.md#files)       |
| `files_async` | Async wrappers via `asyncio.to_thread()`         | [📖](xaeian/readme.md#files_async) |
| `xstring`     | split, replace, strip comments, passwords        | [📖](xaeian/readme.md#xstring)     |
| `crc`         | CRC-8/16/32 with predefined variants             | [📖](xaeian/readme.md#crc)         |
| `colors`      | ANSI 256-color terminal codes                    | [📖](xaeian/readme.md#colors)      |
| `log`         | Colored logging with file rotation               | [📖](xaeian/readme.md#log)         |
| `xtime`       | Datetime parsing, arithmetic, rounding           | [📖](xaeian/readme.md#xtime)       |
| `cstruct`     | Binary struct serialization (C-like)             | [📖](xaeian/readme.md#cstruct)     |
| `serial_port` | Serial communication with colored output         | [📖](xaeian/readme.md#serial_port) |
| `cbash`       | Embedded device console protocol                 | [📖](xaeian/readme.md#cbash)       |
| `db`          | Database abstraction (SQLite, MySQL, PostgreSQL) | [🗃️](xaeian/db/readme.md)          |

## Quick Start

```python
from xaeian import FILE, JSON, logger

# Files
FILE.save("data.txt", "Hello!")
JSON.save("config", {"debug": True})
# Logging
log = logger("app")
log.info("Started")
# Database
from xaeian.db import Database
db = Database("sqlite", "app.db")
db.insert("users", {"name": "Jan"})
```

## License

MIT