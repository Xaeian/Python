# xaeian/files/path.py

"""Path manipulation and resolution utilities."""

import os, sys, re, fnmatch
from .config import get_context
from ..xstring import replace_start

#----------------------------------------------------------------------------------- PATH namespace

class PATH:
  """Static path helpers; normalization and resolution follow the active `Config`."""
  @staticmethod
  def normalize(path:str) -> str:
    """
    Normalize path separators and redundant segments.

    The leading `//` of a UNC share (`//host/share`) and of the `//?/` extended-length prefix
    survives collapsing, since it is the root itself and not a repeated separator. The `//./`
    device namespace is not preserved, its `.` reads as a current-directory segment.
    """
    cfg = get_context()
    if cfg.posix_slash: path = path.replace("\\", "/")
    if cfg.clean:
      unc = path.startswith("//")
      path = re.sub(r"/+", "/", path)
      while "/./" in path: path = path.replace("/./", "/")
      if unc: path = "/" + path
    return path

  @staticmethod
  def expand(path:str) -> str:
    """Expand `~`, `~user` and environment variables `$VAR`, `${VAR}`."""
    path = os.path.expanduser(path)
    path = os.path.expandvars(path)
    return PATH.normalize(path)

  @staticmethod
  def resolve(path:str, read:bool=True) -> str:
    """
    Resolve to absolute: expands `~` and `$VAR`, then joins relative paths onto `root_path`.

    `read=False` ignores the PyInstaller bundle (`_MEIPASS`) base.
    """
    cfg = get_context()
    path = PATH.expand(path)
    if os.path.isabs(path):
      return PATH.normalize(os.path.normpath(path))
    if read and cfg.bundle and hasattr(sys, "_MEIPASS"):
      meipass = PATH.normalize(getattr(sys, "_MEIPASS"))
      root = PATH.normalize(cfg.root_path) if cfg.root_path else ""
      base = root if root and root.startswith(meipass) else meipass
    else:
      if not cfg.auto_resolve: return PATH.normalize(path)
      base = cfg.root_path
    path = replace_start(path, "./", "")
    full = os.path.normpath(os.path.join(base, path))
    return PATH.normalize(full)

  @staticmethod
  def real(path:str) -> str:
    """
    Resolve to an absolute path with every symlink expanded.

    `resolve` only folds `.` and `..` lexically, so a link inside a directory still reads as
    inside it. Use this whenever a path built from untrusted input has to be proven to stay
    within a base directory.
    """
    return PATH.normalize(os.path.realpath(PATH.resolve(path)))

  @staticmethod
  def script_dir() -> str:
    """
    Directory the running program lives in.

    The executable's directory when frozen, else the main script's; the working directory
    when neither is known (REPL).
    """
    if getattr(sys, "frozen", False):
      return PATH.normalize(os.path.dirname(sys.executable))
    main = sys.modules.get("__main__")
    file = getattr(main, "__file__", None) or sys.argv[0]
    if not file: return PATH.normalize(os.getcwd())
    return PATH.normalize(os.path.dirname(os.path.abspath(file)))

  @staticmethod
  def rel(path:str, base:str|None=None) -> str:
    """
    Path relative to `base`, or to `root_path` when `base` is omitted.

    Falls back to the absolute path when the two sit on different drives.
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
    """
    Path relative to `base` with `prefix` prepended; `PATH.rel()` is the plain form.

    Falls back to the absolute path when `path` lies outside `base`. A result that already
    starts with `prefix` is not prefixed twice.
    """
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
          if rel and rel != prefix.rstrip("/") and not rel.startswith(full_prefix):
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
    """Replace the extension with `suffix`, leading dot included; `""` strips it."""
    root, _ = os.path.splitext(PATH.normalize(path))
    return root + suffix

  @staticmethod
  def ensure_suffix(path:str, suffix:str) -> str:
    """Append `suffix` when the extension differs, never replace it: `a.txt` → `a.txt.json`."""
    if not suffix: return PATH.normalize(path)
    path = PATH.normalize(path)
    _, ext = os.path.splitext(path)
    if ext == suffix: return path
    return path + suffix

  @staticmethod
  def is_under(path:str, base:str|None=None, real:bool=False) -> bool:
    """
    Check if path is inside `base`, or inside `root_path` when `base` is omitted.

    `real=True` expands symlinks on both sides first. Without it a link inside `base`
    pointing elsewhere still counts as inside, which untrusted input can exploit.
    """
    cfg = get_context()
    conv = PATH.real if real else PATH.resolve
    abs_path = conv(path)
    if base is None: base = cfg.root_path
    abs_base = conv(base)
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
    """Match a `*` / `?` pattern against the basename only, directories ignored."""
    return fnmatch.fnmatch(PATH.basename(path), pattern)
