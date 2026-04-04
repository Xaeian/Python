# xaeian/files/dir.py

"""Directory operations."""

import os, stat, shutil, zipfile
from typing import Iterator
from .path import PATH

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
  def ensure(path:str, is_file:bool|None=None) -> str:
    """
    Create directory if it doesn't exist.

    Args:
      path: Directory or file path.
      is_file: If `True`, create parent dir. If `None`, auto-detect:
        path ending with `/` is always a directory; otherwise treated
        as a file when the last segment contains a dot (e.g. `data.csv`).
        Extensionless names like `Makefile` need explicit `is_file=True`.

    Example:
      >>> DIR.ensure("data/subdir/")     # creates data/subdir/
      >>> DIR.ensure("data/config.json") # creates data/
      >>> DIR.ensure("data/Makefile", is_file=True) # creates data/
    """
    trailing = path.endswith("/") or path.endswith("\\")
    path = PATH.resolve(path, read=False)
    if is_file is None:
      if trailing:
        is_file = False
      else:
        is_file = bool(PATH.ext(path))
    if is_file:
      path = os.path.dirname(path)
    if path:
      os.makedirs(path, exist_ok=True)
    return PATH.normalize(path)

  @staticmethod
  def remove(path:str, force:bool=False):
    """Recursively remove directory tree."""
    path = PATH.resolve(path, read=False)
    if not os.path.isdir(path):
      raise NotADirectoryError(f"Not a directory: {path}")
    def on_error(func, fpath, exc):
      if force:
        os.chmod(fpath, stat.S_IWRITE)
        func(fpath)
      else:
        raise exc
    shutil.rmtree(path, onexc=on_error)

  @staticmethod
  def move(src:str, dst:str):
    """Move file or directory. Works across filesystems."""
    src = PATH.resolve(src, read=False)
    dst = PATH.resolve(dst, read=False)
    if not os.path.exists(src):
      raise FileNotFoundError(f"Source not found: {src}")
    DIR.ensure(os.path.dirname(dst), is_file=False)
    shutil.move(src, dst)

  @staticmethod
  def copy(src:str, dst:str):
    """Copy file or directory tree."""
    src = PATH.resolve(src, read=False)
    dst = PATH.resolve(dst, read=False)
    if not os.path.exists(src):
      raise FileNotFoundError(f"Source not found: {src}")
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
    bl_names = {b for b in bl if "/" not in b.rstrip("/")}
    bl_rels = {b.rstrip("/") for b in bl if "/" in b.rstrip("/")}
    folders: list[str] = []
    if deep:
      for root, dirs, _ in os.walk(path):
        root_rel = PATH.normalize(os.path.relpath(root, path))
        def _keep(d, root_rel=root_rel):
          if d in bl_names: return False
          rel = d if root_rel == "." else root_rel + "/" + d
          return rel not in bl_rels
        dirs[:] = [d for d in dirs if _keep(d)]
        for d in dirs:
          full = PATH.normalize(os.path.join(root, d))
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
      exts: Extensions to include (e.g. `[".py", ".txt"]`).
      match: Glob pattern for filename (e.g. `"test_*.py"`).
      blacklist: Paths to skip (files or directories, relative to path).

    Yields:
      Absolute file paths.
    """
    path = PATH.resolve(path, read=True)
    if not os.path.isdir(path): return
    bl_dirs: set[str] = set()
    bl_files: set[str] = set()
    bl_names: set[str] = set()
    for b in (blacklist or []):
      full = path + "/" + b.rstrip("/")
      if os.path.isdir(full) or b.endswith("/"):
        bl_dirs.add(full)
      else:
        bl_files.add(b)
      if "/" not in b.rstrip("/"):
        bl_names.add(b.rstrip("/"))
    ext_tuple = tuple(ext.lower() for ext in (exts or []))
    for root, dirs, files in os.walk(path):
      root_norm = PATH.normalize(root)
      dirs[:] = [
        d for d in dirs
        if root_norm + "/" + d not in bl_dirs and d not in bl_names
      ]
      for name in files:
        rel = PATH.normalize(
          os.path.relpath(root_norm + "/" + name, path)
        )
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
      exts: Extensions to include (e.g. `[".py", ".txt"]`).
      match: Glob pattern for filename (e.g. `"test_*.py"`).
      blacklist: Paths to skip (files or directories, relative to path).
      basename: Return only filename when True.
      local: Return paths relative to `path` when True.

    Example:
      >>> DIR.file_list("src", exts=[".py"], blacklist=["__pycache__"])
      ['src/main.py', 'src/utils/helper.py']
    """
    path = PATH.resolve(path, read=True)
    result: list[str] = []
    for f in DIR.iter_files(
      path, exts=exts, match=match, blacklist=blacklist,
    ):
      if basename:
        result.append(PATH.basename(f))
      elif local:
        result.append(PATH.normalize(os.path.relpath(f, path)))
      else:
        result.append(f)
    return result

  @staticmethod
  def zip(path:str, zip_output:str|None=None,
          blacklist:list[str]|None=None) -> str:
    """
    Create ZIP archive from a directory.

    Args:
      path: Source directory path.
      zip_output: Output archive path (default: `"<folder>.zip"`).
      blacklist: Paths to exclude from archive.

    Returns:
      Final ZIP archive path.
    """
    src = PATH.resolve(path, read=True)
    if not os.path.isdir(src):
      raise NotADirectoryError(f"Directory not found: {src}")
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

  @staticmethod
  def unzip(path:str, output:str|None=None) -> str:
    """
    Extract ZIP archive to directory.

    Args:
      path: Source ZIP archive path.
      output: Output directory (default: archive name without `.zip`).

    Returns:
      Output directory path.
    """
    src = PATH.resolve(path, read=True)
    if not os.path.isfile(src):
      raise FileNotFoundError(f"Archive not found: {src}")
    if output is None:
      output = PATH.with_suffix(src, "")
    output = PATH.resolve(output, read=False)
    os.makedirs(output, exist_ok=True)
    with zipfile.ZipFile(src, "r") as zf:
      zf.extractall(output)
    return PATH.normalize(output)
  
  @staticmethod
  def unzip_bytes(data:bytes, output:str) -> str:
    """
    Extract ZIP archive from bytes to directory.

    Args:
      data: ZIP archive as bytes.
      output: Output directory path.

    Returns:
      Output directory path.
    """
    import io
    output = PATH.resolve(output, read=False)
    os.makedirs(output, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data), "r") as zf:
      zf.extractall(output)
    return PATH.normalize(output)