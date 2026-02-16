# xaeian/pdf/tables.py

"""Table rendering with page break support."""
from dataclasses import dataclass, field
from .styles import TableStyle
from .text import TextMetrics
from .constants import Align

#----------------------------------------------------------------------------------------- Cell

@dataclass
class Cell:
  """Table cell data."""
  text: str = ""
  colspan: int = 1
  rowspan: int = 1
  align: str|None = None  # override column align
  style: dict|None = None  # custom styling

#------------------------------------------------------------------------------------ TableData

@dataclass
class TableData:
  """Prepared table data for rendering."""
  header: list[str]|None = None
  header_fitted: list[str]|None = None
  header_height: float = 0
  body: list[list[str]] = field(default_factory=list)
  body_fitted: list[list[str]] = field(default_factory=list)
  body_heights: list[float] = field(default_factory=list)
  column_widths: list[float] = field(default_factory=list)  # mm
  column_aligns: list[str] = field(default_factory=list)
  total_width: float = 0
  total_height: float = 0

#--------------------------------------------------------------------------------- TableBuilder

class TableBuilder:
  """Builds and prepares table for rendering."""
  def __init__(self, metrics:TextMetrics, style:TableStyle|None=None):
    self.metrics = metrics
    self.style = style or TableStyle()
    self._header: list[str]|None = None
    self._body: list[list[str]] = []
    self._col_sizes: list[float] = []  # relative sizes
    self._col_aligns: list[str] = []
    self._width: float|None = None  # total width mm

  def header(self, cells:list[str]) -> "TableBuilder":
    """Set table header."""
    self._header = cells
    return self

  def row(self, cells:list[str]) -> "TableBuilder":
    """Add body row."""
    self._body.append(cells)
    return self

  def rows(self, rows:list[list[str]]) -> "TableBuilder":
    """Add multiple body rows."""
    self._body.extend(rows)
    return self

  def columns(self, sizes:list[float], aligns:list[str]|None=None) -> "TableBuilder":
    """Set column relative sizes and alignments."""
    self._col_sizes = sizes
    self._col_aligns = aligns or [Align.LEFT] * len(sizes)
    return self

  def width(self, width:float) -> "TableBuilder":
    """Set total table width in mm."""
    self._width = width
    return self

  def build(
    self,
    available_width: float,  # mm
    font_family: str = "Helvetica",
    font_mode: str = "Regular",
    font_size: float = 11,
  ) -> TableData:
    """Prepare table data for rendering."""
    width = self._width or available_width
    padding = self.style.padding
    fallback_h = font_size * 1.2 # pt: when `box_fit` returns None
    # Column widths (mm)
    if not self._col_sizes:
      ncols = (len(self._header) if self._header
        else len(self._body[0]) if self._body else 1)
      self._col_sizes = [1] * ncols
    total_size = sum(self._col_sizes)
    col_widths = [width * (s / total_size) for s in self._col_sizes]
    while len(self._col_aligns) < len(col_widths):
      self._col_aligns.append(Align.LEFT)
    # mm → pt for text fitting
    widths_pt = [(w - 2 * padding) * 2.8346 for w in col_widths]
    data = TableData(
      column_widths=col_widths,
      column_aligns=self._col_aligns,
      total_width=width,
    )
    # Fit header
    if self._header:
      fit = self.metrics.box_fit_array(
        self._header, widths_pt,
        family=font_family,
        mode=self.style.header_font_mode,
        size=font_size,
      )
      data.header = self._header
      data.header_fitted = fit["text"]
      h = _max_height(fit["height"], fallback_h)
      data.header_height = (h / 2.8346) + 1
    # Fit body rows
    data.body = self._body
    for row in self._body:
      fit = self.metrics.box_fit_array(
        row, widths_pt,
        family=font_family, mode=font_mode, size=font_size,
      )
      data.body_fitted.append(fit["text"])
      h = _max_height(fit["height"], fallback_h)
      data.body_heights.append((h / 2.8346) + 0.5)
    data.total_height = data.header_height + sum(data.body_heights)
    return data

#-------------------------------------------------------------------------------- Legacy helper

def prepare_table(
  body: list[list[str]],
  header: list[str]|None,
  col_sizes: list[float],
  col_aligns: list[str],
  width: float,
  metrics: TextMetrics,
  style: TableStyle|None = None,
  font_family: str = "Helvetica",
  font_mode: str = "Regular",
  font_size: float = 11,
) -> TableData:
  """Prepare table data - convenience function."""
  builder = TableBuilder(metrics, style)
  if header:
    builder.header(header)
  builder.rows(body).columns(col_sizes, col_aligns).width(width)
  return builder.build(width, font_family, font_mode, font_size)

#-------------------------------------------------------------------------------------- Helpers

def _max_height(heights:list, fallback:float) -> float:
  """Max of heights, filtering None from `box_fit` overflow."""
  valid = [h for h in heights if h is not None]
  return max(valid) if valid else fallback