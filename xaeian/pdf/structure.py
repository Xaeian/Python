# xaeian/pdf/structure.py

"""Document structure - bookmarks, TOC, metadata, hyperlinks."""
from dataclasses import dataclass, field

#-------------------------------------------------------------------------------------- Bookmark
@dataclass
class Bookmark:
  """PDF bookmark/outline entry."""
  title: str
  page: int
  y: float  # position on page (mm from top)
  level: int = 0
  children: list["Bookmark"] = field(default_factory=list)

#-------------------------------------------------------------------------------------- TOCEntry
@dataclass
class TOCEntry:
  """Table of contents entry."""
  title: str
  page: int
  level: int = 0

#-------------------------------------------------------------------------------------- Metadata
@dataclass
class Metadata:
  """PDF document metadata."""
  title: str|None = None
  author: str|None = None
  subject: str|None = None
  keywords: str|None = None
  creator: str = "pdflib"
  producer: str|None = None

  def apply(self, canvas):
    """Apply metadata to canvas."""
    if self.title: canvas.setTitle(self.title)
    if self.author: canvas.setAuthor(self.author)
    if self.subject: canvas.setSubject(self.subject)
    if self.keywords: canvas.setKeywords(self.keywords)
    if self.creator: canvas.setCreator(self.creator)
    if self.producer: canvas.setProducer(self.producer)

#-------------------------------------------------------------------------------------- BookmarkManager
class BookmarkManager:
  """Manages PDF bookmarks/outlines."""
  def __init__(self):
    self._bookmarks: list[Bookmark] = []
    self._keys: dict[str, str] = {}  # internal key tracking

  def add(self, title:str, page:int, y:float, level:int=0) -> str:
    """Add bookmark, return key."""
    key = f"bm_{len(self._bookmarks)}"
    self._bookmarks.append(Bookmark(title, page, y, level))
    self._keys[key] = title
    return key

  def apply(self, canvas, page_height:float):
    """Apply all bookmarks to canvas."""
    for bm in self._bookmarks:
      # Convert y from top-down to bottom-up
      y_canvas = (page_height - bm.y) * 2.8346  # mm to pt
      key = f"bm_{self._bookmarks.index(bm)}"
      canvas.bookmarkPage(key)
      canvas.addOutlineEntry(bm.title, key, level=bm.level)

  def get_toc(self) -> list[TOCEntry]:
    """Generate TOC entries from bookmarks."""
    return [TOCEntry(bm.title, bm.page, bm.level) for bm in self._bookmarks]

#-------------------------------------------------------------------------------------- LinkManager
class LinkManager:
  """Manages hyperlinks."""
  def __init__(self):
    self._links: list[dict] = []

  def add_url(self, url:str, x:float, y:float, width:float, height:float, page:int=1):
    """Add external URL link."""
    self._links.append({
      "type": "url",
      "url": url,
      "x": x, "y": y,
      "width": width, "height": height,
      "page": page,
    })

  def add_internal(self, dest:str, x:float, y:float, width:float, height:float, page:int=1):
    """Add internal document link."""
    self._links.append({
      "type": "internal",
      "dest": dest,
      "x": x, "y": y,
      "width": width, "height": height,
      "page": page,
    })

  def apply(self, canvas, page_height:float, current_page:int=1):
    """Apply links for current page."""
    from reportlab.lib.units import mm
    for link in self._links:
      if link["page"] != current_page:
        continue
      x = link["x"] * mm
      y = (page_height - link["y"] - link["height"]) * mm
      w = link["width"] * mm
      h = link["height"] * mm
      if link["type"] == "url":
        canvas.linkURL(link["url"], (x, y, x + w, y + h), relative=0)
      else:
        canvas.linkAbsolute(link["dest"], (x, y, x + w, y + h))
