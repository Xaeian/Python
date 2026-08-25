# xaeian/files/bound.py

"""Bound namespace proxy and object-oriented `Files` wrapper."""

from typing import Any, Callable, Iterator
from functools import wraps
from inspect import isgeneratorfunction
from ..extras import MissingExtra
from .config import Config, _context
from .path import PATH
from .dir import DIR
from .file import FILE
from .ini import INI
from .csv import CSV
from .json import JSON

#---------------------------------------------------------------------------- Files (bound context)

def _bound_gen(cfg:Config, gen:Iterator):
  """Advance `gen` under `cfg`, restoring the caller's context between yields."""
  while True:
    token = _context.set(cfg)
    try: item = next(gen)
    except StopIteration: return
    finally: _context.reset(token)
    yield item

class _BoundNamespace:
  """Proxy that runs namespace methods under a specific `Config`."""
  def __init__(self, cls, cfg:Config) -> None:
    self._cls = cls
    self._cfg = cfg
    self._cache: dict[str, Callable] = {}

  def __getattr__(self, name:str) -> Any:
    cached = self._cache.get(name)
    if cached is not None: return cached
    method = getattr(self._cls, name)
    if not callable(method): return method
    generator = isgeneratorfunction(method)
    @wraps(method)
    def wrapper(*args, **kwargs) -> Any:
      token = _context.set(self._cfg)
      try:
        result = method(*args, **kwargs)
      finally:
        _context.reset(token)
      # a generator body runs only once advanced, long after this wrapper returned
      return _bound_gen(self._cfg, result) if generator else result
    self._cache[name] = wrapper
    return wrapper

class Files:
  """
  Object-oriented access to file operations with own config context.

  Extra keywords are `Config` fields. `fs.YAML` binds on first use and needs `pyyaml`.

  Example:
    >>> fs = Files(root_path="/data/project")
    >>> fs.FILE.load("test.txt") # resolves against /data/project
  """
  def __init__(self, root_path:str|None=None, **kwargs) -> None:
    cfg = Config(root_path=root_path, **kwargs)
    self.PATH = _BoundNamespace(PATH, cfg)
    self.DIR = _BoundNamespace(DIR, cfg)
    self.FILE = _BoundNamespace(FILE, cfg)
    self.INI = _BoundNamespace(INI, cfg)
    self.CSV = _BoundNamespace(CSV, cfg)
    self.JSON = _BoundNamespace(JSON, cfg)
    self._cfg = cfg

  def __getattr__(self, name:str) -> _BoundNamespace:
    """
    `YAML` binds on first use, so every install carries the same surface.

    Importing it eagerly pulls `pyyaml` into every `import xaeian`,
    and leaves `fs.YAML` present or absent depending on the machine.
    """
    if name != "YAML": raise AttributeError(name)
    from .yaml import YAML # MissingExtra when pyyaml is absent, as any other extra
    bound = _BoundNamespace(YAML, self._cfg)
    setattr(self, name, bound)
    return bound
