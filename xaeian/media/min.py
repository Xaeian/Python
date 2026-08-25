# xaeian/media/min.py

"""Compression for PDFs and images."""

import os
from typing import Any, Sequence
from .utils import PDF_EXTS, IMG_EXTS, require_file

#---------------------------------------------------------------------------------------------- API

def compress(
  src:str,
  dst:str|None = None,
  inplace:bool = False,
  pdf_level:str = "1.7",
  pdf_settings:str = "/ebook",
  pdf_programs:Sequence[str] = ("gswin64c", "gswin32c", "gs"),
  # Image
  max_px:int = 1920,
  img_format:str = "keep",
  quality:int = 80,
  target_kB:int|None = None,
  avif_speed:int = 6,
  recursive:bool = True,
) -> list[dict[str, Any]]:
  """
  Compress a PDF, an image, or a directory of images: auto-detects PDF vs image.

  With `dst` None: overwrite source when `inplace`, else write `<base>-min<ext>`,
  or a `<dir>-min/` sibling tree for a directory. PDF compression needs Ghostscript on PATH.

  Args:
    pdf_level: PDF compatibility version written out (1.2-1.7).
    pdf_settings: Ghostscript preset (/screen /ebook /printer /prepress /default).
    pdf_programs: Ghostscript executable candidates, first one found is used.
    max_px: Long-side cap, only ever downscales.
    img_format: "keep", "auto", "avif", "webp", "jpg", "png".
    quality: 1-100 starting point, stepped down until `target_kB` fits.
    avif_speed: 0-10, lower is slower and smaller.
    recursive: Walk subdirectories when `src` is a directory.

  Returns:
    One dict per file: `src`, `dst`, `orig_kB`, `new_kB`;
    images add `orig_size` and `new_size` (width, height) pixel pairs and `format`.
  """
  if os.path.isdir(src):
    from .img import img_compress
    return img_compress(src, dst, max_px, img_format, quality, target_kB, avif_speed,
      recursive, inplace)
  src = require_file(src, "Input")
  ext = os.path.splitext(src)[1].lower()
  if ext in PDF_EXTS:
    from .pdf import pdf_compress
    orig_kB = os.path.getsize(src) / 1024
    out = pdf_compress(src, dst, pdf_level, pdf_settings, pdf_programs, inplace)
    return [{"src": src, "dst": out, "orig_kB": orig_kB, "new_kB": os.path.getsize(out) / 1024}]
  if ext in IMG_EXTS:
    from .img import img_compress
    return img_compress(src, dst, max_px, img_format, quality, target_kB, avif_speed,
      recursive, inplace)
  raise ValueError(f"Unsupported format: {ext} (expected PDF, image, or directory)")
