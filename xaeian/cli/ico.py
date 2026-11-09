# xaeian/cli/ico.py

"""`xn ico` - convert an image to a multi-size .ico."""

import os, sys
from ..log import Print
from ..colors import Color as c, grey, fmt_path
from ..files import PATH
from ..media.ico import img_to_ico, pick_sizes, source_side
from .args import make_parser, add_help

p = Print()

EXAMPLES = """
examples:
  xn ico logo.png                   # sizes picked from the source → logo.ico
  xn ico logo.png -o favicon.ico    # custom output path
  xn ico photo.jpg --fit crop       # center-crop to square
  xn ico logo.png --sizes 16,32,48  # only these sizes
  xn ico logo.png --upscale         # include sizes larger than the source
"""

def main() -> None:
  parser = make_parser("Convert image to multi-size .ico (auto-picks sizes from source)",
    EXAMPLES)
  parser.add_argument("src", help="Input image path")
  parser.add_argument("-o", "--output", dest="dst", default=None, metavar="PATH",
    help="Output .ico path (default: <name>.ico)")
  parser.add_argument("--fit", choices=["pad", "crop"], default="pad",
    help="Non-square handling (default: pad)")
  parser.add_argument("--sizes", default=None, metavar="LIST",
    help="Comma-separated sizes (default: auto)")
  parser.add_argument("--upscale", action="store_true",
    help="Allow upscaling beyond source size")
  add_help(parser)
  args = parser.parse_args()
  name = PATH.basename(args.src)
  sizes = None
  if args.sizes:
    try:
      sizes = [int(s.strip()) for s in args.sizes.split(",")]
    except ValueError:
      p.err(f"Invalid sizes {c.BLUE}{args.sizes}{c.END} "
        f"{grey('(expected comma-separated integers)')}")
      sys.exit(1)
  try:
    result = img_to_ico(args.src, args.dst, sizes, args.fit, args.upscale)
  except FileNotFoundError:
    p.err(f"File {fmt_path(name, c.ORANGE)} not found")
    sys.exit(1)
  except ValueError as e:
    p.err(f"Cannot process {fmt_path(name, c.ORANGE)} | {e}")
    sys.exit(1)
  except Exception as e:
    p.err(f"Failed to convert {fmt_path(name, c.ORANGE)} | {e}")
    sys.exit(1)
  out_name = PATH.basename(result)
  src_w, src_h, side = source_side(args.src, args.fit)
  icon_sizes = pick_sizes(side, sizes, args.upscale)
  sizes_str = grey(",").join(f"{c.CYAN}{s}{c.END}" for s in icon_sizes)
  file_kB = os.path.getsize(result) / 1024
  p.ok(f"Converted {fmt_path(name, c.ORANGE)} → {fmt_path(out_name)} "
    f"{grey(f'({file_kB:.1f}kB)')}")
  p.gap(f"Source: {c.CYAN}{src_w}{c.END}×{c.CYAN}{src_h}{c.END}px, "
    f"fit: {c.BLUE}{args.fit}{c.END}, "
    f"sizes: [{sizes_str}]")

if __name__ == "__main__":
  main()
