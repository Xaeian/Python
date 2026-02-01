# xaeian/log.py

"""
Colored logging with file rotation.

Provides `logger()` factory function for creating loggers with
colored console output and rotating file handlers.

Log levels use 3-char abbreviations: `DBG`, `INF`, `WRN`, `ERR`, `CRT`, `PNC`.

Example:
  >>> from xaeian import logger
  >>> log = logger("app", file="app.log")
  >>> log.info("Server started on port 8080")
  2025-01-15 14:32:01 INF Server started on port 8080
"""

import logging
from logging.handlers import RotatingFileHandler
import os
import sys

from .colors import Color

PANIC = 60
logging.addLevelName(PANIC, "PNC")

def _datefmt(date:bool, time:bool) -> str:
  """Build datetime format string from flags."""
  parts = []
  if date: parts.append("%Y-%m-%d")
  if time: parts.append("%H:%M:%S")
  return " ".join(parts)


def _fmt(date:bool, time:bool) -> str:
  """Build log format string from flags."""
  if date or time: return "%(asctime)s %(levelname)-3s %(message)s"
  return "%(levelname)-3s %(message)s"

#------------------------------------------------------------------------------------ Formatters

class LogFormatter(logging.Formatter):
  """Log formatter with 3-character level abbreviations."""

  LEVELS = {
    "DEBUG": "DBG",
    "INFO": "INF",
    "WARNING": "WRN",
    "ERROR": "ERR",
    "CRITICAL": "CRT",
  }

  def format(self, record:logging.LogRecord) -> str:
    """Format log record with abbreviated level name."""
    record.levelname = self.LEVELS.get(record.levelname, record.levelname)
    return super().format(record)

class ColorFormatter(LogFormatter):
  """
  Colored log formatter for terminal output.

  Applies ANSI colors to level names and timestamps.
  Colors: `DBG`=green, `INF`=blue, `WRN`=yellow, `ERR`=red,
  `CRT`=magenta, `PNC`=gold.
  """

  COLORS = {
    "DBG": Color.GREEN,
    "INF": Color.BLUE,
    "WRN": Color.YELLOW,
    "ERR": Color.RED,
    "CRT": Color.MAGENTA,
    "PNC": Color.GOLD,
  }
  def __init__(self, date:bool=True, time:bool=True):
    self.show_date = date
    self.show_time = time
    super().__init__(datefmt=_datefmt(date, time))

  def format(self, record:logging.LogRecord) -> str:
    """Format log record with colors."""
    record.levelname = self.LEVELS.get(record.levelname, record.levelname)
    lvl = record.levelname
    color = self.COLORS.get(lvl, Color.WHITE)
    text = record.getMessage()
    msg = f"{color}{lvl}{Color.END} {Color.WHITE}{text}{Color.END}"
    if self.show_date or self.show_time:
      ts = self.formatTime(record, self.datefmt)
      msg = f"{Color.GREY}{ts}{Color.END} {msg}"
    if record.exc_info: msg += f"\n{self.formatException(record.exc_info)}"
    return msg

#----------------------------------------------------------------------------------------- Logger

class Logger(logging.Logger):
  """
  Extended logger with colored output and file rotation.

  Adds `panic()` method for highest severity level.

  Example:
    >>> log = Logger("myapp")
    >>> log.set_stream(color=True)
    >>> log.set_file("myapp.log", max_bytes=1000000)
    >>> log.info("Started")
  """
  def __init__(self, name:str, level:int=logging.NOTSET):
    super().__init__(name, level)
    self._init_handlers()

  def _init_handlers(self):
    """Initialize handler tracking attributes."""
    if not hasattr(self, "_file_handler"): self._file_handler: RotatingFileHandler|None = None
    if not hasattr(self, "_stream_handler"): self._stream_handler: logging.Handler|None = None
    if not hasattr(self, "_file_path"): self._file_path: str = ""

  def panic(self, msg, *args, **kwargs):
    """Log message with PANIC level (above CRITICAL)."""
    self.log(PANIC, msg, *args, **kwargs)

  @property
  def file(self) -> str:
    """Current log file path, or empty string if disabled."""
    return self._file_path

  @file.setter
  def file(self, path:str):
    """Set log file path."""
    self.set_file(file=path)

  def set_file(
    self,
    file: str|bool|None = None,
    level: int = logging.INFO,
    date: bool = True,
    time: bool = True,
    max_bytes: int = 5_000_000,
    backup_count: int = 3,
  ) -> None:
    """
    Configure file logging with rotation.

    Args:
      file: Log file path. `True` for `"{name}.log"`. Falsy to disable.
      level: Minimum log level for file output.
      date: Include date in timestamps.
      time: Include time in timestamps.
      max_bytes: Max file size before rotation (default 5MB).
      backup_count: Number of backup files to keep.
    """
    if file is True: file = f"{self.name}.log"
    elif not file: file = ""
    if self._file_handler:
      self.removeHandler(self._file_handler)
      try: self._file_handler.close()
      except Exception: pass
      self._file_handler = None
      self._file_path = ""
    if not file: return
    d = os.path.dirname(file)
    if d: os.makedirs(d, exist_ok=True)
    fh = RotatingFileHandler(file, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8")
    fh.setLevel(level)
    fh.setFormatter(LogFormatter(_fmt(date, time), _datefmt(date, time)))
    self.addHandler(fh)
    self._file_handler = fh
    self._file_path = file

  @property
  def stream(self) -> bool:
    """Whether console output is enabled."""
    return self._stream_handler is not None

  @stream.setter
  def stream(self, enable:bool):
    """Enable/disable console output."""
    self.set_stream(enable=enable)

  def set_stream(
    self,
    enable: bool = True,
    level: int = logging.INFO,
    color: bool = True,
    date: bool = True,
    time: bool = True,
  ) -> None:
    """
    Configure console logging.

    Args:
      enable: Enable or disable console output.
      level: Minimum log level for console.
      color: Use colored output with ANSI codes.
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
    sh.setLevel(level)
    if color: sh.setFormatter(ColorFormatter(date, time))
    else: sh.setFormatter(LogFormatter(_fmt(date, time), _datefmt(date, time)))
    self.addHandler(sh)
    self._stream_handler = sh


logging.setLoggerClass(Logger)

#----------------------------------------------------------------------------------------- Factory

def logger(
  name: str = "app",
  file: str|bool|None = True,
  stream: bool = True,
  stream_lvl: int = logging.INFO,
  file_lvl: int = logging.INFO,
  color: bool = True,
  date_stream: bool = True,
  time_stream: bool = True,
  date_file: bool = True,
  time_file: bool = True,
  max_bytes: int = 5_000_000,
  backup_count: int = 3,
) -> Logger:
  """
  Create or reconfigure logger with console and file output.

  Args:
    name: Logger name. Use `"app.module"` for child loggers.
    file: Log file path. `True` for `"{name}.log"`. Falsy to disable.
    stream: Enable console output.
    stream_lvl: Minimum level for console.
    file_lvl: Minimum level for file.
    color: Use colored console output.
    date_stream: Show date in console timestamps.
    time_stream: Show time in console timestamps.
    date_file: Show date in file timestamps.
    time_file: Show time in file timestamps.
    max_bytes: Max file size before rotation (default 5MB).
    backup_count: Number of backup files to keep.

  Returns:
    Configured `Logger` instance with `panic()` method.

  Example:
    >>> log = logger("app", file="app.log")
    >>> log.info("Server started")
  """
  log: Logger = logging.getLogger(name)
  log._init_handlers()
  log.setLevel(logging.DEBUG)
  log.propagate = False
  log.set_stream(enable=stream, level=stream_lvl, color=color, date=date_stream, time=time_stream)
  log.set_file(file=file, level=file_lvl, date=date_file, time=time_file,
    max_bytes=max_bytes, backup_count=backup_count)
  return log

#---------------------------------------------------------------------------------------- Tests

if __name__ == "__main__":
  log = logger("demo", file=False, color=True)
  log.debug("debug (hidden at INFO level)")
  log.info("info message")
  log.warning("warning message")
  log.error("error message")
  log.critical("critical message")
  log.panic("panic message")
  print()
  log2 = logger("demo2", file=False, date_stream=False)
  log2.info("time only")
  log3 = logger("demo3", file=False, date_stream=False, time_stream=False)
  log3.info("no timestamp")
  print()
  log4 = logger("demo4", file=False, stream_lvl=logging.DEBUG)
  log4.debug("debug visible now")
