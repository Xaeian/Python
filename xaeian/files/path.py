# xaeian/files/path.py

"""Path manipulation and resolution utilities."""

import os, sys, re, fnmatch
from .config import get_context
from ..xstring import replace_start

#------------------------------------------------------------------------------- PATH namespace

class PATH:
  """
  Path manipulation and resolution utilities.

  Example:
    >>> PATH.resolve("data/file.txt")
    '/home/user/project/data/file.txt'
    >>> PATH.expand("~/data/$PROJECT")
    '/home/user/data/myproject'
  """

  @staticmethod
  def normalize(path:str) -> str:
    """Normalize path separators and redundant segments."""
    cfg = get_context()
    if cfg.posix_slash: path = path.replace("\\", "/")
    if cfg.clean:
      path = re.sub(r"/+", "/", path)
      while "/./" in path: path = path.replace("/./", "/")
    return path

  @staticmethod
  def expand(path:str) -> str:
    """
    Expand `~`, `~user` and environment variables `$VAR`, `${VAR}`.

    Example:
      >>> PATH.expand("~/data/$PROJECT")
      '/home/user/data/myproject'
    """
    path = os.path.expanduser(path)
    path = os.path.expandvars(path)
    return PATH.normalize(path)

  @staticmethod
  def resolve(path:str, read:bool=True) -> str:
    """
    Resolve path to absolute using current config.

    Expands `~` and `$VAR`, then resolves relative paths
    against `root_path`.
    """
    cfg = get_context()
    path = PATH.expand(path)
    if os.path.isabs(path):
      return PATH.normalize(os.path.normpath(path))
    if read and cfg.bundle and hasattr(sys, "_MEIPASS"):
      meipass = PATH.normalize(getattr(sys, "_MEIPASS"))
      root = PATH.normalize(cfg.root_path) if cfg.root_path else ""
      if root and root.startswith(meipass):
        base = root
      else:
        base = meipass
    else:
      if not cfg.auto_resolve: return PATH.normalize(path)
      base = cfg.root_path
    path = replace_start(path, "./", "")
    full = os.path.normpath(os.path.join(base, path))
    return PATH.normalize(full)

  @staticmethod
  def rel(path:str, base:str|None=None) -> str:
    """
    Return path relative to base (or `root_path`).

    Args:
      path: Target path.
      base: Reference directory. Defaults to `root_path`.

    Returns:
      Relative path string, or absolute if on different drive.

    Example:
      >>> PATH.rel("/home/user/project/src/main.py")
      'src/main.py'
    """
    cfg = get_context()
    abs_path = PATH.resolve(path)
    abs_base = PATH.resolve(base) if base else cfg.root_path
    try:
      rel = os.path.relpath(abs_path, abs_base)
    except ValueError:
      return PATH.normalize(abs_path)
    rel = PATH.normalize(rel)
    if rel == ".": return ""
    return rel

  @staticmethod
  def local(path:str, base:str|None=None, prefix:str="") -> str:
    """Deprecated: use `PATH.rel()`. Kept for backward compatibility."""
    cfg = get_context()
    abs_path = PATH.resolve(path)
    if base is None: base = cfg.root_path
    abs_base = PATH.resolve(base)
    try:
      rel = os.path.relpath(abs_path, abs_base)
      rel = PATH.normalize(rel)
      if not rel.startswith("../") and rel != "..":
        if rel == ".": rel = ""
        if prefix:
          sep = "" if prefix.endswith("/") else "/"
          full_prefix = prefix + sep
          if rel and rel != prefix.rstrip("/") \
              and not rel.startswith(full_prefix):
            rel = full_prefix + rel
          elif not rel:
            rel = prefix.rstrip("/")
        return rel
    except ValueError:
      pass
    return PATH.normalize(abs_path)

  @staticmethod
  def exists(path:str) -> bool:
    """Check if path exists (file or directory)."""
    return os.path.exists(PATH.resolve(path))

  @staticmethod
  def is_file(path:str) -> bool:
    """Check if path is an existing file."""
    return os.path.isfile(PATH.resolve(path))

  @staticmethod
  def is_dir(path:str) -> bool:
    """Check if path is an existing directory."""
    return os.path.isdir(PATH.resolve(path))

  @staticmethod
  def basename(path:str) -> str:
    """Return final component of path."""
    return os.path.basename(PATH.normalize(path))

  @staticmethod
  def dirname(path:str) -> str:
    """Return directory part of path."""
    return PATH.normalize(os.path.dirname(PATH.normalize(path)))

  @staticmethod
  def stem(path:str) -> str:
    """Return filename without extension."""
    name = PATH.basename(path)
    stem, _ = os.path.splitext(name)
    return stem

  @staticmethod
  def ext(path:str) -> str:
    """Return file extension including leading dot, or empty string."""
    _, ext = os.path.splitext(PATH.basename(path))
    return ext

  @staticmethod
  def with_suffix(path:str, suffix:str) -> str:
    """Replace file extension with given suffix (include dot)."""
    root, _ = os.path.splitext(PATH.normalize(path))
    return root + suffix

  @staticmethod
  def ensure_suffix(path:str, suffix:str) -> str:
    """Ensure path has given suffix as extension."""
    if not suffix: return PATH.normalize(path)
    path = PATH.normalize(path)
    _, ext = os.path.splitext(path)
    if ext == suffix: return path
    return path + suffix

  @staticmethod
  def is_under(path:str, base:str|None=None) -> bool:
    """Check if path is inside given base directory."""
    cfg = get_context()
    abs_path = PATH.resolve(path)
    if base is None: base = cfg.root_path
    abs_base = PATH.resolve(base)
    try:
      rel = os.path.relpath(abs_path, abs_base)
    except ValueError:
      return False
    rel = PATH.normalize(rel)
    return rel != ".." and not rel.startswith("../")

  @staticmethod
  def join(*parts:str, read:bool=True) -> str:
    """Join path parts and resolve."""
    if not parts: raise ValueError("PATH.join requires at least one part")
    return PATH.resolve(os.path.join(*parts), read=read)

  @staticmethod
  def match(path:str, pattern:str) -> bool:
    """
    Simple pattern matching for filenames.

    Supports `*` (any chars) and `?` (single char).
    Matches against basename only.

    Example:
      >>> PATH.match("src/main.py", "*.py")
      True
    """
    return fnmatch.fnmatch(PATH.basename(path), pattern)