# xaeian/files.py

"""
File operations with context-based path resolution.

Provides namespace classes for common file operations:
- `PATH` — path manipulation and resolution
- `DIR` — directory operations (create, remove, list, zip)
- `FILE` — file read/write/append
- `INI` — INI config files
- `CSV` — CSV data files
- `JSON` — JSON data files

Global configuration via `set_context()` and context manager `files_context()`.

Example:
  >>> from xaeian.files import FILE, JSON, set_context
  >>> set_context(root_path="data")
  >>> FILE.save("log.txt", "hello")
  >>> config = JSON.load("config")  # reads data/config.json
"""

import os, sys, re, stat, shutil
import zipfile, csv, json
from typing import Any, Sequence
from dataclasses import dataclass, replace
from contextlib import contextmanager
from contextvars import ContextVar
from .xstring import replace_start, ensure_suffix

#---------------------------------------------------------------------------------- Core config

def _default_root_path() -> str:
  if getattr(sys, "frozen", False): return os.path.dirname(sys.executable)
  return os.getcwd()

@dataclass
class Config:
  """
  Global path and IO configuration.

  Attributes:
    bundle: Use PyInstaller bundle (`_MEIPASS`) when available.
    root_path: Base directory for resolving relative paths.
    auto_resolve: Join relative paths with `root_path` when `True`.
    posix_slash: Normalize backslashes to `"/"` when `True`.
    clean: Collapse `"//"` and `"/./"` segments when `True`.
    encoding: Default text encoding for file operations.
  """
  bundle: bool = False
  root_path: str|None = None
  auto_resolve: bool = True
  posix_slash: bool = True
  clean: bool = True
  encoding: str = "utf-8"

  def __post_init__(self):
    if self.root_path is None: self.root_path = _default_root_path()

_context: ContextVar[Config] = ContextVar("xaeian_files_config", default=Config())

def get_context() -> Config:
  """
  Get current configuration for this context/thread.

  Returns:
    Current `Config` instance.

  Example:
    >>> cfg = get_context()
    >>> cfg.root_path
    '/home/user/project'
  """
  return _context.get()

def set_context(
  *,
  bundle: bool|None = None,
  root_path: str|None = None,
  auto_resolve: bool|None = None,
  posix_slash: bool|None = None,
  clean: bool|None = None,
  encoding: str|None = None,
) -> Config:
  """
  Update configuration for this context/thread.

  Only provided arguments are updated; others remain unchanged.

  Args:
    bundle: Enable/disable PyInstaller bundle mode.
    root_path: Base directory for relative path resolution.
    auto_resolve: Join relative paths with `root_path` when `True`.
    posix_slash: Normalize backslashes to `"/"` when `True`.
    clean: Collapse redundant path separators when `True`.
    encoding: Default encoding for text file operations.

  Returns:
    Updated `Config` instance.

  Example:
    >>> set_context(root_path="data", encoding="utf-8")
    >>> set_context(auto_resolve=False)
  """
  cfg = get_context()
  updates: dict[str, Any] = {}
  if bundle is not None: updates["bundle"] = bundle
  if root_path is not None: updates["root_path"] = root_path
  if auto_resolve is not None: updates["auto_resolve"] = auto_resolve
  if posix_slash is not None: updates["posix_slash"] = posix_slash
  if clean is not None: updates["clean"] = clean
  if encoding is not None: updates["encoding"] = encoding
  if updates:
    new_cfg = replace(cfg, **updates)
    if new_cfg.root_path is None: new_cfg = replace(new_cfg, root_path=_default_root_path())
    _context.set(new_cfg)
    return new_cfg
  return cfg

@contextmanager
def files_context(**overrides: Any):
  """
  Temporarily override configuration within a block.

  Configuration is restored when exiting the context manager,
  even if an exception occurs.

  Args:
    **overrides: Config attributes to override (same as `set_context()`).

  Yields:
    Temporary `Config` instance.

  Example:
    >>> with files_context(root_path="/tmp", bundle=True):
    ...   FILE.save("test.txt", "temporary")
    >>> # original config restored here
  """
  cfg = get_context()
  if overrides:
    new_cfg = replace(cfg, **overrides)
    if new_cfg.root_path is None: new_cfg = replace(new_cfg, root_path=_default_root_path())
  else:
    new_cfg = cfg
  token = _context.set(new_cfg)
  try:
    yield new_cfg
  finally:
    _context.reset(token)

#--------------------------------------------------------------------------------- Path helpers

class PATH:
  """
  Path manipulation and resolution utilities.

  All methods are static. Uses current `Config` for resolution.

  Example:
    >>> PATH.resolve("data/file.txt")
    '/home/user/project/data/file.txt'
    >>> PATH.basename("/path/to/file.txt")
    'file.txt'
    >>> PATH.stem("/path/to/file.txt")
    'file'
  """

  @staticmethod
  def normalize(path:str) -> str:
    """
    Normalize path separators and redundant segments.

    Converts backslashes to forward slashes (if `posix_slash=True`)
    and collapses `"//"` and `"/./"` segments (if `clean=True`).

    Args:
      path: Path string to normalize.

    Returns:
      Normalized path string.

    Example:
      >>> PATH.normalize("data\\\\subdir//file.txt")
      'data/subdir/file.txt'
    """
    cfg = get_context()
    if cfg.posix_slash: path = path.replace("\\", "/")
    if cfg.clean:
      path = re.sub(r"/+", "/", path)
      while "/./" in path: path = path.replace("/./", "/")
    return path

  @staticmethod
  def resolve(path:str, read:bool=True) -> str:
    """
    Resolve path to absolute using current config.

    Absolute paths are normalized and returned as-is.
    Relative paths are joined with `root_path` (or `_MEIPASS` in bundle mode).

    Args:
      path: Path to resolve (relative or absolute).
      read: When `True` and bundle mode enabled, resolve from `_MEIPASS`.

    Returns:
      Resolved absolute path.

    Example:
      >>> set_context(root_path="/home/user")
      >>> PATH.resolve("data/file.txt")
      '/home/user/data/file.txt'
      >>> PATH.resolve("/absolute/path")
      '/absolute/path'
    """
    cfg = get_context()
    if os.path.isabs(path): return PATH.normalize(os.path.normpath(path))
    if read and cfg.bundle and hasattr(sys, "_MEIPASS"):
      base = getattr(sys, "_MEIPASS")
    else:
      if not cfg.auto_resolve: return PATH.normalize(path)
      base = cfg.root_path
    path = replace_start(path, "./", "")
    full = os.path.normpath(os.path.join(base, path))
    return PATH.normalize(full)

  @staticmethod
  def local(path:str, base:str|None=None, prefix:str="") -> str:
    """Convert absolute path to path relative to given base (or root_path)."""
    cfg = get_context()
    abs_path = os.path.abspath(path)
    if base is None: base = cfg.root_path
    abs_base = os.path.abspath(base)
    try:
      rel = os.path.relpath(abs_path, abs_base)
      rel = PATH.normalize(rel)
      if not rel.startswith(".."):
        if prefix and not rel.startswith(prefix + "/") and not rel.startswith(prefix):
          rel = prefix + rel
        return rel
    except ValueError:
      pass
    return PATH.normalize(abs_path)

  @staticmethod
  def basename(path:str) -> str:
    """Return normalized final component of path."""
    path = PATH.normalize(path)
    return os.path.basename(path)

  @staticmethod
  def dirname(path:str) -> str:
    """Return normalized directory part of path."""
    path = PATH.normalize(path)
    return PATH.normalize(os.path.dirname(path))

  @staticmethod
  def stem(path:str) -> str:
    """Return filename without extension."""
    name = PATH.basename(path)
    stem, _ = os.path.splitext(name)
    return stem

  @staticmethod
  def ext(path:str) -> str:
    """Return file extension including leading dot, or empty string."""
    name = PATH.basename(path)
    _, ext = os.path.splitext(name)
    return ext

  @staticmethod
  def with_suffix(path:str, suffix:str) -> str:
    """Replace file extension with given suffix (suffix should include dot)."""
    path = PATH.normalize(path)
    root, _ = os.path.splitext(path)
    return root + suffix

  @staticmethod
  def ensure_suffix(path:str, suffix:str) -> str:
    """Ensure path has given suffix as extension (suffix with leading dot)."""
    if not suffix: return PATH.normalize(path)
    path = PATH.normalize(path)
    root, ext = os.path.splitext(path)
    if ext == suffix: return path
    return root + suffix

  @staticmethod
  def is_under(path:str, base:str|None=None) -> bool:
    """Check if path is inside given base directory (or root_path)."""
    cfg = get_context()
    abs_path = os.path.abspath(path)
    if base is None: base = cfg.root_path
    abs_base = os.path.abspath(base)
    try:
      rel = os.path.relpath(abs_path, abs_base)
    except ValueError:
      return False
    rel = PATH.normalize(rel)
    return not rel.startswith("..")

  @staticmethod
  def join(*parts:str, read:bool=False) -> str:
    """
    Join path parts and resolve using current config.
    By default treats result as write-target (read=False).
    """
    if not parts: raise ValueError("PATH.join requires at least one part")
    raw = os.path.join(*parts)
    return PATH.resolve(raw, read=read)

#-------------------------------------------------------------------------------- DIR namespace

class DIR:
  """
  Directory operations.

  All methods are static. Paths are resolved using current `Config`.

  Example:
    >>> DIR.ensure("data/subdir/")
    >>> DIR.file_list("data", exts=[".txt", ".log"])
    ['data/file1.txt', 'data/file2.log']
    >>> DIR.zip("data", "archive.zip")
  """

  @staticmethod
  def ensure(path:str) -> None:
    """
    Create directory if it doesn't exist.

    Detects file paths (containing `.`) and creates parent directory.

    Args:
      path: Directory path, or file path (creates parent).

    Example:
      >>> DIR.ensure("data/subdir/")
      >>> DIR.ensure("data/config.json")  # creates data/
    """
    if "." in os.path.basename(path): path = os.path.dirname(path)
    if path: os.makedirs(path, exist_ok=True)

  @staticmethod
  def remove(path:str, force:bool=False):
    """
    Recursively remove directory tree.

    Args:
      path: Directory path to remove.
      force: Clear read-only attributes before deletion.

    Raises:
      FileNotFoundError: Directory does not exist.
      OSError: Filesystem error during removal.
    """
    path = PATH.resolve(path, read=False)
    if not os.path.isdir(path): raise FileNotFoundError(f"Directory not found: {path}")
    def on_error(func, fpath, exc):
      if force:
        os.chmod(fpath, stat.S_IWRITE)
        func(fpath)
      else:
        raise exc
    shutil.rmtree(path, onexc=on_error)

  @staticmethod
  def remove_empty(path:str, force:bool=False):
    """
    Remove empty subdirectories under given path (and path itself if empty).

    Args:
      path: Base directory to clean.
      force: Clear read-only attributes before deletion.
    """
    path = PATH.resolve(path, read=False)
    if not os.path.isdir(path): return
    for root, dirs, _ in os.walk(path, topdown=False):
      for d in dirs:
        full = os.path.join(root, d)
        try:
          if force: os.chmod(full, stat.S_IWRITE | stat.S_IREAD | stat.S_IEXEC)
          os.rmdir(full)
        except OSError:
          pass
    try:
      if force: os.chmod(path, stat.S_IWRITE | stat.S_IREAD | stat.S_IEXEC)
      os.rmdir(path)
    except OSError:
      pass

  @staticmethod
  def move(src:str, dst:str):
    """
    Move file or directory. Works across filesystems.

    Args:
      src: Source path.
      dst: Destination path.

    Raises:
      FileNotFoundError: Source does not exist.
      OSError: Filesystem error during move.
    """
    src = PATH.resolve(src, read=False)
    dst = PATH.resolve(dst, read=False)
    if not os.path.exists(src): raise FileNotFoundError(f"Source not found: {src}")
    dst_dir = os.path.dirname(dst)
    if dst_dir and not os.path.exists(dst_dir): os.makedirs(dst_dir, exist_ok=True)
    shutil.move(src, dst)

  @staticmethod
  def copy(src:str, dst:str):
    """
    Copy file or directory tree.

    Args:
      src: Source path.
      dst: Destination path.

    Raises:
      FileNotFoundError: Source does not exist.
      OSError: Filesystem error during copy.
    """
    src = PATH.resolve(src, read=False)
    dst = PATH.resolve(dst, read=False)
    if not os.path.exists(src): raise FileNotFoundError(f"Source not found: {src}")
    if os.path.isdir(src):
      shutil.copytree(src, dst, dirs_exist_ok=True)
    else:
      dst_dir = os.path.dirname(dst)
      if dst_dir and not os.path.exists(dst_dir): os.makedirs(dst_dir, exist_ok=True)
      shutil.copy2(src, dst)

  @staticmethod
  def folder_list(path:str, deep:bool=False, basename:bool=False) -> list[str]:
    """
    List subdirectories under given path.

    Args:
      path: Base directory to scan.
      deep: Walk recursively when True.
      basename: Return only last component when True.

    Returns:
      List of directory paths (or names) under given path.
    """
    path = PATH.resolve(path, read=True)
    folders: list[str] = []
    if not os.path.isdir(path): return []
    if deep:
      for root, dirs, _ in os.walk(path):
        for d in dirs:
          folders.append(d if basename else PATH.normalize(os.path.join(root, d)))
    else:
      for name in os.listdir(path):
        full = os.path.join(path, name)
        if os.path.isdir(full): folders.append(name if basename else PATH.normalize(full))
    return folders

  @staticmethod
  def file_list(
    path: str,
    exts: list[str]|None = None,
    blacklist: list[str]|None = None,
    basename: bool = False,
  ) -> list[str]:
    """
    List files under directory with optional extension filter and blacklist.

    Args:
      path: Base directory to scan.
      exts: Optional list of extensions to include (case-insensitive).
      blacklist: Optional list of directory paths (relative to path) to skip.
      basename: Return only filename when True.

    Returns:
      List of file paths (or names) under given path.
    """
    path = PATH.resolve(path, read=True)
    result: list[str] = []
    bl = [path + "/" + b for b in (blacklist or [])]
    ext_tuple = tuple(ext.lower() for ext in (exts or []))
    for root, _, filelist in os.walk(path):
      root_norm = PATH.normalize(root)
      if any(root_norm.startswith(b) for b in bl): continue
      for name in filelist:
        if not ext_tuple or name.lower().endswith(ext_tuple):
          result.append(name if basename else root_norm + "/" + name)
    return result

  @staticmethod
  def zip(path:str, zip_output:str|None=None) -> str:
    """
    Create ZIP archive from a directory.

    Args:
      path: Source directory path.
      zip_output: Optional output archive path. If None, archive is
        created as "<folder>.zip" under current root_path.

    Returns:
      Final ZIP archive path.
    """
    src = PATH.resolve(path, read=True)
    if not os.path.isdir(src): raise NotADirectoryError(f"Directory not found: {src}")
    if zip_output is None:
      folder_name = PATH.basename(src) or "archive"
      zip_output = folder_name + ".zip"
    else:
      zip_output = ensure_suffix(zip_output, ".zip")
    zip_output = PATH.resolve(zip_output, read=False)
    out_dir = os.path.dirname(zip_output)
    if out_dir and not os.path.exists(out_dir): os.makedirs(out_dir, exist_ok=True)
    out_abs = os.path.abspath(zip_output)
    with zipfile.ZipFile(zip_output, "w", zipfile.ZIP_DEFLATED) as zipf:
      for root, _, files in os.walk(src):
        for file in files:
          full_path = os.path.join(root, file)
          if os.path.abspath(full_path) == out_abs: continue
          rel_path = os.path.relpath(full_path, src)
          zipf.write(full_path, rel_path)
    return PATH.normalize(zip_output)

#------------------------------------------------------------------------------- FILE namespace

class FILE:
  """
  File read/write operations.

  All methods are static. Paths are resolved using current `Config`.
  Parent directories are created automatically on write.

  Example:
    >>> FILE.save("data/log.txt", "Hello!")
    >>> content = FILE.load("data/log.txt")
    >>> FILE.append("data/log.txt", "\\nWorld!")
  """

  @staticmethod
  def exists(path:str|Sequence[str]) -> bool:
    """
    Check if file(s) exist.

    Args:
      path: Single path or sequence of paths.

    Returns:
      `True` if all files exist, `False` if any is missing.

    Example:
      >>> FILE.exists("config.json")
      True
      >>> FILE.exists(["a.txt", "b.txt"])
      False
    """
    if isinstance(path, str): path = [path]
    for p in path:
      p = PATH.resolve(p, read=True)
      if not os.path.isfile(p): return False
    return True

  @staticmethod
  def remove(path:str|Sequence[str]) -> bool:
    """
    Remove file(s) if they exist.

    Args:
      path: Single path or sequence of paths.

    Returns:
      `True` if all files were removed, `False` if any didn't exist.

    Raises:
      OSError: On filesystem errors during removal.

    Example:
      >>> FILE.remove("temp.txt")
      True
      >>> FILE.remove(["a.txt", "b.txt"])
    """
    if isinstance(path, str): path = [path]
    success = True
    for p in path:
      p = PATH.resolve(p, read=False)
      if os.path.exists(p): os.remove(p)
      else: success = False
    return success

  @staticmethod
  def load(path:str, binary:bool=False) -> str|bytes:
    """
    Load entire file content.

    Args:
      path: File path to read.
      binary: When `True` returns `bytes`, otherwise `str`.

    Returns:
      File content as `str` (text mode) or `bytes` (binary mode).

    Raises:
      FileNotFoundError: When file doesn't exist.
      OSError: On filesystem errors.
      UnicodeDecodeError: On encoding errors (text mode).

    Example:
      >>> FILE.load("config.txt")
      'key=value'
      >>> FILE.load("data.bin", binary=True)
      b'\\x00\\x01\\x02'
    """
    cfg = get_context()
    path = PATH.resolve(path, read=True)
    mode = "rb" if binary else "r"
    encoding = None if binary else cfg.encoding
    with open(path, mode, encoding=encoding) as file:
      return file.read()

  @staticmethod
  def load_lines(path:str) -> list[str]:
    """
    Load text file as list of lines.

    Raises:
      OSError / FileNotFoundError / UnicodeError on error.
    """
    cfg = get_context()
    path = PATH.resolve(path, read=True)
    with open(path, "r", encoding=cfg.encoding) as file:
      return file.readlines()

  @staticmethod
  def save(path:str, content:str|bytes):
    """
    Save whole content to file (overwrite).
    Creates parent directories when needed.

    Raises:
      OSError / UnicodeError on error.
    """
    cfg = get_context()
    path = PATH.resolve(path, read=False)
    dst_dir = os.path.dirname(path)
    if dst_dir and not os.path.exists(dst_dir): os.makedirs(dst_dir, exist_ok=True)
    mode = "wb" if isinstance(content, bytes) else "w"
    encoding = None if mode == "wb" else cfg.encoding
    with open(path, mode, encoding=encoding) as file:
      file.write(content)

  @staticmethod
  def save_lines(path:str, lines:list[str]):
    """
    Save list of lines to text file.
    Lines are written as provided; include newline characters where needed.

    Raises:
      OSError / UnicodeError on error.
    """
    FILE.save(path, "".join(lines))

  @staticmethod
  def append(path:str, content:str|bytes):
    """
    Append raw content to file, creating it if needed.

    Raises:
      OSError / UnicodeError on error.
    """
    cfg = get_context()
    path = PATH.resolve(path, read=False)
    dst_dir = os.path.dirname(path)
    if dst_dir and not os.path.exists(dst_dir): os.makedirs(dst_dir, exist_ok=True)
    mode = "ab" if isinstance(content, bytes) else "a"
    encoding = None if mode == "ab" else cfg.encoding
    with open(path, mode, encoding=encoding) as file:
      file.write(content)

  @staticmethod
  def append_line(path:str, line:str, newline:str="\n"):
    """
    Append single text line to file, adding newline automatically.

    Raises:
      OSError / UnicodeError on error.
    """
    FILE.append(path, line + newline)

#-------------------------------------------------------------------------------- INI namespace

class INI:
  """
  INI configuration file operations.

  Supports sections, automatic type conversion, and comments.
  Extension `".ini"` is added automatically if missing.

  Example:
    >>> INI.save("config", {"debug": True, "server": {"port": 8080}})
    >>> config = INI.load("config")
    >>> config["server"]["port"]
    8080
  """

  @staticmethod
  def format(value:Any) -> str:
    """
    Convert Python value to INI-safe string.

    Args:
      value: Value to format (`None`, `bool`, `int`, `float`, `str`).

    Returns:
      INI-formatted string representation.

    Raises:
      ValueError: For unsupported types.

    Example:
      >>> INI.format(True)
      'true'
      >>> INI.format("hello world")
      '"hello world"'
      >>> INI.format(3.14)
      '3.14'
    """
    if value is None: return ""
    if isinstance(value, bool): return "true" if value else "false"
    if isinstance(value, int): return str(value)
    if isinstance(value, float): return repr(value)
    if isinstance(value, str):
      s = value.replace("\\", r"\\").replace('"', r'\"')
      return f'"{s}"'
    raise ValueError(f"Unsupported value type: {type(value).__name__}")

  @staticmethod
  def parse(text:str) -> Any:
    """
    Parse INI value string to Python type.

    Inverse of `format()`. Handles quoted strings, booleans,
    integers (including `0x`, `0b`, `0o` prefixes), and floats.

    Args:
      text: Raw value string from INI file.

    Returns:
      Converted value: `None`, `bool`, `int`, `float`, or `str`.

    Example:
      >>> INI.parse("123")
      123
      >>> INI.parse("true")
      True
      >>> INI.parse('"hello"')
      'hello'
      >>> INI.parse("0xFF")
      255
    """
    if not text: return None
    text = text.strip()
    if not text: return None
    # Quoted string
    if text[0] in "\"'":
      quote = text[0]
      end = text.find(quote, 1)
      inner = text[1:end] if end > 0 else text[1:]
      return inner.replace(r'\"', '"').replace(r"\\", "\\")
    # Bool
    low = text.lower()
    if low == "true": return True
    if low == "false": return False
    # Int (supports 0x, 0b, 0o prefixes)
    if not text.startswith("+"):
      try: return int(text, base=0)
      except ValueError: pass
    # Float
    try: return float(text)
    except ValueError: pass
    # Plain string
    return text

  @staticmethod
  def load(path:str) -> dict:
    """
    Load an INI file into a nested dict.

    Args:
      path: INI file path; ".ini" is added if missing.

    Returns:
      Dict with top-level keys and sections as nested dicts,
      for example `{key: value}` and `{section: {key: value}}`.
      If the file is missing, returns an empty `{}`. Values are
      automatically converted to `bool`/`int`/`float` when possible;
      otherwise they remain as `str`.
    """
    cfg = get_context()
    path = ensure_suffix(path, ".ini")
    path = PATH.resolve(path, read=True)
    if not os.path.exists(path): return {}
    with open(path, "r", encoding=cfg.encoding) as file:
      lines = file.readlines()
    ini: dict[str, Any] = {}
    section: str|None = None
    for raw in lines:
      line = raw.strip()
      if not line or line[0] in ";#": continue
      if line.startswith("[") and "]" in line:
        section = line[1:line.index("]")].strip()
        ini[section] = {}
        continue
      if "=" not in line: continue
      key, _, rest = line.partition("=")
      key = key.strip()
      rest = rest.strip()
      value: Any = None
      if rest:
        if rest[0] in "\"'":
          quote = rest[0]
          end = rest.find(quote, 1)
          value = rest[1:end] if end > 0 else rest[1:]
        else:
          for i, ch in enumerate(rest):
            if ch in ";#":
              rest = rest[:i].rstrip()
              break
          if rest:
            low = rest.lower()
            if low == "true": value = True
            elif low == "false": value = False
            elif not rest.startswith("+"):
              try: value = int(rest, base=0)
              except ValueError:
                try: value = float(rest)
                except ValueError: value = rest
            else:
              value = rest
      if section is not None: ini[section][key] = value
      else: ini[key] = value
    return ini

  @staticmethod
  def save_raw(path:str, data:dict) -> None:
    """
    Save a dict to an INI file without comments.

    Args:
      path: INI file path; ".ini" is added if missing.
      data: Mapping of keys and sections to write. Top-level keys are
        written as `key = value`, section dicts as `[section]` blocks.
    """
    cfg = get_context()
    path = ensure_suffix(path, ".ini")
    path = PATH.resolve(path, read=False)
    dst_dir = os.path.dirname(path)
    if dst_dir and not os.path.exists(dst_dir): os.makedirs(dst_dir, exist_ok=True)
    with open(path, "w", encoding=cfg.encoding) as f:
      for key, value in data.items():
        if isinstance(value, dict):
          f.write(f"[{key}]\n")
          for sub_key, sub_value in value.items():
            f.write(f"{sub_key} = {INI.format(sub_value)}\n")
        else:
          f.write(f"{key} = {INI.format(value)}\n")

  @staticmethod
  def save(
    path: str,
    data: dict,
    comment_section: dict|None = None,
    comment_field: dict|None = None,
    comment_section_char: str = "# ",
    comment_field_char: str = " # ",
  ) -> None:
    """
    Save a dict to an INI file with optional comments.

    Args:
      path: INI file path; ".ini" is added if missing.
      data: Mapping of top-level keys and sections. Top-level fields are
        written as `key = value`, sections as `[section]` with inner keys.
        Values may be plain (`value`) or tuples `(value, comment)` for
        inline comments.
      comment_section: Optional mapping `{section: text}` for section
        comments written above the `[section]` header.
      comment_field: Optional mapping for inline field comments:
        `{None: {key: text}, section: {key: text}}`.
      comment_section_char: Prefix used for standalone comment lines.
      comment_field_char: Separator inserted before inline comments.
    """
    cfg = get_context()
    path = ensure_suffix(path, ".ini")
    path = PATH.resolve(path, read=False)
    dst_dir = os.path.dirname(path)
    if dst_dir and not os.path.exists(dst_dir): os.makedirs(dst_dir, exist_ok=True)
    comment_section = comment_section or {}
    comment_field = comment_field or {}

    def write_comment_lines(f, text:str):
      if not text: return
      for line in str(text).splitlines():
        line = line.strip()
        if not line: continue
        f.write(f"{comment_section_char}{line}\n")

    with open(path, "w", encoding=cfg.encoding) as file:
      wrote_anything = False
      top_field_comments = comment_field.get(None, {}) or {}
      for key, value in list(data.items()):
        if isinstance(value, dict): continue
        inline_comment = None
        val = value
        if isinstance(value, tuple) and len(value) == 2:
          val, inline_comment = value
        if key in top_field_comments:
          inline_comment = top_field_comments[key]
        line = f"{key} = {INI.format(val)}"
        if inline_comment: line += f"{comment_field_char}{inline_comment}"
        file.write(line + "\n")
        wrote_anything = True
      for section, content in data.items():
        if not isinstance(content, dict): continue
        if wrote_anything: file.write("\n")
        write_comment_lines(file, comment_section.get(section, ""))
        file.write(f"[{section}]\n")
        section_comment_map = comment_field.get(section, {}) or {}
        for key, value in content.items():
          inline_comment = None
          val = value
          if isinstance(value, tuple) and len(value) == 2:
            val, inline_comment = value
          if key in section_comment_map:
            inline_comment = section_comment_map[key]
          line = f"{key} = {INI.format(val)}"
          if inline_comment: line += f"{comment_field_char}{inline_comment}"
          file.write(line + "\n")
        wrote_anything = True

#-------------------------------------------------------------------------------- CSV namespace

class CSV:
  """
  CSV file operations.

  Supports reading/writing with automatic type conversion.
  Extension `".csv"` is added automatically if missing.

  Example:
    >>> CSV.save("data", [{"name": "Alice", "age": 30}])
    >>> rows = CSV.load("data")
    >>> rows[0]["name"]
    'Alice'
  """

  @staticmethod
  def load(
    path: str,
    delimiter: str = ",",
    types: dict[str, type]|None = None,
  ) -> list[dict[str, Any]]:
    """
    Load CSV file as list of dicts.

    First row is used as header (column names).

    Args:
      path: CSV file path (`".csv"` added if missing).
      delimiter: Column separator character.
      types: Optional `{column: type}` for value casting.

    Returns:
      List of row dicts. Empty `[]` if file doesn't exist.

    Example:
      >>> CSV.load("users")
      [{'name': 'Alice', 'age': '30'}, {'name': 'Bob', 'age': '25'}]
      >>> CSV.load("users", types={"age": int})
      [{'name': 'Alice', 'age': 30}, {'name': 'Bob', 'age': 25}]
    """
    cfg = get_context()
    path = ensure_suffix(path, ".csv")
    path = PATH.resolve(path, read=True)
    if not os.path.exists(path): return []
    rows: list[dict[str, Any]] = []
    with open(path, "r", encoding=cfg.encoding, newline="") as file:
      reader = csv.DictReader(file, delimiter=delimiter)
      for row in reader:
        if types:
          for col, ctype in types.items():
            if col in row and row[col] not in (None, ""):
              try:
                if ctype is int: row[col] = ctype(row[col], base=0)
                else: row[col] = ctype(row[col])
              except (ValueError, TypeError):
                row[col] = None
        rows.append(row)
    return rows

  @staticmethod
  def load_raw(
    path: str,
    delimiter: str = ",",
    types: dict[str, type]|None = None,
    include_header: bool = True,
  ) -> list[list[Any]]:
    """
    Load CSV file as list of lists.

    Args:
      path: CSV file path; ".csv" is added if missing.
      delimiter: Column separator.
      types: Optional mapping {column_name: type} for casting.
      include_header: When False, header row is stripped.

    Returns:
      List of rows (each row is a list). Empty list if file does not exist.
    """
    cfg = get_context()
    path = ensure_suffix(path, ".csv")
    path = PATH.resolve(path, read=True)
    if not os.path.exists(path): return []
    with open(path, "r", encoding=cfg.encoding, newline="") as file:
      reader = csv.reader(file, delimiter=delimiter)
      rows: list[list[Any]] = [r for r in reader]
    if not rows: return []
    if types:
      header = rows[0]
      idx_map: dict[int, type] = {
        i: types[name] for i, name in enumerate(header) if name in types
      }
      for r in rows[1:]:
        for i, ctype in idx_map.items():
          if i < len(r) and r[i] not in (None, ""):
            try:
              r[i] = ctype(r[i], base=0) if ctype is int else ctype(r[i])
            except (ValueError, TypeError):
              r[i] = None
    return rows if include_header else rows[1:]

  @staticmethod
  def add_row(path:str, datarow:dict[str, Any]|list[Any], delimiter:str=","):
    """
    Append single row to CSV file, creating it if needed.

    Args:
      path: CSV file path; ".csv" is added if missing.
      datarow: Row data as dict (uses keys as header) or list.
      delimiter: Column separator.
    """
    if datarow is None: raise ValueError("datarow must not be None")
    cfg = get_context()
    path = ensure_suffix(path, ".csv")
    path = PATH.resolve(path, read=False)
    dst_dir = os.path.dirname(path)
    if dst_dir and not os.path.exists(dst_dir): os.makedirs(dst_dir, exist_ok=True)
    file_exists = os.path.isfile(path)
    with open(path, "a", newline="", encoding=cfg.encoding) as csv_file:
      if isinstance(datarow, dict):
        field_names = list(datarow.keys())
        writer = csv.DictWriter(csv_file, fieldnames=field_names, delimiter=delimiter)
        if not file_exists: writer.writeheader()
        writer.writerow(datarow)
      elif isinstance(datarow, list):
        writer = csv.writer(csv_file, delimiter=delimiter)
        writer.writerow(datarow)
      else:
        raise ValueError("datarow must be a dict or list")

  @staticmethod
  def save(
    path: str,
    data: list[dict[str, Any]]|list[list[Any]],
    field_names: list[str]|None = None,
    delimiter: str = ",",
  ) -> None:
    """
    Save whole CSV file from list of dicts or list of lists.

    Args:
      path: CSV file path; ".csv" is added if missing.
      data: Rows to write. Either list of dicts or list of lists.
      field_names: Optional header list. Required for list-of-lists mode.
      delimiter: Column separator.
    """
    if not data: return
    cfg = get_context()
    path = ensure_suffix(path, ".csv")
    path = PATH.resolve(path, read=False)
    dst_dir = os.path.dirname(path)
    if dst_dir and not os.path.exists(dst_dir): os.makedirs(dst_dir, exist_ok=True)
    with open(path, "w", newline="", encoding=cfg.encoding) as csv_file:
      if all(isinstance(row, dict) for row in data):
        field_names = field_names or list(data[0].keys())
        writer = csv.DictWriter(csv_file, fieldnames=field_names, delimiter=delimiter)
        writer.writeheader()
        writer.writerows(data)
      elif all(isinstance(row, list) for row in data):
        if not field_names:
          raise ValueError("field_names must be provided when saving list rows")
        writer = csv.writer(csv_file, delimiter=delimiter)
        writer.writerow(field_names)
        writer.writerows(data)
      else:
        raise ValueError("data must be a list of dicts or a list of lists")

  @staticmethod
  def save_vectors(
    path: str,
    *columns: list[Any],
    header: list[str]|None = None,
    delimiter: str = ",",
  ) -> None:
    """
    Save multiple equal-length vectors as CSV columns.

    Args:
      path: Output CSV file path; ".csv" is added if missing.
      *columns: Column vectors (lists) of equal length.
      header: Optional header row; must match number of columns.
      delimiter: Column separator.
    """
    if not columns: raise ValueError("No data vectors provided")
    vector_lengths = {len(col) for col in columns}
    if len(vector_lengths) > 1: raise ValueError("All data vectors must have the same length")
    if header and len(header) != len(columns):
      raise ValueError("Header length must match number of vectors")
    cfg = get_context()
    path = ensure_suffix(path, ".csv")
    path = PATH.resolve(path, read=False)
    dst_dir = os.path.dirname(path)
    if dst_dir and not os.path.exists(dst_dir): os.makedirs(dst_dir, exist_ok=True)
    with open(path, "w", newline="", encoding=cfg.encoding) as file:
      writer = csv.writer(file, delimiter=delimiter)
      if header: writer.writerow(header)
      for values in zip(*columns): writer.writerow(values)

#------------------------------------------------------------------------------- JSON namespace

class JSON:
  """
  JSON file operations.

  Supports compact, pretty, and smart formatting modes.
  Extension `".json"` is added automatically if missing.

  Example:
    >>> JSON.save("config", {"debug": True, "port": 8080})
    >>> JSON.load("config")
    {'debug': True, 'port': 8080}
    >>> JSON.save_pretty("config", {"a": 1}, indent=2)
  """

  @staticmethod
  def load(path:str, otherwise:Any=None) -> Any:
    """
    Load JSON file.

    Args:
      path: File path (`".json"` added if missing).
      otherwise: Fallback value when file missing or empty.

    Returns:
      Parsed JSON (`dict`, `list`, etc.) or `otherwise`.

    Raises:
      json.JSONDecodeError: On invalid JSON syntax.
      OSError: On filesystem errors.

    Example:
      >>> JSON.load("config")
      {'debug': True, 'port': 8080}
      >>> JSON.load("missing", otherwise={})
      {}
    """
    cfg = get_context()
    path = ensure_suffix(path, ".json")
    path = PATH.resolve(path, read=True)
    if not os.path.isfile(path): return otherwise
    with open(path, "r", encoding=cfg.encoding) as file:
      content = file.read()
    if not content: return otherwise
    return json.loads(content)

  @staticmethod
  def save(path:str, content:Any) -> None:
    """
    Save JSON to file in compact form.

    No extra whitespace, smallest file size.

    Args:
      path: File path (`".json"` added if missing).
      content: Any JSON-serializable value.

    Example:
      >>> JSON.save("data", {"a": 1, "b": [1, 2, 3]})
      # writes: {"a":1,"b":[1,2,3]}
    """
    cfg = get_context()
    path = ensure_suffix(path, ".json")
    path = PATH.resolve(path, read=False)
    dst_dir = os.path.dirname(path)
    if dst_dir and not os.path.exists(dst_dir): os.makedirs(dst_dir, exist_ok=True)
    with open(path, "w", encoding=cfg.encoding) as file:
      json.dump(content, file, separators=(",", ":"))

  @staticmethod
  def save_pretty(path:str, content:Any, indent:int=2, sort_keys:bool=False) -> None:
    """
    Save JSON to file in standard pretty-printed form.
    Always expands objects/arrays to multiple lines (diff-friendly).

    Args:
      path: JSON file path; ".json" is added if missing.
      content: Any JSON-serializable value.
      indent: Indentation size (spaces).
      sort_keys: Sort dict keys for stable output.

    Example:
      >>> data = {"b": 2, "a": {"x": 1, "y": 2}, "arr": [1, 2, 3]}
      >>> JSON.save_pretty("out.json", data, indent=2, sort_keys=True)
    """
    cfg = get_context()
    path = ensure_suffix(path, ".json")
    path = PATH.resolve(path, read=False)
    dst_dir = os.path.dirname(path)
    if dst_dir and not os.path.exists(dst_dir): os.makedirs(dst_dir, exist_ok=True)
    with open(path, "w", encoding=cfg.encoding, newline="\n") as file:
      json.dump(content, file, indent=indent, ensure_ascii=False, sort_keys=sort_keys)
      file.write("\n")

  def smart(obj, indent:int=2, max_line:int=100, array_wrap:int=10):
    def is_primitive(v):
      return v is None or isinstance(v, (bool, int, float, str))
    def is_numeric_array(v):
      return isinstance(v, list) and all(isinstance(x, (int, float)) for x in v)
    def is_2d_numeric(v):
      return isinstance(v, list) and all(is_numeric_array(row) for row in v)
    def compact(v):
      return json.dumps(v, separators=(',', ':'))
    def fits_line(v):
      return len(compact(v)) <= max_line

    def format_numeric_array(arr, depth):
      """Standard numeric array — newline after ["""
      if len(arr) <= array_wrap and fits_line(arr): return json.dumps(arr)
      pad = ' ' * (depth * indent)
      pad_inner = ' ' * ((depth + 1) * indent)
      chunks = [arr[i:i+array_wrap] for i in range(0, len(arr), array_wrap)]
      lines = [json.dumps(chunk)[1:-1] for chunk in chunks]
      return '[\n' + pad_inner + (',\n' + pad_inner).join(lines) + '\n' + pad + ']'

    def format_numeric_row(arr, base_indent):
      """Row of 2D array — [ x, y, z ] with spaces for multiline."""
      if fits_line(arr): return json.dumps(arr)
      chunks = [arr[i:i+array_wrap] for i in range(0, len(arr), array_wrap)]
      lines = []
      for i, chunk in enumerate(chunks):
        line = json.dumps(chunk)[1:-1]
        if i == 0: lines.append('[ ' + line + ',')
        elif i == len(chunks) - 1: lines.append(' ' + line + ' ]')
        else: lines.append(' ' + line + ',')
      return ('\n' + base_indent).join(lines)

    def format_2d_numeric(arr, depth):
      pad = ' ' * (depth * indent)
      pad_inner = ' ' * ((depth + 1) * indent)
      rows = [format_numeric_row(row, pad_inner) for row in arr]
      return '[\n' + pad_inner + (',\n' + pad_inner).join(rows) + '\n' + pad + ']'

    def fmt(v, depth=0):
      pad = ' ' * (depth * indent)
      pad_inner = ' ' * ((depth + 1) * indent)
      if is_primitive(v): return json.dumps(v)
      if is_2d_numeric(v): return format_2d_numeric(v, depth)
      if is_numeric_array(v): return format_numeric_array(v, depth)
      if isinstance(v, list):
        if not v: return '[]'
        if fits_line(v): return json.dumps(v)
        items = [fmt(x, depth + 1) for x in v]
        return '[\n' + pad_inner + (',\n' + pad_inner).join(items) + '\n' + pad + ']'
      if isinstance(v, dict):
        if not v: return '{}'
        if fits_line(v): return json.dumps(v)
        items = []
        for key, val in v.items():
          formatted_val = fmt(val, depth + 1)
          items.append(f'{json.dumps(key)}: {formatted_val}')
        return '{\n' + pad_inner + (',\n' + pad_inner).join(items) + '\n' + pad + '}'
      return json.dumps(v)

    return fmt(obj)

  @staticmethod
  def save_smart(path:str, content:Any, max_line:int=100, array_wrap:int=10) -> None:
    """
    Save JSON to file with smart formatting.
    Small objects/arrays stay inline, large ones are split. Numeric arrays
    are grouped into rows of `array_wrap` elements for readability.

    Args:
      path: JSON file path; ".json" is added if missing.
      content: Any JSON-serializable value.
      max_line: Max character length for inline objects/arrays.
      array_wrap: Max numbers per line in numeric arrays.

    Example:
      >>> data = {
      ...   "name": "sensor",
      ...   "values": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 11.0, 12.0]
      ... }
      >>> JSON.save_smart("output.json", data, array_wrap=5)
    """
    cfg = get_context()
    path = ensure_suffix(path, ".json")
    path = PATH.resolve(path, read=False)
    dst_dir = os.path.dirname(path)
    if dst_dir and not os.path.exists(dst_dir): os.makedirs(dst_dir, exist_ok=True)
    with open(path, "w", encoding=cfg.encoding) as file:
      file.write(JSON.smart(content, max_line=max_line, array_wrap=array_wrap))

#---------------------------------------------------------------------------------------- Tests

if __name__ == "__main__":
  import tempfile
  with tempfile.TemporaryDirectory() as tmp:
    set_context(root_path=tmp)
    FILE.save("test.txt", "Hello!")
    print("load:", FILE.load("test.txt"))
    FILE.append("test.txt", " World!")
    print("append:", FILE.load("test.txt"))
    print()
    JSON.save("cfg", {"debug": True, "port": 8080})
    print("json:", JSON.load("cfg"))
    print()
    CSV.save("data", [{"a": 1, "b": 2}, {"a": 3, "b": 4}])
    print("csv:", CSV.load("data", types={"a": int, "b": int}))
    print()
    INI.save("settings", {"main": {"key": "value", "num": 42}})
    print("ini:", INI.load("settings"))
    print()
    DIR.ensure("sub/dir/")
    FILE.save("sub/f1.txt", "1")
    FILE.save("sub/f2.txt", "2")
    print("files:", DIR.file_list("sub", exts=[".txt"], basename=True))
    print()
    p = "data/sub/file.txt"
    print("basename:", PATH.basename(p))
    print("dirname:", PATH.dirname(p))
    print("stem:", PATH.stem(p))
    print("ext:", PATH.ext(p))