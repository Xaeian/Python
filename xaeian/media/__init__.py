# xaeian/media/__init__.py

"""
Media file operations: PDF and image compression, conversion, metadata.

`compress` and `scrub_metadata` dispatch on the extension: they are the usual entry points.
Underneath sit the per-format `pdf_*`, `img_*` and `ico` functions,
exported only where the `media` extra is installed, since Pillow and pypdf load at import.

PDF compression additionally needs the Ghostscript binary on PATH, not a pip dependency.
The `xn min`, `xn meta` and `xn ico` commands drive this package from `xaeian.cli`.
"""

__extras__ = ("media", ["Pillow", "pypdf", "PyMuPDF"])

from ..extras import MissingExtra
from .min import compress
from .meta import scrub_metadata

__all__ = ["compress", "scrub_metadata"]

try:
  from .img import img_compress, img_convert, img_resize, img_scrub_metadata
  from .pdf import (
    pdf_compress, pdf_scrub_metadata, pdf_merge, pdf_split, pdf_extract, pdf_add_text,
    parse_pages,
  )
  from .ico import img_to_ico, pick_sizes, source_side, DEFAULT_SIZES
  __all__ += [
    "img_compress", "img_convert", "img_resize", "img_scrub_metadata",
    "pdf_compress", "pdf_scrub_metadata", "pdf_merge", "pdf_split", "pdf_extract",
    "pdf_add_text", "parse_pages",
    "img_to_ico", "pick_sizes", "source_side", "DEFAULT_SIZES",
  ]
except MissingExtra:
  pass
