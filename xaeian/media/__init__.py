# xaeian/media/__init__.py

"""
Media file operations: PDF and image compression, conversion, metadata.

Submodules:
  - `xaeian.media.pdf`: PDF compress/merge/split/extract/metadata/text overlay
  - `xaeian.media.img`: image resize/convert/compress/metadata scrub
  - `xaeian.media.ico`: multi-size `.ico` generation
  - `xaeian.media.min`: unified compression for PDFs and images
  - `xaeian.media.meta`: metadata inspection and scrubbing

Requires: `Pillow`, `pypdf`, `PyMuPDF`
"""

__extras__ = {"media": ["Pillow", "pypdf", "PyMuPDF"]}
