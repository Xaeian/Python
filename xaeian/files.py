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

Global configuration via context manager `file_context()`.
Object-oriented access via `Files(root_path=...)`.
"""

import os, sys, re, stat, shutil, hashlib, fnmatch
import zipfile, csv, json
from typing import Any, Sequence, Iterator, Callable
from dataclasses import dataclass, replace
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
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
  """Get current configuration for this context/thread."""
  return _context.get()

def set_context(**overrides) -> Config:
  """Set global file context configuration."""
  cfg = get_context()
  new_cfg = replace(cfg, **overrides)
  if new_cfg.root_path is None: new_cfg = replace(new_cfg, root_path=_default_root_path())
  _context.set(new_cfg)
  return new_cfg

@contextmanager
def file_context(**overrides: Any):
  """Temporarily override configuration within a block."""
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

#-------------------------------------------------------------------------------- PATH namespace

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
  def normalize(path: str) -> str:
    """Normalize path separators and redundant segments."""
    cfg = get_context()
    if cfg.posix_slash: path = path.replace("\\", "/")
    if cfg.clean:
      path = re.sub(r"/+", "/", path)
      while "/./" in path: path = path.replace("/./", "/")
    return path

  @staticmethod
  def expand(path: str) -> str:
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
  def resolve(path: str, read: bool = True) -> str:
    """
    Resolve path to absolute using current config.

    Expands `~` and `$VAR`, then resolves relative paths against `root_path`.
    """
    cfg = get_context()
    path = PATH.expand(path)
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
  def local(path: str, base: str|None = None, prefix: str = "") -> str:
    """Convert absolute path to path relative to given base (or root_path)."""
    cfg = get_context()
    abs_path = os.path.abspath(PATH.expand(path))
    if base is None: base = cfg.root_path
    abs_base = os.path.abspath(PATH.expand(base))
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
  def exists(path: str) -> bool:
    """Check if path exists (file or directory)."""
    return os.path.exists(PATH.expand(path))

  @staticmethod
  def is_file(path: str) -> bool:
    """Check if path is an existing file."""
    return os.path.isfile(PATH.expand(path))

  @staticmethod
  def is_dir(path: str) -> bool:
    """Check if path is an existing directory."""
    return os.path.isdir(PATH.expand(path))

  @staticmethod
  def basename(path: str) -> str:
    """Return final component of path."""
    return os.path.basename(PATH.normalize(path))

  @staticmethod
  def dirname(path: str) -> str:
    """Return directory part of path."""
    return PATH.normalize(os.path.dirname(PATH.normalize(path)))

  @staticmethod
  def stem(path: str) -> str:
    """Return filename without extension."""
    name = PATH.basename(path)
    stem, _ = os.path.splitext(name)
    return stem

  @staticmethod
  def ext(path: str) -> str:
    """Return file extension including leading dot, or empty string."""
    _, ext = os.path.splitext(PATH.basename(path))
    return ext

  @staticmethod
  def with_suffix(path: str, suffix: str) -> str:
    """Replace file extension with given suffix (include dot)."""
    root, _ = os.path.splitext(PATH.normalize(path))
    return root + suffix

  @staticmethod
  def ensure_suffix(path: str, suffix: str) -> str:
    """Ensure path has given suffix as extension."""
    if not suffix: return PATH.normalize(path)
    path = PATH.normalize(path)
    _, ext = os.path.splitext(path)
    if ext == suffix: return path
    return path + suffix

  @staticmethod
  def is_under(path: str, base: str|None = None) -> bool:
    """Check if path is inside given base directory."""
    cfg = get_context()
    abs_path = os.path.abspath(PATH.expand(path))
    if base is None: base = cfg.root_path
    abs_base = os.path.abspath(PATH.expand(base))
    try:
      rel = os.path.relpath(abs_path, abs_base)
    except ValueError:
      return False
    return not PATH.normalize(rel).startswith("..")

  @staticmethod
  def join(*parts: str, read: bool = True) -> str:
    """Join path parts and resolve."""
    if not parts: raise ValueError("PATH.join requires at least one part")
    return PATH.resolve(os.path.join(*parts), read=read)

  @staticmethod
  def match(path: str, pattern: str) -> bool:
    """
    Simple pattern matching for filenames.

    Supports `*` (any chars) and `?` (single char).
    Matches against basename only.

    Example:
      >>> PATH.match("src/main.py", "*.py")
      True
    """
    return fnmatch.fnmatch(PATH.basename(path), pattern)

#-------------------------------------------------------------------------------- DIR namespace

class DIR:
  """
  Directory operations.

  Example:
    >>> DIR.ensure("data/subdir")
    >>> DIR.file_list("data", exts=[".txt"])
    ['data/file1.txt', 'data/file2.txt']
  """

  @staticmethod
  def ensure(path: str, is_file: bool|None = None) -> str:
    """
    Create directory if it doesn't exist.

    Args:
      path: Directory or file path.
      is_file: If ``True``, create parent dir. If ``None``, auto-detect:
        path ending with ``/`` is always a directory; otherwise treated
        as a file when the last segment contains a dot (e.g. ``data.csv``).
        Extensionless names like ``Makefile`` need explicit ``is_file=True``.

    Example:
      >>> DIR.ensure("data/subdir/") # creates data/subdir/
      >>> DIR.ensure("data/config.json") # creates data/
      >>> DIR.ensure("data/Makefile", is_file=True) # creates data/
    """
    path = PATH.expand(path)
    if is_file is None:
      if path.endswith("/") or path.endswith("\\"):
        is_file = False
      else:
        is_file = bool(PATH.ext(path))
    if is_file:
      path = os.path.dirname(path)
    if path:
      os.makedirs(path, exist_ok=True)
    return PATH.normalize(path)

  @staticmethod
  def remove(path: str, force: bool = False):
    """Recursively remove directory tree."""
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
  def move(src: str, dst: str):
    """Move file or directory. Works across filesystems."""
    src, dst = PATH.resolve(src, read=False), PATH.resolve(dst, read=False)
    if not os.path.exists(src): raise FileNotFoundError(f"Source not found: {src}")
    DIR.ensure(dst, is_file=not os.path.isdir(src))
    shutil.move(src, dst)

  @staticmethod
  def copy(src: str, dst: str):
    """Copy file or directory tree."""
    src, dst = PATH.resolve(src, read=False), PATH.resolve(dst, read=False)
    if not os.path.exists(src): raise FileNotFoundError(f"Source not found: {src}")
    if os.path.isdir(src):
      shutil.copytree(src, dst, dirs_exist_ok=True)
    else:
      DIR.ensure(dst, is_file=True)
      shutil.copy2(src, dst)

  @staticmethod
  def folder_list(
    path: str,
    deep: bool = False,
    basename: bool = False,
    blacklist: list[str]|None = None,
  ) -> list[str]:
    """
    List subdirectories under given path.

    Args:
      path: Base directory to scan.
      deep: Walk recursively when True.
      basename: Return only folder name when True.
      blacklist: Folder names/paths to skip.
    """
    path = PATH.resolve(path, read=True)
    if not os.path.isdir(path): return []
    bl = set(blacklist or [])
    folders: list[str] = []
    if deep:
      for root, dirs, _ in os.walk(path):
        dirs[:] = [d for d in dirs if d not in bl]
        for d in dirs:
          full = PATH.normalize(os.path.join(root, d))
          rel = PATH.local(full, path)
          if rel not in bl:
            folders.append(d if basename else full)
    else:
      for name in os.listdir(path):
        if name in bl: continue
        full = os.path.join(path, name)
        if os.path.isdir(full):
          folders.append(name if basename else PATH.normalize(full))
    return folders

  @staticmethod
  def iter_files(
    path: str,
    exts: list[str]|None = None,
    match: str|None = None,
    blacklist: list[str]|None = None,
  ) -> Iterator[str]:
    """
    Iterate files under directory (memory efficient).

    Args:
      path: Base directory to scan.
      exts: Extensions to include (e.g. [".py", ".txt"]).
      match: Glob pattern for filename (e.g. "test_*.py").
      blacklist: Paths to skip (files or directories, relative to path).

    Yields:
      Absolute file paths.
    """
    path = PATH.resolve(path, read=True)
    if not os.path.isdir(path): return
    bl_dirs: set[str] = set()
    bl_files: set[str] = set()
    for b in (blacklist or []):
      full = path + "/" + b.rstrip("/")
      if os.path.isdir(full) or b.endswith("/"):
        bl_dirs.add(full)
      else:
        bl_files.add(b)
    ext_tuple = tuple(ext.lower() for ext in (exts or []))
    for root, dirs, files in os.walk(path):
      root_norm = PATH.normalize(root)
      dirs[:] = [d for d in dirs if root_norm + "/" + d not in bl_dirs and d not in bl_dirs]
      for name in files:
        rel = PATH.local(root_norm + "/" + name, path)
        if rel in bl_files or name in bl_files: continue
        if ext_tuple and not name.lower().endswith(ext_tuple): continue
        if match and not PATH.match(name, match): continue
        yield root_norm + "/" + name

  @staticmethod
  def file_list(
    path: str,
    exts: list[str]|None = None,
    match: str|None = None,
    blacklist: list[str]|None = None,
    basename: bool = False,
    local: bool = False,
  ) -> list[str]:
    """
    List files under directory with filters.

    Args:
      path: Base directory to scan.
      exts: Extensions to include (e.g. [".py", ".txt"]).
      match: Glob pattern for filename (e.g. "test_*.py").
      blacklist: Paths to skip (files or directories, relative to path).
      basename: Return only filename when True.
      local: Return paths relative to `path` when True.

    Example:
      >>> DIR.file_list("src", exts=[".py"], blacklist=["__pycache__", ".env"])
      ['src/main.py', 'src/utils/helper.py']
    """
    path = PATH.resolve(path, read=True)
    result: list[str] = []
    for f in DIR.iter_files(path, exts=exts, match=match, blacklist=blacklist):
      if basename:
        result.append(PATH.basename(f))
      elif local:
        result.append(PATH.local(f, path))
      else:
        result.append(f)
    return result

  @staticmethod
  def zip(path: str, zip_output: str|None = None, blacklist: list[str]|None = None) -> str:
    """
    Create ZIP archive from a directory.

    Args:
      path: Source directory path.
      zip_output: Output archive path (default: "<folder>.zip").
      blacklist: Paths to exclude from archive.

    Returns:
      Final ZIP archive path.
    """
    src = PATH.resolve(path, read=True)
    if not os.path.isdir(src): raise NotADirectoryError(f"Directory not found: {src}")
    if zip_output is None:
      folder_name = PATH.basename(src) or "archive"
      zip_output = folder_name + ".zip"
    zip_output = PATH.ensure_suffix(zip_output, ".zip")
    zip_output = PATH.resolve(zip_output, read=False)
    DIR.ensure(zip_output, is_file=True)
    out_abs = os.path.abspath(zip_output)
    with zipfile.ZipFile(zip_output, "w", zipfile.ZIP_DEFLATED) as zipf:
      for f in DIR.iter_files(src, blacklist=blacklist):
        if os.path.abspath(f) == out_abs: continue
        rel = os.path.relpath(f, src)
        zipf.write(f, rel)
    return PATH.normalize(zip_output)

#-------------------------------------------------------------------------------- FILE namespace

class FILE:
  """
  File read/write operations.

  Example:
    >>> FILE.save("data/log.txt", "Hello!")
    >>> content = FILE.load("data/log.txt")
  """

  @staticmethod
  def exists(path: str|Sequence[str]) -> bool:
    """Check if file(s) exist."""
    if isinstance(path, str): path = [path]
    for p in path:
      p = PATH.resolve(p, read=True)
      if not os.path.isfile(p): return False
    return True

  @staticmethod
  def remove(path: str|Sequence[str], missing_ok: bool = True) -> bool:
    """Remove file(s)."""
    if isinstance(path, str): path = [path]
    success = True
    for p in path:
      p = PATH.resolve(p, read=False)
      try:
        os.remove(p)
      except FileNotFoundError:
        if not missing_ok: raise
        success = False
    return success

  @staticmethod
  def load(path: str, binary: bool = False) -> str|bytes:
    """Load entire file content."""
    cfg = get_context()
    path = PATH.resolve(path, read=True)
    mode = "rb" if binary else "r"
    encoding = None if binary else cfg.encoding
    with open(path, mode, encoding=encoding) as file:
      return file.read()

  @staticmethod
  def load_lines(path: str) -> list[str]:
    """Load text file as list of lines."""
    cfg = get_context()
    path = PATH.resolve(path, read=True)
    with open(path, "r", encoding=cfg.encoding) as file:
      return file.readlines()

  @staticmethod
  def save(path: str, content: str|bytes):
    """Save whole content to file (overwrite)."""
    cfg = get_context()
    path = PATH.resolve(path, read=False)
    DIR.ensure(path, is_file=True)
    mode = "wb" if isinstance(content, bytes) else "w"
    encoding = None if mode == "wb" else cfg.encoding
    with open(path, mode, encoding=encoding) as file:
      file.write(content)

  @staticmethod
  def save_lines(path: str, lines: list[str]):
    """Save list of lines to text file."""
    FILE.save(path, "".join(lines))

  @staticmethod
  def append(path: str, content: str|bytes):
    """Append content to file, creating it if needed."""
    cfg = get_context()
    path = PATH.resolve(path, read=False)
    DIR.ensure(path, is_file=True)
    mode = "ab" if isinstance(content, bytes) else "a"
    encoding = None if mode == "ab" else cfg.encoding
    with open(path, mode, encoding=encoding) as file:
      file.write(content)

  @staticmethod
  def append_line(path: str, line: str, newline: str = "\n"):
    """Append single text line to file."""
    FILE.append(path, line + newline)

  @staticmethod
  def hash(path: str, algo: str = "sha256", chunk_size: int = 8192) -> str:
    """
    Calculate file hash.

    Args:
      path: File path.
      algo: Hash algorithm (md5, sha1, sha256, sha512).
      chunk_size: Read buffer size.

    Example:
      >>> FILE.hash("data.bin", algo="md5")
      'd41d8cd98f00b204e9800998ecf8427e'
    """
    path = PATH.resolve(path, read=True)
    h = hashlib.new(algo)
    with open(path, "rb") as f:
      while chunk := f.read(chunk_size):
        h.update(chunk)
    return h.hexdigest()

  @staticmethod
  def size(path: str) -> int:
    """Return file size in bytes."""
    return os.path.getsize(PATH.expand(path))

  @staticmethod
  def mtime(path: str) -> float:
    """Return file modification time as Unix timestamp."""
    return os.path.getmtime(PATH.expand(path))

#-------------------------------------------------------------------------------- INI namespace

class INI:
  """INI configuration file operations."""

  @staticmethod
  def format(value: Any) -> str:
    """Convert Python value to INI-safe string."""
    if value is None: return ""
    if isinstance(value, bool): return "true" if value else "false"
    if isinstance(value, int): return str(value)
    if isinstance(value, float): return repr(value)
    if isinstance(value, str):
      s = value.replace("\\", r"\\").replace('"', r'\"')
      return f'"{s}"'
    raise ValueError(f"Unsupported value type: {type(value).__name__}")

  @staticmethod
  def parse(text: str) -> Any:
    """Parse INI value string to Python type."""
    if not text: return None
    text = text.strip()
    if not text: return None
    if text[0] in "\"'":
      quote = text[0]
      end = text.find(quote, 1)
      inner = text[1:end] if end > 0 else text[1:]
      return inner.replace(r'\"', '"').replace(r"\\", "\\")
    low = text.lower()
    if low == "true": return True
    if low == "false": return False
    if not text.startswith("+"):
      try: return int(text, base=0)
      except ValueError: pass
    try: return float(text)
    except ValueError: pass
    return text

  @staticmethod
  def _strip_inline_comment(text: str) -> str:
    """Strip inline comment from unquoted INI value."""
    for i, ch in enumerate(text):
      if ch in ";#":
        return text[:i].rstrip()
    return text

  @staticmethod
  def load(path: str) -> dict:
    """Load an INI file into a nested dict."""
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
      if rest and rest[0] not in "\"'":
        rest = INI._strip_inline_comment(rest)
      value = INI.parse(rest)
      if section is not None: ini[section][key] = value
      else: ini[key] = value
    return ini

  @staticmethod
  def save(
    path: str,
    data: dict,
    comment_section: dict|None = None,
    comment_field: dict|None = None,
    comment_section_char: str = "# ",
    comment_field_char: str = " # ",
  ) -> None:
    """Save a dict to an INI file with optional comments."""
    cfg = get_context()
    path = ensure_suffix(path, ".ini")
    path = PATH.resolve(path, read=False)
    DIR.ensure(path, is_file=True)
    comment_section = comment_section or {}
    comment_field = comment_field or {}
    def write_comment_lines(f, text: str):
      if not text: return
      for line in str(text).splitlines():
        line = line.strip()
        if line: f.write(f"{comment_section_char}{line}\n")
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
  """CSV file operations."""

  @staticmethod
  def _cast(value: str, ctype: type) -> Any:
    """Cast CSV string value to target type."""
    if value in (None, ""): return None
    try:
      return ctype(value)
    except (ValueError, TypeError):
      return None

  @staticmethod
  def load(
    path: str,
    delimiter: str = ",",
    types: dict[str, type]|None = None,
  ) -> list[dict[str, Any]]:
    """Load CSV file as list of dicts."""
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
            if col in row:
              row[col] = CSV._cast(row[col], ctype)
        rows.append(row)
    return rows

  @staticmethod
  def load_raw(
    path: str,
    delimiter: str = ",",
    types: dict[str, type]|None = None,
    include_header: bool = True,
  ) -> list[list[Any]]:
    """Load CSV file as list of lists."""
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
          if i < len(r):
            r[i] = CSV._cast(r[i], ctype)
    return rows if include_header else rows[1:]

  @staticmethod
  def load_vectors(
    path: str,
    delimiter: str = ",",
    types: dict[str, type]|None = None,
    group_by: str|None = None,
  ) -> dict[str, list[Any]] | dict[Any, dict[str, list[Any]]]:
    """
    Load CSV as dict of column vectors.

    Args:
      path: CSV file path.
      types: Optional {column: type} for casting.
      group_by: Column to group by.

    Returns:
      {column: [values...]} or {group: {column: [values...]}}
    """
    rows = CSV.load(path, delimiter=delimiter, types=types)
    if not rows: return {}
    columns = list(rows[0].keys())
    if group_by is None:
      result: dict[str, list[Any]] = {col: [] for col in columns}
      for row in rows:
        for col in columns:
          result[col].append(row.get(col))
      return result
    if group_by not in columns:
      raise ValueError(f"group_by column '{group_by}' not found")
    other_cols = [c for c in columns if c != group_by]
    grouped: dict[Any, dict[str, list[Any]]] = {}
    for row in rows:
      key = row.get(group_by)
      if key not in grouped:
        grouped[key] = {col: [] for col in other_cols}
      for col in other_cols:
        grouped[key][col].append(row.get(col))
    return grouped

  @staticmethod
  def add_row(path: str, datarow: dict[str, Any]|list[Any], delimiter: str = ","):
    """Append single row to CSV file."""
    if datarow is None: raise ValueError("datarow must not be None")
    cfg = get_context()
    path = ensure_suffix(path, ".csv")
    path = PATH.resolve(path, read=False)
    DIR.ensure(path, is_file=True)
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
        raise ValueError("datarow must be dict or list")

  @staticmethod
  def save(
    path: str,
    data: list[dict[str, Any]]|list[list[Any]],
    field_names: list[str]|None = None,
    delimiter: str = ",",
  ) -> None:
    """Save whole CSV file from list of dicts or list of lists."""
    if not data: return
    cfg = get_context()
    path = ensure_suffix(path, ".csv")
    path = PATH.resolve(path, read=False)
    DIR.ensure(path, is_file=True)
    with open(path, "w", newline="", encoding=cfg.encoding) as csv_file:
      if all(isinstance(row, dict) for row in data):
        field_names = field_names or list(data[0].keys())
        writer = csv.DictWriter(csv_file, fieldnames=field_names, delimiter=delimiter)
        writer.writeheader()
        writer.writerows(data)
      elif all(isinstance(row, list) for row in data):
        if not field_names:
          raise ValueError("field_names required for list rows")
        writer = csv.writer(csv_file, delimiter=delimiter)
        writer.writerow(field_names)
        writer.writerows(data)
      else:
        raise ValueError("data must be list of dicts or list of lists")

  @staticmethod
  def save_vectors(
    path: str,
    *columns: list[Any],
    header: list[str]|None = None,
    delimiter: str = ",",
  ) -> None:
    """Save multiple equal-length vectors as CSV columns."""
    if not columns: raise ValueError("No data vectors provided")
    vector_lengths = {len(col) for col in columns}
    if len(vector_lengths) > 1: raise ValueError("All vectors must have same length")
    if header and len(header) != len(columns):
      raise ValueError("Header length must match number of vectors")
    cfg = get_context()
    path = ensure_suffix(path, ".csv")
    path = PATH.resolve(path, read=False)
    DIR.ensure(path, is_file=True)
    with open(path, "w", newline="", encoding=cfg.encoding) as file:
      writer = csv.writer(file, delimiter=delimiter)
      if header: writer.writerow(header)
      for values in zip(*columns): writer.writerow(values)

#-------------------------------------------------------------------------------- JSON namespace

class JSON:
  """JSON file operations."""

  @staticmethod
  def load(path: str, otherwise: Any = None) -> Any:
    """Load JSON file."""
    cfg = get_context()
    path = ensure_suffix(path, ".json")
    path = PATH.resolve(path, read=True)
    if not os.path.isfile(path): return otherwise
    with open(path, "r", encoding=cfg.encoding) as file:
      content = file.read()
    if not content: return otherwise
    return json.loads(content)

  @staticmethod
  def save(path: str, content: Any) -> None:
    """Save JSON to file in compact form."""
    cfg = get_context()
    path = ensure_suffix(path, ".json")
    path = PATH.resolve(path, read=False)
    DIR.ensure(path, is_file=True)
    with open(path, "w", encoding=cfg.encoding) as file:
      json.dump(content, file, separators=(",", ":"))

  @staticmethod
  def save_pretty(path: str, content: Any, indent: int = 2, sort_keys: bool = False) -> None:
    """Save JSON in pretty-printed form."""
    cfg = get_context()
    path = ensure_suffix(path, ".json")
    path = PATH.resolve(path, read=False)
    DIR.ensure(path, is_file=True)
    with open(path, "w", encoding=cfg.encoding, newline="\n") as file:
      json.dump(content, file, indent=indent, ensure_ascii=False, sort_keys=sort_keys)
      file.write("\n")

  @staticmethod
  def smart(obj, indent:int=2, max_line:int=100, array_wrap:int=10, compact_dict:bool=True) -> str:
    """Format JSON with smart inline/multiline decisions."""
    def is_primitive(v):
      return v is None or isinstance(v, (bool, int, float, str))
    def is_numeric_array(v):
      return isinstance(v, list) and v and all(isinstance(x, (int, float)) for x in v)
    def is_2d_numeric(v):
      return isinstance(v, list) and v and all(is_numeric_array(row) for row in v)
    def is_flat_dict(v):
      return isinstance(v, dict) and v and all(is_primitive(val) for val in v.values())
    def compact(v):
      return json.dumps(v, separators=(',', ':'))
    def fits_line(v):
      return len(compact(v)) <= max_line
    def format_numeric_array(arr, depth):
      if len(arr) <= array_wrap and fits_line(arr): return json.dumps(arr)
      pad = ' ' * (depth * indent)
      pad_inner = ' ' * ((depth + 1) * indent)
      chunks = [arr[i:i+array_wrap] for i in range(0, len(arr), array_wrap)]
      lines = [json.dumps(chunk)[1:-1] for chunk in chunks]
      return '[\n' + pad_inner + (',\n' + pad_inner).join(lines) + '\n' + pad + ']'
    def format_numeric_row(arr, base_indent):
      if fits_line(arr): return json.dumps(arr)
      chunks = [arr[i:i+array_wrap] for i in range(0, len(arr), array_wrap)]
      if len(chunks) == 1:
        return '[ ' + json.dumps(chunks[0])[1:-1] + ' ]'
      lines = []
      for i, chunk in enumerate(chunks):
        line = json.dumps(chunk)[1:-1]
        if i == 0: lines.append('[ ' + line + ',')
        elif i == len(chunks) - 1: lines.append('  ' + line + ' ]')
        else: lines.append('  ' + line + ',')
      return ('\n' + base_indent).join(lines)
    def format_2d_numeric(arr, depth):
      pad = ' ' * (depth * indent)
      pad_inner = ' ' * ((depth + 1) * indent)
      rows = [format_numeric_row(row, pad_inner) for row in arr]
      return '[\n' + pad_inner + (',\n' + pad_inner).join(rows) + '\n' + pad + ']'
    def format_flat_dict(d, depth):
      pad = ' ' * (depth * indent)
      pad_inner = ' ' * ((depth + 1) * indent)
      entries = [f'{json.dumps(k)}: {json.dumps(v)}' for k, v in d.items()]
      lines, current, length = [], [], 0
      for entry in entries:
        added = len(entry) + (2 if current else 0)
        if current and length + added > max_line:
          lines.append(', '.join(current))
          current, length = [entry], len(entry)
        else:
          current.append(entry)
          length += added
      if current: lines.append(', '.join(current))
      return '{\n' + pad_inner + (',\n' + pad_inner).join(lines) + '\n' + pad + '}'
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
        if compact_dict and is_flat_dict(v): return format_flat_dict(v, depth)
        items = []
        for key, val in v.items():
          formatted_val = fmt(val, depth + 1)
          items.append(f'{json.dumps(key)}: {formatted_val}')
        return '{\n' + pad_inner + (',\n' + pad_inner).join(items) + '\n' + pad + '}'
      return json.dumps(v)
    return fmt(obj)

  @staticmethod
  def save_smart(path: str, content: Any, max_line: int = 100, array_wrap: int = 10, compact_dict: bool = True) -> None:
    """Save JSON with smart formatting."""
    cfg = get_context()
    path = ensure_suffix(path, ".json")
    path = PATH.resolve(path, read=False)
    DIR.ensure(path, is_file=True)
    with open(path, "w", encoding=cfg.encoding) as file:
      file.write(JSON.smart(content, max_line=max_line, array_wrap=array_wrap, compact_dict=compact_dict))

#------------------------------------------------------------------------- Files (bound context)

_NAMESPACE_CLASSES = (PATH, DIR, FILE, INI, CSV, JSON)

class _BoundNamespace:
  """Proxy that runs namespace methods under a specific `Config`."""

  def __init__(self, cls, cfg: Config):
    self._cls = cls
    self._cfg = cfg
    self._cache: dict[str, Callable] = {}

  def __getattr__(self, name: str):
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

  def __init__(self, root_path: str|None = None, **kwargs):
    cfg = Config(root_path=root_path, **kwargs)
    self.PATH = _BoundNamespace(PATH, cfg)
    self.DIR = _BoundNamespace(DIR, cfg)
    self.FILE = _BoundNamespace(FILE, cfg)
    self.INI = _BoundNamespace(INI, cfg)
    self.CSV = _BoundNamespace(CSV, cfg)
    self.JSON = _BoundNamespace(JSON, cfg)

#---------------------------------------------------------------------------------------- Tests

if __name__ == "__main__":
  import tempfile
  with tempfile.TemporaryDirectory() as tmp:
    fs = Files(root_path=tmp)
    fs.FILE.save("test.txt", "Hello!")
    print("load:", fs.FILE.load("test.txt"))
    fs.FILE.append("test.txt", " World!")
    print("append:", fs.FILE.load("test.txt"))
    print("hash:", fs.FILE.hash("test.txt", algo="md5"))
    print()
    fs.JSON.save("cfg", {"debug": True, "port": 8080})
    print("json:", fs.JSON.load("cfg"))
    print()
    fs.CSV.save("data", [{"a": 1, "b": 2}, {"a": 3, "b": 4}])
    print("csv:", fs.CSV.load("data", types={"a": int, "b": int}))
    print()
    fs.INI.save("settings", {"main": {"key": "value", "num": 42}})
    print("ini:", fs.INI.load("settings"))
    print()
    fs.DIR.ensure("sub/dir/")
    fs.FILE.save("sub/f1.txt", "1")
    fs.FILE.save("sub/f2.txt", "2")
    fs.FILE.save("sub/dir/f3.py", "3")
    print("files:", fs.DIR.file_list("sub", exts=[".txt"], basename=True))
    print()
    print("expand:", fs.PATH.expand("~/test"))
    print("exists:", fs.PATH.exists(tmp))
    print("match:", fs.PATH.match("test.py", "*.py"))
    print()
    # `file_context` still works
    with file_context(root_path=tmp):
      FILE.save("ctx_test.txt", "context manager works")
      print("with:", FILE.load("ctx_test.txt"))