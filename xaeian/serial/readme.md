# `xaeian.serial`

Serial communication: low-level port, continuous numeric recorders with CSV logging, embedded shell client. Requires `pip install xaeian[serial]`.

## `SerialPort`

Base class with colored console output, file logging, address filtering, optional CRC. Context manager support.

```py
from xaeian.serial import SerialPort, serial_scan
from xaeian.crc import crc16_modbus

serial_scan() # ["COM3", "COM4", "/dev/ttyUSB0"]

with SerialPort("COM3", 115200) as sp:
  sp.send(b"AT\r\n")
  raw = sp.read()                  # bytes
  lines = sp.read_lines()          # list[str]
  line = sp.read_line()            # one line, str

# Multi-device bus with address filter + CRC
with SerialPort("COM3", 9600, address=0x42, crc=crc16_modbus) as sp:
  sp.send(b"\x01\x03\x00\x00")     # auto-prepend address, append CRC
  resp = sp.read()                 # auto-verify CRC, strip address
```

Color attrs are class-level - override in subclass or per instance:

```py
class QuietPort(SerialPort):
  COLOR_TIME = Color.CREMA
  COLOR_INFO = Color.SKY

# or runtime
sp = SerialPort("COM3")
sp.COLOR_TIME = Color.SILVER
```

## `Recorder`

Stream-based single numeric value reader. Robust to mid-value `\r\n` splits (Brymen, Rigol). Built-in regex patterns for common multimeter formats.

```py
from xaeian.serial import Recorder

# Class-level regex constants
Recorder.SCI_NORM  # 1.23456e+02 (SCPI, Brymen, Rigol)
Recorder.SCI       # general scientific notation
Recorder.FLOAT     # 123.456
Recorder.NUM       # int or float (default)

rec = Recorder("COM7", baudrate=9600, name="U1",
  regex=Recorder.SCI_NORM, err_delay_ms=5000)

rec.connect()
while True:
  v = rec.read_value() # latest float, or None on timeout/no match
```

## `MultiRecorder`

For instruments emitting N values per line (separator-delimited), like STM32/Arduino. Wrong-shape line returns `None` (error signal).

```py
from xaeian.serial import MultiRecorder

mr = MultiRecorder("COM9", count=4, separator=",",
  columns=["U", "I", "T", "RPM"], name="STM",
  regex=Recorder.FLOAT)

mr.connect()
vals = mr.read_values() # [12.5, 0.34, 25.0, 1500] or None
```

## `RecorderPool`

Orchestrates N recorders with threading and CSV logging. One reader thread per recorder, one reap thread that snapshots to CSV at `period_ms`. Override `make_row()` for custom columns.

```py
from xaeian.serial import Recorder, MultiRecorder, RecorderPool

recs = [
  Recorder("COM7", name="U1", regex=Recorder.SCI_NORM),
  Recorder("COM8", name="I1", regex=Recorder.SCI_NORM),
  MultiRecorder("COM9", count=4, name="STM",
    columns=["U", "I", "T", "RPM"], regex=Recorder.FLOAT),
]

pool = RecorderPool(recs, period_ms=1000,
  csv_path="series.csv", capture_path="capture.csv",
  skip_empty=True) # skip rows where all recorders are None

pool.start()       # spawns daemon read + reap threads
pool.capture()     # one-shot snapshot to capture_path
pool.stop()        # signal + join (timeout_ms=2000 per thread)

# Custom row with extra column
class MyPool(RecorderPool):
  def make_row(self):
    row = super().make_row()
    row["step"] = ctrl.step
    return row
```

## `Shell`

Python client for embedded SH shell (`lib/sh` C firmware). Wraps standard built-ins; use `exec()` for everything else.

```py
from xaeian.serial import Shell

with Shell("/dev/ttyUSB0") as sh:
  # basic
  sh.ping()         # True/False (retries 3x)
  sh.uid()          # bytes (12-byte device UID)

  # RTC
  sh.set_time()     # sync to host time
  sh.get_time()     # datetime|None

  # MBB file operations
  sh.mbb_list()                # ["config", "data", "log"]
  sh.mbb_select("config")
  used, total = sh.mbb_info()  # (123, 2048)
  cfg = sh.mbb_load_str()
  sh.mbb_save(cfg + "\nextra", append=False)
  sh.mbb_copy("config", "config_bak")
  sh.mbb_clear()

  # Cooperative wakeup
  sh.trig(42)       # wakes TRIG_Wait / TRIG_WaitFor on device

  # Power
  sh.reboot()
  sh.reset()
  sh.sleep("standby") # stop|stop0|stop1|standby|shutdown

  # Non-standard via exec
  sh.exec("alarm 1 set everyday 06:00:00")
  sh.exec("flash erase 5", timeout_ms=2000)
  sh.exec("ping", retries=3,
    validator=lambda r: "pong" in r.lower())
```

Helper for parsing response tokens:

```py
from xaeian.serial import convert_value

convert_value("true")  # True
convert_value("123")   # 123
convert_value("3.14")  # 3.14
convert_value("hello") # "hello"
convert_value("null")  # None
convert_value(None)    # None
```