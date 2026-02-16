# xaeian/pdf/__init__.py

__extras__ = {"pdf": ["reportlab", "Pillow"]}

"""
pdflib - PDF generation library with fluent API.

Example:
  from pdflib import PDF, Align, TableStyle
  
  with PDF("output.pdf") as pdf:
    pdf.font("Barlow", 12, "Bold")
    pdf.text("Hello World", align=Align.CENTER)
    pdf.enter()
    pdf.table([["A", "B"], ["C", "D"]], header=["Col1", "Col2"])
"""

# Core
from .core import PDF

# Constants
from .constants import (
  Unit,
  PageSize,
  Align,
  Colors,
  Defaults,
  # Page sizes
  A4, A3, A5, LETTER, LEGAL,
)

# Styles
from .styles import (
  Style,
  TableStyle,
  Styles,
)

# Layout
from .layout import (
  Cursor,
  PageGeometry,
)

# Text
from .text import (
  TextMetrics,
  BoxFitResult,
)

# Tables
from .tables import (
  TableBuilder,
  TableData,
  Cell,
)

# Fonts
from .fonts import (
  FontManager,
)

# Structure
from .structure import (
  Metadata,
  Bookmark,
  TOCEntry,
  BookmarkManager,
  LinkManager,
)

# Utils
from .utils import (
  to_mm,
  to_pt,
  mm_to_pt,
  parse_color,
  color_alpha,
  parse_margin,
)

__version__ = "2.0.0"
__all__ = [
  # Core
  "PDF",
  # Constants
  "Unit", "PageSize", "Align", "Colors", "Defaults",
  "A4", "A3", "A5", "LETTER", "LEGAL",
  # Styles
  "Style", "TableStyle", "Styles",
  # Layout
  "Cursor", "PageGeometry",
  # Text
  "TextMetrics", "BoxFitResult",
  # Tables
  "TableBuilder", "TableData", "Cell",
  # Fonts
  "FontManager",
  # Structure
  "Metadata", "Bookmark", "TOCEntry", "BookmarkManager", "LinkManager",
  # Utils
  "to_mm", "to_pt", "mm_to_pt", "parse_color", "color_alpha", "parse_margin",
]
