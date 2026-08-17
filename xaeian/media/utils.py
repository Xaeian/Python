# xaeian/media/utils.py

"""Shared constants and helpers for media subpackage."""

import os
from ..files import DIR

PDF_EXTS = {".pdf"}
IMG_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff", ".tif", ".avif"}

def require_file(path:str, label:str="File") -> str:
  """Resolve to absolute path, raise `FileNotFoundError` prefixed with `label` if missing."""
  path = os.path.abspath(path)
  if not os.path.isfile(path):
    raise FileNotFoundError(f"{label} not found: {path}")
  return path

def resolve_dst(src:str, dst:str|None, inplace:bool, suffix:str) -> str:
  """
  Resolve absolute output path: explicit `dst` > `inplace` overwrite > `<base>-<suffix><ext>`.

  `src` must already be absolute, `suffix` is given without the dash ("min", "nometa").
  An explicit `dst` also gets its parent directory created; the result is always a file path,
  so a `dst` carrying no extension still names a file, never a directory.
  """
  if dst is not None:
    out = os.path.abspath(dst)
    DIR.ensure(out, is_file=True)
    return out
  if inplace:
    return src
  base, ext = os.path.splitext(src)
  return f"{base}-{suffix}{ext}"