# xaeian/eda/kicad_fp.py

"""KiCad footprint generator and STEP file utilities.

Provides `Footprint` builder class for generating `.kicad_mod` files
with properties, drawing primitives, pads, and 3D model references.
Output is compact single-line S-expressions for minimal file size.

Presets: `XS`, `S`, `M`, `L`, `XL` size tiers with line/font standards.
Ref designators: `REF["connector"]` → `"J**"`.

Example:
  >>> from xaeian.eda import Footprint, REF, L
  >>> fp = Footprint("SOT-23", ref=REF["transistor"], style=S)
  >>> fp.properties()
  >>> fp.pad_smd(1, -0.95, 0, 0.9, 0.8)
  >>> fp.model("${L3D}/SOT/SOT-23.step")
  >>> fp.save("./SOT.pretty")
"""
import re, uuid
from dataclasses import dataclass
from ..xstring import strip_comments
from ..files import FILE, PATH

def _uid() -> str:
  return str(uuid.uuid4())

def _n(v:float) -> str:
  """Format number: `1.0` → `1`, `1.5` → `1.5`."""
  if v == int(v): return str(int(v))
  return f"{v:g}"

#-------------------------------------------------------------------------------------- Presets

@dataclass
class Style:
  """Line widths and font settings for a size tier."""
  silk: float         # SilkS outline width
  silk_detail: float  # SilkS inner detail width
  crtyd: float        # CrtYd width
  fab: float          # Fab width
  font_size: float    # Reference/Value font size
  font_thick: float   # Reference/Value font thickness

# Size tiers: XXS (<1.5mm) → XS (1.5-3mm) → S (3-6mm) → M (6-15mm) → L (15-30mm) → XL (>30mm)
XXS = Style(silk=0.08, silk_detail=0.05, crtyd=0.05, fab=0.06, font_size=0.4, font_thick=0.06)
XS  = Style(silk=0.1,  silk_detail=0.06, crtyd=0.05, fab=0.08, font_size=0.6, font_thick=0.08)
S   = Style(silk=0.12, silk_detail=0.08, crtyd=0.05, fab=0.1,  font_size=0.8, font_thick=0.1)
M   = Style(silk=0.15, silk_detail=0.1,  crtyd=0.05, fab=0.12, font_size=1.0, font_thick=0.12)
L   = Style(silk=0.2,  silk_detail=0.12, crtyd=0.05, fab=0.15, font_size=1.2, font_thick=0.14)
XL  = Style(silk=0.25, silk_detail=0.15, crtyd=0.05, fab=0.2,  font_size=1.5, font_thick=0.16)

# Reference designators
REF = {
  "connector": "J**",
  "resistor": "R**",
  "capacitor": "C**",
  "ic": "U**",
  "transistor": "Q**",
  "diode": "D**",
  "inductor": "L**",
  "crystal": "Y**",
  "switch": "SW**",
  "fuse": "F**",
  "relay": "K**",
  "transformer": "T**",
  "led": "D**",
  "motor": "M**",
}

#------------------------------------------------------------------------------------- Footprint

class Footprint:
  """KiCad `.kicad_mod` footprint builder."""

  def __init__(self, name:str, ref:str="REF**",
    layer:str="F.Cu", style:Style=L,
  ):
    self.name = name
    self.ref = ref
    self.layer = layer
    self.style = style
    self._lines: list[str] = []

  def _add(self, line:str):
    self._lines.append(line)

  #---------------------------------------------------------------------------------- Properties

  def properties(self,
    ref_at:tuple = (0, 0, 0),
    ref_layer:str = "F.Fab",
    ref_font:tuple|None = None,
    val_at:tuple = (0, 1.6, 180),
    val_layer:str = "F.Fab",
    val_font:tuple|None = None,
  ):
    """Add Reference, Value, Datasheet, Description properties."""
    s = self.style
    font = ref_font or (s.font_size, s.font_size, s.font_thick)
    self._prop("Reference", self.ref, ref_at, ref_layer, font)
    font = val_font or (s.font_size, s.font_size, s.font_thick)
    self._prop("Value", self.name, val_at, val_layer, font)
    for name in ("Datasheet", "Description"):
      self._add(
        f'\t(property "{name}" "" (at 0 0 0) (layer "F.Fab") (hide yes)'
        f' (uuid "{_uid()}")'
        f' (effects (font (size 1.27 1.27) (thickness 0.15))))'
      )

  def _prop(self, name:str, value:str,
    at:tuple, layer:str, font:tuple,
  ):
    x, y, angle = at
    s1, s2, th = font
    self._add(
      f'\t(property "{name}" "{value}"'
      f' (at {_n(x)} {_n(y)} {_n(angle)})'
      f' (layer "{layer}")'
      f' (uuid "{_uid()}")'
      f' (effects (font (size {_n(s1)} {_n(s2)}) (thickness {_n(th)}))))'
    )

  def attr(self, kind:str = "through_hole"):
    """Set footprint attribute."""
    self._add(f'\t(attr {kind})')

  #---------------------------------------------------------------------------- Drawing primitives

  def line(self, x1:float, y1:float, x2:float, y2:float,
    width:float, layer:str,
  ):
    """Add `fp_line`."""
    self._add(
      f'\t(fp_line (start {_n(x1)} {_n(y1)}) (end {_n(x2)} {_n(y2)})'
      f' (stroke (width {_n(width)}) (type solid))'
      f' (layer "{layer}") (uuid "{_uid()}"))'
    )

  def rect(self, x1:float, y1:float, x2:float, y2:float,
    width:float, layer:str,
  ):
    """Add rectangle as 4 `fp_line` segments."""
    self.line(x1, y1, x2, y1, width, layer)
    self.line(x2, y1, x2, y2, width, layer)
    self.line(x2, y2, x1, y2, width, layer)
    self.line(x1, y2, x1, y1, width, layer)

  def filled_rect(self, x1:float, y1:float, x2:float, y2:float,
    width:float, layer:str,
  ):
    """Add `fp_rect` with fill."""
    self._add(
      f'\t(fp_rect (start {_n(x1)} {_n(y1)}) (end {_n(x2)} {_n(y2)})'
      f' (stroke (width {_n(width)}) (type solid))'
      f' (fill yes) (layer "{layer}") (uuid "{_uid()}"))'
    )

  def circle(self, cx:float, cy:float, radius:float,
    width:float, layer:str,
  ):
    """Add `fp_circle`."""
    self._add(
      f'\t(fp_circle (center {_n(cx)} {_n(cy)})'
      f' (end {_n(cx + radius)} {_n(cy)})'
      f' (stroke (width {_n(width)}) (type solid))'
      f' (layer "{layer}") (uuid "{_uid()}"))'
    )

  def arc(self, cx:float, cy:float, ex:float, ey:float,
    angle:float, width:float, layer:str,
  ):
    """Add `fp_arc`."""
    self._add(
      f'\t(fp_arc (start {_n(cx)} {_n(cy)})'
      f' (end {_n(ex)} {_n(ey)}) (angle {_n(angle)})'
      f' (stroke (width {_n(width)}) (type solid))'
      f' (layer "{layer}") (uuid "{_uid()}"))'
    )

  def text(self, txt:str, x:float, y:float, layer:str,
    size:float = 1, thickness:float = 0.15, angle:float = 0,
  ):
    """Add `fp_text`."""
    self._add(
      f'\t(fp_text user "{txt}" (at {_n(x)} {_n(y)} {_n(angle)})'
      f' (layer "{layer}") (uuid "{_uid()}")'
      f' (effects (font (size {_n(size)} {_n(size)})'
      f' (thickness {_n(thickness)}))))'
    )

  #---------------------------------------------------------------------------------------- Pads

  def pad_tht(self, num:int|str, x:float, y:float,
    w:float, h:float, drill:float,
    shape:str = "oval", rratio:float|None = None,
    drill_offset:tuple|None = None,
  ):
    """Add through-hole pad. Shape: `circle`, `oval`, `rect`, `roundrect`."""
    rr = f' (roundrect_rratio {rratio})' if rratio is not None else ""
    if drill_offset:
      dx, dy = drill_offset
      dr = f'(drill {_n(drill)} (offset {_n(dx)} {_n(dy)}))'
    else:
      dr = f'(drill {_n(drill)})'
    self._add(
      f'\t(pad "{num}" thru_hole {shape} (at {_n(x)} {_n(y)})'
      f' (size {_n(w)} {_n(h)}) {dr}'
      f' (layers "*.Cu" "*.Mask") (remove_unused_layers no)'
      f'{rr} (uuid "{_uid()}"))'
    )

  def pad_smd(self, num:int|str, x:float, y:float,
    w:float, h:float,
    shape:str = "roundrect", rratio:float = 0.25,
    layers:str = "F.Cu F.Paste F.Mask",
  ):
    """Add SMD pad."""
    rr = f' (roundrect_rratio {rratio})' if rratio is not None else ""
    self._add(
      f'\t(pad "{num}" smd {shape} (at {_n(x)} {_n(y)})'
      f' (size {_n(w)} {_n(h)}) (layers "{layers}")'
      f'{rr} (uuid "{_uid()}"))'
    )

  def pad_npth(self, x:float, y:float, drill:float):
    """Add non-plated through hole."""
    self._add(
      f'\t(pad "" np_thru_hole circle (at {_n(x)} {_n(y)})'
      f' (size {_n(drill)} {_n(drill)}) (drill {_n(drill)})'
      f' (layers "*.Cu" "*.Mask") (uuid "{_uid()}"))'
    )

  #------------------------------------------------------------------------------------- 3D model

  def model(self, path:str,
    offset:tuple = (0, 0, 0),
    scale:tuple = (1, 1, 1),
    rotate:tuple = (0, 0, 0),
  ):
    """Add 3D model reference."""
    ox, oy, oz = offset
    sx, sy, sz = scale
    rx, ry, rz = rotate
    self._add(
      f'\t(model "{path}"'
      f' (offset (xyz {_n(ox)} {_n(oy)} {_n(oz)}))'
      f' (scale (xyz {_n(sx)} {_n(sy)} {_n(sz)}))'
      f' (rotate (xyz {_n(rx)} {_n(ry)} {_n(rz)})))'
    )

  #-------------------------------------------------------------------------------------- Output

  def raw(self, text:str):
    """Add raw S-expression line."""
    self._add(text)

  def build(self) -> str:
    """Build complete footprint string."""
    header = [
      f'(footprint "{self.name}"',
      f'\t(version 20241229)',
      f'\t(generator "pcbnew")',
      f'\t(generator_version "9.0")',
      f'\t(layer "{self.layer}")',
    ]
    footer = [
      f'\t(embedded_fonts no)',
      f')',
    ]
    return "\n".join(header + self._lines + footer)

  def save(self, directory:str) -> str:
    """Save `.kicad_mod` file to directory. Returns filepath."""
    path = f"{directory}/{self.name}.kicad_mod"
    FILE.save(path, self.build())
    return path

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
    r'\(pad\s+"([^"]+)"\s+(smd|thru_hole|np_thru_hole)\s+(\w+)\s+'
    r'\(at\s+([^)]+)\)\s+\(size\s+([^)]+)\)\s+'
    r'(?:\(drill\s+((?:[^()]*|\([^)]*\))*)\)\s+)?'
    r'\(layers\s+([^)]+)\)\s*'
    r'(?:\(remove_unused_layers\s+no\)\s+)?'
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
  # Clean up multiple blank lines
  text = re.sub(r"\n{2,}", "\n", text)
  return text

def _compact_pad(m) -> str:
  """Rebuild pad as single line from regex match."""
  num, mount, shape = m[1], m[2], m[3]
  at, size = m[4], m[5]
  drill_raw, layers = m[6], m[7]
  rratio, uid = m[8], m[9]
  parts = [f'(pad "{num}" {mount} {shape} (at {at}) (size {size})']
  if drill_raw:
    parts.append(f'(drill {drill_raw})')
  parts.append(f'(layers {layers})')
  if mount == "thru_hole":
    parts.append("(remove_unused_layers no)")
  if rratio:
    parts.append(f'(roundrect_rratio {rratio})')
  parts.append(f'(uuid "{uid}"))')
  return " ".join(parts)

def clean_footprint(filepath:str, style:Style=L, dry:bool=False) -> tuple[int, int]:
  """Clean and compact a hand-drawn `.kicad_mod` footprint.

  Applies style tier fonts/widths, removes cruft,
  compacts multi-line to single-line S-expressions.

  Args:
    filepath: Path to `.kicad_mod` file.
    style: Size tier for line widths and fonts.
    dry: When `True`, don't write changes.

  Returns:
    Tuple of `(original_size, new_size)` in bytes.
  """
  text = FILE.load(filepath)
  orig_size = len(text)
  stem = PATH.stem(filepath)
  s = style
  fs = _n(s.font_size)
  ft = _n(s.font_thick)
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
  # Fix Fab width
  text = re.sub(
    r'(\(width )\d+\.?\d*(\)\s*\(type solid\)\s*\)\s*\(layer "F\.Fab")',
    rf'\g<1>{_n(s.fab)}\2',
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
    r"FILE_NAME\s*\(.*?'\);",
    lambda m: _clean_file_name(m.group(), fname),
    text, flags=re.DOTALL,
  )
  text = re.sub(
    r"FILE_DESCRIPTION\s*\(.*?'\);",
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
  if not dry:
    FILE.save(filepath, text)
  return orig_size, new_size