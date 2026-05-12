# xaeian/serial/rec.py

__extras__ = ("serial", ["pyserial"])

"""
Continuous numeric reader and recorder pool.

`Recorder` extends `SerialPort` with stream-based value parsing. Each instance
owns its parsing contract (regex, single vs multi-value). The pool calls a
uniform `update()` method per recorder - polymorphism handles the variation.

`MultiRecorder` handles instruments emitting N values per line separated by
e.g. `,`. Subclass `Recorder` for any other shape (header filtering, etc.).

`RecorderPool` accepts pre-configured recorders, runs a read thread per
recorder, plus a reap thread that snapshots and writes CSV at `period_ms`.

Example:
  >>> from xaeian.serial import Recorder, MultiRecorder, RecorderPool
  >>> recs = [
  ...   Recorder("COM7", name="U1", regex=Recorder.SCI_NORM),
  ...   MultiRecorder("COM8", name="STM", count=4,
  ...     columns=["U", "I", "T", "RPM"], regex=Recorder.FLOAT),
  ... ]
  >>> pool = RecorderPool(recs, csv_path="series.csv")
  >>> pool.start()
  >>> # ... do work ...
  >>> pool.stop()
"""

import re, time, threading
from .port import SerialPort
from ..colors import Color as c
from ..xtime import Time
from ..files import CSV

#------------------------------------------------------------------------------------- Recorder

class Recorder(SerialPort):
  """
  Stream-based single numeric value reader.

  Accumulates raw bytes into a rolling buffer and extracts the latest match
  via unanchored regex. Robust to mid-value `\\r\\n` splits (Brymen, Rigol).

  Numeric regex patterns (use as `regex=` arg):
    `SCI_NORM` - 1.23456e+02 (SCPI, Brymen, Rigol)
    `SCI`      - general scientific notation
    `FLOAT`    - 123.456
    `NUM`      - int or float

  Override class attributes to customize colors:
    `COLOR_NAME` - device name prefix (default `TURQUS`)
    plus inherited `COLOR_TIME`, `COLOR_ADDR`, `COLOR_INFO`, etc.

  Args:
    name: Device identifier shown in console prefix.
    regex: Pattern for value extraction (defaults to `NUM`).
    color: ANSI color for raw data lines.
    err_delay_ms: Milliseconds without fresh data before forced disconnect.
  """
  SCI_NORM = r"-?[1-9]\.\d+[eE][+-]?\d{2}"
  SCI = r"-?\d+\.?\d*[eE][+-]?\d+"
  FLOAT = r"-?\d+\.\d+"
  NUM = r"-?\d+(?:\.\d+)?"

  _BUF_MAX = 4096
  _LINES_MAX = 32

  COLOR_NAME = c.TURQUS

  def __init__(
    self,
    port:str,
    baudrate:int = 9600,
    timeout:float = 0.1,
    buffer_size:int = 8192,
    print_console:bool = True,
    print_file:str = "",
    time_disp:bool = True,
    time_utc:bool = False,
    time_format:str = "%Y-%m-%d %H:%M:%S.%f",
    name:str = "",
    regex:str|None = None,
    color:str = c.WHITE,
    err_delay_ms:int = 5000,
  ):
    self.name = name
    self.regex = regex
    self.color = color
    self.err_delay_ms = err_delay_ms
    self.err_time:float = 0
    self.value:float|None = None
    self._buffer = ""             # char-stream (no \r\n) for read_value
    self._print_buf = ""          # incomplete display line awaiting \r\n
    self._lines_seen:list[str] = []  # complete lines (used by MultiRecorder)
    self._snapshot:dict = {name: None}  # last-known row contribution
    super().__init__(port, baudrate, timeout, buffer_size,
      print_console, print_file, time_disp, time_utc, time_format)

  #-------------------------------------------------------------------------------------- Print

  def print(self, text:str, prefix:str=""):
    """Add device name to prefix, preserving any caller-supplied prefix."""
    name_prefix = f"{self.COLOR_NAME}{self.name}{c.END}"
    combined = f"{name_prefix} {prefix}".strip()
    super().print(text, combined)

  #------------------------------------------------------------------------------------ Timeout

  def _check_timeout(self) -> bool:
    """Returns `True` if `err_delay_ms` elapsed since last successful read."""
    # err_time is the future deadline (epoch seconds) by which we expect a fresh read
    if self.err_time and time.time() > self.err_time:
      self.disconnect()
      self.print_error(f"Serial port {self.port} not responding")
      return True
    return False

  def _reset_timeout(self):
    """Reset deadline `err_delay_ms` into the future after successful read."""
    self.err_time = time.time() + self.err_delay_ms / 1000  # ms → s for time.time

  def _reset_state(self):
    """Clear rolling buffers. Call on timeout/error/disconnect."""
    self._buffer = ""
    self._print_buf = ""
    self._lines_seen.clear()

  #------------------------------------------------------------------------------------ Control

  def scan(self):
    """Check connection liveness and drain RX buffer. Call when idle."""
    if self._check_timeout(): return
    if not self.connect(): return
    try:
      self.clear(self.color)
      self._reset_timeout()
    except Exception:
      if self.debug: raise

  #-------------------------------------------------------------------------------- Read engine

  def _read_and_print(self) -> list[str]:
    """
    Read fresh bytes, accumulate buffers, print complete lines.

    Maintains three buffers:
      - `_print_buf`: partial line awaiting `\\r\\n` (display only)
      - `_buffer`: char-stream without `\\r\\n` (for `read_value` finditer)
      - `_lines_seen`: complete lines (for line-based parsing in subclasses)

    Returns newly-arrived complete lines (may be empty).
    """
    try:
      resp = self.serial.read(self.buffer_size)
      if not resp: return []
      text = resp.decode("utf-8", errors="ignore")
      # display: hold partial trailing line, emit completed ones
      self._print_buf += text
      parts = re.split(r"[\r\n]+", self._print_buf)
      self._print_buf = parts[-1]  # last part is incomplete (or "" if ended w/ \r\n)
      new_lines = []
      for line in parts[:-1]:
        if line.strip():
          self.print(f"{self.color}{line.strip()}{c.END}")
          new_lines.append(line.strip())
      # cap print buf in case instrument streams without newlines
      if len(self._print_buf) > self._BUF_MAX:
        self._print_buf = self._print_buf[-self._BUF_MAX:]
      # line history for subclasses doing line-based parsing
      self._lines_seen += new_lines
      if len(self._lines_seen) > self._LINES_MAX:
        self._lines_seen = self._lines_seen[-self._LINES_MAX:]
      # char-stream for read_value: strip \r\n to glue mid-value splits
      self._buffer += re.sub(r"[\r\n]+", "", text)
      if len(self._buffer) > self._BUF_MAX:
        self._buffer = self._buffer[-self._BUF_MAX:]
      return new_lines
    except Exception:
      self._reset_state()
      if self.debug: raise
      return []

  @staticmethod
  def _strip_anchors(pattern:str) -> str:
    """Strip `^`/`$` so pattern works as substring match (finditer/search)."""
    if pattern.startswith("^"): pattern = pattern[1:]
    if pattern.endswith("$"): pattern = pattern[:-1]
    return pattern

  #--------------------------------------------------------------------------------- Read value

  def read_value(self) -> float|None:
    """
    Read latest numeric value from stream. Uses `self.regex` (defaults to `NUM`).

    Returns:
      Latest parsed float, or `None` on timeout / no data / no match yet.
      Cached value if no fresh match this call.
    """
    if self._check_timeout():
      self._reset_state()
      self.value = None
      return None
    if not self.connect():
      self._reset_state()
      self.value = None
      return None
    self._read_and_print()
    pattern = self._strip_anchors(self.regex or self.NUM)
    matches = list(re.finditer(pattern, self._buffer))
    if matches:
      last = matches[-1]
      try:
        self.value = float(last.group())
        self._reset_timeout()
        self._buffer = self._buffer[last.end():]  # consume past match, keep tail
      except ValueError:
        pass
    return self.value

  #------------------------------------------------------------------------------ Pool contract

  def update(self) -> dict:
    """
    Pool entry point. Reads fresh data and returns row contribution as dict.
    Override in subclasses for custom shapes. Base: single value at `self.name`.
    """
    self.read_value()
    self._snapshot = {self.name: self.value}
    return self._snapshot

  @property
  def snapshot(self) -> dict:
    """Last `update()` result. Read by reap thread without triggering IO."""
    return self._snapshot

  def has_value(self) -> bool:
    """True if at least one value in snapshot is non-`None`."""
    return any(v is not None for v in self._snapshot.values())


#-------------------------------------------------------------------------------- MultiRecorder

class MultiRecorder(Recorder):
  """
  Reader for instruments emitting N values per line, separator-delimited.

  Suits STM32 / Arduino style emitters like `1.234,5.678,9.012,4.567\\r\\n`.
  Latest complete line is authoritative - if its split count differs from
  `count`, all columns nullify for that tick (error signal in CSV).

  Args:
    count: Exact number of values expected per line.
    separator: Char/string between values (regex-escaped internally).
    columns: Column names for each value. Defaults to `{name}_0`, `{name}_1`,...
    regex: Pattern for each value (defaults to `NUM`).
  """
  def __init__(
    self,
    port:str,
    count:int,
    separator:str = ",",
    columns:list[str]|None = None,
    baudrate:int = 9600,
    timeout:float = 0.1,
    buffer_size:int = 8192,
    print_console:bool = True,
    print_file:str = "",
    time_disp:bool = True,
    time_utc:bool = False,
    time_format:str = "%Y-%m-%d %H:%M:%S.%f",
    name:str = "",
    regex:str|None = None,
    color:str = c.WHITE,
    err_delay_ms:int = 5000,
  ):
    self.count = count
    self.separator = separator
    self.columns = columns or [f"{name}_{i}" for i in range(count)]
    self.values:list[float]|None = None
    super().__init__(port, baudrate, timeout, buffer_size,
      print_console, print_file, time_disp, time_utc, time_format,
      name, regex, color, err_delay_ms)
    self._snapshot = {col: None for col in self.columns}

  def read_values(self) -> list[float]|None:
    """
    Read fixed-count tuple of values from the latest complete line.

    Returns:
      `list[float]` of length `count` from latest line, or `None` on wrong
      shape / parse error. Cached values if no new line arrived.
    """
    if self._check_timeout():
      self._reset_state()
      self.values = None
      return None
    if not self.connect():
      self._reset_state()
      self.values = None
      return None
    new_lines = self._read_and_print()
    if not new_lines: return self.values  # no fresh line, cached OK
    pattern = self._strip_anchors(self.regex or self.NUM)
    sep = re.escape(self.separator)
    # newest line is authoritative; older lines in same batch ignored
    line = new_lines[-1]
    parts = re.split(sep, line)
    if len(parts) != self.count:
      self.values = None
      return None  # wrong shape on latest line = error signal
    try:
      self.values = [float(re.search(pattern, p.strip()).group()) for p in parts]
      self._reset_timeout()
      return self.values
    except (AttributeError, ValueError):
      # AttributeError if re.search returned None for some part
      self.values = None
      return None

  def update(self) -> dict:
    """Read and return all columns. Nulls all on wrong-shape line."""
    self.read_values()
    if self.values is None:
      self._snapshot = {col: None for col in self.columns}
    else:
      self._snapshot = dict(zip(self.columns, self.values))
    return self._snapshot


#--------------------------------------------------------------------------------- RecorderPool

class RecorderPool:
  """
  Multi-recorder orchestration with threading and CSV logging.

  Spawns one read thread per recorder (each calls `rec.update()` in a tight
  loop) plus a reap thread that reads `rec.snapshot` at `period_ms` and
  appends a CSV row. The pool is dumb - all parsing logic lives in the
  recorders themselves (polymorphism via `update()`).

  Args:
    recs: Pre-configured `Recorder` / `MultiRecorder` instances.
    period_ms: CSV append period for reap loop, in milliseconds.
    csv_path: CSV file for continuous reap loop.
    capture_path: CSV file for `capture()` one-shot rows.
    skip_empty: Skip CSV row when no recorder has any non-`None` value.
    time_format: Format for the `time` column in CSV rows.

  Example:
    >>> recs = [
    ...   Recorder("COM7", name="U1", regex=Recorder.SCI_NORM),
    ...   Recorder("COM8", name="U2", regex=Recorder.SCI_NORM),
    ...   MultiRecorder("COM9", name="STM", count=4,
    ...     columns=["U","I","T","RPM"], regex=Recorder.FLOAT),
    ... ]
    >>> pool = RecorderPool(recs, csv_path="series.csv")
    >>> pool.start()
    >>> try:
    ...   while True: time.sleep(0.1)
    ... except KeyboardInterrupt: pass
    >>> pool.stop()
  """
  def __init__(
    self,
    recs:list[Recorder],
    period_ms:int = 1000,
    csv_path:str = "series.csv",
    capture_path:str = "capture.csv",
    skip_empty:bool = True,
    time_format:str = "%Y-%m-%d %H:%M:%S.%f",
  ):
    self.recs = recs
    self.period_ms = period_ms
    self.csv_path = csv_path
    self.capture_path = capture_path
    self.skip_empty = skip_empty
    self.time_format = time_format
    self._stop = False
    self._threads:list[threading.Thread] = []

  def make_row(self) -> dict:
    """
    Build one CSV row from current snapshots. Override to add custom columns
    (e.g. `step` counter from external controller).
    """
    row = {"time": Time().to(self.time_format)}
    for rec in self.recs: row.update(rec.snapshot)
    return row

  def _has_value(self) -> bool:
    """True if at least one recorder has any non-`None` snapshot value."""
    return any(rec.has_value() for rec in self.recs)

  def _read_loop(self, rec:Recorder):
    rec.connect()
    while not self._stop: rec.update()
    rec.disconnect()

  def _reap_loop(self):
    period_s = self.period_ms / 1000  # time.sleep takes seconds
    while not self._stop:
      watch = Time().to("ts")
      if not self.skip_empty or self._has_value():
        CSV.add_row(self.csv_path, self.make_row())
      # compensate for write latency to keep period_ms rhythm
      drift = Time().to("ts") - watch
      time.sleep(max(0, period_s - drift))

  def start(self):
    """Spawn reader + reap daemon threads. Non-blocking."""
    self._stop = False
    for rec in self.recs:
      t = threading.Thread(target=self._read_loop, args=(rec,))
      t.daemon = True
      t.start()
      self._threads.append(t)
    t = threading.Thread(target=self._reap_loop)
    t.daemon = True
    t.start()
    self._threads.append(t)

  def stop(self, timeout_ms:int = 2000):
    """Signal stop and join all threads. `timeout_ms` is per-thread cap."""
    self._stop = True
    for t in self._threads: t.join(timeout=timeout_ms / 1000)
    self._threads.clear()

  def capture(self):
    """One-shot capture of current snapshots to `capture_path`. Skips if empty."""
    if self.skip_empty and not self._has_value():
      print(f"{c.YELLOW}No measurement, capture skipped{c.END}")
      return
    row = self.make_row()
    for rec in self.recs:
      vals = ", ".join(f"{k}={v}" for k, v in rec.snapshot.items())
      rec.print(f"{c.LIME}Captured: {vals}")
    CSV.add_row(self.capture_path, row)