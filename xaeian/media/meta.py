# xaeian/media/meta.py

"""
Metadata removal for PDFs and images.

Example:
  >>> from xaeian.media.meta import scrub_metadata
  >>> scrub_metadata("report.pdf")
  >>> scrub_metadata("photo.jpg", inplace=True)
"""

import os, sys
from xaeian import Print, Color as c
from .utils import PDF_EXTS, IMG_EXTS, require_file

p = Print()

def scrub_metadata(src:str, dst:str|None=None, inplace:bool=False) -> str:
  """Remove metadata from file: auto-detects PDF vs image.

  Args:
    src: Input file path.
    dst: Output path. None = auto (see `inplace`).
    inplace: If True and dst is None, overwrite source. Otherwise add -nometa suffix.

  Returns:
    Output file path.
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

EXAMPLES = """
examples:
  xn meta report.pdf             Strip PDF metadata → report-nometa.pdf
  xn meta photo.jpg              Strip EXIF → photo-nometa.jpg
  xn meta photo.jpg -i           Strip EXIF in-place
  xn meta scan.png -o clean.png  Custom output path
"""

def main():
  import argparse
  def fmt(prog):
    return argparse.RawDescriptionHelpFormatter(prog, max_help_position=34, width=90)
  class MetaParser(argparse.ArgumentParser):
    def format_help(self): return "\n" + super().format_help().rstrip() + "\n\n"
  parser = MetaParser(
    description="Remove metadata from PDFs and images (auto-detects by extension)",
    formatter_class=fmt,
    add_help=False,
    usage=argparse.SUPPRESS,
    epilog=EXAMPLES,
  )
  parser.add_argument("src", help="Input file path")
  parser.add_argument("-o", "--output", dest="dst", default=None, metavar="PATH",
    help="Output path (default: <n>-nometa.<ext>)")
  parser.add_argument("-i", "--inplace", action="store_true", help="Overwrite source file")
  parser.add_argument("-h", "--help", action="help", help="Show this help message and exit")
  args = parser.parse_args()
  name = os.path.basename(args.src)
  ext = os.path.splitext(name)[1].lower()
  try:
    result = scrub_metadata(args.src, args.dst, args.inplace)
  except FileNotFoundError:
    p.err(f"File {c.ORANGE}{name}{c.END} not found")
    sys.exit(1)
  except ValueError as e:
    p.err(f"Format {c.BLUE}{ext}{c.END} not supported {c.GREY}(PDF or image expected){c.END}")
    sys.exit(1)
  except Exception as e:
    p.err(f"Failed to scrub {c.ORANGE}{name}{c.END} | {e}")
    sys.exit(1)
  out_name = os.path.basename(result)
  if args.inplace:
    p.ok(f"Scrubbed {c.ORANGE}{name}{c.END} {c.GREY}(in-place){c.END}")
  else:
    p.ok(f"Scrubbed {c.ORANGE}{name}{c.END} → {c.BLUE}{out_name}{c.END}")

if __name__ == "__main__":
  main()