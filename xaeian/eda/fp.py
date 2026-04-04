# xaeian/eda/fp.py

"""KiCad footprint generator.

Provides `Footprint` builder class for generating `.kicad_mod` files
with properties, drawing primitives, pads, and 3D model references.
Output is compact single-line S-expressions for minimal file size.

Presets: `XS`, `S`, `M`, `L`, `XL` size tiers with line/font standards.
Ref designators: `REF["connector"]` → `"J**"`.

Example:
  >>> from xaeian.eda.fp import Footprint, REF, S
  >>> fp = Footprint("SOT-23", ref=REF["transistor"], style=S)
  >>> fp.properties()
  >>> fp.pad_smd(1, -0.95, 0, 0.9, 0.8)
  >>> fp.model("${L3D}/SOT/SOT-23.step")
  >>> fp.save("./SOT.pretty")
"""
import uuid
from dataclasses import dataclass
from ..files import FILE

def _uid() -> str:
  return str(uuid.uuid4())

def fmt_number(v:float) -> str:
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
      f' (at {fmt_number(x)} {fmt_number(y)} {fmt_number(angle)})'
      f' (layer "{layer}")'
      f' (uuid "{_uid()}")'
      f' (effects (font (size {fmt_number(s1)} {fmt_number(s2)}) (thickness {fmt_number(th)}))))'
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
      f'\t(fp_line (start {fmt_number(x1)} {fmt_number(y1)}) (end {fmt_number(x2)} {fmt_number(y2)})'
      f' (stroke (width {fmt_number(width)}) (type solid))'
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
      f'\t(fp_rect (start {fmt_number(x1)} {fmt_number(y1)}) (end {fmt_number(x2)} {fmt_number(y2)})'
      f' (stroke (width {fmt_number(width)}) (type solid))'
      f' (fill yes) (layer "{layer}") (uuid "{_uid()}"))'
    )

  def circle(self, cx:float, cy:float, radius:float,
    width:float, layer:str,
  ):
    """Add `fp_circle`."""
    self._add(
      f'\t(fp_circle (center {fmt_number(cx)} {fmt_number(cy)})'
      f' (end {fmt_number(cx + radius)} {fmt_number(cy)})'
      f' (stroke (width {fmt_number(width)}) (type solid))'
      f' (layer "{layer}") (uuid "{_uid()}"))'
    )

  def arc(self, sx:float, sy:float, mx:float, my:float,
    ex:float, ey:float, width:float, layer:str,
  ):
    """Add `fp_arc` (3-point: start, midpoint, end)."""
    self._add(
      f'\t(fp_arc (start {fmt_number(sx)} {fmt_number(sy)})'
      f' (mid {fmt_number(mx)} {fmt_number(my)})'
      f' (end {fmt_number(ex)} {fmt_number(ey)})'
      f' (stroke (width {fmt_number(width)}) (type solid))'
      f' (layer "{layer}") (uuid "{_uid()}"))'
    )

  def text(self, txt:str, x:float, y:float, layer:str,
    size:float = 1, thickness:float = 0.15, angle:float = 0,
  ):
    """Add `fp_text`."""
    self._add(
      f'\t(fp_text user "{txt}" (at {fmt_number(x)} {fmt_number(y)} {fmt_number(angle)})'
      f' (layer "{layer}") (uuid "{_uid()}")'
      f' (effects (font (size {fmt_number(size)} {fmt_number(size)})'
      f' (thickness {fmt_number(thickness)}))))'
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
      dr = f'(drill {fmt_number(drill)} (offset {fmt_number(dx)} {fmt_number(dy)}))'
    else:
      dr = f'(drill {fmt_number(drill)})'
    self._add(
      f'\t(pad "{num}" thru_hole {shape} (at {fmt_number(x)} {fmt_number(y)})'
      f' (size {fmt_number(w)} {fmt_number(h)}) {dr}'
      f' (layers "*.Cu" "*.Mask") (remove_unused_layers no)'
      f'{rr} (uuid "{_uid()}"))'
    )

  def pad_smd(self, num:int|str, x:float, y:float,
    w:float, h:float,
    shape:str = "roundrect", rratio:float = 0.25,
    layers:list[str]|None = None,
  ):
    """Add SMD pad."""
    if layers is None: layers = ["F.Cu", "F.Paste", "F.Mask"]
    rr = f' (roundrect_rratio {rratio})' if rratio is not None else ""
    ly = " ".join(f'"{l}"' for l in layers)
    self._add(
      f'\t(pad "{num}" smd {shape} (at {fmt_number(x)} {fmt_number(y)})'
      f' (size {fmt_number(w)} {fmt_number(h)}) (layers {ly})'
      f'{rr} (uuid "{_uid()}"))'
    )

  def pad_npth(self, x:float, y:float, drill:float):
    """Add non-plated through hole."""
    self._add(
      f'\t(pad "" np_thru_hole circle (at {fmt_number(x)} {fmt_number(y)})'
      f' (size {fmt_number(drill)} {fmt_number(drill)}) (drill {fmt_number(drill)})'
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
      f' (offset (xyz {fmt_number(ox)} {fmt_number(oy)} {fmt_number(oz)}))'
      f' (scale (xyz {fmt_number(sx)} {fmt_number(sy)} {fmt_number(sz)}))'
      f' (rotate (xyz {fmt_number(rx)} {fmt_number(ry)} {fmt_number(rz)})))'
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