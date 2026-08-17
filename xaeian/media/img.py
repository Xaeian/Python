# xaeian/media/img.py

"""
Image manipulation: resize, convert, compress, metadata.

Pillow-backed. AVIF encoding needs a Pillow build with AVIF support, `img_compress` falls
back to the next candidate format when it is missing.
"""

import os
from io import BytesIO
from typing import Literal
from PIL import Image, ImageOps
from ..files import DIR, FILE, PATH
from .utils import IMG_EXTS, require_file, resolve_dst

#-------------------------------------------------------------------------------------------- Types

ImgFormat = Literal["keep", "auto", "avif", "webp", "jpg", "png"]

#---------------------------------------------------------------------------------------- Internals

def _save(img:Image.Image, path:str, **kw) -> None:
  """Encode in memory, then `FILE.save`, so a refusing encoder never truncates the target."""
  bio = BytesIO()
  bio.name = path # PIL takes the output format from the target extension
  img.save(bio, **kw)
  FILE.save(path, bio.getvalue())

def _has_alpha(img:Image.Image) -> bool:
  return img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)

def _flatten_rgb(img:Image.Image, bg:tuple=(255, 255, 255)) -> Image.Image:
  """Composite any alpha onto `bg`, since JPEG cannot carry a transparency channel."""
  if _has_alpha(img):
    base = Image.new("RGB", img.size, bg)
    if img.mode != "RGBA":
      img = img.convert("RGBA")
    base.paste(img, mask=img.split()[-1])
    return base
  return img.convert("RGB") if img.mode != "RGB" else img

def _resize_max(img:Image.Image, max_px:int) -> tuple[Image.Image, tuple, tuple]:
  """Downscale to fit `max_px` on the long side → (img, orig_size, new_size)."""
  w, h = img.size
  scale = min(max_px / max(w, h), 1.0)
  if scale < 1.0:
    new_size = (max(1, int(w * scale)), max(1, int(h * scale)))
    return img.resize(new_size, Image.LANCZOS), (w, h), new_size
  return img, (w, h), (w, h)

def _try_encode(img:Image.Image, fmt:str, quality:int, avif_speed:int=6) -> bytes|None:
  """Encode to bytes, None when the format is unsupported or the encoder fails."""
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
  """Ordered (PIL format, ext) candidates, preferred first then fallbacks, empty when none fit."""
  if req == "keep":
    m = _fmt_from_ext(src_ext)
    return [m] if m else []
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
  img:Image.Image,
  fmt_order:list[tuple[str, str]],
  quality:int,
  target_kB:int|None = None,
  avif_speed:int = 6,
  pick_smallest:bool = False,
) -> tuple[bytes|None, str|None, str|None, int|None]:
  """
  Encode along `fmt_order`, stopping at the first fit → (data, fmt, ext, quality).

  With `target_kB` set, quality steps down by 5 to a floor of 35. `pick_smallest` tries
  every format and keeps the smallest result instead of stopping early. PNG is lossless,
  so it is only ever tried once at the starting quality. When nothing reaches `target_kB`
  the smallest attempt is returned anyway, so the goal is best-effort, not a guarantee.
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

#----------------------------------------------------------------------------------------- Metadata

def img_scrub_metadata(src:str, dst:str|None=None, inplace:bool=False) -> str:
  """
  Remove all metadata (EXIF, ICC, comments) by rebuilding the pixel data into a fresh image.

  Not lossless: JPEG output is re-encoded at quality 95, and only the first frame of a
  multi-frame file survives. The EXIF orientation tag is dropped without being baked into
  the pixels, so a photo that relied on it comes out sideways.

  `dst` None → `-nometa` suffix beside the source, or the source itself when `inplace`.
  """
  src = require_file(src, "Image")
  image = Image.open(src)
  data = list(image.getdata())
  clean = Image.new(image.mode, image.size)
  if image.mode == "P":
    clean.putpalette(image.getpalette())
    if "transparency" in image.info:
      clean.info["transparency"] = image.info["transparency"]
  clean.putdata(data)
  image.close() # the source handle must be gone before an in-place save replaces the file
  out_path = resolve_dst(src, dst, inplace, "nometa")
  ext = PATH.ext(out_path).lower()
  if ext == ".png":
    _save(clean, out_path, optimize=True, compress_level=9)
  elif ext in (".jpg", ".jpeg"):
    _save(clean, out_path, quality=95, optimize=True, progressive=True)
  elif ext == ".webp":
    _save(clean, out_path, method=6)
  else:
    _save(clean, out_path)
  return out_path

#------------------------------------------------------------------------------------------- Resize

def img_resize(
  src:str,
  dst:str|None = None,
  width:int|None = None,
  height:int|None = None,
  scale:float|None = None,
  inplace:bool = False,
) -> str:
  """
  Resize image, upscaling as readily as downscaling.

  Args:
    dst: None → `-resized` suffix beside the source, or the source itself when `inplace`.
    width: Alone keeps aspect ratio, together with `height` forces exact size.
    scale: Factor for both sides, used only when `width` and `height` are None.
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
  image.close() # the source handle must be gone before an in-place save replaces the file
  out_path = resolve_dst(src, dst, inplace, "resized")
  _save(resized, out_path)
  return out_path

#------------------------------------------------------------------------------------------ Convert

def img_convert(src:str, dst:str, quality:int=90) -> str:
  """
  Convert image to the format named by the `dst` extension.

  `quality` 1-100 applies to jpg/webp/avif, png and anything else ignore it.
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

#----------------------------------------------------------------------------------------- Compress

def img_compress(
  src:str,
  dst:str|None = None,
  max_px:int = 1920,
  format:ImgFormat = "keep",
  quality:int = 80,
  target_kB:int|None = None,
  avif_speed:int = 6,
  recursive:bool = True,
  inplace:bool = False,
) -> list[dict]:
  """
  Compress a file or a directory of images: resize, re-encode, pick best format.

  EXIF rotation is baked into the pixels and all other metadata is dropped. Skipped without
  an error: files Pillow cannot open, multi-frame files, and files no encoder accepts, which
  under "keep" means gif, bmp and tiff. Two sources landing on one output path raise
  `FileExistsError`, as does an in-place output that would overwrite an unrelated file.

  Args:
    dst: None → `-min` suffix on a file, `-min/` sibling tree on a directory.
    max_px: Long-side cap in px, only ever downscales.
    format: "keep" = source format, "auto" = whichever encodes smallest,
      "avif"/"webp"/"jpg"/"png" = force, with fallbacks if the encoder is missing.
    quality: Starting quality 1-100.
    target_kB: Size goal, quality steps down to 35 trying to reach it, best effort only.
    avif_speed: AVIF encoder speed 0-10, lower is slower and smaller.
    inplace: Overwrite source, deleting the original when the format changes.

  Returns:
    One dict per file with keys: src, dst, orig_size, new_size, orig_kB, new_kB, format.
    `*_size` is a (width, height) pixel pair, `*_kB` are whole kB rounded down.
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
  taken: dict[str, str] = {} # case-folded output path → the source that claimed it
  for filepath in files:
    if not is_single:
      rel = os.path.relpath(filepath, src)
      if dst is not None:
        out_dir = os.path.join(dst, os.path.dirname(rel))
      elif inplace:
        out_dir = os.path.dirname(filepath)
      else:
        base_dir = f"{src.rstrip(os.sep)}-min"
        out_dir = os.path.join(base_dir, os.path.dirname(rel))
    try:
      img = Image.open(filepath)
      if getattr(img, "n_frames", 1) > 1: continue # a re-encode keeps the first frame only
      img = ImageOps.exif_transpose(img)
    except Exception:
      continue
    orig_kB = os.path.getsize(filepath) // 1024 # before potential overwrite
    img, orig_size, new_size = _resize_max(img, max_px)
    src_ext = os.path.splitext(filepath)[1].lower()
    fmt_order = _pick_formats(format, img, src_ext)
    data, fmt, ext, q_used = _encode_best(img, fmt_order, quality, target_kB, avif_speed,
      pick_smallest=(format == "auto"))
    if data is None: continue
    stem = os.path.splitext(os.path.basename(filepath))[0]
    if is_single:
      if dst is not None: final = dst # explicit dst wins over inplace
      elif inplace: final = os.path.join(os.path.dirname(filepath), f"{stem}{ext}")
      else: final = os.path.join(os.path.dirname(filepath), f"{stem}-min{ext}")
    else:
      final = os.path.join(out_dir, f"{stem}{ext}")
    key = os.path.normcase(final)
    if key in taken:
      raise FileExistsError(f"Two sources map to one output: '{taken[key]}' and '{filepath}'")
    taken[key] = filepath
    renamed = inplace and dst is None and key != os.path.normcase(filepath)
    if renamed and os.path.exists(final):
      raise FileExistsError(f"Output would overwrite an unrelated file: '{filepath}' → {final}")
    FILE.save(final, data)
    if renamed: FILE.remove(filepath)
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