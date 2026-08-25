# xaeian/media/meta.py

"""Metadata removal for PDFs and images."""

import os
from .utils import PDF_EXTS, IMG_EXTS, require_file

#---------------------------------------------------------------------------------------------- API

def scrub_metadata(src:str, dst:str|None=None, inplace:bool=False) -> str:
  """
  Remove metadata from a file: auto-detects PDF vs image.

  With `dst` None: overwrite source when `inplace`, else write `<base>-nometa<ext>`.
  """
  src = require_file(src, "Input")
  ext = os.path.splitext(src)[1].lower()
  if ext in PDF_EXTS:
    from .pdf import pdf_scrub_metadata
    return pdf_scrub_metadata(src, dst, inplace)
  if ext in IMG_EXTS:
    from .img import img_scrub_metadata
    return img_scrub_metadata(src, dst, inplace)
  raise ValueError(f"Unsupported format: {ext} (expected PDF or image)")
