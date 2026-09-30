# tests/test_media.py

"""
Media operations on files generated in tmp: no fixtures shipped, no Ghostscript required.

PDF compression shells out to Ghostscript and stays untested here;
the pypdf-backed operations and the image pipeline run for real.
"""

import time, tracemalloc
import pytest

pytest.importorskip("PIL", reason="media needs the [media] extra")
pypdf = pytest.importorskip("pypdf", reason="media needs the [media] extra")

from PIL import Image
from xaeian.media import (
  compress, scrub_metadata, pdf_merge, pdf_split, pdf_extract, img_to_ico, parse_pages,
)

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

def a_scrub_that_fails_midway_keeps_the_only_copy(booklet, monkeypatch):
  """In place the output is the source: a writer that dies halfway must not truncate it."""
  before = open(booklet, "rb").read()
  def broken(self, stream):
    stream.write(b"%PDF-1.3 half")
    raise OSError("disk full")
  monkeypatch.setattr(pypdf.PdfWriter, "write", broken)
  with pytest.raises(OSError):
    scrub_metadata(booklet, inplace=True)
  assert open(booklet, "rb").read() == before

def parse_pages_clamps_before_building_the_range():
  """"1-3000000" on a 5-page file never allocates the whole range."""
  tracemalloc.start()
  started = time.perf_counter()
  pages = parse_pages("1-3000000", total=5)
  peak = tracemalloc.get_traced_memory()[1]
  tracemalloc.stop()
  assert pages == [0, 1, 2, 3, 4]
  assert peak < 1_000_000, f"parse_pages allocated {peak} bytes for a 5-page document"
  assert time.perf_counter() - started < 1.0

def parse_pages_reads_ordinary_specs():
  assert parse_pages("1,3,5-7,!6", total=10) == [0, 2, 4, 6]
  assert parse_pages("8-", total=10) == [7, 8, 9]
  assert parse_pages("!1", total=3) == [1, 2]

#-------------------------------------------------------------------------------------------- icons

def an_icon_size_above_256_is_refused_by_name(photo):
  """The ICO directory stores a side in one byte: 257 and up cannot be written at all."""
  with pytest.raises(ValueError, match="1-256"):
    img_to_ico(photo, sizes=[16, 512])
