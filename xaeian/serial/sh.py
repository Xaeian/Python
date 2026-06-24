# xaeian/serial/sh.py

"""
Python client for embedded Shell (`lib/sh` C firmware).

Sends text commands and parses responses, stripping the device's echo prefix
(`>> command^E\\r\\n`) and trailing whitespace. ANSI color escapes from the
device prompt are dropped automatically.

Wraps standard built-ins from `cmd.h`:
  - basic: `ping`, `uid`
  - mbb: `list`, `select`, `info`, `active`, `clear`, `save`, `load`, `copy`, `print`
  - rtc: `get_time`, `set_time`
  - trig: `trig(code)`
  - power: `reboot`, `reset`, `sleep(mode)`

For non-standard commands or device-specific extensions use `exec()` directly:

  >>> sh.exec("alarm 1 set everyday 06:00:00")
  >>> sh.exec("addr set 0x42")

Example:
  >>> from xaeian.serial import Shell
  >>> with Shell("/dev/ttyUSB0") as sh:
  ...   if sh.ping():
  ...     sh.set_time()
  ...     sh.mbb_select("config")
  ...     data = sh.mbb_load_str()
"""

__extras__ = ("serial", ["pyserial"])

import re, time
from datetime import datetime, timezone
from typing import Callable
from .port import SerialPort
from ..colors import Color as c

#-------------------------------------------------------------------------------------- Helpers

def convert_value(value:str|None):
  """
  Convert response token to Python type. Falls through to `str` if no match.

  Returns:
    `None` for empty/`null`, `bool` for `true`/`false`, `int`, `float`,
    or original `str`.
  """
  if not value or value.lower() == "null": return None
  lower = value.lower()
  if lower == "true": return True
  if lower == "false": return False
  try: return int(value)
  except ValueError:
    try: return float(value)
    except ValueError: return value

#------------------------------------------------------------------------------------------- Shell

class Shell(SerialPort):
  """
  Client for devices running the embedded Shell shell.

  The device echoes input with a `>> ` prompt and `^E` marker before newline.
  `strip_echo=True` drops that echoed line so callers see just the response.

  Args:
    console_mode: Auto-append `\\n` to commands (matches device `console_mode`).
    strip_echo: Drop echoed `>> command^E\\r\\n` line from response.
    pack_size: Chunk size in bytes for MBB binary transfers.
    print_limit: Max chars printed per response line.
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
    self._mbb_list:list[str]|None = None  # cached, refreshed on demand
    super().__init__(port, baudrate, timeout, buffer_size,
      print_console, print_file, time_disp, time_utc, time_format,
      address, print_limit, crc, debug)

  #--------------------------------------------------------------------------------------- Exec

  def exec(
    self,
    command:str|bytes,
    timeout_ms:int|None = None,
    retries:int = 0,
    retry_delay_ms:int = 100,
    validator:Callable[[str], bool]|None = None,
  ) -> str|None:
    """
    Send command, read response, return as stripped string.

    Retries on validator failure or exception. Per-call `timeout_ms` overrides
    the port's default read timeout for this exec only (restored after).

    Args:
      command: Command string. `\\n` auto-appended in `console_mode`.
      timeout_ms: One-shot read timeout override in milliseconds.
      retries: Retry count on validator failure or exception.
      retry_delay_ms: Delay between retries.
      validator: `Callable(response) → bool`. `False` triggers retry.

    Returns:
      Response string (echo stripped, whitespace trimmed) or `None` on failure.
    """
    original_timeout = self.serial.timeout if self.serial else self.timeout
    attempts = retries + 1
    while attempts:
      attempts -= 1
      if timeout_ms is not None and self.serial:
        self.serial.timeout = timeout_ms / 1000  # pyserial wants seconds
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
      if validator and resp is not None and not validator(resp):
        if not attempts: return None
        time.sleep(retry_delay_ms / 1000)
        continue
      return resp
    return None

  def _exec_once(self, command:str|bytes) -> str|None:
    """Single send/read cycle. Internal; called by `exec` inside retry loop."""
    if self.console_mode and isinstance(command, str) and not command.endswith("\n"):
      command += "\n"
    self.send(command)
    resp = self.read(print_conv2str=True, remove_ansi=True)
    if resp is None: return None
    text = resp.decode("utf-8", errors="ignore") if isinstance(resp, bytes) else resp
    if self.strip_echo:
      # device echoes ">> cmd^E\r\n" before response - cut first line
      nl = text.find("\n")
      if nl >= 0: text = text[nl + 1:]
      else: text = ""
    return text.strip()

  def _exec_bytes(self, command:str, timeout_ms:int|None=None) -> bytes|None:
    """
    Send text command, read raw bytes response. No ANSI strip, no decode.
    Used by MBB binary load for chunks - the response is binary file content.
    """
    if self.console_mode and not command.endswith("\n"): command += "\n"
    original_timeout = self.serial.timeout if self.serial else self.timeout
    if timeout_ms is not None and self.serial:
      self.serial.timeout = timeout_ms / 1000
    self.send(command)
    resp = self.read()  # raw bytes, no decode/strip
    if timeout_ms is not None and self.serial:
      self.serial.timeout = original_timeout
    if resp is None: return None
    if self.strip_echo:
      nl = resp.find(b"\n")
      if nl >= 0: resp = resp[nl + 1:]
    return resp

  #-------------------------------------------------------------------------------------- Basic

  def ping(self, retries:int = 3, retry_delay_ms:int = 500) -> bool:
    """Check device liveness. Returns `True` if response contains `pong`."""
    resp = self.exec(
      "ping",
      retries = retries,
      retry_delay_ms = retry_delay_ms,
      validator = lambda r: "pong" in r.lower(),
    )
    return resp is not None

  def uid(self) -> bytes|None:
    """Get device UID (12 bytes / 24 hex chars), or `None` on parse failure."""
    resp = self.exec("uid")
    if not resp: return None
    match = self.RE_UID.search(resp)
    if match: return bytes.fromhex(match.group())
    return None

  #---------------------------------------------------------------------------------------- MBB

  def mbb_list(self, refresh:bool = False) -> list[str]:
    """Get list of registered MBB names. Cached - pass `refresh=True` to reload."""
    if refresh or self._mbb_list is None:
      resp = self.exec("mbb list")
      match = self.RE_MBB_LIST.search(resp or "")
      self._mbb_list = match.group(1).strip().split() if match else []
    return self._mbb_list

  def mbb_select(self, name:str) -> bool:
    """Select MBB for subsequent operations. Returns `True` if confirmed."""
    if name not in self.mbb_list(): return False
    resp = self.exec(f"mbb select {name}")
    return bool(resp and "selected" in resp.lower())

  def mbb_active(self) -> str|None:
    """Get name of currently active MBB."""
    resp = self.exec("mbb active")
    if not resp: return None
    # response format depends on firmware; typically just the name on a line
    tokens = resp.strip().split()
    return tokens[-1] if tokens else None

  def mbb_info(self) -> tuple[int, int]|None:
    """Get `(used, total)` byte counts of active MBB, or `None` on parse fail."""
    resp = self.exec("mbb info")
    if not resp: return None
    # response may have prefix like "mbb info:" or just "name 123/2048 ..."
    match = self.RE_MBB_SIZE.search(resp)
    if match: return int(match.group(1)), int(match.group(2))
    return None

  def mbb_clear(self) -> bool:
    """Clear active MBB content. Returns `True` on success."""
    resp = self.exec("mbb clear")
    return bool(resp and "ok" in resp.lower() or "clear" in (resp or "").lower())

  def mbb_print(self) -> str|None:
    """Print active MBB metadata via device (name, size/limit, flash, mutex)."""
    return self.exec("mbb print")

  def mbb_copy(self, src:str, dst:str) -> bool:
    """Copy content `src` MBB → `dst` MBB. Returns `True` on success."""
    resp = self.exec(f"mbb copy from {src} to {dst}")
    return bool(resp and ("ok" in resp.lower() or "copied" in resp.lower()))

  def mbb_save(self, data:str|bytes, append:bool = False) -> bool:
    """
    Save data to active MBB. Chunks data via `pack_size`, ack per chunk.

    Args:
      data: Content to write. `str` is utf-8 encoded.
      append: `True` to append to existing content, `False` to overwrite.
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
    # initial cmd announces how many packs incoming, device responds "pack: N"
    resp = self.exec(f"mbb {action} {pack_count}")
    if self._parse_pack_number(resp) != pack_count: return False
    # send each chunk, device acks with decreasing pack count down to 0
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
    Load entire content of active MBB as bytes.

    Each `mbb load <limit> <offset>` chunk is deterministic: device sends
    exactly `limit` raw bytes followed by `\\r\\n` from `DBG_Enter()`. Read
    the exact byte count requested, then consume the trailing newline.
    No buffer-size guessing.
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
      self.serial.read(2)  # DBG_Enter() trailing \r\n
      offset += limit
    return bytes(result)

  def mbb_load_str(self, strict:bool = True) -> str|None:
    """Load active MBB as utf-8 string. `strict=False` drops non-ASCII bytes."""
    data = self.mbb_load()
    if data is None: return None
    return self.bytes_to_string(data, strict=strict)

  @classmethod
  def _parse_pack_number(cls, text:str|None) -> int|None:
    """Extract pack counter from response like `pack: 5`. Returns int or `None`."""
    if not text: return None
    match = cls.RE_PACK_NBR.search(text)
    return int(match.group(1)) if match else None

  #---------------------------------------------------------------------------------------- RTC

  def get_time(self) -> datetime|None:
    """Read device RTC datetime. Returns `None` if RTC unset or parse failed."""
    resp = self.exec("rtc")
    if not resp: return None
    match = self.RE_DATETIME.search(resp)
    if match: return datetime.strptime(match.group(), "%Y-%m-%d %H:%M:%S")
    return None

  def set_time(self, utc:bool|None = None):
    """
    Set device RTC to current host time.

    Args:
      utc: `True` for UTC, `False` for local. `None` uses `self.time_utc`.
    """
    use_utc = utc if utc is not None else self.time_utc
    now = datetime.now(timezone.utc) if use_utc else datetime.now()
    self.exec(f"rtc {now.strftime('%Y-%m-%d %H:%M:%S')}")

  #--------------------------------------------------------------------------------------- Trig

  def trig(self, code:int):
    """
    Send trigger event to device.

    Device-side handlers waiting via `TRIG_Wait`/`TRIG_WaitFor` are woken up
    with this `code`. Used for cooperative scheduling / async wakeup signals.
    """
    self.exec(f"trig {code}")

  #-------------------------------------------------------------------------------------- Power

  def reboot(self):
    """Issue `pwr reboot` to device."""
    self.exec("pwr reboot")

  def reset(self):
    """Issue `pwr reset` to device."""
    self.exec("pwr reset")

  def sleep(self, mode:str = "stop"):
    """
    Put device to sleep.

    Args:
      mode: `stop`, `stop0`, `stop1`, `standby`, `standbysram`, or `shutdown`.
    """
    self.exec(f"pwr sleep {mode}")