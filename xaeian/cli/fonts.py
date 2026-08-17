# xaeian/cli/fonts.py

"""
Rename font files to one of two flat layouts.

- `web` (default): `inter-400.ttf`, `jetbrains-mono-700-italic.ttf`, optional CSS.
- `system`: `Inter-Regular.ttf`, `JetBrainsMono-BoldItalic.ttf`, for reportlab/PIL/fontconfig.

Names come from filenames alone. `Oblique` counts as italic and is renamed `Italic`.
Variable fonts are kept in web mode, skipped in system mode (static instances only).
"""

import os, sys, re, io
from ..files import PATH, DIR, FILE
from ..log import Print
from ..colors import Color as c

p = Print()

#---------------------------------------------------------------------------------------- Internals

FONT_EXTS = [".woff2", ".woff", ".ttf", ".otf"]
FORMAT_MAP = {
  ".woff2": "woff2",
  ".woff": "woff",
  ".ttf": "truetype",
  ".otf": "opentype",
}
FORMAT_PRIORITY = [".woff2", ".woff", ".ttf", ".otf"]

WEIGHT_MAP = {
  "thin": 100, "hairline": 100,
  "extralight": 200, "ultralight": 200,
  "light": 300,
  "regular": 400, "normal": 400, "book": 400,
  "medium": 500,
  "semibold": 600, "demibold": 600,
  "bold": 700,
  "extrabold": 800, "ultrabold": 800,
  "black": 900, "heavy": 900,
}

WEIGHT_TO_MODE = {
  100: "Thin",
  200: "ExtraLight",
  300: "Light",
  400: "Regular",
  500: "Medium",
  600: "SemiBold",
  700: "Bold",
  800: "ExtraBold",
  900: "Black",
}

KNOWN_FAMILIES = {
  "jetbrainsmono": "JetBrains Mono",
  "sourcecodepro": "Source Code Pro",
  "sourcesanspro": "Source Sans Pro",
  "sourceserifpro": "Source Serif Pro",
  "sourcesans3": "Source Sans 3",
  "sourceserif4": "Source Serif 4",
  "ibmplexmono": "IBM Plex Mono",
  "ibmplexsans": "IBM Plex Sans",
  "ibmplexserif": "IBM Plex Serif",
  "dmsans": "DM Sans",
  "dmserif": "DM Serif",
  "dmmono": "DM Mono",
  "spacegrotesk": "Space Grotesk",
  "spacemono": "Space Mono",
  "firasans": "Fira Sans",
  "firacode": "Fira Code",
  "firamono": "Fira Mono",
  "redhatdisplay": "Red Hat Display",
  "redhatmono": "Red Hat Mono",
  "redhattext": "Red Hat Text",
  "playfairdisplay": "Playfair Display",
  "worksans": "Work Sans",
  "publicsans": "Public Sans",
  "interdisplay": "Inter Display",
  "dejavu": "DejaVu",
  "dejavusans": "DejaVu Sans",
  "dejavusansmono": "DejaVu Sans Mono",
  "dejavuserif": "DejaVu Serif",
  "dejavusanscondensed": "DejaVu Sans Condensed",
  "dejavucondensed": "DejaVu Condensed",
  "dejavuserifcondensed": "DejaVu Serif Condensed",
  "notosans": "Noto Sans",
  "notoserif": "Noto Serif",
  "notomono": "Noto Mono",
  "robotomono": "Roboto Mono",
  "robotoslab": "Roboto Slab",
  "robotocondensed": "Roboto Condensed",
}

# Compound subsets are stored joined: `latin-ext` → `latinext`
JUNK_TOKENS = {
  "latin", "latinext", "cyrillic", "cyrillicext", "greek", "greekext",
  "vietnamese", "arabic", "hebrew", "devanagari", "thai",
}

#------------------------------------------------------------------------------ Family name helpers

def _slug_to_family(slug:str) -> str:
  """`jetbrains-mono` → `JetBrains Mono`"""
  key = slug.replace("-", "")
  if key in KNOWN_FAMILIES:
    return KNOWN_FAMILIES[key]
  return " ".join(w.capitalize() for w in slug.split("-"))

def _camel_split(s:str) -> str:
  """`InterDisplay` → `Inter Display`, `JetBrainsMono` → `JetBrains Mono`"""
  key = s.lower()
  if key in KNOWN_FAMILIES:
    return KNOWN_FAMILIES[key]
  return re.sub(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", s)

def _resolve_family(raw:str) -> str:
  """Family name from a raw stem, PascalCase or lowercase slug."""
  if raw == raw.lower():
    return _slug_to_family(raw)
  return _camel_split(raw)

def _family_to_slug(family:str) -> str:
  """`JetBrains Mono` → `jetbrains-mono`"""
  return re.sub(r"\s+", "-", family.strip()).lower()

def _family_to_pascal(family:str) -> str:
  """`JetBrains Mono` → `JetBrainsMono`, `Inter Display` → `InterDisplay`"""
  return "".join(w for w in re.split(r"\s+", family.strip()) if w)

#----------------------------------------------------------------------------- Style/weight parsing

def _extract_weight_italic(style:str) -> tuple[int|str, bool]:
  """Weight and italic flag from style: `BoldItalic`, `Bold-Italic`, `700italic`, `Oblique`."""
  s = re.sub(r"[-_\s]+", "", style.lower()) # `Bold-Italic` is the same style as `BoldItalic`
  italic = "italic" in s or "oblique" in s or s.endswith("it")
  s = re.sub(r"italic|oblique|(?<=\w)it$", "", s)
  if not s or s in ("regular", "normal", "book"):
    return 400, italic
  if s == "var" or "variable" in s:
    return "var", italic
  m = re.match(r"^(\d{3})$", s)
  if m:
    return max(100, min(900, int(m.group(1)))), italic
  return WEIGHT_MAP.get(s, 400), italic

def _strip_junk(parts:list[str]) -> list[str]:
  """Drop subset names (`latin`, `latin-ext`, ...) and version tags (`v12`)."""
  out = []
  i = 0
  while i < len(parts):
    if re.match(r"^v\d+$", parts[i]):
      i += 1
      continue
    if i + 1 < len(parts):
      pair = parts[i] + parts[i + 1]
      if pair in JUNK_TOKENS:
        i += 2
        continue
    if parts[i] in JUNK_TOKENS:
      i += 1
      continue
    out.append(parts[i])
    i += 1
  return out

def _strip_italic_suffix(raw:str) -> tuple[str, bool]:
  """Strip `Italic`/`Oblique` suffix (with or without hyphen)."""
  m = re.match(r"^(.+?)-?(?:[Ii]talic|[Oo]blique)$", raw)
  if m and m.group(1):
    return m.group(1), True
  return raw, False

def _parse_filename(stem:str) -> tuple[str, int|str, bool]|None:
  """
  Parse a filename stem into `(family, weight, italic)`, `None` when unparsable.

  Weight is `"var"` for variable fonts, else 100-900. Handles `Inter-BoldItalic`, `foo-700italic`,
  `inter-700-italic`, `foo-v12-latin-regular`, `Inter[wght]`, `source-code-pro-VariableFont_wght`.
  """
  if "[" in stem:
    pre = stem.split("[")[0].rstrip("-")
    pre, italic = _strip_italic_suffix(pre)
    return _resolve_family(pre), "var", italic
  vf = re.match(r"^(.+?)-?VariableFont[_\-].*$", stem, re.IGNORECASE)
  if vf:
    fam = vf.group(1)
    fam, italic = _strip_italic_suffix(fam)
    return _resolve_family(fam), "var", italic
  if "-" not in stem:
    if stem.lower().endswith("variable"):
      fam = stem[:-8]
      return (_camel_split(fam), "var", False) if fam else None
    return _camel_split(stem), 400, False
  first, rest = stem.split("-", 1)
  # CamelCase original naming
  if first != first.lower():
    weight, italic = _extract_weight_italic(rest)
    return _camel_split(first), weight, italic
  # lowercase: already renamed, or Google Fonts style
  parts = stem.split("-")
  italic = parts[-1] in ("italic", "oblique")
  if italic:
    parts = parts[:-1]
  if not parts:
    return None
  tail = parts[-1]
  if tail == "var":
    weight, parts = "var", parts[:-1]
  elif re.match(r"^(\d{3})(italic|oblique)?$", tail):
    m = re.match(r"^(\d{3})(italic|oblique)?$", tail)
    weight = max(100, min(900, int(m.group(1))))
    italic = italic or bool(m.group(2))
    parts = parts[:-1]
  else:
    clean = re.sub(r"(italic|oblique)$", "", tail)
    if clean in WEIGHT_MAP:
      weight = WEIGHT_MAP[clean]
      italic = italic or tail != clean
      parts = parts[:-1]
    else:
      weight = 400
  parts = _strip_junk(parts)
  slug = "-".join(parts)
  return (_slug_to_family(slug), weight, italic) if slug else None

#------------------------------------------------------------------------------------ Target naming

def _weight_to_mode(weight:int|str, italic:bool) -> str:
  """PascalCase style name; PostScript convention makes `(400, True)` → `Italic`."""
  if weight == "var":
    return "Variable" + ("Italic" if italic else "")
  base = WEIGHT_TO_MODE.get(weight, "Regular")
  if italic:
    return "Italic" if base == "Regular" else f"{base}Italic"
  return base

def _build_target(family:str, weight:int|str, italic:bool, ext:str, mode:str) -> str|None:
  """Target filename, `None` to skip (variable font in system mode)."""
  if mode == "system":
    if weight == "var":
      return None # caller logs the skip
    fam = _family_to_pascal(family)
    return f"{fam}-{_weight_to_mode(weight, italic)}{ext}"
  slug = _family_to_slug(family)
  return f"{slug}-{weight}{'-italic' if italic else ''}{ext}"

#------------------------------------------------------------------------------- Metadata rewriting

def _rewrite_metadata(path:str, family:str, weight:int|str, italic:bool):
  """
  Rewrite the TTF/OTF name table, OS/2 weight class and the fsSelection/macStyle style bits.

  Variable fonts get `weight=400`: a single `usWeightClass` cannot carry an axis range.
  """
  from fontTools.ttLib import TTFont
  font = TTFont(path)
  name_table = font["name"]
  os2 = font.get("OS/2")
  head = font.get("head")
  weight_int = 400 if weight == "var" else int(weight)
  subfamily = _weight_to_mode(weight_int, italic)
  full_name = f"{family} {subfamily}".strip()
  postscript = full_name.replace(" ", "").replace("-", "")
  records = {
    1: family,
    2: subfamily,
    3: f"{postscript};1.000;XAEIAN", # unique ID
    4: full_name,
    6: postscript,
    16: family,
    17: subfamily,
  }
  for name_id, value in records.items():
    name_table.setName(value, name_id, 1, 0, 0)      # Mac Roman
    name_table.setName(value, name_id, 3, 1, 0x409)  # Windows Unicode US
  # nameID 18-25 (compatible full, variations) would override the records above
  name_table.names = [
    n for n in name_table.names
    if n.nameID not in {18, 19, 20, 21, 22, 23, 24, 25}
  ]
  bold = weight_int >= 700 # one rule for both tables, so their bits cannot disagree
  regular = weight_int == 400 and not italic # REGULAR never coexists with ITALIC or BOLD
  if os2 is not None:
    os2.usWeightClass = weight_int
    os2.fsSelection &= ~0x61 # clear stale ITALIC, BOLD and REGULAR bits
    os2.fsSelection |= (0x01 if italic else 0) | (0x20 if bold else 0) | (0x40 if regular else 0)
  if head is not None:
    head.macStyle &= ~0x3 # clear stale bold/italic bits
    head.macStyle |= (1 if bold else 0) | (2 if italic else 0)
  buf = io.BytesIO()
  font.save(buf)
  font.close() # the read handle has to go before the atomic swap can replace the file
  FILE.save(path, buf.getvalue())

#---------------------------------------------------------------------------------------------- API

def rename_fonts(
  root:str,
  css:str|None = None,
  dry_run:bool = False,
  mode:str = "web",
  meta:bool = False,
) -> list[dict]:
  """
  Rename the font files in `root` (top level only) to the `web` or `system` layout.

  Args:
    css: Output CSS file path, web mode only.
    meta: Rewrite TTF/OTF name table to match the new file, needs `fonttools`.

  Returns:
    One dict per kept file with keys `family`, `slug`, `weight`, `italic`, `filename`, `ext`;
    `weight` is 100-900 or `"var"`. Unparsable, duplicate and colliding files are left alone.
  """
  if mode not in ("web", "system"):
    raise ValueError(f"mode must be 'web' or 'system', got {mode!r}")
  if mode == "system" and css:
    p.wrn(f"--css ignored in {c.ORANGE}system{c.END} mode")
    css = None
  if meta:
    try:
      import fontTools # noqa: F401
    except ImportError:
      p.err(f"--meta needs {c.ORANGE}fontTools{c.END} | pip install fonttools")
      sys.exit(1)
  root = os.path.abspath(root)
  if not PATH.is_dir(root):
    raise FileNotFoundError(f"Directory not found: {root}")
  files = sorted(
    f for f in os.listdir(root)
    if PATH.ext(f).lower() in FONT_EXTS
  )
  if not files:
    p.wrn(f"No font files in {c.ORANGE}{root}{c.END}")
    return []
  results = []
  taken: dict[str, str] = {} # new_name → original name
  n_ok = 0
  n_skip_var = 0
  for name in files:
    ext = PATH.ext(name).lower()
    stem = PATH.stem(name)
    parsed = _parse_filename(stem)
    if parsed is None:
      p.dot(f"{c.GREY}SKIP {name}{c.END}")
      continue
    family, weight, italic = parsed
    new_name = _build_target(family, weight, italic, ext, mode)
    if new_name is None:
      n_skip_var += 1
      p.dot(f"{c.GREY}VARIABLE {name} (skipped in system mode){c.END}")
      continue
    if new_name in taken:
      p.wrn(f"DUPE {c.ORANGE}{name}{c.END} → {new_name} "
        f"{c.GREY}(kept {taken[new_name]}){c.END}")
      continue
    old_path = root + "/" + name
    new_path = root + "/" + new_name
    # samefile keeps case-only renames working on a case-insensitive FS
    if name != new_name and PATH.exists(new_path) and not os.path.samefile(old_path, new_path):
      p.wrn(f"COLLISION {c.ORANGE}{new_name}{c.END} exists, skipping {name}")
      continue
    if name == new_name:
      n_ok += 1
    else:
      p.dot(f"{name} → {c.CYAN}{new_name}{c.END}")
      if not dry_run:
        os.rename(old_path, new_path)
    if meta and not dry_run:
      try:
        _rewrite_metadata(new_path, family, weight, italic)
      except Exception as e:
        p.wrn(f"META {c.ORANGE}{new_name}{c.END} | {e}")
    taken[new_name] = name
    slug = _family_to_slug(family)
    results.append({
      "family": family, "slug": slug, "weight": weight,
      "italic": italic, "filename": new_name, "ext": ext,
    })
  if n_ok:
    p.inf(f"{c.GREY}{n_ok} already named correctly{c.END}")
  if n_skip_var:
    p.inf(f"{c.GREY}{n_skip_var} variable fonts skipped (system mode){c.END}")
  if css:
    _generate_css(root, css, results, dry_run)
  return results

def _generate_css(font_dir:str, css_path:str, results:list[dict], dry_run:bool):
  """One `@font-face` per family+weight+italic, format variants collapsed into one src list."""
  if not results:
    p.wrn(f"No fonts to write CSS for, skipping {c.ORANGE}{css_path}{c.END}")
    return
  css_path = os.path.abspath(css_path)
  rel = os.path.relpath(font_dir, PATH.dirname(css_path)).replace("\\", "/")
  faces: dict[tuple, list[dict]] = {}
  for r in results:
    key = (r["family"], r["weight"], r["italic"])
    faces.setdefault(key, []).append(r)
  sorted_keys = sorted(faces, key=lambda k: (
    k[0], 0 if k[1] == "var" else k[1], k[2],
  ))
  blocks = []
  for key in sorted_keys:
    family, weight, italic = key
    variants = faces[key]
    variants.sort(key=lambda v: (
      FORMAT_PRIORITY.index(v["ext"]) if v["ext"] in FORMAT_PRIORITY else 99
    ))
    src_parts = [
      f'url("{rel}/{v["filename"]}") format("{FORMAT_MAP.get(v["ext"], "woff2")}")'
      for v in variants
    ]
    src = ",\n    ".join(src_parts)
    style = "italic" if italic else "normal"
    w = "100 900" if weight == "var" else str(weight)
    blocks.append(
      f"@font-face {{\n"
      f"  font-display: swap;\n"
      f'  font-family: "{family}";\n'
      f"  font-style: {style};\n"
      f"  font-weight: {w};\n"
      f"  src: {src};\n"
      f"}}"
    )
  content = "\n".join(blocks) + "\n"
  if dry_run:
    print(f"\n--- {css_path} ---")
    print(content)
  else:
    DIR.ensure(css_path, is_file=True)
    FILE.save(css_path, content)
    p.ok(f"CSS → {c.TEAL}{css_path}{c.END} {c.GREY}({len(blocks)} faces){c.END}")

#---------------------------------------------------------------------------------------------- CLI

EXAMPLES = """
examples:
  xn fonts web/fonts/                              Web flat (slug-weight)
  xn fonts web/fonts/ --css web/css/fonts.css      Web + CSS
  xn fonts assets/fonts/ --mode system             System flat (PascalCase)
  xn fonts assets/fonts/ --mode system --meta      + rewrite TTF metadata
  xn fonts fonts/ --dry-run                        Preview without changes
"""

def main():
  from ._args import _make_parser, _add_help
  parser = _make_parser("Rename font files to xaeian convention (web or system layout)", EXAMPLES)
  parser.add_argument("root", help="Directory with font files")
  parser.add_argument("--mode", choices=["web", "system"], default="web",
    help="Layout: web (slug-weight + CSS) or system (PascalCase, reportlab/PIL)")
  parser.add_argument("--css", default=None, metavar="PATH",
    help="Output CSS file path (web mode only)")
  parser.add_argument("--meta", action="store_true",
    help="Rewrite TTF/OTF name table to match new files (needs fontTools)")
  parser.add_argument("--dry-run", action="store_true",
    help="Preview without renaming or writing files")
  _add_help(parser)
  args = parser.parse_args()
  root = os.path.abspath(args.root)
  if not PATH.is_dir(root):
    p.err(f"Directory {c.ORANGE}{root}{c.END} not found")
    sys.exit(1)
  flags = []
  if args.dry_run: flags.append(f"{c.GREY}dry run{c.END}")
  if args.meta: flags.append(f"{c.GREY}meta{c.END}")
  flag_str = f" ({', '.join(flags)})" if flags else ""
  p.inf(f"Scanning {c.ORANGE}{root}{c.END} mode={c.CYAN}{args.mode}{c.END}{flag_str}")
  try:
    results = rename_fonts(
      root, css=args.css, dry_run=args.dry_run,
      mode=args.mode, meta=args.meta,
    )
  except Exception as e:
    p.err(f"Rename failed | {e}")
    sys.exit(1)
  if results:
    families = set(r["family"] for r in results)
    p.ok(f"Processed {c.TEAL}{len(results)}{c.END} fonts "
      f"({c.CYAN}{len(families)}{c.END} families)")

if __name__ == "__main__":
  main()
