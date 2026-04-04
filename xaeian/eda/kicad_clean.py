import re
from ..xstring import strip_comments
from ..files import FILE, PATH
from .fp import Style, L, fmt_number

#----------------------------------------------------------------------------- Footprint cleanup

def _round_coords(text:str) -> str:
  """Round coordinate floats to 2 decimal places, skip UUIDs."""
  def _round_match(m):
    full = m.group(0)
    if "-" in full and len(full) > 38: return full  # UUID
    v = round(float(full), 2)
    if v == int(v): return str(int(v))
    return f"{v:g}"
  return re.sub(r"-?\d+\.\d{3,}", _round_match, text)

def _compact_block(text:str) -> str:
  """Collapse multi-line S-expression blocks to single lines."""
  # Collapse property blocks
  text = re.sub(
    r'\(property\s+"([^"]+)"\s+"([^"]*)"\s+'
    r'\(at\s+([^)]+)\)\s+'
    r'(?:\(unlocked\s+yes\)\s+)?'
    r'\(layer\s+"([^"]+)"\)\s+'
    r'(?:\(hide\s+yes\)\s+)?'
    r'\(uuid\s+"([^"]+)"\)\s+'
    r'\(effects\s+\(font\s+\(size\s+([^)]+)\)\s+'
    r'\(thickness\s+([^)]+)\)\s*\)\s*'
    r'(?:\(justify\s+[^)]*\)\s*)?'
    r'\)\s*\)',
    lambda m: (
      f'(property "{m[1]}" "{m[2]}" (at {m[3]}) (layer "{m[4]}")'
      + (' (hide yes)' if '(hide yes)' in m.group(0) else '')
      + f' (uuid "{m[5]}")'
      f' (effects (font (size {m[6]}) (thickness {m[7]}))))'
    ),
    text, flags=re.DOTALL,
  )
  # Collapse fp_line blocks
  text = re.sub(
    r'\(fp_line\s+\(start\s+([^)]+)\)\s+\(end\s+([^)]+)\)\s+'
    r'\(stroke\s+\(width\s+([^)]+)\)\s+\(type\s+solid\)\s*\)\s+'
    r'\(layer\s+"([^"]+)"\)\s+\(uuid\s+"([^"]+)"\)\s*\)',
    r'(fp_line (start \1) (end \2) (stroke (width \3) (type solid))'
    r' (layer "\4") (uuid "\5"))',
    text, flags=re.DOTALL,
  )
  # Collapse fp_rect blocks
  text = re.sub(
    r'\(fp_rect\s+\(start\s+([^)]+)\)\s+\(end\s+([^)]+)\)\s+'
    r'\(stroke\s+\(width\s+([^)]+)\)\s+\(type\s+solid\)\s*\)\s+'
    r'\(fill\s+(yes|no)\)\s+'
    r'\(layer\s+"([^"]+)"\)\s+\(uuid\s+"([^"]+)"\)\s*\)',
    r'(fp_rect (start \1) (end \2) (stroke (width \3) (type solid))'
    r' (fill \4) (layer "\5") (uuid "\6"))',
    text, flags=re.DOTALL,
  )
  # Collapse fp_arc blocks
  text = re.sub(
    r'\(fp_arc\s+\(start\s+([^)]+)\)\s+\(mid\s+([^)]+)\)\s+'
    r'\(end\s+([^)]+)\)\s+'
    r'\(stroke\s+\(width\s+([^)]+)\)\s+\(type\s+solid\)\s*\)\s+'
    r'\(layer\s+"([^"]+)"\)\s+\(uuid\s+"([^"]+)"\)\s*\)',
    r'(fp_arc (start \1) (mid \2) (end \3)'
    r' (stroke (width \4) (type solid)) (layer "\5") (uuid "\6"))',
    text, flags=re.DOTALL,
  )
  # Collapse pad blocks
  text = re.sub(
    r'\(pad\s+"([^"]*)"\s+(smd|thru_hole|np_thru_hole)\s+(\w+)\s+'
    r'\(at\s+([^)]+)\)\s+\(size\s+([^)]+)\)\s+'
    r'(?:\(drill\s+((?:[^()]*|\([^)]*\))*)\)\s+)?'
    r'\(layers\s+([^)]+)\)\s*'
    r'(?:\(remove_unused_layers\s+no\)\s+)?'
    r'(?:\(solder_mask_margin\s+([^)]+)\)\s+)?'
    r'(?:\(roundrect_rratio\s+([^)]+)\)\s+)?'
    r'\(uuid\s+"([^"]+)"\)\s*\)',
    lambda m: _compact_pad(m),
    text, flags=re.DOTALL,
  )
  # Collapse model blocks
  text = re.sub(
    r'\(model\s+"([^"]+)"\s+'
    r'\(offset\s+\(xyz\s+([^)]+)\)\s*\)\s+'
    r'\(scale\s+\(xyz\s+([^)]+)\)\s*\)\s+'
    r'\(rotate\s+\(xyz\s+([^)]+)\)\s*\)\s*\)',
    r'(model "\1" (offset (xyz \2)) (scale (xyz \3)) (rotate (xyz \4)))',
    text, flags=re.DOTALL,
  )
  # Collapse fp_poly blocks
  text = re.sub(
    r'\(fp_poly\s+\(pts\s+((?:\(xy\s+[^)]+\)\s*)+)\)\s+'
    r'\(stroke\s+\(width\s+([^)]+)\)\s+\(type\s+solid\)\s*\)\s+'
    r'\(fill\s+(yes|no)\)\s+'
    r'\(layer\s+"([^"]+)"\)\s+\(uuid\s+"([^"]+)"\)\s*\)',
    lambda m: (
      f'(fp_poly (pts {" ".join(m[1].split())})'
      f' (stroke (width {m[2]}) (type solid))'
      f' (fill {m[3]}) (layer "{m[4]}") (uuid "{m[5]}"))'
    ),
    text, flags=re.DOTALL,
  )
  # Clean up multiple blank lines
  text = re.sub(r"\n{2,}", "\n", text)
  return text

def _compact_pad(m) -> str:
  num, mount, shape = m[1], m[2], m[3]
  at, size = m[4], m[5]
  drill_raw, layers = m[6], m[7]
  smm, rratio, uid = m[8], m[9], m[10]
  parts = [f'(pad "{num}" {mount} {shape} (at {at}) (size {size})']
  if drill_raw:
    parts.append(f'(drill {drill_raw})')
  parts.append(f'(layers {layers})')
  if mount == "thru_hole":
    parts.append("(remove_unused_layers no)")
  if smm:
    parts.append(f'(solder_mask_margin {smm})')
  if rratio:
    parts.append(f'(roundrect_rratio {rratio})')
  parts.append(f'(uuid "{uid}"))')
  return " ".join(parts)

def clean_footprint(filepath:str, style:Style=L,
  restyle:bool=True, dry:bool=False,
) -> tuple[int, int]:
  """Clean and compact a hand-drawn `.kicad_mod` footprint.

  Applies style tier fonts/widths, removes cruft,
  compacts multi-line to single-line S-expressions.

  Args:
    filepath: Path to `.kicad_mod` file.
    style: Size tier for line widths and fonts.
    restyle: When `True`, apply style tier widths and fonts.
    dry: When `True`, don't write changes.

  Returns:
    Tuple of `(original_size, new_size)` in bytes.
  """
  text = FILE.load(filepath)
  orig_size = len(text)
  stem = PATH.stem(filepath)
  s = style
  fs = fmt_number(s.font_size)
  ft = fmt_number(s.font_thick)
  # Fix Value text to match filename
  text = re.sub(
    r'(\(property "Value" ")[^"]*(")',
    rf'\g<1>{stem}\2',
    text,
  )
  # Fix Value at position
  text = re.sub(
    r'(\(property "Value" "[^"]*"\s+)\(at [^)]+\)',
    rf'\g<1>(at 0 1.6 180)',
    text,
  )
  # Remove (unlocked yes)
  text = re.sub(r'\s*\(unlocked yes\)', '', text)
  # Remove (justify ...) from property effects
  text = re.sub(r'\s*\(justify[^)]*\)', '', text)
  if restyle:
    # Fix Reference + Value font to style
    text = re.sub(
      r'(\(property "(Reference|Value)" [^(]*)'
      r'(\(size )\d+\.?\d*\s+\d+\.?\d*\)',
      rf'\g<1>\g<3>{fs} {fs})',
      text,
    )
    text = re.sub(
      r'(\(property "(Reference|Value)" .+?)'
      r'(\(thickness )\d+\.?\d*\)',
      rf'\g<1>\g<3>{ft})',
      text, flags=re.DOTALL,
    )
    # Fab width
    text = re.sub(
      r'\(width\s+\d+\.?\d*\)\s*\(type\s+solid\)\s*\)\s*'
      r'(?:\(fill\s+(?:yes|no)\)\s*)?'
      r'\(layer\s+"F\.Fab"\)',
      lambda m: re.sub(
        r'\(width\s+\d+\.?\d*', f'(width {fmt_number(s.fab)}', m.group(0), count=1,
      ),
      text, flags=re.DOTALL,
    )
    # Silk width remap: max → s.silk, rest → s.silk_detail
    silk_widths = set()
    for m in re.finditer(
      r'\(width\s+(\d+\.?\d*)\)\s*\(type\s+solid\)\s*\)\s*'
      r'(?:\(fill\s+(?:yes|no)\)\s*)?'
      r'\(layer\s+"F\.SilkS"\)',
      text, flags=re.DOTALL,
    ):
      silk_widths.add(m.group(1))
    if silk_widths:
      max_w = max(silk_widths, key=lambda x: float(x))
      def _remap_silk(m):
        w = m.group(1)
        target = fmt_number(s.silk if w == max_w else s.silk_detail)
        return re.sub(
          r'\(width\s+' + re.escape(w),
          f'(width {target}', m.group(0), count=1,
        )
      text = re.sub(
        r'\(width\s+(\d+\.?\d*)\)\s*\(type\s+solid\)\s*\)\s*'
        r'(?:\(fill\s+(?:yes|no)\)\s*)?'
        r'\(layer\s+"F\.SilkS"\)',
        _remap_silk,
        text, flags=re.DOTALL,
      )
    # CrtYd width
    text = re.sub(
      r'\(width\s+\d+\.?\d*\)\s*\(type\s+solid\)\s*\)\s*'
      r'(?:\(fill\s+(?:yes|no)\)\s*)?'
      r'\(layer\s+"F\.CrtYd"\)',
      lambda m: re.sub(
        r'\(width\s+\d+\.?\d*', f'(width {fmt_number(s.crtyd)}', m.group(0), count=1,
      ),
      text, flags=re.DOTALL,
    )
  # Round coordinate artifacts
  text = _round_coords(text)
  # Compact to single-line S-expressions
  text = _compact_block(text)
  new_size = len(text)
  if not dry:
    FILE.save(filepath, text)
  return orig_size, new_size

#------------------------------------------------------------------------------------- STEP ops

def _clean_file_name(block:str, fname:str) -> str:
  """Rebuild FILE_NAME keeping author and date, clearing junk."""
  date = re.search(r"'(\d{4}-\d{2}-\d{2}T[\d:]+)'", block)
  date = date.group(1) if date else ""
  after_date = block.split(date, 1)[-1] if date else block
  author = re.search(r"(\([^)]*\))", after_date)
  author = author.group(1) if author else "('')"
  return f"FILE_NAME('{fname}','{date}',{author},(''),'','','');"

def clean_step(filepath:str, dry:bool=False) -> tuple[int, int]:
  """Clean STEP file: strip comments, minimize header, fix names.

  Args:
    filepath: Path to `.step` / `.stp` file.
    dry: When `True`, don't write changes.

  Returns:
    Tuple of `(original_size, new_size)` in bytes.
  """
  text = FILE.load(filepath)
  orig_size = len(text)
  text = strip_comments(text, line=None, block=("/*", "*/"), quotes="'")
  text = re.sub(r"\n{2,}", "\n", text)
  basename = PATH.basename(filepath)
  stem = PATH.stem(filepath)
  parent = PATH.basename(PATH.dirname(filepath))
  fname = f"{parent}/{basename}" if parent else basename
  text = re.sub(
    r"FILE_NAME\s*\(.*?'\s*\)\s*;",
    lambda m: _clean_file_name(m.group(), fname),
    text, flags=re.DOTALL,
  )
  text = re.sub(
    r"FILE_DESCRIPTION\s*\(.*?'\s*\)\s*;",
    f"FILE_DESCRIPTION(('{stem}'),'2;1');",
    text, flags=re.DOTALL,
  )
  text = re.sub(
    r"FILE_SCHEMA\s*\(\s*\(\s*'AUTOMOTIVE_DESIGN[^']*'\s*\)\s*\)",
    "FILE_SCHEMA(('AUTOMOTIVE_DESIGN'))",
    text,
  )
  text = re.sub(
    r"(PRODUCT\s*\(\s*')([^']*?)('\s*,\s*')([^']*?)(')",
    rf"\g<1>{stem}\3{stem}\5",
    text,
  )
  new_size = len(text)
  if "ENDSEC;" not in text or "END-ISO-10303-21;" not in text:
    raise ValueError(f"Sanity check failed: {filepath} — missing ENDSEC or END marker")
  if not dry:
    FILE.save(filepath, text)
  return orig_size, new_size