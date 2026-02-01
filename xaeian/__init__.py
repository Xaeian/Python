# xaeian/__init__.py

"""
Xaeian - Python utilities library.

Modules:
  - `xaeian.xstring` — String manipulation utilities
  - `xaeian.files` — File/directory operations with context
  - `xaeian.crc` — CRC-8/16/32 checksums
  - `xaeian.colors` — ANSI terminal colors
  - `xaeian.log` — Colored logging with rotation
  - `xaeian.xtime` — Datetime parsing and arithmetic
  - `xaeian.cstruct` — Binary struct serialization
  - `xaeian.serial_port` — Serial communication
  - `xaeian.cbash` — Embedded device console
  - `xaeian.db` — Database abstraction (SQLite, MySQL, PostgreSQL)

Example:
  >>> from xaeian import logger, JSON, split_sql
  >>> from xaeian.db import Database
  >>> from xaeian.xtime import Time
"""

__version__ = "0.1.0"
__repo__ = "Xaeian/Python"
__python__ = ">=3.10"
__description__ = "Python utilities for files, strings, time, serial, structs, and database"
__author__ = "Xaeian"
__keywords__ = ["utilities", "files", "database", "serial", "crc", "struct"]

from .xstring import (
  replace_start, replace_end, replace_map,
  ensure_prefix, ensure_suffix,
  split_str, split_sql,
  strip_comments, strip_comments_c,
  strip_comments_sql, strip_comments_py,
  generate_password,
)

from .files import (
  set_context as set_files_context,
  files_context,
  PATH, DIR, FILE, INI, CSV, JSON,
)

from .crc import CRC
from .colors import Color, Ico
from .log import logger

__all__ = [
  "__version__",
  "replace_start", "replace_end", "replace_map",
  "ensure_prefix", "ensure_suffix",
  "split_str", "split_sql",
  "strip_comments", "strip_comments_c",
  "strip_comments_sql", "strip_comments_py",
  "generate_password",
  "set_files_context", "files_context",
  "PATH", "DIR", "FILE", "INI", "CSV", "JSON",
  "CRC",
  "Color", "Ico", "logger",
]
