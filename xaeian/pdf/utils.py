# xaeian/pdf/utils.py

"""Utility functions - unit conversion, color parsing, helpers."""
from reportlab.lib.units import mm as RL_MM
from .constants import Unit

#-------------------------------------------------------------------------------------- Units
def to_mm(value:float, unit:str="mm") -> float:
  """Convert value from given unit to millimeters."""
  unit = unit.lower()
  factors = {"mm": Unit.MM, "cm": Unit.CM, "in": Unit.INCH, "inch": Unit.INCH,
             "pt": Unit.PT, "px": Unit.PX}
  if unit not in factors:
    raise ValueError(f"Unknown unit: {unit}. Use: mm, cm, in, pt, px")
  return value * factors[unit]

def to_pt(value_mm:float) -> float:
  """Convert millimeters to points."""
  return value_mm * RL_MM

def mm_to_pt(*values:float) -> list[float]|float:
  """Convert mm values to points. Returns single value or list."""
  result = [v * RL_MM for v in values]
  return result[0] if len(result) == 1 else result

#-------------------------------------------------------------------------------------- Colors
def parse_color(color:tuple|str|None) -> tuple[float, float, float]:
  """Parse color from tuple or hex string to (r, g, b) 0-1 range."""
  if color is None:
    return (0, 0, 0)
  if isinstance(color, tuple):
    if len(color) >= 3:
      return (color[0], color[1], color[2])
    raise ValueError("Color tuple must have at least 3 values (r, g, b)")
  if isinstance(color, str):
    color = color.lstrip("#")
    if len(color) == 3:
      color = "".join(c * 2 for c in color)
    if len(color) != 6:
      raise ValueError(f"Invalid hex color: {color}")
    r = int(color[0:2], 16) / 255
    g = int(color[2:4], 16) / 255
    b = int(color[4:6], 16) / 255
    return (r, g, b)
  raise ValueError(f"Invalid color type: {type(color)}")

def color_alpha(color:tuple, alpha:float) -> tuple[float, float, float, float]:
  """Add alpha channel to color tuple."""
  r, g, b = parse_color(color)
  return (r, g, b, alpha)

#-------------------------------------------------------------------------------------- Margin
def parse_margin(margin:float|tuple) -> tuple[float, float, float]:
  """Parse margin to (lr, top, bot) tuple."""
  if isinstance(margin, (int, float)):
    return (margin, margin, margin)
  if isinstance(margin, tuple):
    if len(margin) == 1:
      return (margin[0], margin[0], margin[0])
    if len(margin) == 2:
      return (margin[0], margin[1], margin[1])
    if len(margin) >= 3:
      return (margin[0], margin[1], margin[2])
  raise ValueError(f"Invalid margin: {margin}")

#-------------------------------------------------------------------------------------- Text
def sanitize_text(text:str, link_char:str="·", enter_in:str="\n", enter_out:str="\n") -> str:
  """Prepare text for rendering - handle special chars."""
  text = text.replace(link_char, "¶")
  text = text.replace(enter_in, enter_out)
  return text
