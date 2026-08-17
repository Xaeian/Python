# xaeian/files/dir.py

"""Directory operations."""

import io, os, stat, shutil, zipfile
from typing import Iterator
from .path import PATH
from ..xstring import ensure_suffix

#------------------------------------------------------------------------------------ DIR namespace

class DIR:
  """Static directory helpers; paths resolve against the active `Config`."""
  @staticmethod
  def ensure(path:str, is_file:bool|None=None) -> str:
    """
    Create directory if it doesn't exist.

    `is_file=True` creates the parent dir instead. When `None` it is auto-detected: a trailing
    `/` is always a directory, otherwise an extension on the last segment means file, so names
    without one - `Makefile`, `.gitignore` - need an explicit `is_file=True`.
    """
    trailing = path.endswith("/") or path.endswith("\\")
    path = PATH.resolve(path, read=False)
    if is_file is None: is_file = not trailing and bool(PATH.ext(path))
    if is_file:
      path = os.path.dirname(path)
    if path:
      os.makedirs(path, exist_ok=True)
    return PATH.normalize(path)

  @staticmethod
  def _resolve_write(path:str, ext:str) -> str:
    """Append `ext`, resolve for writing and create the parent directory."""
    path = ensure_suffix(path, ext)
    path = PATH.resolve(path, read=False)
    DIR.ensure(path, is_file=True)
    return path

  @staticmethod
  def remove(path:str, force:bool=False):
    """
    Recursively remove directory tree. `force` clears the read-only bit and retries.

    Raises `NotADirectoryError` when the path is missing, unlike `FILE.remove`.
    """
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
    """Copy file or directory tree, overwriting files and merging into existing directories."""
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
    path:str,
    deep:bool = False,
    basename:bool = False,
    blacklist:list[str]|None = None,
  ) -> list[str]:
    """
    List subdirectories under given path.

    `deep` walks recursively, `basename` returns bare names. A `blacklist` entry without `/`
    skips that folder name at any depth, one with `/` a path relative to `path`.
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
        prefix = "" if root_rel == "." else root_rel + "/"
        dirs[:] = [d for d in dirs if d not in bl_names and prefix + d not in bl_rels]
        for d in dirs:
          folders.append(d if basename else PATH.normalize(os.path.join(root, d)))
    else:
      for name in os.listdir(path):
        if name in bl: continue
        full = os.path.join(path, name)
        if os.path.isdir(full):
          folders.append(name if basename else PATH.normalize(full))
    return folders

  @staticmethod
  def iter_files(
    path:str,
    exts:list[str]|None = None,
    match:str|None = None,
    blacklist:list[str]|None = None,
    deep:bool = True,
  ) -> Iterator[str]:
    """
    Iterate files under directory (memory efficient), yielding absolute paths.

    `exts` carry the leading dot and match case-insensitively (`[".py", ".txt"]`), `match` is a
    glob on the filename (`"test_*.py"`), `blacklist` holds names or paths relative to `path`,
    `deep=False` stays on the top level.
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
    if deep:
      walker = os.walk(path)
    else:
      names = [n for n in os.listdir(path) if os.path.isfile(os.path.join(path, n))]
      walker = [(path, [], names)]
    for root, dirs, files in walker:
      root_norm = PATH.normalize(root)
      dirs[:] = [d for d in dirs if root_norm + "/" + d not in bl_dirs and d not in bl_names]
      for name in files:
        rel = PATH.normalize(os.path.relpath(root_norm + "/" + name, path))
        if rel in bl_files or name in bl_files: continue
        if ext_tuple and not name.lower().endswith(ext_tuple): continue
        if match and not PATH.match(name, match): continue
        yield root_norm + "/" + name

  @staticmethod
  def file_list(
    path:str,
    exts:list[str]|None = None,
    match:str|None = None,
    blacklist:list[str]|None = None,
    basename:bool = False,
    local:bool = False,
    deep:bool = True,
  ) -> list[str]:
    """
    List files under directory, filtered as in `iter_files`.

    Paths come back absolute, as bare names under `basename`, relative to `path` under `local`.
    """
    path = PATH.resolve(path, read=True)
    result: list[str] = []
    for f in DIR.iter_files(path, exts=exts, match=match, blacklist=blacklist, deep=deep):
      if basename:
        result.append(PATH.basename(f))
      elif local:
        result.append(PATH.normalize(os.path.relpath(f, path)))
      else:
        result.append(f)
    return result

  @staticmethod
  def zip(path:str, zip_output:str|None=None, blacklist:list[str]|None=None) -> str:
    """
    Create ZIP archive from a directory, entries stored relative to it.

    `zip_output` defaults to `"<folder>.zip"`, `blacklist` filters as in `iter_files`.
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
    """Extract ZIP archive. `output` defaults to the archive path without `.zip`."""
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
    """Extract a ZIP archive held in memory into `output` directory."""
    output = PATH.resolve(output, read=False)
    os.makedirs(output, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data), "r") as zf:
      zf.extractall(output)
    return PATH.normalize(output)
