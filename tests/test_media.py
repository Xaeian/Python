# tests/test_media.py

"""
Media operations on files generated in tmp: no fixtures shipped, no Ghostscript required.

PDF compression shells out to Ghostscript and stays untested here; the pypdf-backed
operations and the image pipeline run for real.
"""

import pytest

pytest.importorskip("PIL", reason="media needs the [media] extra")
pypdf = pytest.importorskip("pypdf", reason="media needs the [media] extra")

from PIL import Image
from xaeian.media import compress, scrub_metadata, pdf_merge, pdf_split, pdf_extract

@pytest.fixture
def photo(tmp_path):
  """A JPEG large enough that resizing to 64px visibly shrinks it."""
  path = tmp_path / "photo.jpg"
  Image.new("RGB", (640, 480), (200, 60, 60)).save(path, quality=95)
  return str(path)

@pytest.fixture
def booklet(tmp_path):
  """A three-page PDF written by pypdf itself."""
  path = tmp_path / "booklet.pdf"
  writer = pypdf.PdfWriter()
  for _ in range(3):
    writer.add_blank_page(width=200, height=200)
  with open(path, "wb") as f:
    writer.write(f)
  return str(path)

#------------------------------------------------------------------------------------------- images

def compress_returns_one_row_per_file(photo, tmp_path):
  rows = compress(photo, str(tmp_path / "small.jpg"), max_px=64)
  assert len(rows) == 1
  row = rows[0]
  assert set(row) >= {"src", "dst", "orig_kB", "new_kB", "orig_size", "new_size", "format"}
  assert row["new_size"][0] <= 64
  assert row["new_kB"] < row["orig_kB"]

def scrub_metadata_writes_a_sibling_by_default(photo, tmp_path):
  out = scrub_metadata(photo)
  assert out.endswith("photo-nometa.jpg")
  assert Image.open(out).size == (640, 480)

#--------------------------------------------------------------------------------------------- pdfs

def merge_split_and_extract_round_trip(booklet, tmp_path):
  extracted = pdf_extract(booklet, str(tmp_path / "middle.pdf"), 2)
  assert len(pypdf.PdfReader(extracted).pages) == 1
  merged = pdf_merge([booklet, extracted], str(tmp_path / "merged.pdf"))
  assert len(pypdf.PdfReader(merged).pages) == 4
  parts = pdf_split(booklet, str(tmp_path / "pages"))
  assert len(parts) == 3
