# xaeian/cli/fonts.py

"""
Rename font files and generate fonts.css matching xaeian convention.

Parses filenames only: no external dependencies.

Convention:
  files:  {family}-{weight}[-italic].{ext}  (lowercase, hyphens)
  CSS:    font-family: "JetBrains Mono"      (natural names)

Example:
  >>> from xaeian.cli.fonts import rename_fonts
  >>> results = rename_fonts("web/fonts/")
  >>> results = rename_fonts("web/fonts/", css="web/css/fonts.css")
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
  "regular": 400, "normal": 400,
  "medium": 500,
  "semibold": 600, "demibold": 600,
  "bold": 700,
  "extrabold": 800, "ultrabold": 800,
  "black": 900, "heavy": 900,
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
}

# Single tokens and compound pairs (joined without hyphen) to strip from slugs.
# Compound: `latin-ext` → join as `latinext` → match.
JUNK_TOKENS = {
  "latin", "latinext", "cyrillic", "cyrillicext", "greek", "greekext",
  "vietnamese", "arabic", "hebrew", "devanagari", "thai",
}

def _camel_split(s:str) -> str:
  """`InterDisplay` → `Inter Display`, `JetBrainsMono` → `JetBrains Mono`"""
  key = s.lower()
  if key in KNOWN_FAMILIES:
    return KNOWN_FAMILIES[key]
  return re.sub(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", s)

def _family_to_slug(family:str) -> str:
  """`JetBrains Mono` → `jetbrains-mono`"""
  return re.sub(r"\s+", "-", family.strip()).lower()

def _resolve_family(raw:str) -> str:
  """Route to `_camel_split` or `_slug_to_family` based on case."""
  if raw == raw.lower():
    return _slug_to_family(raw)
  return _camel_split(raw)

def _extract_weight_italic(style:str) -> tuple[int|str, bool]:
  """Extract weight and italic from a style string like `bolditalic`, `700italic`,
  `semibold`, `300`, `regular`. Returns (weight, italic)."""
  s = style.lower().strip()
  italic = "italic" in s or s.endswith("it")
  s = re.sub(r"italic|(?<=\w)it$", "", s).strip()
  if not s or s in ("regular", "normal"):
    return 400, italic
  if s == "var" or "variable" in s:
    return "var", italic
  m = re.match(r"^(\d{3})$", s)
  if m:
    return max(100, min(900, int(m.group(1)))), italic
  return WEIGHT_MAP.get(s, 400), italic

def _strip_junk(parts:list[str]) -> list[str]:
  """Strip subset names (`latin`, `latin-ext`, `cyrillic-ext`, ...) and version
  tags (`v12`) from a list of slug parts. Checks both single tokens and adjacent
  pairs joined without hyphen (e.g. `latin` + `ext` → `latinext`)."""
  out = []
  i = 0
  while i < len(parts):
    # Version tag: `v12`, `v2`
    if re.match(r"^v\d+$", parts[i]):
      i += 1
      continue
    # Try pair first: `latin` + `ext` → `latinext`
    if i + 1 < len(parts):
      pair = parts[i] + parts[i + 1]
      if pair in JUNK_TOKENS:
        i += 2
        continue
    # Single junk token
    if parts[i] in JUNK_TOKENS:
      i += 1
      continue
    out.append(parts[i])
    i += 1
  return out

def _strip_italic_suffix(raw:str) -> tuple[str, bool]:
  """Strip `Italic`/`italic` suffix (with or without hyphen) from a string."""
  m = re.match(r"^(.+?)-?[Ii]talic$", raw)
  if m and m.group(1):
    return m.group(1), True
  return raw, False

def _parse_filename(stem:str) -> tuple[str, int|str, bool]|None:
  """Parse font filename stem into (family, weight, italic).
  Weight is `"var"` for variable fonts, `int` for static.
  Handles originals (`Inter-BoldItalic`), already-renamed (`inter-700-italic`),
  Google Fonts (`foo-v12-latin-regular`, `foo-latin-ext-700`),
  combined (`foo-700italic`), and variable (`source-code-pro-VariableFont_wght`,
  `source-code-pro-italic[wght]`, `InterItalic[wght]`)."""
  # Bracket variable: `Inter[wght]`, `Inter-Italic[wght]`,
  # `source-code-pro-italic[wght]`, `InterItalic[wght]`
  if "[" in stem:
    pre = stem.split("[")[0].rstrip("-")
    pre, italic = _strip_italic_suffix(pre)
    return _resolve_family(pre), "var", italic
  # `VariableFont_wght` suffix: `Foo-VariableFont_wght`,
  # `source-code-pro-VariableFont_wght`
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
  # CamelCase original: `Inter-BoldItalic`, `JetBrainsMono-Regular`
  if first != first.lower():
    weight, italic = _extract_weight_italic(rest)
    return _camel_split(first), weight, italic
  # Lowercase: already-renamed or Google Fonts style
  parts = stem.split("-")
  # Strip trailing `italic`
  italic = parts[-1] == "italic"
  if italic: parts = parts[:-1]
  if not parts: return None
  # Pop weight from tail
  tail = parts[-1]
  if tail == "var":
    weight, parts = "var", parts[:-1]
  elif re.match(r"^(\d{3})(italic)?$", tail):
    m = re.match(r"^(\d{3})(italic)?$", tail)
    weight = max(100, min(900, int(m.group(1))))
    italic = italic or bool(m.group(2))
    parts = parts[:-1]
  elif re.sub(r"italic$", "", tail) in WEIGHT_MAP:
    clean = re.sub(r"italic$", "", tail)
    weight = WEIGHT_MAP[clean]
    italic = italic or tail != clean
    parts = parts[:-1]
  else:
    weight = 400
  # Strip junk tokens (subset names, version tags)
  parts = _strip_junk(parts)
  slug = "-".join(parts)
  return (_slug_to_family(slug), weight, italic) if slug else None

def _slug_to_family(slug:str) -> str:
  """Reverse slug to family name: `jetbrains-mono` → `JetBrains Mono`."""
  key = slug.replace("-", "")
  if key in KNOWN_FAMILIES:
    return KNOWN_FAMILIES[key]
  return " ".join(w.capitalize() for w in slug.split("-"))

#------------------------------------------------------------------------------------------ API

def rename_fonts(
  root: str,
  css: str|None = None,
  dry_run: bool = False,
) -> list[dict]:
  """Rename font files to xaeian convention and optionally generate CSS.

  Args:
    root: Directory with font files.
    css: Output CSS file path (e.g. `css/fonts.css`).
    dry_run: Preview without renaming.

  Returns:
    List of dicts with keys: family, slug, weight, italic, filename, ext.
  """
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
  taken = set()
  n_ok = 0
  for name in files:
    ext = PATH.ext(name).lower()
    stem = PATH.stem(name)
    meta = _parse_filename(stem)
    if meta is None:
      p.dot(f"{c.GREY}SKIP {name}{c.END}")
      continue
    family, weight, italic = meta
    slug = _family_to_slug(family)
    new_name = f"{slug}-{weight}{'-italic' if italic else ''}{ext}"
    if new_name in taken:
      p.wrn(f"DUPE {c.ORANGE}{name}{c.END} → {new_name}")
      continue
    old_path = root + "/" + name
    new_path = root + "/" + new_name
    # Collision check: `os.path.samefile` handles case-only renames on
    # case-insensitive FS (Windows, macOS) where target "exists" but
    # is actually the same file under different case.
    if name != new_name and PATH.exists(new_path) \
        and not os.path.samefile(old_path, new_path):
      p.wrn(f"COLLISION {c.ORANGE}{new_name}{c.END} exists, skipping")
      continue
    if name == new_name:
      n_ok += 1
    else:
      p.dot(f"{name} → {c.CYAN}{new_name}{c.END}")
      if not dry_run:
        os.rename(old_path, new_path)
    taken.add(new_name)
    results.append({
      "family": family, "slug": slug, "weight": weight,
      "italic": italic, "filename": new_name, "ext": ext,
    })
  if n_ok:
    p.inf(f"{c.GREY}{n_ok} already named correctly{c.END}")
  if css:
    _generate_css(root, css, results, dry_run)
  return results

def _generate_css(font_dir:str, css_path:str, results:list[dict], dry_run:bool):
  if not results:
    p.wrn(f"No fonts to write CSS for, skipping {c.ORANGE}{css_path}{c.END}")
    return
  css_path = os.path.abspath(css_path)
  rel = os.path.relpath(font_dir, PATH.dirname(css_path)).replace("\\", "/")
  # Group by logical face: (family, weight, italic)
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
    # Sort sources by format priority: woff2 → woff → ttf → otf
    variants.sort(key=lambda v: (
      FORMAT_PRIORITY.index(v["ext"]) if v["ext"] in FORMAT_PRIORITY else 99
    ))
    src_parts = []
    for v in variants:
      fmt = FORMAT_MAP.get(v["ext"], "woff2")
      src_parts.append(f'url("{rel}/{v["filename"]}") format("{fmt}")')
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

#------------------------------------------------------------------------------------------ CLI

EXAMPLES = """
examples:
  xn fonts web/fonts/                         Rename only
  xn fonts web/fonts/ --css web/css/fonts.css  Rename + generate CSS
  xn fonts web/fonts/ --dry-run                Preview without changes
"""

def main():
  import argparse
  def fmt(prog):
    return argparse.RawDescriptionHelpFormatter(prog, max_help_position=34, width=90)
  class FontsParser(argparse.ArgumentParser):
    def format_help(self): return "\n" + super().format_help().rstrip() + "\n\n"
  parser = FontsParser(
    description="Rename font files to xaeian convention",
    formatter_class=fmt,
    add_help=False,
    usage=argparse.SUPPRESS,
    epilog=EXAMPLES,
  )
  parser.add_argument("root", help="Directory with font files")
  parser.add_argument("--css", default=None, metavar="PATH",
    help="Output CSS file path (e.g. css/fonts.css)")
  parser.add_argument("--dry-run", action="store_true",
    help="Preview without renaming files")
  parser.add_argument("-h", "--help", action="help",
    help="Show this help message and exit")
  args = parser.parse_args()
  root = os.path.abspath(args.root)
  if not PATH.is_dir(root):
    p.err(f"Directory {c.ORANGE}{root}{c.END} not found")
    sys.exit(1)
  p.inf(f"Scanning {c.ORANGE}{root}{c.END}"
    f"{' ' + c.GREY + '(dry run)' + c.END if args.dry_run else ''}...")
  try:
    results = rename_fonts(root, args.css, args.dry_run)
  except Exception as e:
    p.err(f"Rename failed | {e}")
    sys.exit(1)
  if results:
    families = set(r["family"] for r in results)
    p.ok(f"Processed {c.TEAL}{len(results)}{c.END} fonts "
      f"({c.CYAN}{len(families)}{c.END} families)")

if __name__ == "__main__":
  main()