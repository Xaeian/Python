# Xaeian

Python utilities. Zero dependencies for core. Optional extras for time, serial, media, database and more...

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
pip install xaeian[pdf]       # + reportlab, Pillow
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
| `pdf`         | PDF document generation _(reportlab)_              | [xaeian/pdf/readme.md](https://github.com/Xaeian/Python/blob/main/xaeian/pdf/readme.md)     |
| `eda`         | E-series, KiCad export, NgSpice runner             | [xaeian/eda/readme.md](https://github.com/Xaeian/Python/blob/main/xaeian/eda/readme.md)     |
| `net`         | Network clients _(SFTP, FTP)_                      | [xaeian/net/readme.md](https://github.com/Xaeian/Python/blob/main/xaeian/net/readme.md)     |
| `cli`         | tree, dupes, wifi scripts                          | [xaeian/cli/readme.md](https://github.com/Xaeian/Python/blob/main/xaeian/cli/readme.md)     |