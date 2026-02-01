# xaeian/cbash.py

"""
Serial console client for embedded devices (CBash firmware).

Extends `SerialPort` with command execution and file/RTC operations
for devices running CBash-compatible firmware.

Requires: `pyserial` (via `serial_port` module)

Example:
  >>> from xaeian.cbash import CBash
  >>> with CBash("/dev/ttyUSB0") as cb:
  ...   cb.ping()
  ...   cb.set_time()
  ...   cb.file_select("config")
  ...   data = cb.file_load_str()
"""

import re, time
from datetime import datetime, timezone
from typing import Callable
from .serial_port import SerialPort

def convert_value(value:str|None):
  """
  Convert string to appropriate Python type.

  Args:
    value: String value to convert.

  Returns:
    Converted value: `None`, `bool`, `int`, `float`, or `str`.

  Example:
    >>> convert_value("123")
    123
    >>> convert_value("true")
    True
  """
  if not value or value.lower() == "null": return None
  lower = value.lower()
  if lower == "true": return True
  if lower == "false": return False
  try: return int(value)
  except ValueError:
    try: return float(value)
    except ValueError: return value

#------------------------------------------------------------------------------------------ CBash

class CBash(SerialPort):
  """
  Serial console for embedded devices with file and RTC commands.

  Extends `SerialPort` with CBash firmware protocol support:
  - Command execution with retry and validation
  - File operations (list, select, load, save)
  - RTC (Real-Time Clock) get/set
  - Device control (ping, reboot)

  Args:
    port: Serial port name.
    baudrate: Baud rate (default `115200`).
    pack_size: Chunk size for file transfers.
    console_mode: Auto-append newline to commands.
    echo_mode: Strip echoed command from response.

  Example:
    >>> with CBash("/dev/ttyUSB0") as cb:
    ...   if cb.ping():
    ...     cb.set_time()
    ...     files = cb.file_list()
  """
  RE_UID = re.compile(r'\b[a-fA-F0-9]{24}\b')
  RE_FILE_LIST = re.compile(r'File list:\s*(.*)', re.IGNORECASE)
  RE_FILE_SIZE = re.compile(r'(\d+)\s*/\s*(\d+)')
  RE_PACK_NBR = re.compile(r'pack:\s*(\d+)')
  RE_DATETIME = re.compile(r'\b\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\b')

  def __init__(
    self,
    port: str,
    baudrate: int = 115200,
    timeout: float = 0.2,
    buffer_size: int = 8192,
    print_console: bool = True,
    print_file: str = "cbash.ansi",
    time_disp: bool = True,
    time_utc: bool = False,
    time_format: str = "%Y-%m-%d %H:%M:%S.%f",
    address: int|None = None,
    print_limit: int = 512,
    pack_size: int = 1024,
    console_mode: bool = True,
    echo_mode: bool = False,
    crc = None,
    logger = None,
    debug: bool = False,
  ):
    self.pack_size = pack_size
    self.files: dict = {}
    self.console_mode = console_mode
    self.echo_mode = echo_mode
    self._file_list: list[str]|None = None
    super().__init__(port, baudrate, timeout, buffer_size,
      print_console, print_file, time_disp, time_utc, time_format,
      address, print_limit, crc, logger, debug)

  #----------------------------------------------------------------------------------- Command exec

  def exec(
    self,
    command: str|bytes,
    as_string: bool = True,
    timeout: float|None = None,
    retries: int = 0,
    retry_delay: float = 0.1,
    validator: Callable[[str|bytes], bool]|None = None,
  ) -> bytes|str|None:
    """
    Execute command and return response.

    Args:
      command: Command to send (newline auto-appended in console_mode).
      as_string: Return decoded string (True) or raw bytes (False).
      timeout: Response timeout in seconds (None = use default).
      retries: Number of retry attempts on failure.
      retry_delay: Delay between retries in seconds.
      validator: Optional callback to validate response.

    Returns:
      Response string/bytes or None on failure.
    """
    attempt = 0
    max_attempts = retries + 1
    original_timeout = self.serial.timeout if self.serial else self.timeout
    while attempt < max_attempts:
      attempt += 1
      if timeout is not None and self.serial: self.serial.timeout = timeout
      try:
        resp = self._exec_once(command, as_string)
        if timeout is not None and self.serial: self.serial.timeout = original_timeout
        if validator and resp is not None:
          if not validator(resp):
            if attempt < max_attempts:
              time.sleep(retry_delay)
              continue
            return None
        return resp
      except Exception as e:
        if timeout is not None and self.serial: self.serial.timeout = original_timeout
        if self.debug: raise
        if attempt < max_attempts: time.sleep(retry_delay)
        else:
          self.print_error(f"Command failed after {max_attempts} attempts: {e}")
          return None
    return None

  def _exec_once(self, command:str|bytes, as_string:bool=True) -> bytes|str|None:
    """Execute command once without retry logic."""
    if self.console_mode and isinstance(command, str) and not command.endswith("\n"):
      command += "\n"
    self.send(command)
    resp = self.read(print_conv2str=True, remove_ansi=as_string)
    if resp is None: return None
    if self.echo_mode:
      idx = resp.find(b"\n") if isinstance(resp, bytes) else resp.find("\n")
      if idx >= 0: resp = resp[idx + 1:]
      else: resp = b"" if isinstance(resp, bytes) else ""
    if self.console_mode:
      if isinstance(resp, bytes) and resp.endswith(b"\r\n"): resp = resp[:-2]
      elif isinstance(resp, str) and resp.endswith("\r\n"): resp = resp[:-2]
    if as_string:
      if isinstance(resp, bytes): return resp.decode("utf-8", errors="ignore").strip()
      return resp.strip()
    return resp

  #----------------------------------------------------------------------------------- Basic commands

  def ping(self) -> bool:
    resp = self.exec("PING")
    if not resp: return False
    return "pong" in resp.lower()

  def uid(self) -> bytes|None:
    """Get device UID as bytes (12 bytes / 24 hex chars)."""
    resp = self.exec("UID")
    if not resp: return None
    match = self.RE_UID.search(resp)
    if match: return bytes.fromhex(match.group())
    return None

  #----------------------------------------------------------------------------------- File operations

  def file_list(self, refresh:bool=False) -> list[str]:
    """Get list of available files. Cached unless refresh=True."""
    if refresh or self._file_list is None:
      resp = self.exec("FILE list")
      match = self.RE_FILE_LIST.search(resp or "")
      self._file_list = match.group(1).strip().split() if match else []
    return self._file_list

  def file_select(self, file_name:str) -> bool:
    """Select file for subsequent operations."""
    if file_name not in self.file_list(): return False
    resp = self.exec(f"FILE select {file_name}")
    if resp and f"file {file_name} selected" in resp.lower(): return True
    return False

  def file_size(self) -> tuple[int, int]|None:
    """Get (used, total) size of selected file, or None on error."""
    resp = self.exec("FILE info")
    if not resp: return None
    idx = resp.lower().rfind('file')
    if idx == -1: return None
    resp = resp[idx:]
    match = self.RE_FILE_SIZE.search(resp)
    if match: return int(match.group(1)), int(match.group(2))
    return None

  @classmethod
  def _parse_pack_number(cls, text:str|None) -> int|None:
    """Extract pack number from response like 'pack: 5'."""
    if not text: return None
    match = cls.RE_PACK_NBR.search(text)
    return int(match.group(1)) if match else None

  def file_save(self, data:str|bytes, append:bool=False) -> bool:
    """Save data to selected file."""
    if not data: return False
    size_info = self.file_size()
    if size_info is None:
      self.print_error("Cannot get file size")
      return False
    used, total = size_info
    free_space = total - used if append else total
    if len(data) > free_space:
      self.print_error("No space in selected file")
      return False
    pack_count = (len(data) + self.pack_size - 1) // self.pack_size
    action = "append" if append else "save"
    resp = self.exec(f"FILE {action} {pack_count}")
    if self._parse_pack_number(resp) != pack_count: return False
    offset = 0
    remaining = pack_count
    while remaining:
      chunk = data[offset:offset + self.pack_size]
      resp = self.exec(chunk)
      if self._parse_pack_number(resp) != remaining - 1: return False
      offset += self.pack_size
      remaining -= 1
    return True

  def file_load(self) -> bytes|None:
    """Load entire content of selected file as bytes."""
    size_info = self.file_size()
    if size_info is None: return None
    used, _ = size_info
    if used == 0: return b""
    pack_count = (used + self.pack_size - 1) // self.pack_size
    result = b""
    for i in range(pack_count):
      offset = i * self.pack_size
      chunk = self.exec(f"FILE load {self.pack_size} {offset}", as_string=False)
      if chunk is None: return None
      result += chunk
    return result[:used]

  def file_load_str(self, strict:bool=True) -> str|None:
    """Load entire content of selected file as string."""
    data = self.file_load()
    if data is None: return None
    return self.bytes_to_string(data, strict=strict)

  #-------------------------------------------------------------------------------------------- RTC

  def set_time(self, utc:bool|None=None):
    """Set device RTC to current time."""
    use_utc = utc if utc is not None else self.time_utc
    now = datetime.now(timezone.utc) if use_utc else datetime.now()
    self.exec(f"RTC {now.strftime('%Y-%m-%d %H:%M:%S')}")

  def get_time(self) -> datetime|None:
    """Get device RTC time."""
    resp = self.exec("RTC")
    if not resp: return None
    match = self.RE_DATETIME.search(resp)
    if match: return datetime.strptime(match.group(), "%Y-%m-%d %H:%M:%S")
    return None

  #------------------------------------------------------------------------------------------ Power

  def reboot(self, immediate:bool=False):
    """Reboot device. If immediate=True, reboot without delay."""
    command = "PWR reboot now" if immediate else "PWR reboot"
    self.exec(command)

