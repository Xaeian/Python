# xaeian/media/ico.py

"""
Image to ICO conversion -- multi-size favicon generator.

Uses Pillow for image processing, writes ICO manually for full control.

Example:
  >>> from xaeian.media.ico import img_to_ico
  >>> img_to_ico("logo.png")
  >>> img_to_ico("photo.jpg", sizes=[16, 32, 48], fit="crop")
"""

import os, sys, struct
from io import BytesIO
from typing import Literal
from xaeian import Print, Color as c
from .utils import require_file

try:
  from PIL import Image, ImageOps
except ImportError:
  raise ImportError("Pillow is required: pip install Pillow")

p = Print()

DEFAULT_SIZES = [16, 20, 24, 32, 40, 48, 64, 96, 128, 256]

FitMode = Literal["pad", "crop"]

#----------------------------------------------------------------------------------- Internals

def _make_square(img:Image.Image, fit:FitMode) -> Image.Image:
  w, h = img.size
  if w == h:
    return img
  if fit == "crop":
    s = min(w, h)
    x0, y0 = (w - s) // 2, (h - s) // 2
    return img.crop((x0, y0, x0 + s, y0 + s))
  s = max(w, h)
  out = Image.new("RGBA", (s, s), (0, 0, 0, 0))
  out.paste(img, ((s - w) // 2, (s - h) // 2))
  return out

def _pick_sizes(max_side:int, sizes:list[int]|None, upscale:bool) -> list[int]:
  pool = sizes if sizes else DEFAULT_SIZES
  if upscale:
    return sorted(pool)
  picked = [s for s in pool if s <= max_side]
  return sorted(picked) if picked else [max_side]

def _write_ico(path:str, sizes:list[int], blobs:list[bytes]):
  count = len(sizes)
  header = struct.pack("<HHH", 0, 1, count)
  entries = []
  offset = 6 + 16 * count
  for s, blob in zip(sizes, blobs):
    w = 0 if s == 256 else s
    entries.append(struct.pack("<BBBBHHII", w, w, 0, 0, 1, 32, len(blob), offset))
    offset += len(blob)
  with open(path, "wb") as f:
    f.write(header)
    for e in entries:
      f.write(e)
    for blob in blobs:
      f.write(blob)

#----------------------------------------------------------------------------------------- API

def img_to_ico(
  src: str,
  dst: str|None = None,
  sizes: list[int]|None = None,
  fit: FitMode = "pad",
  upscale: bool = False,
) -> str:
  """Convert image to multi-size .ico file.

  Args:
    src: Input image path (png/jpg/webp/...).
    dst: Output .ico path. None = same name with .ico extension.
    sizes: Icon sizes to include. None = auto from DEFAULT_SIZES.
    fit: Non-square handling -- "pad" (transparent padding) or "crop" (center crop).
    upscale: Allow sizes larger than source image.

  Returns:
    Output file path.
  """
  src = require_file(src, "Image")
  try:
    img = ImageOps.exif_transpose(Image.open(src)).convert("RGBA")
  except Exception as e:
    raise ValueError(f"Cannot open image: {e}")
  img = _make_square(img, fit)
  icon_sizes = _pick_sizes(max(img.size), sizes, upscale)
  resample = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
  blobs = []
  for s in icon_sizes:
    bio = BytesIO()
    img.resize((s, s), resample=resample).save(bio, format="PNG", optimize=True)
    blobs.append(bio.getvalue())
  out_path = os.path.abspath(dst) if dst else os.path.splitext(src)[0] + ".ico"
  _write_ico(out_path, icon_sizes, blobs)
  return out_path

#----------------------------------------------------------------------------------------- CLI

EXAMPLES = """
examples:
  xn ico logo.png                   Auto sizes -> logo.ico
  xn ico logo.png -o favicon.ico    Custom output
  xn ico photo.jpg --fit crop       Center-crop to square
  xn ico logo.png --sizes 16,32,48  Specific sizes
  xn ico logo.png --upscale         Include sizes > source
"""

def main():
  import argparse
  def fmt(prog):
    return argparse.RawDescriptionHelpFormatter(prog, max_help_position=34, width=90)
  class IcoParser(argparse.ArgumentParser):
    def format_help(self): return "\n" + super().format_help().rstrip() + "\n\n"
  parser = IcoParser(
    description="Convert image to multi-size .ico (auto-picks sizes from source)",
    formatter_class=fmt,
    add_help=False,
    usage=argparse.SUPPRESS,
    epilog=EXAMPLES,
  )
  parser.add_argument("src", help="Input image path")
  parser.add_argument("-o", "--output", dest="dst", default=None, metavar="PATH",
    help="Output .ico path (default: <n>.ico)")
  parser.add_argument("--fit", choices=["pad", "crop"], default="pad",
    help="Non-square handling (default: pad)")
  parser.add_argument("--sizes", default=None, metavar="LIST",
    help="Comma-separated sizes (default: auto)")
  parser.add_argument("--upscale", action="store_true",
    help="Allow upscaling beyond source size")
  parser.add_argument("-h", "--help", action="help", help="Show this help message and exit")
  args = parser.parse_args()
  name = os.path.basename(args.src)
  sizes = None
  if args.sizes:
    try:
      sizes = [int(s.strip()) for s in args.sizes.split(",")]
      if any(s < 1 or s > 512 for s in sizes):
        p.err(f"Sizes must be {c.CYAN}1{c.END}–{c.CYAN}512{c.END} px")
        sys.exit(1)
    except ValueError:
      p.err(f"Invalid sizes {c.BLUE}{args.sizes}{c.END} {c.GREY}(expected comma-separated "
        f"integers){c.END}")
      sys.exit(1)
  try:
    result = img_to_ico(args.src, args.dst, sizes, args.fit, args.upscale)
  except FileNotFoundError:
    p.err(f"File {c.ORANGE}{name}{c.END} not found")
    sys.exit(1)
  except ValueError as e:
    p.err(f"Cannot process {c.ORANGE}{name}{c.END} | {e}")
    sys.exit(1)
  except Exception as e:
    p.err(f"Failed to convert {c.ORANGE}{name}{c.END} | {e}")
    sys.exit(1)
  out_name = os.path.basename(result)
  img = Image.open(args.src)
  src_w, src_h = img.size
  icon_sizes = _pick_sizes(max(src_w, src_h), sizes, args.upscale)
  sizes_str = f"{c.GREY},{c.END}".join(f"{c.CYAN}{s}{c.END}" for s in icon_sizes)
  file_kB = os.path.getsize(result) / 1024
  p.ok(f"Converted {c.ORANGE}{name}{c.END} → {c.BLUE}{out_name}{c.END} "
    f"{c.GREY}({file_kB:.1f} kB){c.END}")
  p.gap(f"Source: {c.CYAN}{src_w}{c.END}×{c.CYAN}{src_h}{c.END} px, "
    f"fit: {c.BLUE}{args.fit}{c.END}, "
    f"sizes: [{sizes_str}]")

if __name__ == "__main__":
  main()