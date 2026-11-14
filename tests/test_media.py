# tests/test_media.py

"""
Media operations on files generated in tmp: no fixtures shipped, no Ghostscript required.

PDF compression shells out to Ghostscript and stays untested here;
the pypdf-backed operations and the image pipeline run for real.
"""

import logging, threading, time, tracemalloc
import pytest

pytest.importorskip("PIL", reason="media needs the [media] extra")
pypdf = pytest.importorskip("pypdf", reason="media needs the [media] extra")

from PIL import Image
from xaeian.media import (
  compress, scrub_metadata, pdf_merge, pdf_split, pdf_extract, pdf_insert, pdf_page_count,
  img_to_ico, parse_pages,
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
  writer.write(path)
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

def insert_puts_pages_in_place_keeping_bookmarks_links_and_info(booklet, tmp_path):
  from pypdf.generic import ArrayObject, DictionaryObject, NameObject, NumberObject
  marked = tmp_path / "marked.pdf"
  writer = pypdf.PdfWriter()
  for _ in range(4):
    writer.add_blank_page(width=200, height=200)
  writer.add_outline_item("Fourth", 3)
  link = DictionaryObject({ # page 1 → page 4, by the page itself, as a PDF maker links
    NameObject("/Type"): NameObject("/Annot"), NameObject("/Subtype"): NameObject("/Link"),
    NameObject("/Rect"): ArrayObject([NumberObject(n) for n in (10, 10, 50, 50)]),
    NameObject("/Dest"): ArrayObject([writer.pages[3].indirect_reference, NameObject("/Fit")]),
  })
  writer.pages[0][NameObject("/Annots")] = ArrayObject([writer._add_object(link)])
  writer.add_metadata({"/Title": "Marked"})
  writer.write(marked)
  out = pdf_insert(str(marked), booklet, 2, replace=1, dst=str(tmp_path / "out.pdf"))
  reader = pypdf.PdfReader(out)
  assert len(reader.pages) == 6 # page 1, the booklet's three for page 2, then pages 3 and 4
  fourth = reader.pages[5].indirect_reference
  assert [reader.get_destination_page_number(item) for item in reader.outline] == [5]
  link = reader.pages[0]["/Annots"][0].get_object()
  assert link["/Dest"][0] == fourth # the link still leads to the page it led to
  assert reader.metadata.title == "Marked"
  with pytest.raises(ValueError):
    pdf_insert(str(marked), booklet, 5, replace=1)

def insert_leaves_the_bookmarks_of_the_inserted_file_and_pypdf_quiet(booklet, tmp_path, caplog):
  # An article with bookmarks and a link inside it, as a publisher's PDF comes
  from pypdf.generic import ArrayObject, DictionaryObject, NameObject, NumberObject
  article = tmp_path / "article.pdf"
  writer = pypdf.PdfWriter()
  for _ in range(2):
    writer.add_blank_page(width=200, height=200)
  writer.add_outline_item("Its own", 1)
  link = DictionaryObject({
    NameObject("/Type"): NameObject("/Annot"), NameObject("/Subtype"): NameObject("/Link"),
    NameObject("/Rect"): ArrayObject([NumberObject(n) for n in (10, 10, 50, 50)]),
    NameObject("/Dest"): ArrayObject([writer.pages[1].indirect_reference, NameObject("/Fit")]),
  })
  writer.pages[0][NameObject("/Annots")] = ArrayObject([writer._add_object(link)])
  writer.write(article)
  with caplog.at_level("WARNING"):
    out = pdf_insert(booklet, str(article), 2, dst=str(tmp_path / "out.pdf"))
  reader = pypdf.PdfReader(out)
  assert not reader.outline # its bookmarks would stand after all of the booklet's
  dest = reader.pages[1]["/Annots"][0].get_object()["/Dest"][0]
  assert dest == reader.pages[2].indirect_reference # its link leads on to its own page
  assert not [r for r in caplog.records if r.name.startswith("pypdf")]

def an_article_locked_with_aes_goes_in(booklet, tmp_path):
  locked = tmp_path / "locked.pdf"
  writer = pypdf.PdfWriter()
  writer.add_blank_page(width=200, height=200)
  writer.encrypt(user_password="", owner_password="owner", algorithm="AES-256")
  writer.write(locked)
  out = pdf_insert(booklet, str(locked), 2, dst=str(tmp_path / "out.pdf"))
  assert pdf_page_count(out) == 4

def threads_counting_pages_leave_the_pypdf_logger_as_it_was(booklet):
  """Each call quiets pypdf and restores it, so calls from two threads take turns."""
  log = logging.getLogger("pypdf")
  level = log.level
  for _ in range(10): # an unguarded race slips through one round at times, never ten
    threads = [threading.Thread(target=pdf_page_count, args=(booklet,)) for _ in range(8)]
    for thread in threads: thread.start()
    for thread in threads: thread.join()
    assert log.level == level

def page_count_reads_the_pages_and_refuses_a_missing_file(booklet, tmp_path):
  assert pdf_page_count(booklet) == 3
  with pytest.raises(FileNotFoundError):
    pdf_page_count(str(tmp_path / "missing.pdf"))

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
