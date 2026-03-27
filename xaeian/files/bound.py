# xaeian/files/bound.py

"""Bound namespace proxy and object-oriented `Files` wrapper."""

from typing import Callable
from functools import wraps
from .config import Config, _context
from .path import PATH
from .dir import DIR
from .file import FILE
from .ini import INI
from .csv import CSV
from .json import JSON

try:
  from .yaml import YAML
except ImportError:
  YAML = None

#------------------------------------------------------------------------ Files (bound context)

_NAMESPACE_CLASSES = (PATH, DIR, FILE, INI, CSV, JSON)
if YAML is not None:
  _NAMESPACE_CLASSES = _NAMESPACE_CLASSES + (YAML,)

class _BoundNamespace:
  """Proxy that runs namespace methods under a specific `Config`."""

  def __init__(self, cls, cfg:Config):
    self._cls = cls
    self._cfg = cfg
    self._cache: dict[str, Callable] = {}

  def __getattr__(self, name:str):
    cached = self._cache.get(name)
    if cached is not None: return cached
    method = getattr(self._cls, name)
    if not callable(method): return method
    @wraps(method)
    def wrapper(*args, **kwargs):
      token = _context.set(self._cfg)
      try:
        return method(*args, **kwargs)
      finally:
        _context.reset(token)
    self._cache[name] = wrapper
    return wrapper

class Files:
  """
  Object-oriented access to file operations with own config context.

  Example:
    >>> fs = Files(root_path="/data/project")
    >>> fs.FILE.load("test.txt")       # resolves against /data/project
    >>> fs.JSON.save("cfg", {"a": 1})  # same context
  """

  def __init__(self, root_path:str|None=None, **kwargs):
    cfg = Config(root_path=root_path, **kwargs)
    self.PATH = _BoundNamespace(PATH, cfg)
    self.DIR = _BoundNamespace(DIR, cfg)
    self.FILE = _BoundNamespace(FILE, cfg)
    self.INI = _BoundNamespace(INI, cfg)
    self.CSV = _BoundNamespace(CSV, cfg)
    self.JSON = _BoundNamespace(JSON, cfg)
    if YAML is not None:
      self.YAML = _BoundNamespace(YAML, cfg)
