# xaeian/__init__.py

"""
Xaeian - Python utilities library.

Modules:
  - `xaeian.xstring`: String manipulation utilities
  - `xaeian.files`: File/directory operations with context
  - `xaeian.table`: Tabular operations on list[dict]
  - `xaeian.crc`: CRC-8/16/32 checksums
  - `xaeian.colors`: ANSI terminal colors
  - `xaeian.log`: Colored logging with rotation
  - `xaeian.cmd`: Shell command helpers
  - `xaeian.xtime`: Datetime parsing and arithmetic
  - `xaeian.cstruct`: Binary struct serialization
  - `xaeian.serial_port`: Serial communication
  - `xaeian.cbash`: Embedded device console
  - `xaeian.sftp`: SFTP/SSH client for deployment and data collection
  - `xaeian.plot`: Fluent matplotlib wrapper
  - `xaeian.dsp`: Signal processing (filter, FFT, vibration metrics)
  - `xaeian.db`: Database abstraction (SQLite, MySQL, PostgreSQL)
  - `xaeian.media`: PDF and image compression, conversion, metadata
  - `xaeian.eda`: E-series, KiCad export, NgSpice runner
  - `xaeian.cli`: Utility scripts (tree, dupes, wifi)

Example:
  >>> from xaeian import logger, JSON, split_sql, Files, Plot
  >>> from xaeian.db import Database
"""

__version__ = "0.6.0"
__repo__ = "Xaeian/Python"
__python__ = ">=3.12"
__description__ = "Python utilities for files, strings, time, serial, structs, media, electronics, plotting, and database and more..."
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
  generate_password,
)

from .files import (
  file_context, Files,
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
  "generate_password",
  "file_context", "Files",
  "PATH", "DIR", "FILE", "INI", "CSV", "JSON",
  "CRC",
  "logger", "Logger", "Print", "Color", "Ico",
]

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
  from .serial_port import SerialPort, serial_scan
  from .cbash import CBash
  __all__ += ["SerialPort", "CBash", "serial_scan"]
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
