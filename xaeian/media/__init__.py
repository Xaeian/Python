# xaeian/media/__init__.py

"""
Media file operations: PDF and image compression, conversion, metadata.

Submodules:
  - `xaeian.media.pdf`: PDF compress/merge/split/extract/metadata/text overlay
  - `xaeian.media.img`: image resize/convert/compress/metadata scrub
  - `xaeian.media.ico`: multi-size `.ico` generation
  - `xaeian.media.min`: unified compression for PDFs and images
  - `xaeian.media.meta`: metadata removal for PDFs and images

`min`, `meta` and `ico` also run as the `xn min`, `xn meta` and `xn ico` commands.
PDF compression additionally needs the Ghostscript binary on PATH, it is not a pip dependency.
"""

__extras__ = ("media", ["Pillow", "pypdf", "PyMuPDF"])
