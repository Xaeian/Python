# xaeian/serial/rec.py

"""
Threaded numeric value recorders.

`Recorder` reads bytes in a background thread and exposes the latest regex match via `.value`,
surviving values split across reads (Brymen, Rigol). `MultiRecorder` parses N separator-delimited
values per line into `.values`. Both are pure data sources: `start()` spawns the reader thread,
`stop()` joins it, and what happens with the values (CSV, DB, MQTT, plot) is up to the caller.

Example:
  >>> from xaeian.serial import Recorder
  >>> rec = Recorder("COM7", name="U1", regex=Recorder.SCI_NORM)
  >>> rec.start()
  >>> rec.value
  >>> rec.stop()
"""

import re, time, threading
from .port import SerialPort
from ..colors import Color as c

#----------------------------------------------------------------------------------------- Recorder

class Recorder(SerialPort):
  """
  Single numeric value pulled from a byte stream by a background thread.

  The rolling buffer holds the line still being received, so a value split across reads matches
  once its line completes; the last unanchored match in that line wins and rebinds `self.value`,
  which the calling thread reads without a lock.

  Patterns for `regex=`:
    `SCI_NORM` - 1.23456e+02 (SCPI, Brymen, Rigol)
    `SCI` - general scientific notation
    `FLOAT` - 123.456
    `NUM` - int or float

  Args:
    name: Device identifier shown in the console prefix.
    regex: Value pattern, `None` → `NUM`.
    color: ANSI color for raw data lines.
    err_delay_ms: Milliseconds without fresh data before forced disconnect.
  """
  SCI_NORM = r"-?[1-9]\.\d+[eE][+-]?\d{2}"
  SCI = r"-?\d+\.?\d*[eE][+-]?\d+"
  FLOAT = r"-?\d+\.\d+"
  NUM = r"-?\d+(?:\.\d+)?"

  _BUF_MAX = 4096

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
    self._print_buf = "" # incomplete line awaiting \r\n
    self._stop_event = threading.Event()
    self._thread:threading.Thread|None = None
    super().__init__(port, baudrate, timeout, buffer_size,
      print_console, print_file, time_disp, time_utc, time_format)

  #------------------------------------------------------------------------------------------ Print

  def print(self, text:str, prefix:str=""):
    """Prepend the device name to any caller-supplied prefix."""
    name_prefix = f"{self.COLOR_NAME}{self.name}{c.END}"
    combined = f"{name_prefix} {prefix}".strip()
    super().print(text, combined)

  #---------------------------------------------------------------------------------------- Timeout

  def _check_timeout(self) -> bool:
    """Disconnect and report `True` once `err_delay_ms` passed without a successful read."""
    if self.err_time and time.time() > self.err_time:
      self.disconnect()
      self.print_error(f"Serial port {self.port} not responding")
      self.err_time = 0 # fire once, next cycle falls through to connect()
      return True
    return False

  def _reset_timeout(self):
    """Push the deadline `err_delay_ms` into the future after a successful read."""
    self.err_time = time.time() + self.err_delay_ms / 1000

  def _reset_state(self):
    """Clear the rolling buffer. Call on timeout/error/disconnect."""
    self._print_buf = ""

  #------------------------------------------------------------------------------------ Read engine

  def _read_and_print(self) -> list[str]:
    """Read fresh bytes into the buffer, print complete lines, return the new ones."""
    try:
      resp = self.serial.read(self.buffer_size)
      if not resp: return []
      text = resp.decode("utf-8", errors="ignore")
      self._print_buf += text
      parts = re.split(r"[\r\n]+", self._print_buf)
      self._print_buf = parts[-1] # last part is incomplete, "" if the read ended with \r\n
      new_lines = []
      for line in parts[:-1]:
        if line.strip():
          self.print(f"{self.color}{line.strip()}{c.END}")
          new_lines.append(line.strip())
      # cap in case the instrument streams without newlines
      if len(self._print_buf) > self._BUF_MAX:
        self._print_buf = self._print_buf[-self._BUF_MAX:]
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

  #------------------------------------------------------------------------------------- Read value

  def read_value(self) -> float|None:
    """
    Latest numeric value from the newest complete line, also stored in `self.value`.

    The previous value persists until a new match; `None` after a timeout or a failed open.
    """
    if self._check_timeout():
      self._reset_state()
      self.value = None
      return None
    if not self.connect():
      self._reset_state()
      self.value = None
      time.sleep(self.timeout) # pace reconnect attempts while port is absent
      return None
    new_lines = self._read_and_print()
    if not new_lines: return self.value # no fresh line, the cached value stays valid
    pattern = self._strip_anchors(self.regex or self.NUM)
    matches = list(re.finditer(pattern, new_lines[-1]))
    if matches:
      try:
        self.value = float(matches[-1].group())
        self._reset_timeout()
      except ValueError:
        pass
    return self.value

  #-------------------------------------------------------------------------------------- Lifecycle

  def _update_cycle(self):
    """One reader-loop iteration, overridden for other value shapes."""
    self.read_value()

  def _run(self):
    """Thread body: read until stop is signalled."""
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

  def stop(self, timeout_ms:int=2000):
    """Signal stop and join the reader thread, waiting at most `timeout_ms`."""
    self._stop_event.set()
    if self._thread: self._thread.join(timeout=timeout_ms / 1000)
    self._thread = None

#------------------------------------------------------------------------------------ MultiRecorder

class MultiRecorder(Recorder):
  """
  Reader for instruments emitting N separator-delimited values per line.

  Suits STM32 / Arduino emitters like `1.234,5.678,9.012,4.567\\r\\n`. Only the newest complete
  line counts, older ones in the same read are dropped; a split count other than `count` sets
  `self.values` to `None` as an error signal.

  Args:
    count: Exact number of values expected per line.
    separator: Char/string between values, regex-escaped internally.
    regex: Value pattern, `None` → `NUM`.
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
    Values from the newest complete line, also stored in `self.values`.

    `None` on wrong count or parse error, previous values while no new line arrives.
    """
    if self._check_timeout():
      self._reset_state()
      self.values = None
      return None
    if not self.connect():
      self._reset_state()
      self.values = None
      time.sleep(self.timeout) # pace reconnect attempts while port is absent
      return None
    new_lines = self._read_and_print()
    if not new_lines: return self.values # no fresh line, cached values stay valid
    pattern = self._strip_anchors(self.regex or self.NUM)
    sep = re.escape(self.separator)
    line = new_lines[-1]
    parts = re.split(sep, line)
    if len(parts) != self.count:
      self.values = None
      return None
    try:
      self.values = [float(re.search(pattern, p.strip()).group()) for p in parts]
      self._reset_timeout()
      return self.values
    except (AttributeError, ValueError): # AttributeError = re.search found nothing in a part
      self.values = None
      return None

  def _update_cycle(self):
    self.read_values()