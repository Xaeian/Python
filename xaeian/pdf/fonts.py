# xaeian/pdf/fonts.py

"""Font management - registration, path resolution, metrics."""
from pathlib import Path
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.pdfmetrics import stringWidth

#-------------------------------------------------------------------------------------- FontManager
class FontManager:
  """Font registry with lazy loading and path resolution."""
  def __init__(self, font_dir:str="./font"):
    self.font_dir = Path(font_dir)
    self._registered: set[str] = set()
    self._paths: dict[str, str] = {}

  def _font_key(self, family:str, mode:str) -> str:
    """Generate unique font key."""
    return f"{family}-{mode}"

  def _resolve_path(self, family:str, mode:str) -> Path:
    """Find font file path."""
    # Try: font_dir/family/Family-Mode.ttf
    path = self.font_dir / family.lower() / f"{family}-{mode}.ttf"
    if path.exists():
      return path
    # Try: font_dir/Family-Mode.ttf
    path = self.font_dir / f"{family}-{mode}.ttf"
    if path.exists():
      return path
    # Try: font_dir/family.ttf (for single-file fonts)
    if mode == "Regular":
      path = self.font_dir / f"{family}.ttf"
      if path.exists():
        return path
    raise FileNotFoundError(f"Font not found: {family}-{mode} in {self.font_dir}")

  def register(self, family:str, mode:str="Regular") -> str:
    """Register font and return reportlab font name. Lazy - only registers once."""
    key = self._font_key(family, mode)
    if key in self._registered:
      return key
    path = self._resolve_path(family, mode)
    pdfmetrics.registerFont(TTFont(key, str(path)))
    self._registered.add(key)
    self._paths[key] = str(path)
    return key

  def get_path(self, family:str, mode:str="Regular") -> str:
    """Get font file path."""
    key = self._font_key(family, mode)
    if key in self._paths:
      return self._paths[key]
    return str(self._resolve_path(family, mode))

  def is_registered(self, family:str, mode:str="Regular") -> bool:
    """Check if font is registered."""
    return self._font_key(family, mode) in self._registered

  def text_width(self, text:str, family:str, mode:str, size:float) -> float:
    """Get text width in points using reportlab metrics."""
    key = self.register(family, mode)
    return stringWidth(text, key, size)

#-------------------------------------------------------------------------------------- Builtin
BUILTIN_FONTS = {
  "Helvetica": ["Regular", "Bold", "Oblique", "BoldOblique"],
  "Times": ["Roman", "Bold", "Italic", "BoldItalic"],
  "Courier": ["Regular", "Bold", "Oblique", "BoldOblique"],
}

def is_builtin(family:str, mode:str="Regular") -> bool:
  """Check if font is a reportlab built-in."""
  if family in BUILTIN_FONTS:
    return mode in BUILTIN_FONTS[family]
  # Handle aliases
  if family == "Times-Roman":
    return True
  return False

def builtin_name(family:str, mode:str="Regular") -> str:
  """Get reportlab built-in font name."""
  if family == "Helvetica":
    if mode == "Regular": return "Helvetica"
    if mode == "Bold": return "Helvetica-Bold"
    if mode == "Oblique": return "Helvetica-Oblique"
    if mode == "BoldOblique": return "Helvetica-BoldOblique"
  if family == "Times":
    if mode == "Roman" or mode == "Regular": return "Times-Roman"
    if mode == "Bold": return "Times-Bold"
    if mode == "Italic": return "Times-Italic"
    if mode == "BoldItalic": return "Times-BoldItalic"
  if family == "Courier":
    if mode == "Regular": return "Courier"
    if mode == "Bold": return "Courier-Bold"
    if mode == "Oblique": return "Courier-Oblique"
    if mode == "BoldOblique": return "Courier-BoldOblique"
  return family
