# xaeian/mf/pdf.py

"""
PDF manipulation: compress, merge, split, extract, metadata, text overlay.

Uses Ghostscript for compression, pypdf for structure, PyMuPDF (fitz) for text.

Example:
  >>> from xaeian.mf.pdf import pdf_compress, pdf_merge, pdf_extract
  >>> pdf_compress("report.pdf", settings="/ebook")
  >>> pdf_merge(["p1.pdf", "p2.pdf"], "combined.pdf")
  >>> pdf_extract("report.pdf", "pages.pdf", "1,3,5-7")
"""

import os, subprocess
from typing import Literal, Sequence
from pypdf import PdfReader, PdfWriter
from ..files import DIR
from ..cmd import which
from .utils import require_file, resolve_dst

#--------------------------------------------------------------------------------------- Types

PdfCompatLevel = Literal["1.2", "1.3", "1.4", "1.5", "1.6", "1.7"]
PdfSettings = Literal["/screen", "/ebook", "/printer", "/prepress", "/default"]

#----------------------------------------------------------------------------------- Compress

def pdf_compress(
  src: str,
  dst: str|None = None,
  level: PdfCompatLevel = "1.7",
  settings: PdfSettings = "/ebook",
  programs: Sequence[str] = ("gswin64c", "gswin32c", "gs"),
  inplace: bool = False,
) -> str:
  """Compress PDF using Ghostscript.

  Args:
    src: Input PDF path.
    dst: Output path. None = auto (see `inplace`).
    level: PDF compatibility level.
    settings: Ghostscript preset (/screen, /ebook, /printer, /prepress).
    programs: Candidate Ghostscript executables.
    inplace: If True and dst is None, overwrite source. Otherwise add -min suffix.

  Returns:
    Output file path.
  """
  src = require_file(src, "PDF")
  gs_cmd = which(*programs)
  if gs_cmd is None:
    raise RuntimeError("Ghostscript not found")
  out_path = resolve_dst(src, dst, inplace, "min")
  # Inplace needs tmp file: GS can't read and write same file
  if inplace and dst is None:
    base, ext = os.path.splitext(src)
    tmp_path = f"{base}-tmp{ext}"
  else:
    tmp_path = out_path
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
    raise RuntimeError(f"Ghostscript failed (code {proc.returncode})")
  if inplace and dst is None:
    os.replace(tmp_path, src)
  return out_path

#------------------------------------------------------------------------------------- Metadata

def pdf_scrub_metadata(src:str, dst:str|None=None, inplace:bool=False) -> str:
  """Remove all metadata from PDF.

  Args:
    src: Input PDF path.
    dst: Output path. None = auto (see `inplace`).
    inplace: If True and dst is None, overwrite source. Otherwise add -nometa suffix.

  Returns:
    Output file path.
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

#------------------------------------------------------------------------------------- Structure

def pdf_merge(paths:Sequence[str], dst:str) -> str:
  """Merge multiple PDFs into one.

  Args:
    paths: List of input PDF paths.
    dst: Output file path.

  Returns:
    Output file path.
  """
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
  """Split PDF into single-page files.

  Args:
    src: Input PDF path.
    dst_dir: Output directory.
    prefix: Filename prefix (creates prefix_001.pdf, prefix_002.pdf...).

  Returns:
    List of created file paths.
  """
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

#--------------------------------------------------------------------------------------- Pages

def parse_pages(spec:str|int|Sequence[str|int], total:int) -> list[int]:
  """Parse page specification into 0-based indices.

  Args:
    spec: Page spec (1-based): int, str "1,3,5-7,!2", or list [1, "5-7", "!2"].
    total: Total number of pages in document.

  Returns:
    Sorted list of 0-based page indices.
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
  """Extract selected pages from PDF.

  Args:
    src: Input PDF path.
    dst: Output file path.
    pages: Page specification (1-based). Supports:
      int (5), str ("1,3,5-7,!2"), list ([1, 3, "5-7", "!2"]).

  Returns:
    Output file path.
  """
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

#---------------------------------------------------------------------------------------- Text

FitzFontname = Literal[
  "helv", "hebo", "heit", "hebi",
  "tiro", "tibo", "tiit", "tibi",
  "cour", "cobo", "coit", "cobi",
  "symb", "zadb",
]

def pdf_add_text(
  src: str,
  dst: str|None = None,
  text: str = "",
  pos: tuple[float, float] = (50, 50),
  fontname: FitzFontname = "helv",
  fontsize: float = 12,
  color: tuple[float, float, float] = (0, 0, 0),
  pages: Sequence[int]|None = None,
  inplace: bool = False,
) -> str:
  """Add text overlay to PDF pages using PyMuPDF.

  Args:
    src: Input PDF path.
    dst: Output path. None = auto (see `inplace`).
    text: Text to insert.
    pos: (x, y) position in points from top-left.
    fontname: Built-in PDF font name.
    fontsize: Font size in points.
    color: RGB color tuple (0.0-1.0 per channel).
    pages: 0-based page indices to annotate. None = all pages.
    inplace: If True and dst is None, overwrite source. Otherwise add -text suffix.

  Returns:
    Output file path.
  """
  import fitz
  src = require_file(src, "PDF")
  out_path = resolve_dst(src, dst, inplace, "text")
  doc = fitz.open(src)
  for i, page in enumerate(doc):
    if pages is None or i in pages:
      page.insert_text(pos, text, fontname=fontname, fontsize=fontsize, color=color)
  # Fitz can't save to same file: use tmp + replace
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