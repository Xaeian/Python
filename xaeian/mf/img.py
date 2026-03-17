# xaeian/mf/img.py

"""
Image manipulation: resize, convert, compress, metadata.

Uses Pillow for all operations.

Example:
  >>> from xaeian.mf.img import img_resize, img_compress
  >>> img_resize("photo.jpg", width=800)
  >>> img_compress("photos/", "out/", max_px=1280, quality=85)
"""

import os
from io import BytesIO
from typing import Literal
from PIL import Image, ImageOps
from ..files import DIR
from .utils import IMG_EXTS, require_file, resolve_dst

#---------------------------------------------------------------------------------------- Types

ImgFormat = Literal["keep", "auto", "avif", "webp", "jpg", "png"]

#------------------------------------------------------------------------------------ Internals

def _has_alpha(img:Image.Image) -> bool:
  return img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)

def _flatten_rgb(img:Image.Image, bg:tuple=(255, 255, 255)) -> Image.Image:
  """Flatten alpha to RGB with background color."""
  if _has_alpha(img):
    base = Image.new("RGB", img.size, bg)
    if img.mode != "RGBA":
      img = img.convert("RGBA")
    base.paste(img, mask=img.split()[-1])
    return base
  return img.convert("RGB") if img.mode != "RGB" else img

def _resize_max(img:Image.Image, max_px:int) -> tuple[Image.Image, tuple, tuple]:
  """Resize to fit within `max_px`, keeping aspect ratio."""
  w, h = img.size
  scale = min(max_px / max(w, h), 1.0)
  if scale < 1.0:
    new_size = (max(1, int(w * scale)), max(1, int(h * scale)))
    return img.resize(new_size, Image.LANCZOS), (w, h), new_size
  return img, (w, h), (w, h)

def _try_encode(img:Image.Image, fmt:str, quality:int, avif_speed:int=6) -> bytes|None:
  """Encode image to bytes. Returns None on failure."""
  bio = BytesIO()
  try:
    if fmt == "AVIF":
      img.save(bio, format="AVIF", quality=quality, speed=avif_speed)
    elif fmt == "WEBP":
      img.save(bio, format="WEBP", quality=quality, method=6, optimize=True)
    elif fmt == "JPEG":
      _flatten_rgb(img).save(
        bio, format="JPEG", quality=quality,
        optimize=True, progressive=True, subsampling="4:2:0",
      )
    elif fmt == "PNG":
      out = img
      if out.mode == "P":
        out = out.convert("RGBA") if _has_alpha(out) else out.convert("RGB")
      out.save(bio, format="PNG", optimize=True, compress_level=9)
    else:
      return None
    return bio.getvalue()
  except Exception:
    return None

def _fmt_from_ext(ext:str) -> tuple[str, str]|None:
  """Map extension to (PIL format, canonical extension)."""
  if ext in (".jpg", ".jpeg"): return ("JPEG", ".jpg")
  if ext == ".png": return ("PNG", ".png")
  if ext == ".avif": return ("AVIF", ".avif")
  if ext == ".webp": return ("WEBP", ".webp")
  return None

def _pick_formats(req:ImgFormat, img:Image.Image, src_ext:str) -> list[tuple[str, str]]:
  """Build ordered format list for encoding attempts."""
  if req == "keep":
    m = _fmt_from_ext(src_ext)
    if m: return [m]
    return [("JPEG", ".jpg")]
  if req == "avif":
    return [("AVIF", ".avif"), ("WEBP", ".webp"), ("JPEG", ".jpg")]
  if req == "webp":
    return [("WEBP", ".webp"), ("AVIF", ".avif"), ("JPEG", ".jpg")]
  if req == "jpg":
    return [("JPEG", ".jpg")]
  if req == "png":
    return [("PNG", ".png")]
  # auto: size-first
  if _has_alpha(img):
    return [("WEBP", ".webp"), ("AVIF", ".avif"), ("PNG", ".png"), ("JPEG", ".jpg")]
  return [("AVIF", ".avif"), ("WEBP", ".webp"), ("JPEG", ".jpg"), ("PNG", ".png")]

def _encode_best(
  img: Image.Image,
  fmt_order: list[tuple[str, str]],
  quality: int,
  target_kB: int|None = None,
  avif_speed: int = 6,
  pick_smallest: bool = False,
) -> tuple[bytes|None, str|None, str|None, int|None]:
  """Try formats in order, optionally stepping down quality to hit target size.

  When `pick_smallest` is True, tries all formats and returns the smallest
  result instead of the first successful encode.
  """
  q_start = max(1, min(100, quality))
  q_min, step = 35, 5
  best = None
  for fmt, ext in fmt_order:
    data = _try_encode(img, fmt, q_start, avif_speed)
    if data is None: continue
    if fmt == "PNG":
      candidate = (data, fmt, ext, q_start)
      if target_kB is not None and len(data) > target_kB * 1024:
        if best is None or len(data) < len(best[0]): best = candidate
        continue
      if best is None or len(data) < len(best[0]): best = candidate
      if not pick_smallest: return best
      continue
    if target_kB is None:
      candidate = (data, fmt, ext, q_start)
      if best is None or len(data) < len(best[0]): best = candidate
      if not pick_smallest: return best
      continue
    target_bytes = target_kB * 1024
    q = q_start
    while q >= q_min:
      data = _try_encode(img, fmt, q, avif_speed)
      if data is None: break
      if len(data) <= target_bytes:
        candidate = (data, fmt, ext, q)
        if best is None or len(data) < len(best[0]): best = candidate
        if not pick_smallest: return best
        break
      if best is None or len(data) < len(best[0]):
        best = (data, fmt, ext, q)
      q -= step
  if best: return best
  return None, None, None, None

#------------------------------------------------------------------------------------- Metadata

def img_scrub_metadata(src:str, dst:str|None=None, inplace:bool=False) -> str:
  """Remove all metadata (EXIF, etc.) from image.

  Args:
    src: Input image path.
    dst: Output path. None = auto (see `inplace`).
    inplace: If True and dst is None, overwrite source. Otherwise add -nometa suffix.

  Returns:
    Output file path.
  """
  src = require_file(src, "Image")
  image = Image.open(src)
  data = list(image.getdata())
  clean = Image.new(image.mode, image.size)
  clean.putdata(data)
  out_path = resolve_dst(src, dst, inplace, "nometa")
  clean.save(out_path)
  return out_path

#-------------------------------------------------------------------------------------- Resize

def img_resize(
  src: str,
  dst: str|None = None,
  width: int|None = None,
  height: int|None = None,
  scale: float|None = None,
  inplace: bool = False,
) -> str:
  """Resize image.

  Args:
    src: Input image path.
    dst: Output path. None = auto (see `inplace`).
    width: Target width (keeps aspect if height=None).
    height: Target height (keeps aspect if width=None).
    scale: Scale factor (e.g. 0.5 = half size). Ignored if width/height set.
    inplace: If True and dst is None, overwrite source. Otherwise add -resized suffix.

  Returns:
    Output file path.
  """
  src = require_file(src, "Image")
  image = Image.open(src)
  orig_w, orig_h = image.size
  if width and height:
    new_size = (width, height)
  elif width:
    new_size = (width, int(orig_h * width / orig_w))
  elif height:
    new_size = (int(orig_w * height / orig_h), height)
  elif scale:
    new_size = (int(orig_w * scale), int(orig_h * scale))
  else:
    raise ValueError("Specify width, height, or scale")
  resized = image.resize(new_size, Image.LANCZOS)
  out_path = resolve_dst(src, dst, inplace, "resized")
  resized.save(out_path)
  return out_path

#------------------------------------------------------------------------------------- Convert

def img_convert(src:str, dst:str, quality:int=90) -> str:
  """Convert image to different format (detected from `dst` extension).

  Args:
    src: Input image path.
    dst: Output path (extension determines format).
    quality: JPEG/WebP quality (1-100).

  Returns:
    Output file path.
  """
  src = require_file(src, "Image")
  dst = os.path.abspath(dst)
  DIR.ensure(dst)
  image = Image.open(src)
  ext = os.path.splitext(dst)[1].lower()
  if ext in (".jpg", ".jpeg"):
    if image.mode in ("RGBA", "P"):
      image = image.convert("RGB")
    image.save(dst, "JPEG", quality=quality)
  elif ext == ".webp":
    image.save(dst, "WEBP", quality=quality)
  elif ext == ".avif":
    image.save(dst, "AVIF", quality=quality)
  elif ext == ".png":
    image.save(dst, "PNG")
  else:
    image.save(dst)
  return dst

#------------------------------------------------------------------------------------ Compress

def img_compress(
  src: str,
  dst: str|None = None,
  max_px: int = 1920,
  format: ImgFormat = "keep",
  quality: int = 80,
  target_kB: int|None = None,
  avif_speed: int = 6,
  recursive: bool = True,
  inplace: bool = False,
) -> list[dict]:
  """Compress image(s): resize, optimize encoding, pick best format.

  Handles single file or entire directory. Auto-corrects EXIF rotation.

  Args:
    src: Input file or directory path.
    dst: Output file/directory. None = add -min suffix (file) or -min/ dir (dir).
    max_px: Max width/height in pixels. Downscales keeping aspect ratio.
    format: Output format strategy:
      "keep" = same as source, "auto" = smallest size,
      "avif"/"webp"/"jpg"/"png" = force format (with fallback).
    quality: Starting quality 1-100.
    target_kB: Target file size in KB. Steps quality down to reach it.
    avif_speed: AVIF encoder speed 0-10 (lower = slower, better).
    recursive: Walk subdirectories when src is directory.

  Returns:
    List of dicts with keys: src, dst, orig_size, new_size, orig_kB, new_kB, format.
  """
  src = os.path.abspath(src)
  if not os.path.exists(src):
    raise FileNotFoundError(f"Source not found: {src}")
  if os.path.isfile(src):
    files = [src]
    is_single = True
  else:
    files = []
    if recursive:
      for root, _, names in os.walk(src):
        for name in names:
          if os.path.splitext(name)[1].lower() in IMG_EXTS:
            files.append(os.path.join(root, name))
    else:
      for name in os.listdir(src):
        fp = os.path.join(src, name)
        if os.path.isfile(fp) and os.path.splitext(name)[1].lower() in IMG_EXTS:
          files.append(fp)
    is_single = False
  if not files:
    return []
  if dst is not None:
    dst = os.path.abspath(dst)
  results = []
  for filepath in files:
    if is_single:
      if dst is not None:
        out_path = dst
      elif inplace:
        out_path = filepath
      else:
        out_path = None
    else:
      rel = os.path.relpath(filepath, src)
      if dst is not None:
        out_dir = os.path.join(dst, os.path.dirname(rel))
      elif inplace:
        out_dir = os.path.dirname(filepath)
      else:
        base_dir = f"{src.rstrip(os.sep)}-min"
        out_dir = os.path.join(base_dir, os.path.dirname(rel))
      out_path = None
    try:
      img = Image.open(filepath)
      img = ImageOps.exif_transpose(img)
    except Exception:
      continue
    orig_kB = os.path.getsize(filepath) // 1024  # before potential overwrite
    img, orig_size, new_size = _resize_max(img, max_px)
    src_ext = os.path.splitext(filepath)[1].lower()
    fmt_order = _pick_formats(format, img, src_ext)
    data, fmt, ext, q_used = _encode_best(img, fmt_order, quality, target_kB, avif_speed,
      pick_smallest=(format == "auto"))
    if data is None: continue
    stem = os.path.splitext(os.path.basename(filepath))[0]
    if is_single and out_path is not None:
      final = os.path.join(os.path.dirname(filepath), f"{stem}{ext}") if inplace else out_path
    elif is_single:
      final = os.path.join(os.path.dirname(filepath), f"{stem}-min{ext}")
    else:
      os.makedirs(out_dir, exist_ok=True)
      final = os.path.join(out_dir, f"{stem}{ext}")
    DIR.ensure(final)
    with open(final, "wb") as f:
      f.write(data)
    if inplace and final != filepath and os.path.isfile(filepath):
      os.remove(filepath)
    results.append({
      "src": filepath,
      "dst": final,
      "orig_size": orig_size,
      "new_size": new_size,
      "orig_kB": orig_kB,
      "new_kB": len(data) // 1024,
      "format": fmt,
    })
  return results