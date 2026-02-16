# xaeian/pdf/layout.py

"""Layout system - cursor positioning, alignment, page geometry."""
from dataclasses import dataclass
from .constants import Align

#-------------------------------------------------------------------------------------- Cursor
@dataclass
class Cursor:
  """Position tracker with alignment and auto-advance."""
  x: float = 0
  y: float = 0
  x_base: float = 0  # x position after enter()
  align: str = Align.LEFT
  last_height: float = 0
  last_width: float = 0

  def set(self, x:float|None=None, y:float|None=None, align:str|None=None) -> "Cursor":
    """Set cursor position and/or alignment."""
    if x is not None:
      self.x = x
      self.x_base = x
    if y is not None:
      self.y = y
    if align is not None:
      self.align = align
    self.last_height = 0
    self.last_width = 0
    return self

  def move(self, dx:float=0, dy:float=0) -> "Cursor":
    """Relative cursor movement."""
    self.x += dx
    self.y += dy
    return self

  def enter(self, height:float|None=None) -> "Cursor":
    """Move to new line - reset x to base, advance y."""
    self.x = self.x_base
    self.y += height if height is not None else self.last_height
    self.last_height = 0
    return self

  def advance_x(self, width:float) -> "Cursor":
    """Advance x position based on alignment."""
    if self.align == Align.LEFT:
      self.x += width
    elif self.align == Align.RIGHT:
      self.x -= width
    self.last_width = width
    return self

  def record_height(self, height:float) -> "Cursor":
    """Record element height for auto-enter."""
    self.last_height = height
    return self

  def copy(self) -> "Cursor":
    """Create cursor copy."""
    return Cursor(
      x=self.x, y=self.y, x_base=self.x_base,
      align=self.align, last_height=self.last_height, last_width=self.last_width
    )

#-------------------------------------------------------------------------------------- PageGeometry
@dataclass
class PageGeometry:
  """Page dimensions and margins."""
  width: float  # mm
  height: float  # mm
  margin_lr: float = 15  # left-right
  margin_top: float = 15
  margin_bot: float = 15

  @property
  def content_width(self) -> float:
    """Available width for content."""
    return self.width - 2 * self.margin_lr

  @property
  def content_height(self) -> float:
    """Available height for content."""
    return self.height - self.margin_top - self.margin_bot

  def x_for_align(self, width:float, align:str) -> float:
    """Calculate x position for given alignment and element width."""
    if align == Align.LEFT:
      return self.margin_lr
    elif align == Align.CENTER:
      return (self.width - width) / 2
    elif align == Align.RIGHT:
      return self.width - self.margin_lr - width
    return self.margin_lr

  def cursor_to_canvas(self, cursor:Cursor, width:float=0) -> tuple[float, float]:
    """Convert cursor position to canvas coordinates (mm).
    
    Cursor: origin top-left, y grows down
    Canvas: origin bottom-left, y grows up
    Returns (x_mm, y_mm) in canvas coordinates.
    """
    x = cursor.x
    y = self.height - cursor.y - self.margin_top
    # Adjust x based on alignment
    if cursor.align == Align.LEFT:
      x += self.margin_lr
    elif cursor.align == Align.CENTER:
      x += (self.width - width) / 2
    elif cursor.align == Align.RIGHT:
      x += self.width - self.margin_lr - width
    return x, y
