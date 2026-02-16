# Python Style

## Format

- **95** chars max, **2** spaces indent
- Single blank lines only, no double
- No blank after class docstring
- File names: `snake_case.py`, async variants: `files_async.py`

## Imports

```python
# Compact stdlib
import os, sys, re, json, shutil
from typing import Any, Sequence
from dataclasses import dataclass

# Third-party (one per line or grouped)
from reportlab.lib.units import mm

# Local
from .xstring import replace_start, ensure_suffix
from .colors import Color, Ico
```

Lazy imports for optional dependencies:

```python
try:
  import pytz
  from tzlocal import get_localzone
except ImportError:
  raise ImportError("Install with: pip install xaeian[time]")
```

## Spacing

```python
if x:     # YES
if(x):    # NO
if (x):   # NO
d["key"]  # YES
```

## Type Hints

```python
# Tight single-line
def get(key:str, default:int=0) -> int:

# Spaced multi-line
def connect(
  host: str,
  port: int = 5432,
) -> Connection:

# Use | not Union
def load(path:str) -> dict|None:
```

### Custom type aliases for complex signatures

```py
TimeInput = Union[str, int, float, datetime, timedelta, "Time"]
PdfSettings = Literal["/screen", "/ebook", "/printer", "/prepress", "/default"]
```

## Style

```python
# One-liner guards
if not data: return None
if err: raise ValueError("msg")
if not path: return ""

# Double quotes, f-strings
name = "value"
f"Hello {name}"

# Trailing comma in multi-line (args, dicts, lists, __all__)
config = {
  "host": "localhost",
  "port": 8080,
}

__all__ = [
  "FILE", "DIR", "JSON",
  "logger", "Color",
]
```

## Naming

```py
snake_case   # variables, functions, modules
PascalCase   # classes
UPPER_CASE   # constants, namespace classes (FILE, DIR, JSON, CSV)
_prefix      # private helpers
freq_Hz      # unit suffix
```

## Namespace Classes

Static-only utility classes — no `__init__`, no instances:

```python
class FILE:
  """File read/write operations."""

  @staticmethod
  def load(path:str, binary:bool=False) -> str|bytes:
    ...

  @staticmethod
  def save(path:str, content:str|bytes) -> None:
    ...
```

## Separators

```python
# 95 chars total: # + dashes + space + Name
#-------------------------------------------------------------------------------------- Section
  #------------------------------------------------------------------------------------- Nested
```

## Module Docstring

First thing in file, brief + usage:

```python
"""
Colored logging with file rotation.

Provides `logger()` factory for creating loggers with
colored console output and rotating file handlers.

Example:
  >>> from xaeian import logger
  >>> log = logger("app", file="app.log")
  >>> log.info("Server started")
"""
```

## Docstrings

```python
class Foo:
  """Short description."""
  
  def __init__(self):
    pass

def bar(x:int) -> int:
  """Short one-liner."""
  return x + 1

def connect(host:str, port:int=5432) -> Connection:
  """
  Long description.

  Args:
    host: Server hostname.
    port: Server port.

  Returns:
    Active connection object.

  Example:
    >>> conn = connect("localhost", 5432)
  """
  pass
```

## Exports

Public API via `__all__` in `__init__.py`:

```python
__all__ = [
  "FILE", "DIR", "PATH", "JSON", "CSV",
  "Color", "Ico", "logger",
]
```

## Error handling

### `raise` — broken environment, can't continue

```python
# Missing critical dependency at runtime
raise RuntimeError("Ghostscript not found")

# Corrupted state, violated invariant
raise ValueError(f"Unknown database type: {type}")
```

### `None` — lookup miss, normal absence

```python
# No file, no program, no match — caller decides
def version(cmd:str) -> str|None:
def which(*cmds:str) -> str|None:
data = JSON.load("missing", otherwise={})
```

### `log` — long-running services, soft degradation

```python
# DB, servers — crash is worse than degradation
db.strict = False  # default: log + return False
db.strict = True   # migrations/init: raise DatabaseError
```

### Idempotent operations — silent

```python
# ensure, remove, makedirs — no error if already done
DIR.ensure("path/to/dir")   # exists? fine. doesn't? create.
DIR.remove("old", force=True)  # gone? fine. wasn't there? fine.
```

### CLI scripts — print + exit

```python
print(f"{Ico.ERR} Clone failed: {url}")
sys.exit(1)
```