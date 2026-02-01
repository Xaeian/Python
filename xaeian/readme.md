# `xaeian` modules

Detailed usage. For database see [db/readme.md](db/readme.md).

## `files`

File operations with context-based paths.

```python
from xaeian import FILE, DIR, JSON, CSV, INI, PATH
from xaeian import set_files_context, files_context

# Text files
FILE.save("data.txt", "Hello!")
content = FILE.load("data.txt")
FILE.append("data.txt", "\nWorld!")
lines = FILE.load_lines("data.txt")
# Binary
FILE.save("data.bin", b"\x00\x01\x02")
data = FILE.load("data.bin", binary=True)
# JSON (auto .json extension)
JSON.save("config", {"debug": True, "port": 8080})
cfg = JSON.load("config")
JSON.save_pretty("config", cfg, indent=2)
# CSV
CSV.save("users", [{"name": "Jan", "age": 30}, {"name": "Anna", "age": 25}])
rows = CSV.load("users", types={"age": int})
# INI
INI.save("settings", {"main": {"key": "value", "num": 42}})
settings = INI.load("settings")
# Directories
DIR.ensure("data/subdir/")
files = DIR.file_list("data", exts=[".txt", ".json"])
folders = DIR.folder_list("data")
DIR.copy("src", "dst")
DIR.zip("folder", "archive.zip")
# Path utilities
PATH.basename("a/b/file.txt")     # "file.txt"
PATH.dirname("a/b/file.txt")      # "a/b"
PATH.stem("a/b/file.txt")         # "file"
PATH.ext("a/b/file.txt")          # ".txt"
PATH.with_suffix("f.txt", ".md")  # "f.md"
# Context-based paths
set_files_context(root_path="/app/data")
JSON.load("config")  # reads /app/data/config.json
with files_context(root_path="/tmp"):
  FILE.save("temp.txt", "...")  # saves to /tmp/temp.txt
```

## `files_async`

Async wrappers via `asyncio.to_thread()`.

```python
from xaeian.files_async import FILE, JSON

content = await FILE.load("data.txt")
await JSON.save("config", {"key": "value"})
```

## `xstring`

String splitting, replacement, comment stripping, password generation.

```python
from xaeian import (
  split_str, split_sql,
  replace_map, replace_start, replace_end,
  ensure_prefix, ensure_suffix,
  strip_comments_c, strip_comments_sql, strip_comments_py,
  generate_password
)

split_str('a "b c" d') # ['a', '"b c"', 'd']
split_str("a,'b,c',d", sep=",") # ['a', "'b,c'", 'd']
split_sql("SELECT 1; SELECT 'a;b';") # ['SELECT 1;', "SELECT 'a;b';"]
replace_map("Hi {{NAME}}!", {"NAME": "World"}, "{{", "}}")  # "Hi World!"
ensure_prefix("path/file", "/") # "/path/file"
ensure_suffix("config", ".json") # "config.json"
strip_comments_c('int x; // comment\n/* block */') # 'int x; \n'
strip_comments_sql("SELECT * -- comment\nFROM t") # 'SELECT * \nFROM t'
strip_comments_py("x = 1  # comment") # 'x = 1  '
generate_password(16) # 'aB3$xY9!mN2@pQ7&'
generate_password(20, extend_spec=True) # 'kL5#mN8@pQ<xY9!zW2}'
```

## `xtime`

Datetime parsing, arithmetic, rounding. Requires `pip install xaeian[time]`.

```python
from xaeian.xtime import Time

t = Time()                            # now
t = Time("2025-03-01")                # parse date
t = Time("2025-03-01T12:00:00+02:00") # ISO with timezone
t = Time(1700000000)                  # unix timestamp
t = Time("2d")       # now + 2 days
t = Time("-6h")      # now - 6 hours
t = Time("1w 3d")    # now + 1 week 3 days
t2 = t + "1w"        # add 1 week
t2 = t - "3d"        # subtract 3 days
diff = t2 - t        # timedelta
t.round("h")         # round to hour
t.round("d")         # round to day
t.round("w")         # round to week (Monday)
t.to("ts")           # unix timestamp
t.to("iso")          # "2025-03-01T12:00:00"
t.to("date")         # "2025-03-01"
t.to("%d.%m.%Y")     # "01.03.2025"
```

## `log`

Colored logging with file rotation.

```python
from xaeian import logger
import logging

log = logger("app")
log.debug("debug")      # hidden at INFO level
log.info("info")        # 2025-01-15 14:32:01 INF info
log.warning("warning")  # 2025-01-15 14:32:01 WRN warning
log.error("error")      # 2025-01-15 14:32:01 ERR error
log.panic("panic")      # custom level above CRITICAL
log = logger(
  "app",
  file="app.log",
  stream=True,
  color=True,
  stream_lvl=logging.INFO,
  file_lvl=logging.DEBUG,
  max_bytes=5_000_000,
  backup_count=3
)
log.stream = False  # toggle console
log.file = False    # toggle file
```

## `colors`

ANSI 256-color terminal output.

```python
from xaeian.colors import Color

print(f"{Color.RED}Red text{Color.END}")
print(f"{Color.bg(21)}Blue background{Color.END}")
print(f"{Color.BOLD}Bold{Color.END}")
print(f"{Color.fg(208)}Orange 256{Color.END}")
```

## `crc`

CRC-8/16/32 with predefined variants.

```python
from xaeian import CRC
from xaeian.crc import crc32_iso, crc16_modbus, crc8_maxim

crc = crc16_modbus.checksum(b"123456789")       # 0x4B37
crc = crc32_iso.checksum(b"123456789")          # 0xCBF43926
encoded = crc16_modbus.encode(b"Hello!")        # b'Hello!\x73\x3e'
decoded = crc16_modbus.decode(encoded)          # b'Hello!'
corrupted = crc16_modbus.decode(b"bad\x00\x00") # None
my_crc = CRC(
  width=16,
  poly=0x8005,
  init=0xFFFF,
  ref_in=True,
  ref_out=True,
  xor_out=0x0000,
  swap=True
)
```

## `cstruct`

Binary struct serialization _(C-like)_.

```python
from xaeian.cstruct import Struct, Field, Bitfield, Padding, Variant, Type, Endian
from xaeian.crc import crc32_iso

sensor = Struct(name="sensor", endian=Endian.little, crc=crc32_iso)
sensor.add(
  Field(Type.uint32, "timestamp", "s"),
  Bitfield("flags", [("enabled", 1), ("error", 1), ("mode", 6)]),
  Padding(3),
  Field(Type.float, "temperature", "°C"),
)
data = {
  "timestamp": 1234567890,
  "flags": {"enabled": 1, "error": 0, "mode": 5},
  "temperature": 23.5
}
encoded = sensor.encode(data)
decoded = sensor.decode(encoded)
adc = Struct(name="adc")
adc.add(
  Field(Type.uint16, "raw"),
  Field(Type.int16, "temp", "°C", scale=0.01, offset=-40),
)
print(sensor.export_c_header())
print(sensor.export_doc())
```

## `serial_port`

Serial communication with colored output. Requires `pip install xaeian[serial]`.

```python
from xaeian.serial_port import SerialPort
from xaeian.crc import crc16_modbus

with SerialPort("COM3", 115200) as sp:
  sp.send(b"AT\r\n")
  response = sp.read()
with SerialPort(
  "/dev/ttyUSB0",
  baudrate=9600,
  timeout=1.0,
  print_console=True,
  crc=crc16_modbus,
) as sp:
  sp.send(b"HELLO\r\n")
  line = sp.read_line()
```

## `cbash`

Embedded device console protocol. Requires `pip install xaeian[serial]`.

```python
from xaeian.cbash import CBash

with CBash("COM3", 115200) as cb:
  if not cb.ping():
    exit(1)
  cb.set_time()
  files = cb.file_list()
  if cb.file_select("config"):
    content = cb.file_load_str()
  response = cb.exec("STATUS")
  cb.reboot()
```