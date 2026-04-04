# xaeian/eda/sym.py

"""KiCad symbol library generator.

Provides `Symbol` builder and `SymbolLib` container for generating
`.kicad_sym` files. All dimensions in **mil** (converted to mm on output).
Compact single-line S-expressions for minimal file size.

Presets: `S`, `M`, `L` font tiers.
Ref designators: `REF["connector"]` -> `"J"`.

Example:
  >>> from xaeian.eda.sym import Symbol, SymbolLib, REF, M
  >>> lib = SymbolLib()
  >>> sym = Symbol("78L05", ref=REF["ic"], style=M, pin_offset=10)
  >>> sym.properties(ref_at=(0, 270), val_at=(0, 200), bold_val=True)
  >>> sym.prop("Footprint")
  >>> sym.prop("Datasheet")
  >>> sym.prop("Description", "Imax:150mA; Vout:5V;")
  >>> sym.rect(-150, -100, 150, 100)
  >>> sym.pin(1, -200, 50, name="VI", type="power_in")
  >>> sym.pin(2, 0, -200, angle=90, name="GND", type="power_in")
  >>> sym.pin(3, 200, 50, angle=180, name="VO", type="power_out")
  >>> lib.add(sym)
  >>> lib.save("./LDO.kicad_sym")
"""

from dataclasses import dataclass
from ..files import FILE

#----------------------------------------------------------------------------------------- Mil

MIL = 0.0254  # 1mil in mm

def _n(v:float) -> str:
  """Convert mil to mm, format: `100` -> `2.54`, `50` -> `1.27`."""
  mm = round(v * MIL, 4)
  if mm == int(mm): return str(int(mm))
  return f"{mm:g}"

def _a(v:float) -> str:
  """Format angle in degrees (no unit conversion)."""
  if v == int(v): return str(int(v))
  return f"{v:g}"

#-------------------------------------------------------------------------------------- Presets

@dataclass
class Style:
  """Font settings for a symbol size tier. Values in mil."""
  font: float   # Reference, Value, pin name, pin number
  thick: float  # font stroke thickness

# Tier is per component series, not per individual symbol
S  = Style(font=30, thick=6)  # passive (R, C, L, D)
M  = Style(font=40, thick=6)  # connectors, small IC
L  = Style(font=50, thick=6)  # IC, complex components

PROP_FONT = 30   # hidden property font (mil)
PROP_THICK = 6   # hidden property thickness (mil)
DETAIL_THICK = 4 # detail/decoration thickness (mil)

# Reference designators (IEEE 315)
REF = {
  "resistor": "R",
  "resistor_network": "RN",
  "capacitor": "C",
  "inductor": "L",
  "ferrite": "FB",
  "diode": "D",
  "transistor": "Q",
  "ic": "U",
  "connector": "J",
  "switch": "SW",
  "fuse": "F",
  "relay": "K",
  "transformer": "T",
  "crystal": "Y",
  "motor": "M",
  "wire": "W",
  "jumper": "JP",
  "test_point": "TP",
  "hole": "H",
  "fiducial": "FID",
  "mechanical": "MP",
  "battery": "BT",
  "speaker": "SP",
  "microphone": "MK",
  "filter": "FL",
  "antenna": "ANT",
  "power_supply": "PS",
}

#-------------------------------------------------------------------------------------- Symbol

class Symbol:
  """KiCad symbol builder. All coordinates in mil."""

  def __init__(self, name:str, ref:str="REF", style:Style=L,
    pin_offset:float=0, pin_names:bool=True, pin_numbers:bool=True,
  ):
    self.name = name
    self.ref = ref
    self.style = style
    self.pin_offset = pin_offset
    self.pin_names_visible = pin_names
    self.pin_numbers_visible = pin_numbers
    self._props: list[str] = []
    self._graphics: list[str] = []
    self._units: dict[int, list[str]] = {}
    self._unit = 1

  def unit(self, n:int):
    """Switch active unit for subsequent `pin()` calls."""
    self._unit = n

  #---------------------------------------------------------------------------------- Properties

  def _font_str(self, size:float, thick:float,
    bold:bool=False, italic:bool=False,
  ) -> str:
    parts = [f"(size {_n(size)} {_n(size)})"]
    parts.append(f"(thickness {_n(thick)})")
    if bold: parts.append("(bold yes)")
    if italic: parts.append("(italic yes)")
    return f"(font {' '.join(parts)})"

  def properties(self,
    ref_at:tuple=(0, 0), val_at:tuple=(0, 0),
    bold_val:bool=False, italic_val:bool=False, hide_val:bool=False,
  ):
    """Add Reference and Value properties."""
    s = self.style
    rx, ry = ref_at
    vx, vy = val_at
    self._props.append(
      f'\t\t(property "Reference" "{self.ref}"'
      f' (at {_n(rx)} {_n(ry)} 0)'
      f' (effects {self._font_str(s.font, s.thick)}))'
    )
    val_hide = " (hide yes)" if hide_val else ""
    self._props.append(
      f'\t\t(property "Value" "{self.name}"'
      f' (at {_n(vx)} {_n(vy)} 0)'
      f' (effects {self._font_str(s.font, s.thick, bold=bold_val, italic=italic_val)}{val_hide}))'
    )

  def prop(self, name:str, value:str="",
    at:tuple=(0, 0), hide:bool=True,
  ):
    """Add custom property (Manufacturer, Code, LCSC, etc.)."""
    x, y = at
    hfont = self._font_str(PROP_FONT, PROP_THICK)
    hide_s = " (hide yes)" if hide else ""
    self._props.append(
      f'\t\t(property "{name}" "{value}"'
      f' (at {_n(x)} {_n(y)} 0) (effects {hfont}{hide_s}))'
    )

  #---------------------------------------------------------------------------- Drawing primitives

  def rect(self, x1:float, y1:float, x2:float, y2:float,
    fill:str="background", width:float=0,
  ):
    """Add rectangle to shared graphics."""
    self._graphics.append(
      f'\t\t\t(rectangle (start {_n(x1)} {_n(y1)}) (end {_n(x2)} {_n(y2)})'
      f' (stroke (width {_n(width)}) (type solid))'
      f' (fill (type {fill})))'
    )

  def polyline(self, pts:list[tuple],
    fill:str="none", width:float=5,
  ):
    """Add polyline to shared graphics."""
    pts_s = " ".join(f"(xy {_n(x)} {_n(y)})" for x, y in pts)
    self._graphics.append(
      f'\t\t\t(polyline (pts {pts_s})'
      f' (stroke (width {_n(width)}) (type solid))'
      f' (fill (type {fill})))'
    )

  def circle(self, cx:float, cy:float, radius:float,
    fill:str="outline", width:float=0,
  ):
    """Add circle to shared graphics."""
    self._graphics.append(
      f'\t\t\t(circle (center {_n(cx)} {_n(cy)}) (radius {_n(radius)})'
      f' (stroke (width {_n(width)}) (type solid))'
      f' (fill (type {fill})))'
    )

  def arc(self, sx:float, sy:float, mx:float, my:float,
    ex:float, ey:float, width:float=0,
  ):
    """Add 3-point arc to shared graphics."""
    self._graphics.append(
      f'\t\t\t(arc (start {_n(sx)} {_n(sy)})'
      f' (mid {_n(mx)} {_n(my)}) (end {_n(ex)} {_n(ey)})'
      f' (stroke (width {_n(width)}) (type solid))'
      f' (fill (type none)))'
    )

  def text(self, txt:str, x:float, y:float,
    size:float|None=None, thick:float|None=None, angle:float=0,
  ):
    """Add text to shared graphics."""
    sz = size or self.style.font
    th = thick or self.style.thick
    self._graphics.append(
      f'\t\t\t(text "{txt}" (at {_n(x)} {_n(y)} {_a(angle)})'
      f' (effects {self._font_str(sz, th)}))'
    )

  #---------------------------------------------------------------------------------------- Pins

  def pin(self, number:int|str, x:float, y:float,
    angle:float=0, length:float=100,
    name:str|None=None, type:str="passive", graphic:str="line",
  ):
    """Add pin to current unit. Angle: 0=right, 90=up, 180=left, 270=down."""
    pname = name if name is not None else str(number)
    s = self.style
    pfont = self._font_str(s.font, s.thick)
    self._units.setdefault(self._unit, []).append(
      f'\t\t\t(pin {type} {graphic}'
      f' (at {_n(x)} {_n(y)} {_a(angle)})'
      f' (length {_n(length)})'
      f' (name "{pname}" (effects {pfont}))'
      f' (number "{number}" (effects {pfont})))'
    )

  #----------------------------------------------------------------------------------------- Raw

  def raw_gfx(self, text:str):
    """Add raw S-expression to shared graphics."""
    self._graphics.append(text)

  def raw_unit(self, text:str):
    """Add raw S-expression to current unit."""
    self._units.setdefault(self._unit, []).append(text)

  #-------------------------------------------------------------------------------------- Build

  def build(self) -> str:
    """Build symbol S-expression block (without library wrapper)."""
    lines = []
    # Symbol header
    lines.append(f'\t(symbol "{self.name}"')
    if not self.pin_numbers_visible:
      lines.append(f'\t\t(pin_numbers (hide yes))')
    pn_hide = " (hide yes)" if not self.pin_names_visible else ""
    lines.append(
      f'\t\t(pin_names (offset {_n(self.pin_offset)}){pn_hide})'
    )
    lines.append(f'\t\t(exclude_from_sim no)')
    lines.append(f'\t\t(in_bom yes)')
    lines.append(f'\t\t(on_board yes)')
    # Properties
    lines.extend(self._props)
    # Shared graphics: NAME_0_1
    if self._graphics:
      lines.append(f'\t\t(symbol "{self.name}_0_1"')
      lines.extend(self._graphics)
      lines.append(f'\t\t)')
    # Per-unit content: NAME_N_1
    for unum in sorted(self._units.keys()):
      lines.append(f'\t\t(symbol "{self.name}_{unum}_1"')
      lines.extend(self._units[unum])
      lines.append(f'\t\t)')
    lines.append(f'\t\t(embedded_fonts no)')
    lines.append(f'\t)')
    return "\n".join(lines)

#----------------------------------------------------------------------------------- SymbolLib

class SymbolLib:
  """KiCad symbol library container (.kicad_sym)."""

  def __init__(self):
    self._symbols: list[Symbol] = []

  def add(self, sym:Symbol):
    """Add symbol to library."""
    self._symbols.append(sym)

  def build(self) -> str:
    """Build complete .kicad_sym content."""
    lines = [
      f'(kicad_symbol_lib',
      f'\t(version 20241209)',
      f'\t(generator "kicad_symbol_editor")',
      f'\t(generator_version "9.0")',
    ]
    for sym in self._symbols:
      lines.append(sym.build())
    lines.append(')')
    return "\n".join(lines)

  def save(self, path:str) -> str:
    """Save .kicad_sym file. Returns filepath."""
    FILE.save(path, self.build())
    return path