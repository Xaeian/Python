# xaeian/serial/port.py

"""
Serial port communication with colored console output.

Provides `SerialPort` class for serial communication with:
- Colored terminal output with timestamps
- File logging with ANSI codes preserved
- Address filtering for multi-device buses
- CRC support for data integrity
- Context manager for safe resource handling

Colors are class attributes - override via subclass or instance:
  `COLOR_TIME`, `COLOR_ADDR`, `COLOR_INFO`, `COLOR_ERROR`, `COLOR_OK`.

Requires: `pyserial`

Example:
  >>> from xaeian.serial import SerialPort
  >>> with SerialPort("/dev/ttyUSB0", 115200) as sp:
  ...   sp.send("AT\\r\\n")
  ...   response = sp.read()
"""

__extras__ = ("serial", ["pyserial"])

import re
from datetime import datetime, timezone
from typing import Protocol

try:
  import serial as pyserial
except ImportError:
  raise ImportError("Install with: pip install xaeian[serial]")

from ..colors import Color as c

#----------------------------------------------------------------------------------------- Scan

def serial_scan() -> list[str]:
  """Scan available serial/COM ports."""
  from serial.tools import list_ports # type: ignore
  return [p.device for p in list_ports.comports()]

#------------------------------------------------------------------------------------ Protocols

class CRCProto(Protocol):
  """CRC protocol matching `crc.CRC` interface."""
  def encode(self, data:bytes) -> bytes: ...
  def decode(self, data:bytes) -> bytes|None: ...

#-------------------------------------------------------------------------------------- Helpers

_ANSI_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")

def _remove_ansi(data:str|bytes) -> str|bytes:
  """Remove ANSI escape sequences, preserving input type."""
  was_bytes = isinstance(data, bytes)  # remember type to round-trip back
  string = data.decode("utf-8", errors="ignore") if was_bytes else data
  string = _ANSI_RE.sub("", string)
  return string.encode("utf-8") if was_bytes else string

#----------------------------------------------------------------------------------- SerialPort

class SerialPort:
  """
  Serial port handler with colored output and file logging.

  Override these class attributes to customize colors:
    `COLOR_TIME` - timestamp prefix (default `GREY`)
    `COLOR_ADDR` - address byte prefix (default `TURQUS`)
    `COLOR_INFO` - status messages (default `VIOLET`)
    `COLOR_ERROR` - error messages (default `RED`)
    `COLOR_OK` - success messages (default `GREEN`)

  Args:
    port: Serial port name (e.g., `"/dev/ttyUSB0"`, `"COM3"`).
    baudrate: Baud rate (default `115200`).
    timeout: Read timeout in seconds.
    buffer_size: Read buffer size in bytes.
    print_console: Enable console output.
    print_file: Log file path (empty to disable).
    time_disp: Show timestamps in output.
    time_utc: Use UTC time (`False` = local time).
    time_format: Timestamp format string.
    address: Device address for filtering (`None` = disabled).
    print_limit: Max characters to print per message.
    crc: CRC instance for data integrity (`None` = disabled).
    debug: Raise exceptions instead of silent fail.
  """
  COLOR_TIME = c.GREY
  COLOR_ADDR = c.TURQUS
  COLOR_INFO = c.VIOLET
  COLOR_ERROR = c.RED
  COLOR_OK = c.GREEN

  def __init__(
    self,
    port:str,
    baudrate:int = 115200,
    timeout:float = 0.2,
    buffer_size:int = 8192,
    print_console:bool = True,
    print_file:str = "",
    time_disp:bool = True,
    time_utc:bool = False,
    time_format:str = "%Y-%m-%d %H:%M:%S.%f",
    address:int|None = None,
    print_limit:int = 256,
    crc:CRCProto|None = None,
    debug:bool = False,
  ):
    self.serial = None
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

  #------------------------------------------------------------------------------------ Context

  def __enter__(self) -> "SerialPort":
    self.connect()
    return self

  def __exit__(self, exc_type, exc_val, exc_tb) -> None:
    self.disconnect()

  #-------------------------------------------------------------------------------------- Print

  def _timestamp(self) -> str:
    now = datetime.now(timezone.utc) if self.time_utc else datetime.now()
    return now.strftime(self.time_format)

  def print(self, text:str, prefix:str=""):
    """Render line with timestamp, prefix, address. Output to console + file."""
    if len(text) > self.print_limit:
      text = text[:self.print_limit] + f"...{c.END}"  # reset color in case cut mid-ANSI
    # envelope order: addr → prefix → time → text (each prepended to previous)
    if self.time_disp:
      text = f"{self.COLOR_TIME}{self._timestamp()}{c.END} {text}"
    if prefix: text = f"{prefix} {text}"
    if self.address is not None:
      text = f"{self.COLOR_ADDR}0x{self.address:02X}{c.END} {text}"
    if self.print_console: print(text)
    if self.print_file:
      try:
        with open(self.print_file, "a", encoding="utf-8") as f:
          print(text, file=f)
      except Exception:
        if self.debug: raise

  def print_info(self, text:str):
    self.print(f"{self.COLOR_INFO}{text}{c.END}")

  def print_error(self, text:str):
    self.print(f"{self.COLOR_ERROR}{text}{c.END}")

  def print_ok(self, text:str):
    self.print(f"{self.COLOR_OK}{text}{c.END}")

  def print_conv2str(self, resp:bytes, str_color=c.WHITE, bytes_color=c.SALMON) -> str|None:
    """Try to print as string, fallback to bytes. Returns stripped string or None."""
    try:
      stripped = resp.decode("utf-8").rstrip()
      if stripped: self.print(f"{str_color}{stripped}{c.END}")
      return stripped or None
    except UnicodeDecodeError:
      self.print(f"{bytes_color}{resp}{c.END}")
      return None

  def bytes_to_string(self, data:bytes, encoding:str="utf-8", strict:bool=True) -> str|None:
    """Convert bytes to string. If strict=False, drops non-ASCII chars."""
    try:
      return data.decode(encoding).strip()
    except UnicodeDecodeError:
      if strict: return None
      cleaned = bytes(b for b in data if b < 128)
      return cleaned.decode(encoding, errors="ignore").strip()

  #--------------------------------------------------------------------------------- Connection

  def connect(self) -> bool:
    """Open serial port. Idempotent. Returns `True` on success."""
    if self.connected: return True
    try:
      self.serial = pyserial.Serial(self.port, self.baudrate, timeout=self.timeout)
      self.print_info(f"Connect {self.port}")
      self.connected = True
      return True
    except pyserial.SerialException as e:
      self.print_error(f"Serial port {self.port} is used - {e}")
      if self.debug: raise
    except Exception as e:
      self.print_error(f"Serial port {self.port} cannot be opened - {e}")
      if self.debug: raise
    return False

  def disconnect(self):
    """Close serial port. Idempotent."""
    if not self.connected: return
    self.print_info(f"Disconnect {self.port}")
    try: self.serial.close()
    except Exception:
      if self.debug: raise
    self.connected = False

  #------------------------------------------------------------------------------ Address & CRC

  def _check_address(self, resp:bytes) -> bytes|None:
    """Strip leading address byte if matches `self.address`. None = not for us."""
    if resp and resp[0] == self.address: return resp[1:]
    return None

  def _crc_encode(self, data:bytes) -> bytes:
    """Append CRC if enabled, else pass through."""
    if self.crc: return self.crc.encode(data)
    return data

  def _crc_decode(self, data:bytes) -> bytes|None:
    """Verify and strip CRC if enabled. Returns `None` on mismatch."""
    if self.crc:
      result = self.crc.decode(data)
      if result is None:
        self.print_error("CRC check failed")
        if self.debug: raise ValueError("CRC check failed")
      return result
    return data

  #--------------------------------------------------------------------------------------- Read

  def read(
    self,
    str_color = c.WHITE,
    bytes_color = c.SALMON,
    print_conv2str:bool = False,
    remove_ansi:bool = False,
  ) -> bytes|None:
    """
    Read available bytes from port (up to `buffer_size`, blocks until `timeout`).

    Args:
      print_conv2str: Try utf-8 decode for display, fallback to raw bytes.
      remove_ansi: Strip ANSI escape codes from returned data.

    Returns:
      Raw bytes (or ANSI-stripped) or `None` on empty/error/CRC fail.
    """
    try:
      resp = self.serial.read(self.buffer_size)
    except Exception as e:
      self.print_error(f"Read error: {e}")
      if self.debug: raise
      return None
    if self.address is not None: resp = self._check_address(resp)
    if not resp: return None
    resp = self._crc_decode(resp)  # None here = CRC fail, propagate as no-data
    if resp is None: return None
    if print_conv2str: self.print_conv2str(resp, str_color, bytes_color)
    else: self.print(f"{bytes_color}{resp}{c.END}")
    if remove_ansi: resp = _remove_ansi(resp)
    return resp

  def read_line(
    self,
    color = c.WHITE,
    conv2str:bool = True,
    remove_ansi:bool = True,
  ) -> bytes|str|None:
    """
    Read until newline. Returns `str` if `conv2str=True`, else `bytes`. `None` on empty.
    """
    try:
      resp = self.serial.readline(self.buffer_size)
    except Exception as e:
      self.print_error(f"Read error: {e}")
      if self.debug: raise
      return None
    if self.address is not None: resp = self._check_address(resp)
    if not resp: return None
    if conv2str: resp = self.print_conv2str(resp, color, color)
    else: self.print(f"{color}{resp}{c.END}")
    if remove_ansi and resp: resp = _remove_ansi(resp)
    return resp

  def read_lines(self, color=c.WHITE, conv2str:bool=True) -> list[str]|None:
    """Read available bytes, split into lines. Returns `list[str]` or `None` on empty."""
    try:
      resp = self.serial.read(self.buffer_size)
    except Exception as e:
      self.print_error(f"Read error: {e}")
      if self.debug: raise
      return None
    if self.address is not None: resp = self._check_address(resp)
    if not resp: return None
    # collapse CR/LF runs to single \n → strip edges → split (avoids empty lines)
    lines = re.sub(b"[\r\n]+", b"\n", resp).strip(b"\n").split(b"\n")
    result = []
    for line in lines:
      if conv2str: result.append(self.print_conv2str(line, color, color))
      else:
        self.print(f"{color}{line}{c.END}")
        result.append(line)
    return result

  def clear(self, color=c.GREY):
    """Drain remaining bytes from input buffer and flush output."""
    while True:
      resp = self.read_lines(color)
      if not resp: break
    self.flush()

  def flush(self):
    """Flush pending output bytes (tx buffer)."""
    try: self.serial.flush()
    except Exception:
      if self.debug: raise

  #--------------------------------------------------------------------------------------- Send

  def send(self, message:str|bytes, str_color=c.GREY, bytes_color=c.SALMON):
    """Write to port. `str` is utf-8 encoded, `bytes` sent raw. Address + CRC applied."""
    if isinstance(message, str):
      self.print(f"{str_color}{message.strip()}{c.END}")
      data = message.encode("utf-8")
    else:
      data = message
      self.print(f"{bytes_color}{data}{c.END}")
    if self.address is not None: data = bytes([self.address]) + data  # addr before CRC
    data = self._crc_encode(data)
    try: self.serial.write(data)
    except Exception as e:
      self.print_error(f"Write error: {e}")
      if self.debug: raise