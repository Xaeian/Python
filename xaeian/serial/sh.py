# xaeian/serial/sh.py

"""
Python client for embedded Shell (`lib/sh` C firmware).

Sends text commands and parses responses, dropping the device echo (`>> command^E\\r\\n`), the
ANSI escapes of its prompt and trailing whitespace. The methods wrap the `cmd.h` built-ins;
device-specific extensions go through `exec()`:

  >>> sh.exec("alarm 1 set everyday 06:00:00")

Example:
  >>> from xaeian.serial import Shell
  >>> with Shell("/dev/ttyUSB0") as sh:
  ...   if sh.ping():
  ...     sh.set_time()
  ...     sh.mbb_select("config")
  ...     data = sh.mbb_load_str()
"""

import re, time
from datetime import datetime, timezone
from typing import Callable
from .port import SerialPort
from ..colors import Color as c

#------------------------------------------------------------------------------------------ Helpers

def convert_value(value:str|None):
  """
  Convert a response token to a Python type.

  Empty/`null` → `None`, `true`/`false` → `bool`, then `int`, `float`, else the original `str`.
  """
  if not value or value.lower() == "null": return None
  lower = value.lower()
  if lower == "true": return True
  if lower == "false": return False
  try: return int(value)
  except ValueError:
    try: return float(value)
    except ValueError: return value

#-------------------------------------------------------------------------------------------- Shell

class Shell(SerialPort):
  """
  Client for devices running the embedded SH shell.

  Args:
    console_mode: Auto-append `\\n` to commands, matching the device `console_mode`.
    strip_echo: Drop the echoed `>> command^E\\r\\n` first line of every response.
    pack_size: Chunk size in bytes for MBB transfers.
  """
  RE_UID = re.compile(r"\b[a-fA-F0-9]{24}\b")
  RE_DATETIME = re.compile(r"\b\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\b")
  RE_MBB_LIST = re.compile(r"(?:mbb|file)\s+list:\s*(.*)", re.IGNORECASE)
  RE_MBB_SIZE = re.compile(r"(\d+)\s*/\s*(\d+)")
  RE_PACK_NBR = re.compile(r"pack:\s*(\d+)")

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
    print_limit:int = 512,
    console_mode:bool = True,
    strip_echo:bool = True,
    pack_size:int = 1024,
    crc = None,
    debug:bool = False,
  ):
    self.console_mode = console_mode
    self.strip_echo = strip_echo
    self.pack_size = pack_size
    self._mbb_list:list[str]|None = None
    super().__init__(port, baudrate, timeout, buffer_size,
      print_console, print_file, time_disp, time_utc, time_format,
      address, print_limit, crc, debug)

  #------------------------------------------------------------------------------------------- Exec

  def exec(
    self,
    command:str|bytes,
    timeout_ms:int|None = None,
    retries:int = 0,
    retry_delay_ms:int = 100,
    validator:Callable[[str], bool]|None = None,
  ) -> str|None:
    """
    Send command and return the stripped response, `None` once every attempt failed.

    Args:
      timeout_ms: One-shot read timeout override, restored afterwards.
      retries: Extra attempts on empty response, validator failure or exception.
      validator: `Callable(response) → bool`, `False` triggers a retry.
    """
    original_timeout = self.serial.timeout if self.serial else self.timeout
    attempts = retries + 1
    while attempts:
      attempts -= 1
      if timeout_ms is not None and self.serial:
        self.serial.timeout = timeout_ms / 1000 # pyserial wants seconds
      try:
        resp = self._exec_once(command)
      except Exception as e:
        if timeout_ms is not None and self.serial:
          self.serial.timeout = original_timeout
        if self.debug: raise
        if not attempts:
          self.print_error(f"exec failed: {e}")
          return None
        time.sleep(retry_delay_ms / 1000)
        continue
      if timeout_ms is not None and self.serial:
        self.serial.timeout = original_timeout
      if resp is None or (validator and not validator(resp)):
        if not attempts: return None
        time.sleep(retry_delay_ms / 1000)
        continue
      return resp
    return None

  def _exec_once(self, command:str|bytes) -> str|None:
    """Single send/read cycle, one attempt of `exec`."""
    if self.console_mode and isinstance(command, str) and not command.endswith("\n"):
      command += "\n"
    self.send(command)
    resp = self.read(print_conv2str=True, remove_ansi=True)
    if resp is None: return None
    text = resp.decode("utf-8", errors="ignore") if isinstance(resp, bytes) else resp
    if self.strip_echo:
      nl = text.find("\n")
      if nl >= 0: text = text[nl + 1:]
      else: text = ""
    return text.strip()

  def _exec_bytes(self, command:str, timeout_ms:int|None=None) -> bytes|None:
    """Send text command, read raw bytes: no ANSI strip, no decode, MBB chunks are binary."""
    if self.console_mode and not command.endswith("\n"): command += "\n"
    original_timeout = self.serial.timeout if self.serial else self.timeout
    if timeout_ms is not None and self.serial:
      self.serial.timeout = timeout_ms / 1000
    self.send(command)
    resp = self.read()
    if timeout_ms is not None and self.serial:
      self.serial.timeout = original_timeout
    if resp is None: return None
    if self.strip_echo:
      nl = resp.find(b"\n")
      if nl >= 0: resp = resp[nl + 1:]
    return resp

  #------------------------------------------------------------------------------------------ Basic

  def ping(self, retries:int=3, retry_delay_ms:int=500) -> bool:
    """Check device liveness, `True` when the answer contains `pong`."""
    resp = self.exec(
      "ping", retries=retries, retry_delay_ms=retry_delay_ms,
      validator=lambda r: "pong" in r.lower(),
    )
    return resp is not None

  def uid(self) -> bytes|None:
    """Get device UID (12 bytes / 24 hex chars), or `None` on parse failure."""
    resp = self.exec("uid")
    if not resp: return None
    match = self.RE_UID.search(resp)
    if match: return bytes.fromhex(match.group())
    return None

  #-------------------------------------------------------------------------------------------- MBB

  def mbb_list(self, refresh:bool=False) -> list[str]:
    """
    Registered MBB names. Cached for the lifetime of the object.

    An unreadable reply caches as `[]`, so `refresh=True` is the only way back.
    """
    if refresh or self._mbb_list is None:
      resp = self.exec("mbb list")
      match = self.RE_MBB_LIST.search(resp or "")
      self._mbb_list = match.group(1).strip().split() if match else []
    return self._mbb_list

  def mbb_select(self, name:str) -> bool:
    """Select MBB for later use. `False` when `mbb_list` lacks the name or the device declines."""
    if name not in self.mbb_list(): return False
    resp = self.exec(f"mbb select {name}")
    return bool(resp and "selected" in resp.lower())

  def mbb_active(self) -> str|None:
    """Get name of currently active MBB."""
    resp = self.exec("mbb active")
    if not resp: return None
    # format is firmware-dependent, assume the name is the last token
    tokens = resp.strip().split()
    return tokens[-1] if tokens else None

  def mbb_info(self) -> tuple[int, int]|None:
    """Get `(used, total)` byte counts of active MBB, or `None` on parse fail."""
    resp = self.exec("mbb info")
    if not resp: return None
    # response is either "mbb info: name 123/2048 ..." or bare "name 123/2048 ..."
    match = self.RE_MBB_SIZE.search(resp)
    if match: return int(match.group(1)), int(match.group(2))
    return None

  def mbb_clear(self) -> bool:
    """Clear active MBB content."""
    resp = self.exec("mbb clear")
    return bool(resp and ("ok" in resp.lower() or "clear" in resp.lower()))

  def mbb_print(self) -> str|None:
    """Print active MBB metadata via device (name, size/limit, flash, mutex)."""
    return self.exec("mbb print")

  def mbb_copy(self, src:str, dst:str) -> bool:
    """Copy content `src` MBB → `dst` MBB."""
    resp = self.exec(f"mbb copy from {src} to {dst}")
    return bool(resp and ("ok" in resp.lower() or "copied" in resp.lower()))

  def mbb_save(self, data:str|bytes, append:bool=False) -> bool:
    """
    Save to the active MBB in `pack_size` chunks, one ack per chunk.

    `append=False` overwrites the whole MBB. `str` is encoded as utf-8.
    A refused chunk aborts and returns `False`, leaving the MBB half written.
    """
    if not data: return False
    if isinstance(data, str): data = data.encode("utf-8")
    info = self.mbb_info()
    if info is None:
      self.print_error("Cannot get MBB size")
      return False
    used, total = info
    free = total - used if append else total
    if len(data) > free:
      self.print_error("No space in selected MBB")
      return False
    pack_count = (len(data) + self.pack_size - 1) // self.pack_size
    action = "append" if append else "save"
    # announce the incoming pack count, device echoes it back as "pack: N"
    resp = self.exec(f"mbb {action} {pack_count}")
    if self._parse_pack_number(resp) != pack_count: return False
    # device acks each chunk with the count still outstanding, down to 0
    offset = 0
    remaining = pack_count
    while remaining:
      chunk = data[offset:offset + self.pack_size]
      ack = self.exec(chunk)
      if self._parse_pack_number(ack) != remaining - 1: return False
      offset += self.pack_size
      remaining -= 1
    return True

  def mbb_load(self) -> bytes|None:
    """
    Load the entire content of the active MBB.

    Each `mbb load <limit> <offset>` reply is exactly `limit` raw bytes plus the `\\r\\n` of
    `DBG_Enter()`, so the exact count is read and the newline consumed - no size guessing.
    Replies are read off `self.serial` directly, bypassing the `address` and `crc` handling.
    """
    info = self.mbb_info()
    if info is None: return None
    used, _ = info
    if used == 0: return b""
    result = bytearray()
    offset = 0
    while offset < used:
      limit = min(self.pack_size, used - offset)
      cmd = f"mbb load {limit} {offset}"
      if self.console_mode: cmd += "\n"
      self.send(cmd)
      if self.strip_echo:
        self.serial.read_until(b"\n")
      chunk = self.serial.read(limit)
      if len(chunk) != limit:
        self.print_error(f"mbb_load short read off={offset} {len(chunk)}/{limit}")
        return None
      self.print(f"{c.SALMON}{bytes(chunk)}{c.END}")
      result.extend(chunk)
      self.serial.read(2) # DBG_Enter() trailing \r\n
      offset += limit
    return bytes(result)

  def mbb_load_str(self, strict:bool=True) -> str|None:
    """Load active MBB as utf-8 string. `strict=False` drops non-ASCII bytes."""
    data = self.mbb_load()
    if data is None: return None
    return self.bytes_to_string(data, strict=strict)

  @classmethod
  def _parse_pack_number(cls, text:str|None) -> int|None:
    """Extract the pack counter from a response like `pack: 5`."""
    if not text: return None
    match = cls.RE_PACK_NBR.search(text)
    return int(match.group(1)) if match else None

  #-------------------------------------------------------------------------------------------- RTC

  def get_time(self) -> datetime|None:
    """Read device RTC datetime. `None` when the RTC is unset or the reply unparsable."""
    resp = self.exec("rtc")
    if not resp: return None
    match = self.RE_DATETIME.search(resp)
    if match: return datetime.strptime(match.group(), "%Y-%m-%d %H:%M:%S")
    return None

  def set_time(self, utc:bool|None=None):
    """Set device RTC to the current host time. `utc=None` follows `self.time_utc`."""
    use_utc = utc if utc is not None else self.time_utc
    now = datetime.now(timezone.utc) if use_utc else datetime.now()
    self.exec(f"rtc {now.strftime('%Y-%m-%d %H:%M:%S')}")

  #------------------------------------------------------------------------------------------- Trig

  def trig(self, code:int):
    """Wake device handlers blocked on `TRIG_Wait`/`TRIG_WaitFor` with this `code`."""
    self.exec(f"trig {code}")

  #------------------------------------------------------------------------------------------ Power

  def reboot(self):
    """Issue `pwr reboot` to device."""
    self.exec("pwr reboot")

  def reset(self):
    """Issue `pwr reset` to device."""
    self.exec("pwr reset")

  def sleep(self, mode:str="stop"):
    """Put device to sleep: `stop`, `stop0`, `stop1`, `standby`, `standbysram`, `shutdown`."""
    self.exec(f"pwr sleep {mode}")