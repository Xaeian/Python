# xaeian/serial/rec.py

__extras__ = ("serial", ["pyserial"])

"""
Threaded numeric value recorder.

`Recorder` extends `SerialPort` with stream-based value parsing - reads bytes
in a background thread, extracts numeric values via regex, exposes the latest
via `.value`. Robust to mid-value `\\r\\n` splits (Brymen, Rigol).

`MultiRecorder` handles N values per line, separator-delimited, exposes them
via `.values`.

Both classes are pure data sources. Lifecycle: `start()` spawns reader thread,
`stop()` signals and joins it. Application code decides what to do with the
values (CSV, DB, MQTT, plot - not the library's concern).

Example:
  >>> from xaeian.serial import Recorder
  >>> rec = Recorder("COM7", name="U1", regex=Recorder.SCI_NORM)
  >>> rec.start()
  >>> # ... rec.value updates in background ...
  >>> rec.stop()
"""

import re, time, threading
from .port import SerialPort
from ..colors import Color as c

#------------------------------------------------------------------------------------- Recorder

class Recorder(SerialPort):
  """
  Stream-based single numeric value reader with background thread.

  Accumulates raw bytes into a rolling buffer and extracts the latest match
  via unanchored regex. The reader thread updates `self.value` continuously
  while running.

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
    self._buffer = ""                # char-stream (no \r\n) for read_value
    self._print_buf = ""             # incomplete display line awaiting \r\n
    self._lines_seen:list[str] = []  # complete lines (used by MultiRecorder)
    self._stop_event = threading.Event()
    self._thread:threading.Thread|None = None
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
    # err_time is the future deadline by which we expect a fresh read
    if self.err_time and time.time() > self.err_time:
      self.disconnect()
      self.print_error(f"Serial port {self.port} not responding")
      return True
    return False

  def _reset_timeout(self):
    """Reset deadline `err_delay_ms` into the future after successful read."""
    self.err_time = time.time() + self.err_delay_ms / 1000

  def _reset_state(self):
    """Clear rolling buffers. Call on timeout/error/disconnect."""
    self._buffer = ""
    self._print_buf = ""
    self._lines_seen.clear()

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

    Updates `self.value` in place. Returns it for convenience.
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

  #---------------------------------------------------------------------------------- Lifecycle

  def _update_cycle(self):
    """One iteration of the reader loop. Subclasses override for different shapes."""
    self.read_value()

  def _run(self):
    """Background thread body. Read continuously until stop signal."""
    self.connect()
    while not self._stop_event.is_set():
      self._update_cycle()
    self.disconnect()

  def start(self):
    """Spawn reader thread. Non-blocking. Idempotent."""
    if self._thread and self._thread.is_alive(): return
    self._stop_event.clear()
    self._thread = threading.Thread(target=self._run, daemon=True)
    self._thread.start()

  def stop(self, timeout_ms:int = 2000):
    """Signal stop and join the reader thread."""
    self._stop_event.set()
    if self._thread: self._thread.join(timeout=timeout_ms / 1000)
    self._thread = None


#-------------------------------------------------------------------------------- MultiRecorder

class MultiRecorder(Recorder):
  """
  Reader for instruments emitting N values per line, separator-delimited.

  Suits STM32 / Arduino style emitters like `1.234,5.678,9.012,4.567\\r\\n`.
  Latest complete line is authoritative - if its split count differs from
  `count`, `self.values` is set to `None` (error signal).

  Args:
    count: Exact number of values expected per line.
    separator: Char/string between values (regex-escaped internally).
    regex: Pattern for each value (defaults to `NUM`).
  """
  def __init__(
    self,
    port:str,
    count:int,
    separator:str = ",",
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
    self.values:list[float]|None = None
    super().__init__(port, baudrate, timeout, buffer_size,
      print_console, print_file, time_disp, time_utc, time_format,
      name, regex, color, err_delay_ms)

  def read_values(self) -> list[float]|None:
    """
    Read fixed-count tuple of values from the latest complete line.

    Updates `self.values` in place. Returns `None` on wrong shape /
    parse error. Cached values if no new line arrived.
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

  def _update_cycle(self):
    """Override base: read tuple instead of single value."""
    self.read_values()