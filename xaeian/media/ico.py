# xaeian/media/ico.py

"""
Image to ICO conversion -- multi-size favicon generator.

Uses Pillow for image processing, writes ICO manually for full control.

Example:
  >>> from xaeian.media.ico import img_to_ico
  >>> img_to_ico("logo.png")
  >>> img_to_ico("photo.jpg", sizes=[16, 32, 48], fit="crop")
"""

import os, struct
from io import BytesIO
from typing import Literal
from PIL import Image, ImageOps
from .utils import require_file

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
  img = ImageOps.exif_transpose(Image.open(src)).convert("RGBA")
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
  sizes = [int(s) for s in args.sizes.split(",")] if args.sizes else None
  print(img_to_ico(args.src, args.dst, sizes, args.fit, args.upscale))

if __name__ == "__main__":
  main()