# xaeian/cli/meta.py

"""`xn meta` - strip metadata from PDFs and images."""

import os, sys
from ..log import Print
from ..colors import Color as c
from ..files import PATH
from ..media.meta import scrub_metadata
from .args import make_parser, add_help

p = Print()

EXAMPLES = """
examples:
  xn meta report.pdf             Strip PDF metadata → report-nometa.pdf
  xn meta photo.jpg              Strip EXIF → photo-nometa.jpg
  xn meta photo.jpg -i           Strip EXIF in-place
  xn meta scan.png -o clean.png  Custom output path
"""

def main() -> None:
  parser = make_parser("Remove metadata from PDFs and images (auto-detects by extension)",
    EXAMPLES)
  parser.add_argument("src", help="Input file path")
  parser.add_argument("-o", "--output", dest="dst", default=None, metavar="PATH",
    help="Output path (default: <n>-nometa.<ext>)")
  parser.add_argument("-i", "--inplace", action="store_true", help="Overwrite source file")
  add_help(parser)
  args = parser.parse_args()
  name = PATH.basename(args.src)
  ext = PATH.ext(name).lower()
  try:
    result = scrub_metadata(args.src, args.dst, args.inplace)
  except FileNotFoundError:
    p.err(f"File {c.ORANGE}{name}{c.END} not found")
    sys.exit(1)
  except ValueError:
    p.err(f"Format {c.BLUE}{ext}{c.END} not supported {c.GREY}(PDF or image expected){c.END}")
    sys.exit(1)
  except Exception as e:
    p.err(f"Failed to scrub {c.ORANGE}{name}{c.END} | {e}")
    sys.exit(1)
  if PATH.resolve(result) == PATH.resolve(args.src):
    p.ok(f"Scrubbed {c.ORANGE}{name}{c.END} {c.GREY}(in-place){c.END}")
  else:
    out_name = PATH.basename(result)
    p.ok(f"Scrubbed {c.ORANGE}{name}{c.END} → {c.BLUE}{out_name}{c.END}")

if __name__ == "__main__":
  main()
