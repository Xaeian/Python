# xaeian/files/dir.py

"""Directory operations."""

import io, os, stat, shutil, zipfile
from dataclasses import dataclass
from typing import Iterator, Literal, Sequence
from .path import PATH
from ..xstring import ensure_suffix

Shape = Literal["abs", "name", "rel"]
"""How a listing spells its entries: absolute, bare name, or relative to the listed root."""

#---------------------------------------------------------------------------------------- Blacklist

@dataclass(frozen=True)
class _Blacklist:
  """
  What a listing skips, resolved once per call.

  An entry without `/` skips that name at any depth, file or folder alike.
  An entry with `/` is a path relative to the listed root.
  A trailing slash only says "this is a folder", so `"build"` and `"build/"` mean the same.

  Nothing here looks at the disk, so a listing cannot change its answer
  because a directory happens to exist at the moment it runs.
  """
  names: frozenset[str]
  rels: frozenset[str]

  @staticmethod
  def of(entries:Sequence[str]|None) -> "_Blacklist":
    names: set[str] = set()
    rels: set[str] = set()
    for entry in entries or []:
      clean = PATH.normalize(entry).strip("/")
      if not clean: continue
      (rels if "/" in clean else names).add(clean)
    return _Blacklist(frozenset(names), frozenset(rels))

  def skips(self, name:str, rel:str) -> bool:
    """`name` is the bare entry name, `rel` its path relative to the listed root."""
    return name in self.names or rel in self.rels

def _linked(parent:str, name:str) -> bool:
  """
  Is this entry a symlink or a Windows junction?

  A listing walks the tree that physically lives under the path,
  so a link is neither entered nor listed.
  `os.walk` would enter a junction as an ordinary directory, since `islink` is blind to one:
  the walk then leaves the tree it was given,
  or circles back onto an ancestor until the path runs out of room.
  """
  path = os.path.join(parent, name)
  return os.path.islink(path) or os.path.isjunction(path)

def _spell(full:str, root:str, shape:Shape) -> str:
  """Render one listed path in the requested shape."""
  if shape == "abs": return full
  if shape == "name": return PATH.basename(full)
  if shape == "rel": return PATH.normalize(os.path.relpath(full, root))
  raise ValueError(f"Unknown shape: {shape!r}")

#------------------------------------------------------------------------------------ DIR namespace

class DIR:
  """Static directory helpers; paths resolve against the active `Config`."""
  @staticmethod
  def exists(path:str) -> bool:
    """Check if path is an existing directory."""
    return os.path.isdir(PATH.resolve(path, read=True))

  @staticmethod
  def ensure(path:str, is_file:bool|None=None) -> str:
    """
    Create directory if it doesn't exist.

    `is_file=True` creates the parent dir instead. When `None` it is auto-detected:
    a trailing `/` is always a directory, otherwise an extension on the last segment means file.
    A name without one - `Makefile`, `.gitignore` - needs an explicit `is_file=True`.
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
  def remove(path:str, force:bool=False) -> None:
    """
    Recursively remove directory tree. `force` clears the read-only bit and retries.

    Raises `NotADirectoryError` when the path is missing, unlike `FILE.remove`.
    """
    path = PATH.resolve(path, read=False)
    if not os.path.isdir(path):
      raise NotADirectoryError(f"Not a directory: {path}")
    def on_error(func, fpath, exc) -> None:
      if force:
        os.chmod(fpath, stat.S_IWRITE)
        func(fpath)
      else:
        raise exc
    shutil.rmtree(path, onexc=on_error)

  @staticmethod
  def move(src:str, dst:str) -> None:
    """Move file or directory. Works across filesystems."""
    src = PATH.resolve(src, read=False)
    dst = PATH.resolve(dst, read=False)
    if not os.path.exists(src):
      raise FileNotFoundError(f"Source not found: {src}")
    DIR.ensure(os.path.dirname(dst), is_file=False)
    shutil.move(src, dst)

  @staticmethod
  def copy(src:str, dst:str) -> None:
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
    shape:Shape = "abs",
    blacklist:list[str]|None = None,
  ) -> list[str]:
    """
    List subdirectories under given path.

    `deep` walks recursively, `shape` picks how each entry is spelled, and `blacklist` filters
    as described on `_Blacklist`.
    """
    path = PATH.resolve(path, read=True)
    if not os.path.isdir(path): return []
    skip = _Blacklist.of(blacklist)
    folders: list[str] = []
    walker = os.walk(path) if deep else [(path, next(os.walk(path))[1], [])]
    for root, dirs, _ in walker:
      root_rel = PATH.normalize(os.path.relpath(root, path))
      prefix = "" if root_rel == "." else root_rel + "/"
      dirs[:] = [d for d in dirs if not skip.skips(d, prefix + d) and not _linked(root, d)]
      for d in dirs:
        folders.append(_spell(PATH.normalize(os.path.join(root, d)), path, shape))
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

    `exts` carry the leading dot and match case-insensitively (`[".py", ".txt"]`),
    `match` is a glob on the filename (`"test_*.py"`), `deep=False` stays on the top level,
    and `blacklist` filters as described on `_Blacklist`.
    """
    path = PATH.resolve(path, read=True)
    if not os.path.isdir(path): return
    skip = _Blacklist.of(blacklist)
    ext_tuple = tuple(ext.lower() for ext in (exts or []))
    if deep:
      walker = os.walk(path)
    else:
      names = [n for n in os.listdir(path) if os.path.isfile(os.path.join(path, n))]
      walker = [(path, [], names)]
    for root, dirs, files in walker:
      root_norm = PATH.normalize(root)
      root_rel = PATH.normalize(os.path.relpath(root_norm, path))
      prefix = "" if root_rel == "." else root_rel + "/"
      dirs[:] = [d for d in dirs if not skip.skips(d, prefix + d) and not _linked(root, d)]
      for name in files:
        if skip.skips(name, prefix + name): continue
        if ext_tuple and not name.lower().endswith(ext_tuple): continue
        if match and not PATH.match(name, match): continue
        yield root_norm + "/" + name

  @staticmethod
  def file_list(
    path:str,
    exts:list[str]|None = None,
    match:str|None = None,
    blacklist:list[str]|None = None,
    shape:Shape = "abs",
    deep:bool = True,
  ) -> list[str]:
    """List files under directory, filtered as in `iter_files`; `shape` picks the spelling."""
    path = PATH.resolve(path, read=True)
    return [
      _spell(f, path, shape)
      for f in DIR.iter_files(path, exts=exts, match=match, blacklist=blacklist, deep=deep)
    ]

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
