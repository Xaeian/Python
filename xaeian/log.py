# xaeian/log.py

"""
Colored logging with file rotation.

Provides `logger()` factory for service/daemon logging and `Print` for
CLI/script output. Both share a common interface so libraries can accept
either without branching.

Shared interface (short/long):
  `dbg/debug` `inf/info` `wrn/warning` `err/error` `crt/critical` `pnc/panic`
  `space/gap` (indent, inherits last level) `item/dot` (list entry with `-`)

Example:
  >>> log = logger("app", file="app.log")
  >>> log.error("Connection failed")
  >>> log.item("host unreachable") # logged at ERROR level
  >>> p = Print()
  >>> p.err("Connection failed")
  ERR Connection failed
  >>> p.dot("host unreachable") # printed at ERR level
    • host unreachable
"""

import sys, re, logging, builtins
from typing import Literal
from logging.handlers import RotatingFileHandler
from .colors import Color, Ico

PANIC = 60
logging.addLevelName(PANIC, "PNC")

LevelName = Literal["DBG", "INF", "WRN", "ERR", "CRT", "PNC"]
Level = LevelName | int

_LEVELS = {
  "DBG": logging.DEBUG,
  "INF": logging.INFO,
  "WRN": logging.WARNING,
  "ERR": logging.ERROR,
  "CRT": logging.CRITICAL,
  "PNC": PANIC,
}

_ANSI_RE = re.compile(r"\033\[[0-9;]*m")

def _strip_ansi(text:str) -> str:
  return _ANSI_RE.sub("", text)

def _level(v:Level) -> int:
  if isinstance(v, int): return v
  return _LEVELS[v]

def _datefmt(date:bool, time:bool) -> str:
  parts = []
  if date: parts.append("%Y-%m-%d")
  if time: parts.append("%H:%M:%S")
  return " ".join(parts)

def _fmt(date:bool, time:bool) -> str:
  if date or time: return "%(asctime)s %(levelname)-3s %(message)s"
  return "%(levelname)-3s %(message)s"

#----------------------------------------------------------------------------------- Formatters

class LogFormatter(logging.Formatter):
  """Plain formatter with 3-char level abbreviations for file output."""
  LEVELS = {
    "DEBUG": "DBG", "INFO": "INF", "WARNING": "WRN",
    "ERROR": "ERR", "CRITICAL": "CRT", "PNC": "PNC",
  }
  def format(self, record:logging.LogRecord) -> str:
    record.levelname = self.LEVELS.get(record.levelname, record.levelname)
    record.msg = _strip_ansi(str(record.msg))
    return super().format(record)

class ColorFormatter(LogFormatter):
  """Colored formatter for terminal — `DBG` green, `INF` blue, `WRN` yellow,
  `ERR` red, `CRT` magenta, `PNC` gold."""
  COLORS = {
    "DBG": Color.GREEN, "INF": Color.BLUE,   "WRN": Color.YELLOW,
    "ERR": Color.RED,   "CRT": Color.MAGNTA,  "PNC": Color.GOLD,
  }
  def __init__(self, date:bool=True, time:bool=True):
    super().__init__(fmt=_fmt(date, time), datefmt=_datefmt(date, time))

  def format(self, record:logging.LogRecord) -> str:
    record.levelname = self.LEVELS.get(record.levelname, record.levelname)
    lvl = record.levelname
    color = self.COLORS.get(lvl, Color.WHITE)
    text = record.getMessage()
    msg = f"{color}{lvl}{Color.END} {Color.WHITE}{text}{Color.END}"
    if self.datefmt:
      ts = self.formatTime(record, self.datefmt)
      msg = f"{Color.GREY}{ts}{Color.END} {msg}"
    if record.exc_info: msg += f"\n{self.formatException(record.exc_info)}"
    return msg

#---------------------------------------------------------------------------------------- Print

class Print:
  """
  Terminal logger with level filtering, compatible with `Logger` interface.

  `gap`/`dot`/`space`/`item` inherit the level of the last named call —
  suppressed if that level was below the configured minimum.

  Example:
    >>> p = Print(level="WRN")
    >>> p.info("ignored")
    >>> p.error("DB down")
    ERR DB down
    >>> p.dot("retry 1/3")              # inherits ERR, printed
      • retry 1/3
  """
  def __init__(self, file=None, level:Literal["DBG","INF","WRN","ERR","CRT","PNC"]|int="DBG"):
    self._file = file
    self._level = _level(level)
    self._last_level = logging.DEBUG

  def __call__(self, *args, **kwargs):
    if self._file and "file" not in kwargs:
      kwargs["file"] = self._file
    builtins.print(*args, **kwargs)

  def _emit(self, level:int, ico:str, *args, **kwargs):
    self._last_level = level
    if level >= self._level: self(ico, *args, **kwargs)

  def _emit_sub(self, ico:str, *args, **kwargs):
    if self._last_level >= self._level: self(ico, *args, **kwargs)

  def dbg(self, *a, **kw): self._emit(logging.DEBUG,    Ico.DBG, *a, **kw)
  def inf(self, *a, **kw): self._emit(logging.INFO,     Ico.INF, *a, **kw)
  def wrn(self, *a, **kw): self._emit(logging.WARNING,  Ico.WRN, *a, **kw)
  def err(self, *a, **kw): self._emit(logging.ERROR,    Ico.ERR, *a, **kw)
  def crt(self, *a, **kw): self._emit(logging.CRITICAL, Ico.ERR, *a, **kw)
  def pnc(self, *a, **kw): self._emit(PANIC,            Ico.ERR, *a, **kw)
  def tip(self, *a, **kw): self._emit(logging.INFO,     Ico.TIP, *a, **kw)
  def run(self, *a, **kw): self._emit(logging.INFO,     Ico.RUN, *a, **kw)

  def gap(self, *a, **kw):   self._emit_sub(Ico.GAP, *a, **kw)
  def dot(self, *a, **kw):   self._emit_sub(Ico.DOT, *a, **kw)
  def space(self, *a, **kw): self.gap(*a, **kw)   # Logger compat
  def item(self, *a, **kw):  self.dot(*a, **kw)   # Logger compat

  def ok(self, *args, **kwargs):
    """Append ` OK` badge to last arg, print at INF level."""
    suffix = f" {Ico.OK}"
    args = (*args[:-1], str(args[-1]) + suffix) if args else (suffix.lstrip(),)
    self._emit(logging.INFO, Ico.INF, *args, **kwargs)

  # long aliases — Logger compat
  def debug(self, *a, **kw):    self.dbg(*a, **kw)
  def info(self, *a, **kw):     self.inf(*a, **kw)
  def warning(self, *a, **kw):  self.wrn(*a, **kw)
  def error(self, *a, **kw):    self.err(*a, **kw)
  def critical(self, *a, **kw): self.crt(*a, **kw)
  def panic(self, *a, **kw):    self.pnc(*a, **kw)

#---------------------------------------------------------------------------------------- Logger

class Logger(logging.Logger):
  """
  Extended stdlib logger with short aliases and `space`/`item` sub-entries.

  `space`/`item`/`gap`/`dot` emit at the level of the last named call —
  useful for indented details without repeating the level explicitly.

  Example:
    >>> log = Logger("app")
    >>> log.error("Upload failed")
    >>> log.item("timeout after 30s")   # logged at ERROR
    >>> log.item("retries exhausted")   # logged at ERROR
  """
  def __init__(self, name:str, level:int=logging.NOTSET):
    super().__init__(name, level)
    self._init_handlers()

  def _init_handlers(self):
    if not hasattr(self, "_file_handler"):   self._file_handler: RotatingFileHandler|None = None
    if not hasattr(self, "_stream_handler"): self._stream_handler: logging.Handler|None = None
    if not hasattr(self, "_file_path"):      self._file_path: str = ""
    if not hasattr(self, "_last_level"):     self._last_level: int = logging.DEBUG

  # stdlib overrides — track _last_level
  def debug(self, *a, **kw):    self._last_level = logging.DEBUG;    super().debug(*a, **kw)
  def info(self, *a, **kw):     self._last_level = logging.INFO;     super().info(*a, **kw)
  def warning(self, *a, **kw):  self._last_level = logging.WARNING;  super().warning(*a, **kw)
  def error(self, *a, **kw):    self._last_level = logging.ERROR;    super().error(*a, **kw)
  def critical(self, *a, **kw): self._last_level = logging.CRITICAL; super().critical(*a, **kw)
  def panic(self, *a, **kw):    self._last_level = PANIC;            self.log(PANIC, *a, **kw)

  # short aliases — Print compat
  def dbg(self, *a, **kw): self.debug(*a, **kw)
  def inf(self, *a, **kw): self.info(*a, **kw)
  def wrn(self, *a, **kw): self.warning(*a, **kw)
  def err(self, *a, **kw): self.error(*a, **kw)
  def crt(self, *a, **kw): self.critical(*a, **kw)
  def pnc(self, *a, **kw): self.panic(*a, **kw)

  # sub-entries — inherit _last_level
  def space(self, msg="", *a, **kw): self.log(self._last_level, f"    {msg}", *a, **kw)
  def item(self, msg="", *a, **kw):  self.log(self._last_level, f" -  {msg}", *a, **kw)
  def gap(self, *a, **kw): self.space(*a, **kw)
  def dot(self, *a, **kw): self.item(*a, **kw)

  def ok(self, msg="", *a, **kw):
    self.info(f"{msg} {Ico.OK}" if msg else Ico.OK, *a, **kw)

  @property
  def file(self) -> str:
    """Current log file path, empty string if disabled."""
    return self._file_path

  @file.setter
  def file(self, path:str): self.set_file(file=path)

  def set_file(
    self,
    file: str|bool|None = None,
    level: Literal["DBG","INF","WRN","ERR","CRT","PNC"]|int = logging.INFO,
    date: bool = True,
    time: bool = True,
    max_bytes: int = 5_000_000,
    backup_count: int = 3,
  ) -> None:
    """
    Configure rotating file handler.

    Args:
      file: Path, `True` for `"{name}.log"`, falsy to disable.
      level: Minimum level written to file.
      date: Include date in timestamps.
      time: Include time in timestamps.
      max_bytes: Rotation threshold (default 5MB).
      backup_count: Number of rotated files to keep.
    """
    from .files import DIR
    if file is True: file = f"{self.name}.log"
    elif not file: file = ""
    if self._file_handler:
      self.removeHandler(self._file_handler)
      try: self._file_handler.close()
      except Exception: pass
      self._file_handler = None
      self._file_path = ""
    if not file: return
    DIR.ensure(file, is_file=True)
    fh = RotatingFileHandler(file, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8")
    fh.setLevel(_level(level))
    fh.setFormatter(LogFormatter(_fmt(date, time), _datefmt(date, time)))
    self.addHandler(fh)
    self._file_handler = fh
    self._file_path = file

  @property
  def stream(self) -> bool:
    """Whether console handler is active."""
    return self._stream_handler is not None

  @stream.setter
  def stream(self, enable:bool): self.set_stream(enable=enable)

  def set_stream(
    self,
    enable: bool = True,
    level: Literal["DBG","INF","WRN","ERR","CRT","PNC"]|int = logging.INFO,
    color: bool = True,
    date: bool = True,
    time: bool = True,
  ) -> None:
    """
    Configure console handler.

    Args:
      enable: Enable or disable console output.
      level: Minimum level printed to console.
      color: Use ANSI colors.
      date: Include date in timestamps.
      time: Include time in timestamps.
    """
    if self._stream_handler:
      self.removeHandler(self._stream_handler)
      try: self._stream_handler.close()
      except Exception: pass
      self._stream_handler = None
    if not enable: return
    sh = logging.StreamHandler(sys.stdout)
    sh.setLevel(_level(level))
    fmt = ColorFormatter(date, time) if color else LogFormatter(_fmt(date, time), _datefmt(date, time))
    sh.setFormatter(fmt)
    self.addHandler(sh)
    self._stream_handler = sh

logging.setLoggerClass(Logger)

#--------------------------------------------------------------------------------------- Factory

def logger(
  name: str = "app",
  file: str|bool|None = True,
  stream: bool = True,
  stream_lvl: Literal["DBG","INF","WRN","ERR","CRT","PNC"]|int = logging.INFO,
  file_lvl: Literal["DBG","INF","WRN","ERR","CRT","PNC"]|int = logging.INFO,
  color: bool = True,
  date_stream: bool = True,
  time_stream: bool = True,
  date_file: bool = True,
  time_file: bool = True,
  max_bytes: int = 5_000_000,
  backup_count: int = 3,
) -> Logger:
  """
  Create or reconfigure a named logger.

  Args:
    name: Logger name, use `"app.module"` for child loggers.
    file: Log file path. `True` → `"{name}.log"`, falsy → disabled.
    stream: Enable console output.
    stream_lvl: Minimum level for console.
    file_lvl: Minimum level for file.
    color: Colored console output.
    date_stream: Show date in console timestamps.
    time_stream: Show time in console timestamps.
    date_file: Show date in file timestamps.
    time_file: Show time in file timestamps.
    max_bytes: File rotation threshold (default 5MB).
    backup_count: Number of rotated files to keep.

  Returns:
    Configured `Logger` instance.
  """
  log: Logger = logging.getLogger(name)
  if not isinstance(log, Logger):
    raise TypeError(f'Logger "{name}" already exists and not from xaeian')
  log._init_handlers()
  log.setLevel(logging.DEBUG)
  log.propagate = False
  log.set_stream(enable=stream, level=_level(stream_lvl), color=color, date=date_stream, time=time_stream)
  log.set_file(
    file=file, level=_level(file_lvl), date=date_file, time=time_file,
    max_bytes=max_bytes, backup_count=backup_count,
  )
  return log

#----------------------------------------------------------------------------------------- Tests

if __name__ == "__main__":
  log = logger("demo", file=False)
  log.debug("debug"); log.info("info"); log.error("error")
  log.item("detail one"); log.item("detail two")
  log.info("back to info"); log.space("indented")
  log.warning("warning"); log.critical("critical"); log.panic("panic")

  p = Print()
  p.inf("info"); p.err("error")
  p.dot("detail one"); p.dot("detail two")
  p.inf("back to info"); p.gap("indented")
  p.wrn("warning"); p.ok("done")

  p2 = Print(level="WRN")
  p2.info("hidden"); p2.error("visible"); p2.dot("visible — inherits ERR")