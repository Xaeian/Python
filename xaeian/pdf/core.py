# xaeian/pdf/core.py

"""Core PDF class - main facade for document generation."""
import random
from pathlib import Path
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.lib.colors import Color

from .constants import Defaults, Align, A4
from .utils import to_mm, mm_to_pt, parse_margin, parse_color
from .fonts import FontManager, is_builtin, builtin_name
from .styles import Style, TableStyle
from .layout import Cursor, PageGeometry
from .text import TextMetrics
from .tables import TableBuilder, TableData, prepare_table
from .structure import Metadata, BookmarkManager, LinkManager
from . import graphics as gfx

#-------------------------------------------------------------------------------------- PDF
class PDF:
  """Main PDF generator with fluent API.
  
  Example:
    with PDF("output.pdf") as pdf:
      pdf.font("Barlow", 12).text("Hello World")
      pdf.enter().text("New line")
      pdf.save()
  """
  def __init__(
    self,
    path: str,
    width: float = Defaults.PAGE_WIDTH,
    height: float = Defaults.PAGE_HEIGHT,
    margin: float|tuple = Defaults.MARGIN,
    unit: str = Defaults.UNIT,
    font_dir: str = "./font",
    debug: bool = False,
  ):
    self.path = path
    self.debug = debug
    self.unit = unit

    # Page setup
    lr, top, bot = parse_margin(margin)
    self._page = PageGeometry(
      width=to_mm(width, unit),
      height=to_mm(height, unit),
      margin_lr=to_mm(lr, unit),
      margin_top=to_mm(top, unit),
      margin_bot=to_mm(bot, unit),
    )

    # Canvas
    self._canvas = canvas.Canvas(path)
    self._canvas.setPageSize((self._page.width * mm, self._page.height * mm))

    # Components
    self._fonts = FontManager(font_dir)
    self._metrics = TextMetrics(self._fonts)
    self._cursor = Cursor()
    self._bookmarks = BookmarkManager()
    self._links = LinkManager()
    self._metadata = Metadata()

    # Current state
    self._style = Style().with_defaults()
    self._page_num = 1
    self._page_callbacks: list[callable] = []  # header/footer callbacks

  #---------------------------------------------------------------------------------- Context manager
  def __enter__(self) -> "PDF":
    return self

  def __exit__(self, exc_type, exc_val, exc_tb):
    if exc_type is None:
      self.save()

  #---------------------------------------------------------------------------------- Properties
  @property
  def x(self) -> float:
    return self._cursor.x

  @property
  def y(self) -> float:
    return self._cursor.y

  @property
  def page_width(self) -> float:
    return self._page.width

  @property
  def page_height(self) -> float:
    return self._page.height

  @property
  def content_width(self) -> float:
    return self._page.content_width

  @property
  def content_height(self) -> float:
    return self._page.content_height

  @property
  def page_num(self) -> int:
    return self._page_num

  @property
  def c(self):
    """Direct canvas access for advanced use."""
    return self._canvas

  #---------------------------------------------------------------------------------- Page
  def page(self, width:float|None=None, height:float|None=None) -> "PDF":
    """Set page size."""
    if width:
      self._page.width = to_mm(width, self.unit)
    if height:
      self._page.height = to_mm(height, self.unit)
    self._canvas.setPageSize((self._page.width * mm, self._page.height * mm))
    return self

  def new_page(self) -> "PDF":
    """Add new page and reset cursor."""
    self._apply_page_callbacks()
    self._canvas.showPage()
    self._page_num += 1
    self._cursor.set(0, 0)
    self._apply_font()  # re-apply font after page break
    return self

  def margin(self, lr:float, top:float|None=None, bot:float|None=None) -> "PDF":
    """Set page margins."""
    self._page.margin_lr = to_mm(lr, self.unit)
    self._page.margin_top = to_mm(top if top is not None else lr, self.unit)
    self._page.margin_bot = to_mm(bot if bot is not None else top if top is not None else lr, self.unit)
    return self

  #---------------------------------------------------------------------------------- Fonts
  def add_font(self, family:str, mode:str="Regular") -> "PDF":
    """Register font for use."""
    self._fonts.register(family, mode)
    return self

  def font(self, family:str|None=None, size:float|None=None, mode:str|None=None) -> "PDF":
    """Set current font."""
    if family:
      self._style.font_family = family
      self._style.font_mode = mode or "Regular"
    elif mode:
      self._style.font_mode = mode
    if size:
      self._style.font_size = size
    self._apply_font()
    return self

  def _apply_font(self):
    """Apply current font to canvas."""
    family = self._style.font_family
    mode = self._style.font_mode
    size = self._style.font_size
    if is_builtin(family, mode):
      font_name = builtin_name(family, mode)
    else:
      font_name = self._fonts.register(family, mode)
    self._canvas.setFont(font_name, size)

  def _font_name(self) -> str:
    """Get current font name for reportlab."""
    family = self._style.font_family
    mode = self._style.font_mode
    if is_builtin(family, mode):
      return builtin_name(family, mode)
    return f"{family}-{mode}"

  #---------------------------------------------------------------------------------- Cursor
  def cursor(self, x:float|None=None, y:float|None=None, align:str|None=None) -> "PDF":
    """Set cursor position and/or alignment."""
    if x is not None:
      x = to_mm(x, self.unit)
    if y is not None:
      y = to_mm(y, self.unit)
    self._cursor.set(x, y, align)
    return self

  def move(self, dx:float=0, dy:float=0) -> "PDF":
    """Relative cursor movement."""
    self._cursor.move(to_mm(dx, self.unit), to_mm(dy, self.unit))
    return self

  def enter(self, height:float|None=None) -> "PDF":
    """New line - reset x, advance y."""
    h = to_mm(height, self.unit) if height is not None else None
    self._cursor.enter(h)
    return self

  #---------------------------------------------------------------------------------- Colors
  def color(self, r:float, g:float, b:float, a:float=1) -> "PDF":
    """Set fill color."""
    self._canvas.setFillColor(Color(r, g, b, a))
    self._style.color = (r, g, b, a)
    return self

  def color_hex(self, hex_color:str, a:float=1) -> "PDF":
    """Set fill color from hex string."""
    r, g, b = parse_color(hex_color)
    return self.color(r, g, b, a)

  def color_grey(self, light:float=0, a:float=1) -> "PDF":
    """Set greyscale fill color."""
    return self.color(light, light, light, a)

  def color_black(self) -> "PDF":
    """Reset to black fill."""
    return self.color(0, 0, 0, 1)

  def color_rand(self, offset:float=0.2, a:float=0.5) -> "PDF":
    """Set random fill color (for debug)."""
    r = random.uniform(offset, 1 - offset)
    g = random.uniform(offset, 1 - offset)
    b = random.uniform(offset, 1 - offset)
    return self.color(r, g, b, a)

  def stroke_color(self, r:float, g:float, b:float, a:float=1) -> "PDF":
    """Set stroke color."""
    self._canvas.setStrokeColor(Color(r, g, b, a))
    return self

  #---------------------------------------------------------------------------------- Text

  def text(
    self,
    content: str,
    width: float = 0,
    height: float = 0,
    align: str|None = None,
    padding: float = 0,
  ) -> "PDF":
    """Draw text at cursor position."""
    if content is None:
      content = ""
    width_mm = to_mm(width, self.unit) if width else 0
    height_mm = to_mm(height, self.unit) if height else 0
    padding_mm = to_mm(padding, self.unit)
    align = align or Align.LEFT

    family = self._style.font_family
    mode = self._style.font_mode
    size = self._style.font_size

    width_pt = width_mm * mm if width_mm else 0
    height_pt = height_mm * mm if height_mm else 0
    padding_pt = padding_mm * mm

    # Fit text / measure BEFORE computing position
    if width_pt:
      fit = self._metrics.box_fit(
        content, width_pt - 2 * padding_pt, height_pt,
        family, mode, size, autoscale=0.1 if height_pt else None
      )
      if fit is None:
        fit = self._metrics.box_fit(content, width_pt - 2 * padding_pt, 0, family, mode, size)
      text = fit.text if fit else content
      font_size = fit.font_size if fit else size
      text_height = fit.height if fit else self._metrics.lines_height(1, family, mode, size)
      lines = fit.lines if fit else 1
    else:
      text = content
      font_size = size
      text_height = self._metrics.lines_height(1, family, mode, size)
      width_pt = self._metrics.text_width(content, family, mode, size)
      width_mm = width_pt / mm
      lines = 1

    if not height_pt:
      height_pt = text_height
      height_mm = height_pt / mm

    # NOW compute canvas position with correct width
    x_mm, y_mm = self._page.cursor_to_canvas(self._cursor, width_mm)
    x_pt, y_pt = x_mm * mm, y_mm * mm

    # Debug rectangle
    if self.debug:
      self.color_rand()
      self._canvas.rect(x_pt, y_pt - height_pt, width_pt, height_pt, stroke=0, fill=1)
      self.color_black()

    # Vertical centering margin
    margin_v = (height_pt - self._metrics.lines_height(lines, family, mode, font_size)) / 2
    offset_top = self._metrics.line_height(family, mode, font_size)

    # Create text object
    text_obj = self._canvas.beginText(x_pt, y_pt - offset_top - margin_v)
    text_obj.setFont(self._font_name(), font_size)

    for line in text.splitlines():
      line_width = self._metrics.text_width(line, family, mode, font_size)
      if align == Align.CENTER:
        text_obj.setTextOrigin(x_pt + (width_pt - line_width) / 2, text_obj.getY())
      elif align == Align.RIGHT:
        text_obj.setTextOrigin(x_pt - padding_pt + width_pt - line_width, text_obj.getY())
      else:
        text_obj.setTextOrigin(x_pt + padding_pt, text_obj.getY())
      text_obj.textLine(line)

    self._canvas.drawText(text_obj)

    # Update cursor
    self._cursor.advance_x(width_mm)
    self._cursor.record_height(height_mm)
    return self

  #---------------------------------------------------------------------------------- Lines & Shapes
  def line(self, width:float=0, height:float=0, thickness:float=1, dash:tuple|None=None) -> "PDF":
    """Draw line from cursor."""
    x_mm, y_mm = self._page.cursor_to_canvas(self._cursor)
    w_mm = to_mm(width, self.unit)
    h_mm = to_mm(height, self.unit)
    if self._cursor.align == Align.RIGHT:
      x_mm -= w_mm
    elif self._cursor.align == Align.CENTER:
      x_mm -= w_mm / 2
    gfx.draw_line(self._canvas, x_mm * mm, y_mm * mm,
                  (x_mm + w_mm) * mm, (y_mm - h_mm) * mm, thickness, dash)
    return self

  def rect(self, width:float, height:float, thickness:float=0, dash:tuple|None=None, fill:bool=True) -> "PDF":
    """Draw rectangle at cursor."""
    x_mm, y_mm = self._page.cursor_to_canvas(self._cursor)
    w_mm = to_mm(width, self.unit)
    h_mm = to_mm(height, self.unit)
    if self._cursor.align == Align.RIGHT:
      x_mm -= w_mm
    elif self._cursor.align == Align.CENTER:
      x_mm -= w_mm / 2
    gfx.draw_rect(self._canvas, x_mm * mm, (y_mm - h_mm) * mm,
                  w_mm * mm, h_mm * mm, thickness, dash, fill)
    return self

  def circle(self, radius:float, thickness:float=0, fill:bool=True) -> "PDF":
    """Draw circle at cursor (cursor = center)."""
    x_mm, y_mm = self._page.cursor_to_canvas(self._cursor)
    r_mm = to_mm(radius, self.unit)
    gfx.draw_circle(self._canvas, x_mm * mm, y_mm * mm, r_mm * mm, thickness, fill)
    return self

  def path(self, points:list[tuple], close:bool=False, thickness:float=1, fill:bool=False) -> "PDF":
    """Draw path through points (relative to cursor)."""
    x_mm, y_mm = self._page.cursor_to_canvas(self._cursor)
    pts = [(x_mm * mm + to_mm(p[0], self.unit) * mm,
            y_mm * mm - to_mm(p[1], self.unit) * mm) for p in points]
    gfx.draw_path(self._canvas, pts, close, thickness, fill)
    return self

  #---------------------------------------------------------------------------------- Images
  def image(self, path:str, width:float, height:float) -> "PDF":
    """Draw image at cursor."""
    x_mm, y_mm = self._page.cursor_to_canvas(self._cursor)
    w_mm = to_mm(width, self.unit)
    h_mm = to_mm(height, self.unit)
    if self._cursor.align == Align.RIGHT:
      x_mm -= w_mm
    elif self._cursor.align == Align.CENTER:
      x_mm -= w_mm / 2
    gfx.draw_image(self._canvas, path, x_mm * mm, (y_mm - h_mm) * mm, w_mm * mm, h_mm * mm)
    self._cursor.record_height(h_mm)
    return self

  def svg(self, path:str, width:float, height:float) -> "PDF":
    """Draw SVG at cursor."""
    x_mm, y_mm = self._page.cursor_to_canvas(self._cursor)
    w_mm = to_mm(width, self.unit)
    h_mm = to_mm(height, self.unit)
    if self._cursor.align == Align.RIGHT:
      x_mm -= w_mm
    elif self._cursor.align == Align.CENTER:
      x_mm -= w_mm / 2
    gfx.draw_svg(self._canvas, path, x_mm * mm, (y_mm - h_mm) * mm, w_mm * mm, h_mm * mm)
    self._cursor.record_height(h_mm)
    return self

  #---------------------------------------------------------------------------------- Tables
  def table(
    self,
    body: list[list[str]],
    header: list[str]|None = None,
    sizes: list[float]|None = None,
    aligns: list[str]|None = None,
    width: float|None = None,
    style: TableStyle|None = None,
  ) -> "PDF":
    """Draw table at cursor."""
    style = style or TableStyle()
    width_mm = to_mm(width, self.unit) if width else self.content_width - self._cursor.x
    ncols = len(header) if header else len(body[0]) if body else 1
    sizes = sizes or [1] * ncols
    aligns = aligns or [Align.LEFT] * ncols
    # Prepare table data
    data = prepare_table(
      body, header, sizes, aligns, width_mm, self._metrics, style,
      self._style.font_family, self._style.font_mode, self._style.font_size
    )
    # Draw table
    self._draw_table(data, style)
    return self

  def _draw_table(self, data:TableData, style:TableStyle):
    """Internal table rendering."""
    x_start = self._cursor.x
    y_start = self._cursor.y
    padding = style.padding

    # Draw background boxes
    if data.header:
      self.color_grey(style.header_bg[0], style.header_bg[3] if len(style.header_bg) > 3 else 0.5)
      self.rect(data.total_width, data.header_height)
      self.enter(data.header_height).enter(0.2)

    for i, h in enumerate(data.body_heights):
      bg = style.row_bg_odd if i % 2 else style.row_bg_even
      self.color_grey(bg[0], bg[3] if len(bg) > 3 else 0.5)
      self.rect(data.total_width, h)
      self.enter(h)

    self.color_black()

    # Draw horizontal lines
    self.cursor(x_start, y_start)
    self.line(data.total_width, 0, style.border_width)
    if data.header:
      self.enter(data.header_height)
      self.line(data.total_width, 0, style.border_width_header)
      self.enter(0.2)

    for h in data.body_heights:
      self.line(data.total_width, 0, style.border_width)
      self.enter(h)
    self.line(data.total_width, 0, style.border_width)

    # Draw vertical lines
    self.cursor(x_start, y_start)
    total_h = data.header_height + 0.2 + sum(data.body_heights) if data.header else sum(data.body_heights)
    self.line(0, total_h, style.border_width_outer)
    x_col = x_start
    for w in data.column_widths:
      x_col += w
      self.cursor(x_col, y_start)
      self.line(0, total_h, style.border_width_outer)

    # Draw header text
    self.cursor(x_start, y_start)
    if data.header and data.header_fitted:
      old_mode = self._style.font_mode
      self.font(mode=style.header_font_mode)
      for idx, txt in enumerate(data.header_fitted):
        if txt is None:
          txt = data.header[idx]
        align = data.column_aligns[idx] if idx < len(data.column_aligns) else Align.LEFT
        self.text(txt, data.column_widths[idx], data.header_height, align, padding)
      self.font(mode=old_mode)
      self.enter().enter(0.2)

    # Draw body text
    for i, row in enumerate(data.body_fitted):
      for idx, txt in enumerate(row):
        if txt is None:
          txt = data.body[i][idx]
        align = data.column_aligns[idx] if idx < len(data.column_aligns) else Align.LEFT
        self.text(txt, data.column_widths[idx], data.body_heights[i], align, padding)
      self.enter()

    return self

  #---------------------------------------------------------------------------------- Structure
  def bookmark(self, title:str, level:int=0) -> "PDF":
    """Add bookmark at current position."""
    self._bookmarks.add(title, self._page_num, self._cursor.y, level)
    return self

  def link(self, url:str, width:float, height:float) -> "PDF":
    """Add URL link at cursor."""
    self._links.add_url(url, self._cursor.x, self._cursor.y,
                       to_mm(width, self.unit), to_mm(height, self.unit), self._page_num)
    return self

  def metadata(self, title:str|None=None, author:str|None=None,
               subject:str|None=None, keywords:str|None=None) -> "PDF":
    """Set document metadata."""
    if title: self._metadata.title = title
    if author: self._metadata.author = author
    if subject: self._metadata.subject = subject
    if keywords: self._metadata.keywords = keywords
    return self

  #---------------------------------------------------------------------------------- Headers/Footers
  def on_page(self, callback:callable) -> "PDF":
    """Register callback to run on each page (for headers/footers).
    
    Callback receives (pdf, page_num) arguments.
    """
    self._page_callbacks.append(callback)
    return self

  def _apply_page_callbacks(self):
    """Run page callbacks."""
    cursor_backup = self._cursor.copy()
    for cb in self._page_callbacks:
      cb(self, self._page_num)
    self._cursor = cursor_backup

  #---------------------------------------------------------------------------------- Output
  def save(self) -> "PDF":
    """Render and save PDF."""
    self._apply_page_callbacks()
    self._metadata.apply(self._canvas)
    self._bookmarks.apply(self._canvas, self._page.height)
    self._links.apply(self._canvas, self._page.height, self._page_num)
    self._canvas.save()
    return self

  def compress(self, quality:str="screen") -> "PDF":
    """Compress PDF using ghostscript.
    
    Quality: screen, ebook, printer, prepress
    """
    import subprocess
    import shutil
    temp = self.path + ".tmp"
    try:
      subprocess.run([
        "gs", "-sDEVICE=pdfwrite", "-dCompatibilityLevel=1.4",
        f"-dPDFSETTINGS=/{quality}", "-dNOPAUSE", "-dQUIET", "-dBATCH",
        f"-sOutputFile={temp}", self.path
      ], check=True)
      shutil.move(temp, self.path)
    except (subprocess.CalledProcessError, FileNotFoundError):
      if Path(temp).exists():
        Path(temp).unlink()
    return self