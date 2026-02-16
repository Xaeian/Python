# xaeian/pdf/constants.py

"""Constants for PDF library - units, colors, defaults."""
from dataclasses import dataclass

#-------------------------------------------------------------------------------------- Units
class Unit:
  """Unit conversion factors to millimeters."""
  MM = 1.0
  CM = 10.0
  INCH = 25.4
  PT = 0.3528  # 1pt = 0.3528mm
  PX = 0.2646  # 96 DPI

#-------------------------------------------------------------------------------------- PageSize
@dataclass
class PageSize:
  """Common page sizes in mm."""
  width: float
  height: float

  def landscape(self) -> "PageSize":
    return PageSize(self.height, self.width)

# Standard sizes
A4 = PageSize(210, 297)
A3 = PageSize(297, 420)
A5 = PageSize(148, 210)
LETTER = PageSize(215.9, 279.4)
LEGAL = PageSize(215.9, 355.6)

#-------------------------------------------------------------------------------------- Align
class Align:
  """Text/element alignment constants."""
  LEFT = "L"
  RIGHT = "R"
  CENTER = "C"
  JUSTIFY = "J"

#-------------------------------------------------------------------------------------- Colors
class Colors:
  """Predefined colors as (r, g, b) tuples (0-1 range)."""
  BLACK = (0, 0, 0)
  WHITE = (1, 1, 1)
  RED = (1, 0, 0)
  GREEN = (0, 1, 0)
  BLUE = (0, 0, 1)
  GREY = (0.5, 0.5, 0.5)
  LIGHT_GREY = (0.8, 0.8, 0.8)
  DARK_GREY = (0.3, 0.3, 0.3)

#-------------------------------------------------------------------------------------- Defaults
class Defaults:
  """Default values for PDF generation."""
  PAGE_WIDTH = 210  # A4
  PAGE_HEIGHT = 297
  MARGIN = 15
  FONT_FAMILY = "Helvetica"
  FONT_SIZE = 12
  FONT_MODE = "Regular"
  LINE_HEIGHT = 1.2
  UNIT = "mm"
