# xaeian/__init__.py

"""
Xaeian - Python utilities library.

Not re-exported here, import directly: `table` (list[dict] ops), `files_async`, `cmd`,
`cstruct` (binary structs), `net` (SFTP/FTP), `db` (SQLite, MySQL, PostgreSQL), `media` (PDF,
image), `eda` (E-series, KiCad, NgSpice), `cli` (tree, dupes, wifi, fonts).

Example:
  >>> from xaeian import logger, JSON, split_sql, Files, Plot
"""

__version__ = "0.8.1"
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
  "dsp", "signal", "filter", "fft", "vibration", "ftp", "sftp",
]
__scripts__ = {
  "xn": "xaeian.__main__:main",
}

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
from .crc import CRC
from .colors import Color, Ico
from .log import logger, Logger, Print

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
  "CRC",
  "logger", "Logger", "Print", "Color", "Ico",
]

# Extras: exported only where the optional dependency is installed
try:
  from .files import YAML
  __all__ += ["YAML"]
except Exception:
  pass

try:
  from .xtime import Time, TimeInput, time_to
  __all__ += ["Time", "TimeInput", "time_to"]
except Exception:
  pass

try:
  from .serial import (
    SerialPort, serial_scan,
    Recorder, MultiRecorder,
    Shell, convert_value,
  )
  __all__ += [
    "SerialPort", "serial_scan",
    "Recorder", "MultiRecorder",
    "Shell", "convert_value",
  ]
except Exception:
  pass

try:
  from .plot import Plot, quick
  __all__ += ["Plot", "quick"]
except Exception:
  pass

try:
  from .dsp import Signal, Spectrum
  __all__ += ["Signal", "Spectrum"]
except Exception:
  pass