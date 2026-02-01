# xaeian/serial_port.py

"""
Serial port communication with colored console output.

Provides `SerialPort` class for serial communication with:
- Colored terminal output with timestamps
- File logging with ANSI codes preserved
- Address filtering for multi-device buses
- CRC support for data integrity
- Context manager for safe resource handling

Requires: `pyserial`

Example:
  >>> from xaeian.serial_port import SerialPort
  >>> with SerialPort("/dev/ttyUSB0", 115200) as sp:
  ...   sp.send("AT\\r\\n")
  ...   response = sp.read()
"""

import re
import time
from datetime import datetime, timezone
from typing import Protocol

try:
  import serial
except ImportError:
  raise ImportError("Install with: pip install xaeian[serial]")

from .colors import Color

#-------------------------------------------------------------------------------------- Protocols

class Logger(Protocol):
  """Logger protocol for custom logging implementations."""
  def __call__(self, text:str, level:str="info") -> None: ...

class CRCProto(Protocol):
  """CRC protocol matching `crc.CRC` interface."""
  def encode(self, data:bytes) -> bytes: ...
  def decode(self, data:bytes) -> bytes|None: ...

class SerialProto(Protocol):
  """Protocol for serial port (allows mocking in tests)."""
  def read(self, size:int) -> bytes: ...
  def readline(self, size:int) -> bytes: ...
  def write(self, data:bytes) -> int: ...
  def flush(self) -> None: ...
  def close(self) -> None: ...

#---------------------------------------------------------------------------------------- Loggers

def default_logger(text:str, level:str="info") -> None:
  """Default logger — prints to console."""
  print(text)

def null_logger(text:str, level:str="info") -> None:
  """Silent logger — discards all output."""
  pass

#------------------------------------------------------------------------------------- SerialPort

class SerialPort:
  """
  Serial port handler with colored output and logging.

  Features:
  - Colored terminal output with optional timestamps
  - File logging (preserves ANSI codes for `cat` viewing)
  - Address byte filtering for multi-device buses
  - CRC encoding/decoding for data integrity
  - Context manager support (`with` statement)

  Args:
    port: Serial port name (e.g., `"/dev/ttyUSB0"`, `"COM3"`).
    baudrate: Baud rate (default `115200`).
    timeout: Read timeout in seconds.
    buffer_size: Read buffer size in bytes.
    print_console: Enable colored console output.
    print_file: Log file path (empty to disable).
    time_disp: Show timestamps in output.
    time_utc: Use UTC time (`False` = local time).
    time_format: Timestamp format string.
    address: Device address for filtering (`None` = disabled).
    print_limit: Max characters to print per message.
    crc: CRC instance for data integrity (`None` = disabled).
    logger: Custom logger callback.
    debug: Raise exceptions instead of silent fail.

  Example:
    >>> with SerialPort("/dev/ttyUSB0", 115200) as sp:
    ...   sp.send("AT\\r\\n")
    ...   response = sp.read()
  """
  def __init__(
    self,
    port: str,
    baudrate: int = 115200,
    timeout: float = 0.2,
    buffer_size: int = 8192,
    print_console: bool = True,
    print_file: str = "",
    time_disp: bool = True,
    time_utc: bool = False,
    time_format: str = "%Y-%m-%d %H:%M:%S.%f",
    address: int|None = None,
    print_limit: int = 256,
    crc: CRCProto|None = None,
    logger: Logger|None = None,
    debug: bool = False,
    serial_class: type = None,
  ):
    self.serial: SerialProto|None = None
    self.port = port
    self.baudrate = baudrate
    self.timeout = timeout
    self.buffer_size = buffer_size
    self.print_console = print_console
    self.print_file = print_file
    self.time_disp = time_disp
    self.time_utc = time_utc
    self.time_format = time_format
    self.connected = False
    self.address = address
    self.print_limit = print_limit
    self.crc = crc
    self.debug = debug
    self._serial_class = serial_class or serial.Serial
    self._logger = logger or (default_logger if print_console else null_logger)

  #----------------------------------------------------------------------------------- Context manager

  def __enter__(self) -> "SerialPort":
    self.connect()
    return self

  def __exit__(self, exc_type, exc_val, exc_tb) -> None:
    self.disconnect()

  #----------------------------------------------------------------------------------------- Logging

  def _log(self, text:str, level:str="info"):
    """Internal logging with optional file output."""
    if self.print_file:
      try:
        with open(self.print_file, 'a', encoding="utf-8") as f:
          print(text, file=f)
      except Exception:
        if self.debug: raise
    self._logger(text, level)

  def _timestamp(self) -> str:
    now = datetime.now(timezone.utc) if self.time_utc else datetime.now()
    return now.strftime(self.time_format)

  def print(self, text:str, prefix:str=""):
    if len(text) > self.print_limit:
      text = text[:self.print_limit] + f"...{Color.END}"
    if self.time_disp:
      text = f"{Color.CYAN}{self._timestamp()}{Color.END} {text}"
    if prefix: text = f"{prefix} {text}"
    if self.address is not None:
      text = f"{Color.TURQUS}0x{self.address:02X}{Color.END} {text}"
    self._log(text, "info")

  def print_error(self, text:str):
    self.print(f"{Color.RED}{text}{Color.END}")

  def print_ok(self, text:str):
    self.print(f"{Color.GREEN}{text}{Color.END}")

  def print_conv2str(self, resp:bytes, str_color=Color.WHITE, bytes_color=Color.SALMON) -> str|None:
    """Try to print as string, fallback to bytes. Returns decoded string or None."""
    try:
      text = resp.decode("utf-8")
      if text.rstrip(): self.print(f"{str_color}{text.rstrip()}{Color.END}")
      return text
    except UnicodeDecodeError:
      self.print(f"{bytes_color}{resp}{Color.END}")
      return None

  def bytes_to_string(self, data:bytes, encoding:str="utf-8", strict:bool=True) -> str|None:
    """Convert bytes to string. If strict=False, ignores non-ASCII chars."""
    try:
      return data.decode(encoding).strip()
    except UnicodeDecodeError:
      if strict:
        self.print_error("Failed conversion bytes to string")
        return None
      cleaned = bytes(b for b in data if b < 128)
      return cleaned.decode(encoding, errors='ignore').strip()

  #-------------------------------------------------------------------------------------- Connection

  def connect(self) -> bool:
    if self.connected: return True
    try:
      self.serial = self._serial_class(self.port, self.baudrate, timeout=self.timeout)
      self.print(f"{Color.VIOLET}Connect {self.port}{Color.END}")
      self.connected = True
      return True
    except serial.SerialException as e:
      self.print_error(f"Serial port {self.port} is used - {e}")
      if self.debug: raise
    except Exception as e:
      self.print_error(f"Serial port {self.port} cannot be opened - {e}")
      if self.debug: raise
    return False

  def disconnect(self):
    if not self.connected: return
    self.print(f"{Color.VIOLET}Disconnect {self.port}{Color.END}")
    try: self.serial.close()
    except Exception:
      if self.debug: raise
    self.connected = False

  #------------------------------------------------------------------------------------- Address & CRC

  def _check_address(self, resp:bytes) -> bytes|None:
    """Strip address byte from response if it matches."""
    if resp and resp[0] == self.address: return resp[1:]
    return None

  def _crc_encode(self, data:bytes) -> bytes:
    """Apply CRC encoding if enabled."""
    if self.crc: return self.crc.encode(data)
    return data

  def _crc_decode(self, data:bytes) -> bytes|None:
    """Apply CRC decoding if enabled. Returns None on CRC error."""
    if self.crc:
      result = self.crc.decode(data)
      if result is None:
        self.print_error("CRC check failed")
        if self.debug: raise ValueError("CRC check failed")
      return result
    return data

  @staticmethod
  def remove_ansi(data:str|bytes) -> str|bytes:
    """Remove ANSI escape sequences, preserving input type."""
    was_bytes = isinstance(data, bytes)
    string = data.decode("utf-8", errors="ignore") if was_bytes else data
    string = re.sub(r'\x1B\[[0-?]*[ -/]*[@-~]', "", string)
    return string.encode("utf-8") if was_bytes else string

  #-------------------------------------------------------------------------------------------- Read

  def read(self, str_color=Color.WHITE, bytes_color=Color.SALMON,
           print_conv2str:bool=False, remove_ansi:bool=False) -> bytes|None:
    try:
      resp = self.serial.read(self.buffer_size)
    except Exception as e:
      self.print_error(f"Read error: {e}")
      if self.debug: raise
      return None
    if self.address is not None: resp = self._check_address(resp)
    if not resp: return None
    resp = self._crc_decode(resp)
    if resp is None: return None
    if print_conv2str: self.print_conv2str(resp, str_color, bytes_color)
    else: self.print(f"{bytes_color}{resp}{Color.END}")
    if remove_ansi: resp = self.remove_ansi(resp)
    return resp

  def read_line(self, color=Color.WHITE, conv2str:bool=True, remove_ansi:bool=True) -> bytes|str|None:
    try:
      resp = self.serial.readline(self.buffer_size)
    except Exception as e:
      self.print_error(f"Read error: {e}")
      if self.debug: raise
      return None
    if self.address is not None: resp = self._check_address(resp)
    if not resp: return None
    if conv2str: resp = self.print_conv2str(resp, color, color)
    else: self.print(f"{color}{resp}{Color.END}")
    if remove_ansi and resp: resp = self.remove_ansi(resp)
    return resp

  def read_lines(self, color=Color.WHITE, conv2str:bool=True) -> list[str]|None:
    try:
      resp = self.serial.read(self.buffer_size)
    except Exception as e:
      self.print_error(f"Read error: {e}")
      if self.debug: raise
      return None
    if self.address is not None: resp = self._check_address(resp)
    if not resp: return None
    lines = re.sub(b'[\r\n]+', b'\n', resp).strip(b'\n').split(b'\n')
    result = []
    for line in lines:
      if conv2str: result.append(self.print_conv2str(line, color, color))
      else:
        self.print(f"{color}{line}{Color.END}")
        result.append(line)
    return result

  def clear(self, color=Color.GREY):
    while True:
      resp = self.read_lines(color)
      if not resp: break
    self.flush()

  def flush(self):
    try: self.serial.flush()
    except Exception:
      if self.debug: raise

  #-------------------------------------------------------------------------------------------- Send

  def send(self, message:str|bytes, str_color=Color.GREY, bytes_color=Color.SALMON):
    if isinstance(message, str):
      self.print(f"{str_color}{message.strip()}{Color.END}")
      data = message.encode("utf-8")
    else:
      data = message
      self.print(f"{bytes_color}{data}{Color.END}")
    if self.address is not None: data = bytes([self.address]) + data
    data = self._crc_encode(data)
    try: self.serial.write(data)
    except Exception as e:
      self.print_error(f"Write error: {e}")
      if self.debug: raise

#---------------------------------------------------------------------------------------- Recorder

class Recorder(SerialPort):
  """
  Serial port reader that continuously reads and parses numeric values.
  Handles partial lines and connection timeouts gracefully.
  """

  def __init__(
    self,
    port: str,
    baudrate: int = 9600,
    timeout: float = 0.1,
    buffer_size: int = 8192,
    print_console: bool = True,
    print_file: str = "rec.ansi",
    time_disp: bool = True,
    time_utc: bool = False,
    time_format: str = "%Y-%m-%d %H:%M:%S.%f",
    name: str = "",
    color: str = Color.WHITE,
    err_delay: float = 5,
  ):
    """
    Args:
      name: Device identifier for logging
      color: Output color for this device
      err_delay: Seconds without data before disconnect
    """
    self.name = name
    self.color = color
    self.err_delay = err_delay
    self.err_time: float = 0
    self.value: float|None = None
    self._leftover = ""
    super().__init__(port, baudrate, timeout, buffer_size,
      print_console, print_file, time_disp, time_utc, time_format)

  def print(self, text:str, prefix:str=""):
    prefix = f"{Color.TURQUS}{self.name}{Color.END}"
    super().print(text, prefix)

  def _check_timeout(self) -> bool:
    """Returns True if connection timed out."""
    if self.err_time and time.time() > self.err_time:
      self.disconnect()
      self.print_error(f"Serial port {self.port} not responding")
      return True
    return False

  def _reset_timeout(self):
    """Reset timeout counter after successful read."""
    self.err_time = time.time() + self.err_delay

  def scan(self):
    """Check connection and clear buffer. Call periodically."""
    if self._check_timeout(): return
    if not self.connect(): return
    try:
      self.clear(self.color)
      self._reset_timeout()
    except Exception:
      if self.debug: raise

  def read_value(self, regex:str|None=None) -> float|None:
    """
    Read and parse numeric value from serial.
    Handles partial lines by keeping leftover data between calls.
    """
    if self._check_timeout():
      self._leftover = ""
      self.value = None
      return None
    if not self.connect():
      self.value = None
      self._leftover = ""
      return None
    try:
      lines = self.read_lines(self.color)
      if not lines: return self.value
      if self._leftover:
        lines[0] = self._leftover + (lines[0] or "")
        self._leftover = ""
      for i, line in enumerate(reversed(lines)):
        if not line: continue
        if regex and not re.match(regex, line):
          if i == 0: self._leftover = line
          continue
        try:
          self.value = float(line)
          self._reset_timeout()
          break
        except ValueError:
          pass
    except Exception:
      self._leftover = ""
      if self.debug: raise
    return self.value

#---------------------------------------------------------------------------------------- Tests

if __name__ == "__main__":
  try:
    from serial.tools import list_ports
    ports = list(list_ports.comports())
    print("available ports:")
    for p in ports:
      print(f"  {p.device:15} {p.description}")
    if not ports: print("  (none)")
  except ImportError:
    print("pyserial not installed")
  print()
  print("usage:")
  print('  with SerialPort("/dev/ttyUSB0", 115200) as sp:')
  print('    sp.send(b"AT\\r\\n")')
  print('    print(sp.read())')
