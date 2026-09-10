# xaeian/__init__.py

"""
Xaeian - Python utilities library.

Not re-exported here, import the module directly:
`table` (list[dict] ops), `files_async`, `cmd`, `cstruct` (binary structs),
`net` (SFTP/FTP), `db` (SQLite, MySQL, PostgreSQL), `media` (PDF, image),
`eda` (E-series, KiCad, NgSpice), `cli` (`xn` commands).

Example:
  >>> from xaeian import logger, JSON, split_sql, Files, Plot
"""

__version__ = "0.9.2"
__repo__ = "Xaeian/Python"
__python__ = ">=3.12"
__description__ = (
  "Python utilities for files, strings, time, serial, structs, "
  "media, electronics, plotting, and database and more..."
)
__author__ = "Xaeian"
__keywords__ = [
  "utilities", "files", "database", "serial", "crc", "struct",
  "media", "kicad", "plot", "matplotlib", "ngspice", "spice",
  "dsp", "signal", "filter", "fft", "vibration", "ftp", "sftp", "s3", "r2",
]
__scripts__ = {
  "xn": "xaeian.__main__:main",
}

from importlib import import_module
from typing import Any, TYPE_CHECKING

from .xstring import (
  replace_start, replace_end, replace_map,
  ensure_prefix, ensure_suffix,
  split_str, split_sql,
  strip_comments, strip_comments_c,
  strip_comments_sql, strip_comments_py,
  generate_password, generate_token,
)

from .files import (
  file_context, set_context, get_context, Files,
  PATH, DIR, FILE, INI, CSV, JSON,
)
from .extras import MissingExtra
from .crc import CRC
from .colors import Color, Ico
from .log import logger, Logger, Print

# Name → module, loaded on first attribute access.
# An unused extra then costs nothing, and the public surface is the same whether installed or not.
# A missing extra raises `MissingExtra` there; a fault inside an installed one propagates.
_LAZY = {
  "YAML": ".files.yaml",
  "Time": ".xtime", "TimeInput": ".xtime", "time_to": ".xtime",
  "SerialPort": ".serial", "serial_scan": ".serial", "Recorder": ".serial",
  "MultiRecorder": ".serial", "Shell": ".serial", "convert_value": ".serial",
  "Plot": ".plot", "quick": ".plot",
  "Signal": ".dsp", "Spectrum": ".dsp",
}

if TYPE_CHECKING: # the same names again, so a checker and an editor see the real types
  from .files.yaml import YAML
  from .xtime import Time, TimeInput, time_to
  from .serial import SerialPort, serial_scan, Recorder, MultiRecorder, Shell, convert_value
  from .plot import Plot, quick
  from .dsp import Signal, Spectrum

__all__ = [
  "__version__",
  "replace_start", "replace_end", "replace_map",
  "ensure_prefix", "ensure_suffix",
  "split_str", "split_sql",
  "strip_comments", "strip_comments_c",
  "strip_comments_sql", "strip_comments_py",
  "generate_password", "generate_token",
  "file_context", "set_context", "get_context", "Files",
  "PATH", "DIR", "FILE", "INI", "CSV", "JSON",
  "CRC", "MissingExtra",
  "logger", "Logger", "Print", "Color", "Ico",
  *_LAZY,
]

def __getattr__(name:str) -> Any:
  module = _LAZY.get(name)
  if not module: raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
  value = getattr(import_module(module, __name__), name)
  globals()[name] = value # only the first access pays
  return value

def __dir__() -> list[str]:
  return sorted(set(globals()) | set(__all__))
