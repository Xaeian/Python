# xaeian/cli/meta.py

"""`xn meta`: strip metadata from PDFs and images."""

import sys
from ..log import Print
from ..colors import Color as c, grey, fmt_path
from ..files import PATH
from ..media.meta import scrub_metadata
from .args import make_parser, add_help

p = Print()

EXAMPLES = """
examples:
  xn meta report.pdf - strip PDF metadata → report-nometa.pdf
  xn meta photo.jpg - strip EXIF → photo-nometa.jpg
  xn meta photo.jpg -i - strip EXIF in-place
  xn meta scan.png -o clean.png - custom output path
"""

def main() -> None:
  parser = make_parser("Remove metadata from PDFs and images (auto-detects by extension)",
    EXAMPLES)
  parser.add_argument("src", help="Input file path")
  parser.add_argument("-o", "--output", dest="dst", default=None, metavar="PATH",
    help="Output path (default: <name>-nometa.<ext>)")
  parser.add_argument("-i", "--inplace", action="store_true", help="Overwrite source file")
  add_help(parser)
  args = parser.parse_args()
  name = PATH.basename(args.src)
  try:
    result = scrub_metadata(args.src, args.dst, args.inplace)
  except FileNotFoundError:
    p.err(f"File {fmt_path(name, c.ORANGE)} not found")
    sys.exit(1)
  except Exception as e: # an unsupported format says so in its own message
    p.err(f"Failed to scrub {fmt_path(name, c.ORANGE)} | {e}")
    sys.exit(1)
  if PATH.resolve(result) == PATH.resolve(args.src):
    p.ok(f"Scrubbed {fmt_path(name, c.ORANGE)} {grey('(in-place)')}")
  else:
    out_name = PATH.basename(result)
    p.ok(f"Scrubbed {fmt_path(name, c.ORANGE)} → {fmt_path(out_name)}")

if __name__ == "__main__":
  main()
