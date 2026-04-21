# Xaeian

Python utilities. Zero dependencies for core. Optional extras for time, serial, media, database and more...

## Philosophy

Xaeian wraps stdlib boilerplate into intent-level APIs. You read what code does, not how. In real projects this cuts **~35%** of code volume.

This follows the **Zen** of Python:

- Beautiful over ugly: `Time() + "15m"` vs `datetime.now(tz=...) + timedelta(minutes=15)`
- Simple over complex: `db.find_one("users", id=42)` vs acquire/try/finally/dict/close
- Flat over nested: `DIR.zip(src, out)` vs `os.walk` + `zipfile` + `os.path.relpath` loop
- Readability counts: code reads like intentions, not implementation
- One obvious way to do it: `crc16_modbus.encode(frame)`, `JSON.load(path)`, `Time(ts).to("iso")`
- Errors should never pass silently: `DatabaseError` wraps driver exceptions with context
- Namespaces are one honking great idea: `FILE`, `DIR`, `PATH`, `CSV`, `JSON`, `CRC` as static classes

Trade-offs:

- Explicit over implicit: `PATH.resolve` auto-joins with CWD, `db.insert` auto-serializes dicts to JSON and ISO strings to datetime. Convenient in 95% of cases, surprising in the rest. This is a deliberate choice. Where needed, defaults can be disabled (`auto_resolve=False`).
- Performance: extra abstraction layer adds overhead. Path resolution, auto-serialization, placeholder conversion on every call. Negligible for APIs and tools. Not suited for tight loops processing millions of rows.

Type safety comes from Pydantic models and Python type hints on the application layer. Xaeian provides the plumbing underneath. Each layer does one thing and stays out of the way. It works best when you control the stack end-to-end and value compact code over maximum configurability.

## Install

```sh
pip install xaeian            # core
pip install xaeian[time]      # + pytz, tzlocal
pip install xaeian[serial]    # + pyserial
pip install xaeian[plot]      # + matplotlib
pip install xaeian[dsp]       # + scipy
pip install xaeian[db]        # + pymysql, psycopg2
pip install xaeian[db-async]  # + aiomysql, asyncpg, aiosqlite
pip install xaeian[media]     # + pypdf, PyMuPDF, Pillow
pip install xaeian[eda]       # + sexpdata, pypdf, PyMuPDF
pip install xaeian[sftp]      # + paramiko
pip install xaeian[all]       # everything
```

## Examples

```py
from xaeian import FILE, JSON, CSV, logger, split_str, generate_password
from xaeian.xtime import Time
from xaeian.crc import crc16_modbus
from xaeian.db import Database

# Files: auto extension, context-based paths
JSON.save("config", {"debug": True, "port": 8080})
CSV.save("users", [{"name": "Jan", "age": 30}, {"name": "Anna", "age": 25}])

# Time: parse anything, arithmetic with strings
t = Time("2025-03-01") + "2w 3d"
t.round("w") # Monday 00:00
t.to("iso") # "2025-03-17T00:00:00+01:00"

# CRC: encode/decode with Modbus, ISO, custom
frame = crc16_modbus.encode(b"\x01\x03\x00\x00\x00\x0A")
assert crc16_modbus.decode(frame) is not None

# String tools
split_str('a,"b,c",d', sep=",") # ['a', '"b,c"', 'd']
generate_password(16) # 'aB3$xY9!mN2@pQ7&'

# Database: sqlite/mysql/postgres, sync/async
db = Database("sqlite", "app.db")
db.insert("users", {"name": "Jan", "settings": {"theme": "dark"}})
db.find("users", order="name", limit=10)
async with db.transaction():
  db.update("users", {"verified": True}, "id = ?", 42)

# Plot: fluent, stacked panels, auto datetime
from xaeian.plot import Plot
(Plot(theme="dark")
  .line(t, temp, "Temperature [°C]")
  .panel()
  .line(t, hum, "Humidity [%]")
  .title("Sensors")
  .save("dashboard.png"))

# DSP: immutable signals, filters, FFT, vibration metrics
from xaeian.dsp import Signal
sig = Signal.from_accel(raw_x, fs=6666, bits=16, g_range=2)
clean = sig.highpass(10).lowpass(500)
print(f"RMS:{clean.rms:.4f}  peak_freq:{clean.fft().peak_freq:.0f}Hz")

# Binary structs: C-like encoding with CRC, bitfields, scale/offset
from xaeian.cstruct import Struct, Field, Bitfield, Type, Endian
from xaeian.crc import crc32_iso
pkt = Struct(endian=Endian.little, crc=crc32_iso)
pkt.add(
  Field(Type.uint32, "timestamp", "s"),
  Bitfield("flags", [("enabled", 1), ("error", 1), ("mode", 6)]),
  Field(Type.float, "temperature", "°C"),
)
flags = {"enabled": 1, "error": 0, "mode": 5}
raw = pkt.encode({"timestamp": 1234567890, "flags": flags, "temperature": 23.5})
pkt.decode(raw) # {"timestamp": 1234567890, "flags": {...}, "temperature": 23.5}

# Media: compress, strip metadata
from xaeian.media.min import compress
compress("report.pdf") # → report-min.pdf
compress("photos/", max_px=1280) # → photos-min/ (recursive)

# Logging: colored, rotating
log = logger("app", file="app.log")
log.info("started") # 2025-03-01 14:32:01 INF started
```

## CLI

```sh
xn tree .                     # directory tree
xn dupes photos/              # find duplicates
xn wifi                       # saved Wi-Fi passwords
xn min report.pdf             # compress PDF
xn min photo.jpg -f avif      # convert to AVIF
xn min photos/ --max-px 1280  # batch resize
xn meta photo.jpg -i          # strip EXIF in-place
xn ico logo.png -o favicon.ico
```

## Modules

| Module        | Description                                        | Docs                                                                                        |
| ------------- | -------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| `files`       | FILE, DIR, PATH, JSON, CSV, INI                    | [xaeian/readme.md](https://github.com/Xaeian/Python/blob/main/xaeian/readme.md#files)       |
| `files_async` | Async wrappers via `asyncio.to_thread()`           | [xaeian/readme.md](https://github.com/Xaeian/Python/blob/main/xaeian/readme.md#files_async) |
| `table`       | Lightweight tabular ops on `list[dict]`            | [xaeian/readme.md](https://github.com/Xaeian/Python/blob/main/xaeian/readme.md#table)       |
| `xstring`     | Split, replace, strip comments, passwords          | [xaeian/readme.md](https://github.com/Xaeian/Python/blob/main/xaeian/readme.md#xstring)     |
| `xtime`       | Datetime parsing, arithmetic, rounding             | [xaeian/readme.md](https://github.com/Xaeian/Python/blob/main/xaeian/readme.md#xtime)       |
| `colors`      | ANSI 256-color terminal codes                      | [xaeian/readme.md](https://github.com/Xaeian/Python/blob/main/xaeian/readme.md#colors)      |
| `log`         | Colored logging with file rotation                 | [xaeian/readme.md](https://github.com/Xaeian/Python/blob/main/xaeian/readme.md#log)         |
| `crc`         | CRC-8/16/32 with predefined variants               | [xaeian/readme.md](https://github.com/Xaeian/Python/blob/main/xaeian/readme.md#crc)         |
| `cstruct`     | Binary struct serialization _(C-like)_             | [xaeian/readme.md](https://github.com/Xaeian/Python/blob/main/xaeian/readme.md#cstruct)     |
| `cmd`         | Shell command helpers                              | [xaeian/readme.md](https://github.com/Xaeian/Python/blob/main/xaeian/readme.md#cmd)         |
| `serial_port` | Serial communication with colored output           | [xaeian/readme.md](https://github.com/Xaeian/Python/blob/main/xaeian/readme.md#serial_port) |
| `cbash`       | Embedded device console protocol                   | [xaeian/readme.md](https://github.com/Xaeian/Python/blob/main/xaeian/readme.md#cbash)       |
| `plot`        | Fluent matplotlib wrapper with stacked panels      | [xaeian/readme.md](https://github.com/Xaeian/Python/blob/main/xaeian/readme.md#plot)        |
| `dsp`         | Signal processing, SOS filters, FFT, vibration     | [xaeian/readme.md](https://github.com/Xaeian/Python/blob/main/xaeian/readme.md#dsp)         |
| `db`          | Database abstraction _(SQLite, MySQL, PostgreSQL)_ | [xaeian/db/readme.md](https://github.com/Xaeian/Python/blob/main/xaeian/db/readme.md)       |
| `media`       | Compress, convert, strip metadata _(PDF & images)_ | [xaeian/media/readme.md](https://github.com/Xaeian/Python/blob/main/xaeian/media/readme.md) |
| `eda`         | E-series, KiCad export, NgSpice runner             | [xaeian/eda/readme.md](https://github.com/Xaeian/Python/blob/main/xaeian/eda/readme.md)     |
| `net`         | Network clients _(SFTP, FTP)_                      | [xaeian/net/readme.md](https://github.com/Xaeian/Python/blob/main/xaeian/net/readme.md)     |
| `cli`         | tree, dupes, wifi scripts                          | [xaeian/cli/readme.md](https://github.com/Xaeian/Python/blob/main/xaeian/cli/readme.md)     |