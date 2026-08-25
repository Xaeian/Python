# xaeian/cli/min.py

"""`xn min` - compress PDFs and images."""

import os, sys
from ..log import Print
from ..colors import Color as c
from ..files import PATH, FILE
from ..media.min import compress
from .args import make_parser, add_help

p = Print()

EXAMPLES = """
examples:
  xn min report.pdf                   Compress PDF (ebook preset)
  xn min report.pdf -s /screen        Compress PDF for screen
  xn min photo.jpg                    Compress image → photo-min.jpg
  xn min photo.jpg -i                 Compress image in-place
  xn min photos/                      Compress directory recursively
  xn min photos/ --max-px 1280 -q 70  Resize + quality limit
  xn min hero.png -f webp             Convert to WebP
  xn min photos/ --target-kb 200      Fit under 200kB
"""

def main() -> None:
  parser = make_parser("Compress PDFs and images: auto-detects by extension", EXAMPLES)
  parser.add_argument("src", help="Input file or directory")
  parser.add_argument("-o", "--output", dest="dst", default=None, metavar="PATH",
    help="Output path (default: <n>-min.<ext>)")
  parser.add_argument("-i", "--inplace", action="store_true", help="Overwrite source file")
  parser.add_argument("-s", "--pdf-settings", default="/ebook", metavar="PRESET",
    choices=["/screen", "/ebook", "/printer", "/prepress", "/default"],
    help="Ghostscript preset: /screen /ebook /printer /prepress")
  parser.add_argument("--pdf-level", default="1.7", metavar="VER",
    help="PDF compatibility level (default: 1.7)")
  parser.add_argument("--max-px", type=int, default=1920, metavar="PX",
    help="Max width/height in pixels (default: 1920)")
  parser.add_argument("-f", "--format", dest="img_format", default="keep", metavar="FMT",
    choices=["keep", "auto", "avif", "webp", "jpg", "png"],
    help="Format: keep auto avif webp jpg png (default: keep)")
  parser.add_argument("-q", "--quality", type=int, default=80, metavar="Q",
    help="Image quality 1-100 (default: 80)")
  parser.add_argument("--target-kb", type=int, default=None, metavar="KB",
    help="Target file size in kB (steps quality down)")
  parser.add_argument("--avif-speed", type=int, default=6, metavar="N",
    help="AVIF encoder speed 0-10 (default: 6)")
  parser.add_argument("--no-recursive", action="store_true",
    help="Don't walk subdirectories")
  add_help(parser)
  args = parser.parse_args()
  name = PATH.basename(args.src.rstrip("/\\")) or args.src
  ext = PATH.ext(name).lower()
  try:
    result = compress(
      args.src, args.dst, args.inplace,
      args.pdf_level, args.pdf_settings,
      max_px=args.max_px, img_format=args.img_format, quality=args.quality,
      target_kB=args.target_kb, avif_speed=args.avif_speed,
      recursive=not args.no_recursive,
    )
  except FileNotFoundError:
    p.err(f"File {c.ORANGE}{name}{c.END} not found")
    sys.exit(1)
  except ValueError:
    p.err(f"Format {c.BLUE}{ext}{c.END} not supported "
      f"{c.GREY}(PDF, image, or directory expected){c.END}")
    sys.exit(1)
  except Exception as e:
    p.err(f"Failed to compress {c.ORANGE}{name}{c.END} | {e}")
    sys.exit(1)
  if not result:
    p.wrn(f"Nothing compressed in {c.ORANGE}{name}{c.END}")
    sys.exit(0)
  total_orig, total_new = 0, 0
  for r in result:
    src_name = PATH.basename(r["src"])
    dst_name = PATH.basename(r["dst"])
    ratio = (r["new_kB"] / r["orig_kB"] * 100) if r["orig_kB"] else 0
    p.ok(f"{c.ORANGE}{src_name}{c.END} → {c.BLUE}{dst_name}{c.END} "
      f"{c.CYAN}{r['orig_kB']:.0f}{c.END}→{c.CYAN}{r['new_kB']:.0f}{c.END} kB "
      f"{c.GREY}({ratio:.0f}%){c.END}")
    total_orig += r["orig_kB"]
    total_new += r["new_kB"]
  if len(result) > 1:
    total_ratio = (total_new / total_orig * 100) if total_orig else 0
    p.inf(f"Total: {c.CYAN}{total_orig:.0f}{c.END} → {c.CYAN}{total_new:.0f}{c.END} kB "
      f"{c.GREY}({total_ratio:.0f}%, {len(result)} files){c.END}")

if __name__ == "__main__":
  main()
