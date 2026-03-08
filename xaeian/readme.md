# `xaeian`

Python utilities. Zero dependencies for core. Optional extras for time, serial, media, database and more...

## `files`

```py
from xaeian import FILE, DIR, JSON, CSV, INI, PATH

FILE.save("data.txt", "Hello!")
FILE.load("data.txt")
FILE.append("data.txt", "\nMore")
FILE.load("data.bin", binary=True)

JSON.save("config", {"debug": True, "port": 8080})
JSON.load("config")
JSON.save_pretty("config", cfg)

CSV.save("users", [{"name": "Jan", "age": 30}])
CSV.load("users", types={"age": int})

INI.save("settings", {"main": {"key": "value", "num": 42}})
INI.load("settings")

DIR.ensure("data/subdir/")
DIR.file_list("data", exts=[".txt", ".json"])
DIR.zip("folder", "archive.zip")

PATH.stem("a/b/file.txt")          # "file"
PATH.ext("a/b/file.txt")           # ".txt"
PATH.with_suffix("f.txt", ".md")   # "f.md"
```

### Context-based paths

```py
from xaeian import Files, file_context

fs = Files(root_path="/app/data")
fs.JSON.load("config")             # /app/data/config.json
fs.FILE.save("log.txt", "ok")      # /app/data/log.txt

with file_context(root_path="/tmp"):
  FILE.save("temp.txt", "...")     # /tmp/temp.txt
```

### Async

```py
from xaeian.files_async import FILE, JSON, AsyncFiles

await FILE.load("data.txt")
await JSON.save("config", {"key": "value"})

fs = AsyncFiles(root_path="/app/data")
await fs.FILE.load("test.txt")
```

## `table`

Lightweight tabular operations on `list[dict]` — pandas-free.

```py
from xaeian.table import where, select, rename, sort_by, aggregate, join, pluck

rows = CSV.load("data")

where(rows, lambda r: r["status"] == "active")
select(rows, "name", "age", "email")
rename(rows, {"Ref": "Designator", "Pacage": "Footprint"})
sort_by(rows, "age", reverse=True)
pluck(rows, "email") # ["a@b.com", "c@d.com"]

aggregate(rows, "dept", {
  "salary": "sum",
  "name": "first",
  "id": "join:,",
})

join(orders, products, on="product_id", how="left")
```

## `xstring`

```py
from xaeian import (
  split_str, split_sql, replace_map,
  ensure_prefix, ensure_suffix,
  strip_comments_c, generate_password
)

split_str('a "b c" d')                                # ['a', '"b c"', 'd']
split_str("a,'b,c',d", sep=",")                       # ['a', "'b,c'", 'd']
split_sql("SELECT 1; SELECT 'a;b';")                  # ['SELECT 1;', "SELECT 'a;b';"]
replace_map("Hi {{N}}!", {"N": "World"}, "{{", "}}")  # "Hi World!"
strip_comments_c('int x; // comment\n/* block */')    # 'int x; \n'
generate_password(16)                                 # 'aB3$xY9!mN2@pQ7&'
```

## `xtime`

Requires `pip install xaeian[time]`.

```py
from xaeian.xtime import Time

t = Time()                             # now
t = Time("2025-03-01")                 # parse date
t = Time("2025-03-01T12:00:00+02:00")  # ISO with timezone
t = Time(1700000000)                   # unix timestamp
t = Time("2d")                         # now + 2 days
t = Time("-6h 30m")                    # now - 6.5 hours

t + "1w"              # add 1 week
t - "3d"              # subtract 3 days
t2 - t                # timedelta

t.round("h")          # round to hour
t.round("w")          # round to week (Monday)

t.to("ts")            # unix timestamp (float)
t.to("iso")           # "2025-03-01T12:00:00+01:00"
t.to("utc")           # Time in UTC
t.to("%Y-%m-%d")      # "2025-03-01"
```

## `log`

```py
from xaeian import logger

log = logger("app", file="app.log")
log.info("started")       # 2025-03-01 14:32:01 INF started
log.warning("low disk")   # 2025-03-01 14:32:01 WRN low disk
log.error("failed")       # 2025-03-01 14:32:01 ERR failed
log.panic("fatal")        # custom level above CRITICAL

log.stream = False        # toggle console
log.file = False          # toggle file
```

## `colors`

```py
from xaeian.colors import Color, Print

print(f"{Color.RED}Error!{Color.END}")
print(f"{Color.GREEN}OK{Color.END}")

p = Print()
p.inf("info message")    # INF info message
p.err("something broke") # ERR something broke
p.ok("done")             # INF done OK
p.wrn("careful")         # WRN careful
p.run("starting...")     # RUN starting...
```

## `crc`

```py
from xaeian.crc import crc32_iso, crc16_modbus, crc8_maxim, CRC

crc16_modbus.checksum(b"123456789")     # 0x4B37
crc32_iso.checksum(b"123456789")        # 0xCBF43926

encoded = crc16_modbus.encode(b"Hello!")
crc16_modbus.decode(encoded)            # b'Hello!'
crc16_modbus.decode(b"bad\x00\x00")     # None (CRC mismatch)

my_crc = CRC(16, 0x8005, 0xFFFF, True, True, 0x0000, False)
```

## `cstruct`

Binary struct serialization _(C-like)_.

```py
from xaeian.cstruct import Struct, Field, Bitfield, Padding, Type, Endian
from xaeian.crc import crc32_iso

sensor = Struct(name="sensor", endian=Endian.little, crc=crc32_iso)
sensor.add(
  Field(Type.uint32, "timestamp", "s"),
  Bitfield("flags", [("enabled", 1), ("error", 1), ("mode", 6)]),
  Padding(3),
  Field(Type.float, "temperature", "°C"),
)

encoded = sensor.encode({"timestamp": 1234567890, "temperature": 23.5, ...})
decoded = sensor.decode(encoded)
sensor.export_c_header()
sensor.export_doc()
```

## `cmd`

```py
from xaeian.cmd import version, exists, which, run, output

version("python3")            # "3.12.3"
exists("gcc")                 # True/False
which("python3", "python")    # "/usr/bin/python3"
output("git rev-parse HEAD")  # "a1b2c3d..."
run("make -j4", cwd="build")  # CompletedProcess
```

## `serial_port`

Requires `pip install xaeian[serial]`.

```py
from xaeian.serial_port import SerialPort, serial_scan
from xaeian.crc import crc16_modbus

serial_scan() # ["COM3", "COM4"]

with SerialPort("COM3", 115200, crc=crc16_modbus) as sp:
  sp.send(b"AT\r\n")
  response = sp.read()
```

## `cbash`

Embedded device console. Requires `pip install xaeian[serial]`.

```py
from xaeian.cbash import CBash

with CBash("COM3") as cb:
  cb.ping()
  cb.set_time()
  files = cb.file_list()
  cb.file_select("config")
  content = cb.file_load_str()
  cb.reboot()
```

## `plot`

Fluent matplotlib wrapper. Requires `pip install xaeian[plot]`.

```py
from xaeian.plot import Plot, quick

# Simple
Plot().line(x, y, "Temperature [°C]").show()
quick(x, y, "Voltage [V]").save("plot.png")
# Stacked panels with shared x-axis
(Plot(theme="dark", size=(14, 9))
  .line(t, temp, "Temperature [°C]")
  .fill(t, temp + 1, temp - 1, alpha=0.12)
  .hline(25, label="Alarm", color="#EE6677", ls="--")
  .panel()
  .line(t, hum, "Humidity [%]")
  .twinx()
  .line(t, sig, "Signal [dBm]")
  .panel(height=0.7)
  .line(t, v33, "3.3V [V]")
  .line(t, v50, "5.0V [V]")
  .line(t, v12, "12V [V]")
  .ylabel("Voltage [V]")
  .title("Sensor Dashboard — 24h")
  .save("dashboard.png", dpi=200))
# Family of curves (parametric sweep)
(Plot()
  .family(results, "TIME", "V(OUT)", "R={key}")
  .ylabel("Output [V]")
  .show())
# Scatter + log scale
Plot().scatter(freq, z, "Z [Ω]").logx().logy().show()
# Step (digital signals)
Plot().step(t, state, "FSM State").vline(10, label="Event").show()
# Escape hatch to raw matplotlib
p = Plot().line(x, y, "Data")
p.fig   # matplotlib Figure
p.axes  # list[Axes]
```

Themes: `"clean"` _(default, light)_, `"dark"`. Auto datetime formatting, auto ylabel coloring for single series. Labels accept `"Name [unit]"` or `("Name", "unit")` tuples.

```bash
py -m xaeian.plot         # sensor dashboard demo
py -m xaeian.plot family  # parametric sweep demo
```

## `dsp`

Signal processing for embedded sensors. Requires `pip install xaeian[dsp]`.

```py
from xaeian.dsp import Signal

# From raw ADC / accelerometer data
sig = Signal.from_accel(raw_x, fs=6666, bits=16, g_range=2, label="X")
sig = Signal.from_adc(raw, fs=1000, bits=12, vref=3.3, units="V")
sig = Signal([1.0, 2.0, 3.0], fs=1000)  # from array
# Operators — immutable, returns new Signal
sig * 2      # scale
sig1 + sig2  # add (same fs required)
-sig         # invert
abs(sig)     # rectify
# Filter chain — SOS Butterworth, zero-phase
clean = sig.highpass(10).lowpass(500).detrend()
bp = sig.bandpass(100, 1000)
notch = sig.bandstop(49, 51) # mains rejection
# Vibration metrics
sig.rms           # root mean square
sig.peak          # max absolute value
sig.peak_to_peak  # max - min
sig.crest_factor  # peak / rms (>3 = bearing fault)
# Integration (accel → velocity → displacement)
vel = sig.integrate(highpass_Hz=5, units="m/s")
disp = vel.integrate(highpass_Hz=1, units="m")
# FFT → Spectrum object
sp = sig.fft("hann")
sp.peak_freq    # dominant frequency
sp.centroid     # spectral centroid
sp.median_freq  # median frequency
sp.magnitudes   # amplitude array
sp.power        # power array
# PSD (Welch)
f, pxx = sig.psd(nperseg=1024)
# Other transforms
sig.normalize()     # scale to [-1, 1]
sig.envelope()      # Hilbert amplitude envelope
sig.derivative()    # numerical derivative
sig.window("hann")  # apply window function
sig.trim(0.1, 0.5)  # trim by time in seconds
# Multi-axis magnitude
mag = Signal.magnitude(sig_x, sig_y, sig_z)
# Test signals
Signal.sine(100, duration=1.0, fs=10000)
Signal.noise(duration=1.0, fs=10000)
```

```bash
py -m xaeian.dsp   # demo: filter, FFT, metrics, operators
```