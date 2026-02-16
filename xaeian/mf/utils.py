# xaeian/mf/utils.py

"""Shared constants and helpers for mf subpackage."""

import os
from ..files import DIR

PDF_EXTS = {".pdf"}
IMG_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff", ".tif", ".avif"}

def require_file(path:str, label:str="File") -> str:
  """@brief Resolve to absolute path and verify file exists.
  @param[in] path   File path to validate.
  @param[in] label  Label for error message (e.g. "PDF", "Image").
  @return Absolute path.
  """
  path = os.path.abspath(path)
  if not os.path.isfile(path):
    raise FileNotFoundError(f"{label} not found: {path}")
  return path

def resolve_dst(src:str, dst:str|None, inplace:bool, suffix:str) -> str:
  """@brief Resolve output path — common 3-way pattern.

  Priority: explicit `dst` > `inplace` (overwrite) > auto-suffix.

  @param[in] src      Absolute source path.
  @param[in] dst      Explicit destination or None.
  @param[in] inplace  Overwrite source when `dst` is None.
  @param[in] suffix   Auto-suffix without dash (e.g. "min", "nometa").
  @return Resolved absolute output path.
  """
  if dst is not None:
    out = os.path.abspath(dst)
    DIR.ensure(out)
    return out
  if inplace:
    return src
  base, ext = os.path.splitext(src)
  return f"{base}-{suffix}{ext}"