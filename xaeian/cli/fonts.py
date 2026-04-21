# xaeian/cli/fonts.py
"""
Rename font files. Two layouts:

- `web` (default): flat dir, slug-weight-italic naming, optional CSS generation.
  Convention: `inter-400.ttf`, `jetbrains-mono-700-italic.ttf`, etc.
- `system`: flat dir, PascalCase naming for reportlab/PIL/fontconfig.
  Convention: `Inter-Regular.ttf`, `JetBrainsMono-BoldItalic.ttf`.

Both modes parse filenames only — no font file inspection. Optional `--meta`
flag rewrites TTF name table to match new file name (requires `fonttools`).

Convention details:
  - `Oblique` is detected as italic and renamed to `Italic` for consistency.
  - Variable fonts (`[wght]`, `VariableFont_wght`) are kept in web mode but
    skipped in system mode (system mode is for static instances).
  - Subset names (`latin`, `latin-ext`, `cyrillic-ext`, ...) and version
    tags (`v12`) are stripped from the family slug.

Examples:
  >>> from xaeian.cli.fonts import rename_fonts
  >>> rename_fonts("web/fonts/")                                     # web flat
  >>> rename_fonts("web/fonts/", css="web/css/fonts.css")            # web + CSS
  >>> rename_fonts("assets/fonts/", mode="system")                   # system flat
  >>> rename_fonts("assets/fonts/", mode="system", meta=True)        # rewrite TTF metadata
"""
import os, sys, re
from ..files import PATH, DIR, FILE
from ..log import Print
from ..colors import Color as c

p = Print()

#------------------------------------------------------------------------------------ Internals
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

# Reverse map for system mode: weight → PascalCase mode name
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

# Single tokens and compound pairs (joined without hyphen) to strip from slugs.
# Compound: `latin-ext` → join as `latinext` → match.
JUNK_TOKENS = {
  "latin", "latinext", "cyrillic", "cyrillicext", "greek", "greekext",
  "vietnamese", "arabic", "hebrew", "devanagari", "thai",
}

#--------------------------------------------------------------------------- Family name helpers
def _slug_to_family(slug:str) -> str:
  """Reverse slug to family name: `jetbrains-mono` → `JetBrains Mono`."""
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
  """Route to `_camel_split` (for PascalCase) or `_slug_to_family` (lowercase)."""
  if raw == raw.lower():
    return _slug_to_family(raw)
  return _camel_split(raw)

def _family_to_slug(family:str) -> str:
  """`JetBrains Mono` → `jetbrains-mono`"""
  return re.sub(r"\s+", "-", family.strip()).lower()

def _family_to_pascal(family:str) -> str:
  """`JetBrains Mono` → `JetBrainsMono`, `Inter Display` → `InterDisplay`"""
  return "".join(w for w in re.split(r"\s+", family.strip()) if w)

#--------------------------------------------------------------------------- Style/weight parsing
def _extract_weight_italic(style:str) -> tuple[int|str, bool]:
  """Extract weight and italic flag from style string like `BoldItalic`,
  `700italic`, `semibold`, `300`, `regular`, `Oblique`, `BoldOblique`.

  `Oblique` is normalized to italic — they're visually equivalent and the
  distinction matters only for typographic purists. xaeian convention uses
  `Italic` for both.
  """
  s = style.lower().strip()
  italic = "italic" in s or "oblique" in s or s.endswith("it")
  s = re.sub(r"italic|oblique|(?<=\w)it$", "", s).strip()
  if not s or s in ("regular", "normal", "book"):
    return 400, italic
  if s == "var" or "variable" in s:
    return "var", italic
  m = re.match(r"^(\d{3})$", s)
  if m:
    return max(100, min(900, int(m.group(1)))), italic
  return WEIGHT_MAP.get(s, 400), italic

def _strip_junk(parts:list[str]) -> list[str]:
  """Strip subset names (`latin`, `latin-ext`, ...) and version tags (`v12`)."""
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
  """Parse font filename stem into `(family, weight, italic)`.

  Weight is `"var"` for variable fonts, `int` for static instances.
  Handles: originals (`Inter-BoldItalic`, `DejaVuSans-Oblique`),
  already-renamed (`inter-700-italic`), Google Fonts
  (`foo-v12-latin-regular`, `foo-latin-ext-700`),
  combined (`foo-700italic`), variable
  (`source-code-pro-VariableFont_wght`, `Inter[wght]`, `InterItalic[wght]`).
  """
  # Bracket variable: `Inter[wght]`, `Inter-Italic[wght]`, `InterItalic[wght]`
  if "[" in stem:
    pre = stem.split("[")[0].rstrip("-")
    pre, italic = _strip_italic_suffix(pre)
    return _resolve_family(pre), "var", italic
  # `VariableFont_wght` suffix
  vf = re.match(r"^(.+?)-?VariableFont[_\-].*$", stem, re.IGNORECASE)
  if vf:
    fam = vf.group(1)
    fam, italic = _strip_italic_suffix(fam)
    return _resolve_family(fam), "var", italic
  # No hyphen: `InterVariable`, `Roboto`
  if "-" not in stem:
    if stem.lower().endswith("variable"):
      fam = stem[:-8]
      return (_camel_split(fam), "var", False) if fam else None
    return _camel_split(stem), 400, False
  first, rest = stem.split("-", 1)
  # CamelCase original: `Inter-BoldItalic`, `DejaVuSans-Oblique`
  if first != first.lower():
    weight, italic = _extract_weight_italic(rest)
    return _camel_split(first), weight, italic
  # Lowercase: already-renamed or Google Fonts style
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

#--------------------------------------------------------------------------- Target naming
def _weight_to_mode(weight:int|str, italic:bool) -> str:
  """Convert (weight, italic) to PascalCase mode name for system layout.

  Edge cases follow standard PostScript convention:
    `(400, False)` → `Regular`
    `(400, True)`  → `Italic`         (not `RegularItalic`)
    `(700, False)` → `Bold`
    `(700, True)`  → `BoldItalic`
    `(300, True)`  → `LightItalic`
  """
  if weight == "var":
    return "Variable" + ("Italic" if italic else "")
  base = WEIGHT_TO_MODE.get(weight, "Regular")
  if italic:
    return "Italic" if base == "Regular" else f"{base}Italic"
  return base

def _build_target(family:str, weight:int|str, italic:bool, ext:str, mode:str
) -> str|None:
  """Return target filename, or `None` to signal skip."""
  if mode == "system":
    if weight == "var":
      return None  # caller logs the skip
    fam = _family_to_pascal(family)
    return f"{fam}-{_weight_to_mode(weight, italic)}{ext}"
  # web mode: flat slug-weight[-italic]
  slug = _family_to_slug(family)
  return f"{slug}-{weight}{'-italic' if italic else ''}{ext}"

#--------------------------------------------------------------------------- Metadata rewriting
def _rewrite_metadata(path:str, family:str, weight:int|str, italic:bool):
  """Rewrite TTF/OTF name table to match (family, weight, italic).

  Updates standard name records (1=family, 2=subfamily, 4=full, 6=postscript)
  plus OS/2 weight class and fsSelection italic bit. Variable fonts get
  `weight=400` written (the static instance the file currently represents).

  Requires `fonttools` — raises ImportError if missing.
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
  # Name records — both Mac (platform 1) and Windows (platform 3) variants.
  # nameID: 1=family, 2=subfamily, 4=full name, 6=postscript name,
  # 16=preferred family, 17=preferred subfamily.
  records = {
    1: family,
    2: subfamily,
    3: f"{postscript};1.000;XAEIAN",   # unique ID — vendor "XAEIAN" + version
    4: full_name,
    6: postscript,
    16: family,
    17: subfamily,
  }
  for name_id, value in records.items():
    name_table.setName(value, name_id, 1, 0, 0)      # Mac Roman
    name_table.setName(value, name_id, 3, 1, 0x409)  # Windows Unicode US
  # Drop nameID 18-25 (legacy / variations) so they don't override the new ones
  name_table.names = [
    n for n in name_table.names
    if n.nameID < 18 or n.nameID not in {18, 19, 20, 21, 22, 23, 24, 25}
  ]
  if os2 is not None:
    os2.usWeightClass = weight_int
    if italic:
      os2.fsSelection |= 1       # ITALIC bit
      os2.fsSelection &= ~0x40   # clear REGULAR bit
    else:
      os2.fsSelection &= ~1
      if weight_int == 400:
        os2.fsSelection |= 0x40
  if head is not None:
    head.macStyle |= 2 if italic else 0
    head.macStyle |= 1 if weight_int >= 700 else 0
  font.save(path)
  font.close()

#---------------------------------------------------------------------------------------- API
def rename_fonts(
  root: str,
  css: str|None = None,
  dry_run: bool = False,
  mode: str = "web",
  meta: bool = False,
) -> list[dict]:
  """Rename font files to xaeian convention.

  Args:
    root: Directory with font files.
    css: Output CSS file path (web mode only).
    dry_run: Preview without writing.
    mode: `"web"` (flat, slug-weight) or `"system"` (flat, PascalCase).
    meta: Rewrite TTF/OTF name table to match new file (needs `fonttools`).

  Returns:
    List of dicts: `{family, slug, weight, italic, filename, ext}`.
  """
  if mode not in ("web", "system"):
    raise ValueError(f"mode must be 'web' or 'system', got {mode!r}")
  if mode == "system" and css:
    p.wrn(f"--css ignored in {c.ORANGE}system{c.END} mode")
    css = None
  if meta:
    try:
      import fontTools  # noqa: F401
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
  taken: dict[str, str] = {}  # new_name → original name (for collision report)
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
    # Collision check with case-only-rename safety on case-insensitive FS
    if name != new_name and PATH.exists(new_path) \
        and not os.path.samefile(old_path, new_path):
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
  """Write a fonts.css with one `@font-face` per logical face (family+weight+italic),
  collapsing format variants (woff2/woff/ttf/otf) into a single src list."""
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

#---------------------------------------------------------------------------------------- CLI
EXAMPLES = """
examples:
  xn fonts web/fonts/                              Web flat (slug-weight)
  xn fonts web/fonts/ --css web/css/fonts.css      Web + CSS
  xn fonts assets/fonts/ --mode system             System flat (PascalCase)
  xn fonts assets/fonts/ --mode system --meta      + rewrite TTF metadata
  xn fonts fonts/ --dry-run                        Preview without changes
"""

def main():
  import argparse
  def fmt(prog):
    return argparse.RawDescriptionHelpFormatter(prog, max_help_position=34, width=90)
  class FontsParser(argparse.ArgumentParser):
    def format_help(self): return "\n" + super().format_help().rstrip() + "\n\n"
  parser = FontsParser(
    description="Rename font files to xaeian convention (web or system layout)",
    formatter_class=fmt,
    add_help=False,
    usage=argparse.SUPPRESS,
    epilog=EXAMPLES,
  )
  parser.add_argument("root", help="Directory with font files")
  parser.add_argument("--mode", choices=["web", "system"], default="web",
    help="Layout: web (slug-weight + CSS) or system (PascalCase, reportlab/PIL)")
  parser.add_argument("--css", default=None, metavar="PATH",
    help="Output CSS file path (web mode only)")
  parser.add_argument("--meta", action="store_true",
    help="Rewrite TTF/OTF name table to match new files (needs fontTools)")
  parser.add_argument("--dry-run", action="store_true",
    help="Preview without renaming or writing files")
  parser.add_argument("-h", "--help", action="help",
    help="Show this help message and exit")
  args = parser.parse_args()
  root = os.path.abspath(args.root)
  if not PATH.is_dir(root):
    p.err(f"Directory {c.ORANGE}{root}{c.END} not found")
    sys.exit(1)
  flags = []
  if args.dry_run: flags.append(f"{c.GREY}dry run{c.END}")
  if args.meta:    flags.append(f"{c.GREY}meta{c.END}")
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
