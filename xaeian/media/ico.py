# xaeian/media/ico.py

"""
Image to ICO conversion - multi-size favicon generator.

Pillow decodes and resizes, the ICO container is packed by hand for full control.
"""

import os, struct
from io import BytesIO
from typing import Literal
from .utils import require_file

from ..extras import MissingExtra, absent

try:
  from PIL import Image, ImageOps
except ModuleNotFoundError as e:
  if not absent(e, "PIL"): raise
  raise MissingExtra("Install with: pip install xaeian[media]") from e

DEFAULT_SIZES = [16, 20, 24, 32, 40, 48, 64, 96, 128, 256]

FitMode = Literal["pad", "crop"]

#---------------------------------------------------------------------------------------- Internals

def _make_square(img:Image.Image, fit:FitMode) -> Image.Image:
  w, h = img.size
  if w == h:
    return img
  if fit == "crop":
    s = min(w, h)
    x0, y0 = (w - s) // 2, (h - s) // 2
    return img.crop((x0, y0, x0 + s, y0 + s))
  s = max(w, h)
  out = Image.new("RGBA", (s, s), (0, 0, 0, 0))
  out.paste(img, ((s - w) // 2, (s - h) // 2))
  return out

def _write_ico(path:str, sizes:list[int], blobs:list[bytes]):
  """Pack PNG blobs into an ICO: 6-byte header, then one 16-byte directory entry per image."""
  count = len(sizes)
  header = struct.pack("<HHH", 0, 1, count) # reserved, type 1 = icon, image count
  entries = []
  offset = 6 + 16 * count
  for s, blob in zip(sizes, blobs):
    w = 0 if s == 256 else s # the side is a single byte, so 0 encodes 256
    # width, height, palette colors, reserved, planes, bpp, blob length, blob offset
    entries.append(struct.pack("<BBBBHHII", w, w, 0, 0, 1, 32, len(blob), offset))
    offset += len(blob)
  with open(path, "wb") as f:
    f.write(header)
    for e in entries:
      f.write(e)
    for blob in blobs:
      f.write(blob)

#---------------------------------------------------------------------------------------------- API

def pick_sizes(max_side:int, sizes:list[int]|None, upscale:bool) -> list[int]:
  """Ascending pool sizes capped at `max_side` unless `upscale`, or `[max_side]` if none fit."""
  pool = sizes if sizes else DEFAULT_SIZES
  if upscale:
    return sorted(pool)
  picked = [s for s in pool if s <= max_side]
  return sorted(picked) if picked else [max_side]

def img_to_ico(
  src:str,
  dst:str|None = None,
  sizes:list[int]|None = None,
  fit:FitMode = "pad",
  upscale:bool = False,
) -> str:
  """
  Convert image to multi-size .ico file.

  Every entry is stored as a 32-bit RGBA PNG, so the source may carry transparency.

  Args:
    dst: None → `src` with .ico extension.
    sizes: None → DEFAULT_SIZES. Sizes above the source side are dropped unless `upscale`.
    fit: Non-square source, "pad" transparent to square or "crop" centered.
  """
  src = require_file(src, "Image")
  try:
    img = ImageOps.exif_transpose(Image.open(src)).convert("RGBA")
  except Exception as e:
    raise ValueError(f"Cannot open image: {e}")
  img = _make_square(img, fit)
  icon_sizes = pick_sizes(max(img.size), sizes, upscale)
  resample = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
  blobs = []
  for s in icon_sizes:
    bio = BytesIO()
    img.resize((s, s), resample=resample).save(bio, format="PNG", optimize=True)
    blobs.append(bio.getvalue())
  out_path = os.path.abspath(dst) if dst else os.path.splitext(src)[0] + ".ico"
  _write_ico(out_path, icon_sizes, blobs)
  return out_path

def source_side(src:str, fit:FitMode) -> tuple[int, int, int]:
  """Source width, height, and the side `img_to_ico` squares it to under `fit`."""
  w, h = Image.open(src).size
  return w, h, (min(w, h) if fit == "crop" else max(w, h))
