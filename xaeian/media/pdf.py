# xaeian/media/pdf.py

"""
PDF manipulation: compress, merge, split, extract, metadata, text overlay.

Compression shells out to Ghostscript, structure edits use pypdf, text PyMuPDF (fitz).
"""

import os, subprocess
from typing import Literal, NoReturn, Sequence
from pypdf import PdfReader, PdfWriter
from ..files import DIR, FILE
from ..cmd import which
from .utils import require_file, resolve_dst

#-------------------------------------------------------------------------------------------- Types

PdfCompatLevel = Literal["1.2", "1.3", "1.4", "1.5", "1.6", "1.7"]
PdfSettings = Literal["/screen", "/ebook", "/printer", "/prepress", "/default"]

#----------------------------------------------------------------------------------------- Compress

def pdf_compress(
  src:str,
  dst:str|None = None,
  level:PdfCompatLevel = "1.7",
  settings:PdfSettings = "/screen",
  programs:Sequence[str] = ("gswin64c", "gswin32c", "gs"),
  inplace:bool = False,
  verify:bool = True,
) -> str:
  """
  Compress PDF, one of `programs` must be on PATH.

  `settings` ranges from /screen (smallest) to /prepress (largest), it drives image
  downsampling, so a text-only PDF may come out no smaller. `dst` None → `-min` suffix
  beside the source, or the source itself when `inplace`.

  Ghostscript exits 0 on damaged input after writing a stub, so `verify` reads the page count
  before and after and refuses a result that lost pages. A source that cannot be read is refused
  outright, since a conversion cannot be checked against an original nobody can open. Passing
  `verify=False` compresses a malformed file anyway and accepts a silently truncated result.
  """
  src = require_file(src, "PDF")
  src_pages = _page_count(src) if verify else 0
  if verify and not src_pages: _refuse_unreadable(src)
  gs_cmd = which(*programs)
  if gs_cmd is None:
    raise RuntimeError("Ghostscript not found")
  out_path = resolve_dst(src, dst, inplace, "min")
  # GS can't read and write the same file, and a refused result must never reach `out_path`
  base, ext = os.path.splitext(out_path)
  tmp_path = f"{base}-tmp{ext}"
  cmd = [
    gs_cmd,
    "-dNOPAUSE", "-dBATCH", "-dQUIET",
    "-sDEVICE=pdfwrite",
    f"-dCompatibilityLevel={level}",
    f"-dPDFSETTINGS={settings}",
    "-o", tmp_path,
    src,
  ]
  proc = subprocess.run(cmd, check=False)
  if proc.returncode != 0 or not os.path.exists(tmp_path):
    FILE.remove(tmp_path)
    raise RuntimeError(f"Ghostscript failed (code {proc.returncode})")
  out_pages = _page_count(tmp_path) if verify else src_pages
  if out_pages < src_pages:
    FILE.remove(tmp_path)
    raise RuntimeError(f"Ghostscript dropped pages: {out_pages} of {src_pages}")
  os.replace(tmp_path, out_path)
  return out_path

def _page_count(path:str) -> int:
  """Page count, `0` when the file cannot be read as PDF."""
  try:
    return len(PdfReader(path).pages)
  except Exception:
    return 0

def _refuse_unreadable(path:str) -> NoReturn:
  """Raise naming why the PDF could not be read, so the caller knows what to repair."""
  try:
    reason = "encrypted" if PdfReader(path).is_encrypted else "no pages"
  except Exception as e:
    reason = f"malformed ({type(e).__name__})"
  raise RuntimeError(
    f"Cannot read PDF, refusing to compress unverifiable input: {path} - {reason}. "
    "Repair it first, or pass verify=False to compress it unchecked."
  )

#----------------------------------------------------------------------------------------- Metadata

def pdf_scrub_metadata(src:str, dst:str|None=None, inplace:bool=False) -> str:
  """
  Rebuild a PDF with an empty document info dictionary.

  Pages are copied whole, so anything riding on a page (annotations, embedded files) is
  kept: this clears the document info, it does not strip every trace of provenance.
  `dst` None → `-nometa` suffix beside the source, or the source itself when `inplace`.
  """
  src = require_file(src, "PDF")
  reader = PdfReader(src)
  writer = PdfWriter()
  for page in reader.pages:
    writer.add_page(page)
  writer.add_metadata({})
  out_path = resolve_dst(src, dst, inplace, "nometa")
  with open(out_path, "wb") as f:
    writer.write(f)
  return out_path

#---------------------------------------------------------------------------------------- Structure

def pdf_merge(paths:Sequence[str], dst:str) -> str:
  """Merge PDFs into one, pages in the order `paths` are given."""
  if not paths:
    raise ValueError("No input files")
  writer = PdfWriter()
  for path in paths:
    path = require_file(path, "PDF")
    for page in PdfReader(path).pages:
      writer.add_page(page)
  dst = os.path.abspath(dst)
  DIR.ensure(dst)
  with open(dst, "wb") as f:
    writer.write(f)
  return dst

def pdf_split(src:str, dst_dir:str, prefix:str="page") -> list[str]:
  """Split PDF into one file per page, named `<prefix>_001.pdf` upward."""
  src = require_file(src, "PDF")
  dst_dir = os.path.abspath(dst_dir)
  os.makedirs(dst_dir, exist_ok=True)
  reader = PdfReader(src)
  created: list[str] = []
  for i, page in enumerate(reader.pages, 1):
    writer = PdfWriter()
    writer.add_page(page)
    out_path = os.path.join(dst_dir, f"{prefix}_{i:03d}.pdf")
    with open(out_path, "wb") as f:
      writer.write(f)
    created.append(out_path)
  return created

#-------------------------------------------------------------------------------------------- Pages

def parse_pages(spec:str|int|Sequence[str|int], total:int) -> list[int]:
  """
  Parse a 1-based page spec into sorted 0-based indices.

  `spec` takes 5, "1,3,5-7,!2" or [1, "5-7", "!2"]: `!` excludes, an open range "5-"
  runs to `total`, and a spec holding only exclusions starts from every page. Numbers
  beyond `total` are dropped silently, so an over-wide range is a safe way to say "rest".
  """
  if isinstance(spec, int): spec = str(spec)
  elif not isinstance(spec, str): spec = ",".join(str(x) for x in spec)
  include: set[int] = set()
  exclude: set[int] = set()
  has_include = False
  for part in spec.replace(" ", "").split(","):
    if not part: continue
    neg = part.startswith("!")
    if neg: part = part[1:]
    if "-" in part:
      a, b = part.split("-", 1)
      rng = set(range(int(a), (int(b) if b else total) + 1))
    else:
      rng = {int(part)}
    if neg: exclude |= rng
    else:
      include |= rng
      has_include = True
  if not has_include:
    include = set(range(1, total + 1))
  result = sorted((include - exclude) & set(range(1, total + 1)))
  return [p - 1 for p in result]

def pdf_extract(src:str, dst:str, pages:str|int|Sequence[str|int]) -> str:
  """Extract pages into a new PDF, `pages` in the 1-based spec of `parse_pages`."""
  src = require_file(src, "PDF")
  reader = PdfReader(src)
  indices = parse_pages(pages, len(reader.pages))
  writer = PdfWriter()
  for i in indices:
    writer.add_page(reader.pages[i])
  dst = os.path.abspath(dst)
  DIR.ensure(dst)
  with open(dst, "wb") as f:
    writer.write(f)
  return dst

#--------------------------------------------------------------------------------------------- Text

# PyMuPDF base-14 codes: helv/tiro/cour = Helvetica/Times/Courier regular, a bo/it/bi ending
# marks bold, italic, bold-italic; symb = Symbol, zadb = ZapfDingbats
FitzFontname = Literal[
  "helv", "hebo", "heit", "hebi",
  "tiro", "tibo", "tiit", "tibi",
  "cour", "cobo", "coit", "cobi",
  "symb", "zadb",
]

def pdf_add_text(
  src:str,
  dst:str|None = None,
  text:str = "",
  pos:tuple[float, float] = (50, 50),
  fontname:FitzFontname = "helv",
  fontsize:float = 12,
  color:tuple[float, float, float] = (0, 0, 0),
  pages:Sequence[int]|None = None,
  inplace:bool = False,
) -> str:
  """
  Add a text overlay to PDF pages.

  Args:
    dst: None → `-text` suffix beside the source, or the source itself when `inplace`.
    pos: (x, y) in points from the top-left corner, marking the text baseline start.
      `fontsize` is in points as well, 72 to the inch.
    color: RGB, 0.0-1.0 per channel.
    pages: 0-based indices, None → every page.
  """
  import fitz
  src = require_file(src, "PDF")
  out_path = resolve_dst(src, dst, inplace, "text")
  doc = fitz.open(src)
  for i, page in enumerate(doc):
    if pages is None or i in pages:
      page.insert_text(pos, text, fontname=fontname, fontsize=fontsize, color=color)
  # Fitz can't save over the file it opened
  if out_path == src:
    base, ext = os.path.splitext(src)
    tmp_path = f"{base}-tmp{ext}"
    doc.save(tmp_path)
    doc.close()
    os.replace(tmp_path, src)
  else:
    doc.save(out_path)
    doc.close()
  return out_path