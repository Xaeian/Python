# xaeian/mf/min.py

"""
Compression for PDFs and images.

Example:
  >>> from xaeian.mf.min import compress
  >>> compress("report.pdf", settings="/ebook")
  >>> compress("photo.jpg", max_px=1280, quality=85)
"""

import os, sys
from typing import Sequence
from xaeian import Print, Color as c
from .utils import PDF_EXTS, IMG_EXTS, require_file

p = Print()

def compress(
  src: str,
  dst: str|None = None,
  inplace: bool = False,
  # PDF
  pdf_level: str = "1.7",
  pdf_settings: str = "/ebook",
  pdf_programs: Sequence[str] = ("gswin64c", "gswin32c", "gs"),
  # Image
  max_px: int = 1920,
  img_format: str = "keep",
  quality: int = 80,
  target_kB: int|None = None,
  avif_speed: int = 6,
  recursive: bool = True,
):
  """Compress file: auto-detects PDF vs image.

  Args:
    src: Input file or directory.
    dst: Output path. None = auto (see `inplace`).
    inplace: If True and dst is None, overwrite source.
    pdf_level: PDF compatibility level.
    pdf_settings: Ghostscript preset.
    pdf_programs: Candidate Ghostscript executables.
    max_px: Max image width/height in pixels.
    img_format: Image format strategy ("keep", "auto", "avif", "webp", "jpg", "png").
    quality: Image starting quality 1-100.
    target_kB: Target image file size in KB.
    avif_speed: AVIF encoder speed 0-10.
    recursive: Walk subdirectories for image directories.

  Returns:
    str for single PDF, list[dict] for image(s).
  """
  if os.path.isdir(src):
    from .img import img_compress
    return img_compress(src, dst, max_px, img_format, quality, target_kB, avif_speed,
      recursive, inplace)
  src = require_file(src, "Input")
  ext = os.path.splitext(src)[1].lower()
  if ext in PDF_EXTS:
    from .pdf import pdf_compress
    return pdf_compress(src, dst, pdf_level, pdf_settings, pdf_programs, inplace)
  if ext in IMG_EXTS:
    from .img import img_compress
    return img_compress(src, dst, max_px, img_format, quality, target_kB, avif_speed,
      recursive, inplace)
  raise ValueError(f"Unsupported format: {ext} (expected PDF, image, or directory)")

EXAMPLES = """
examples:
  xn min report.pdf                   Compress PDF (ebook preset)
  xn min report.pdf -s /screen        Compress PDF for screen
  xn min photo.jpg                    Compress image → photo-min.jpg
  xn min photo.jpg -i                 Compress image in-place
  xn min photos/                      Compress directory recursively
  xn min photos/ --max-px 1280 -q 70  Resize + quality limit
  xn min hero.png -f webp             Convert to WebP
  xn min photos/ --target-kb 200      Fit under 200 kB
"""

def main():
  import argparse
  def fmt(prog):
    return argparse.RawDescriptionHelpFormatter(prog, max_help_position=34, width=90)
  class MinParser(argparse.ArgumentParser):
    def format_help(self): return "\n" + super().format_help().rstrip() + "\n\n"
  parser = MinParser(
    description="Compress PDFs and images: auto-detects by extension",
    formatter_class=fmt,
    add_help=False,
    usage=argparse.SUPPRESS,
    epilog=EXAMPLES,
  )
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
  parser.add_argument("-h", "--help", action="help", help="Show this help message and exit")
  args = parser.parse_args()
  name = os.path.basename(args.src.rstrip("/\\")) or args.src
  ext = os.path.splitext(name)[1].lower()
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
  except ValueError as e:
    p.err(f"Format {c.BLUE}{ext}{c.END} not supported "
      f"{c.GREY}(PDF, image, or directory expected){c.END}")
    sys.exit(1)
  except Exception as e:
    p.err(f"Failed to compress {c.ORANGE}{name}{c.END} | {e}")
    sys.exit(1)
  if isinstance(result, str):
    orig_kB = os.path.getsize(args.src) / 1024
    new_kB = os.path.getsize(result) / 1024
    ratio = (new_kB / orig_kB * 100) if orig_kB else 0
    out_name = os.path.basename(result)
    p.ok(f"Compressed {c.ORANGE}{name}{c.END} → {c.BLUE}{out_name}{c.END}")
    p.gap(f"{c.CYAN}{orig_kB:.0f}{c.END} → {c.CYAN}{new_kB:.0f}{c.END} kB "
      f"{c.GREY}({ratio:.0f}%){c.END}")
  elif isinstance(result, list):
    if not result:
      p.wrn(f"No images found in {c.ORANGE}{name}{c.END}")
      sys.exit(0)
    total_orig, total_new = 0, 0
    for r in result:
      src_name = os.path.basename(r["src"])
      dst_name = os.path.basename(r["dst"])
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