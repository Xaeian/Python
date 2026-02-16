# xaeian/pdf/text.py

"""Text measurement and box fitting."""
from dataclasses import dataclass
from PIL import ImageFont
from reportlab.pdfbase.pdfmetrics import stringWidth
from .fonts import FontManager

#-------------------------------------------------------------------------------------- BoxFitResult

@dataclass
class BoxFitResult:
  """Result of text box fitting."""
  text: str
  font_size: float
  height: float  # total height in pt
  lines: int
  overflow: bool = False

#-------------------------------------------------------------------------------------- TextMetrics

class TextMetrics:
  """Text measurement with font support."""
  def __init__(self, font_manager:FontManager):
    self.fonts = font_manager

  def _font_key(self, family:str, mode:str) -> str:
    return f"{family}-{mode}"

  def text_width(self, text:str, family:str, mode:str, size:float) -> float:
    """Get text width in points."""
    from .fonts import is_builtin, builtin_name
    if is_builtin(family, mode): font_name = builtin_name(family, mode)
    else: font_name = self.fonts.register(family, mode)
    return stringWidth(text, font_name, size)

  def line_height(self, family:str, mode:str, size:float) -> float:
    """Get single line height (ascent) in points."""
    from .fonts import is_builtin
    if is_builtin(family, mode): return size * 0.8
    try:
      path = self.fonts.get_path(family, mode)
      font = ImageFont.truetype(path, int(size))
      ascent, _ = font.getmetrics()
      return float(ascent)
    except:
      return size * 0.8

  def lines_height(self, lines:int, family:str, mode:str, size:float) -> float:
    """Get total height for N lines in points."""
    from .fonts import is_builtin
    if lines <= 0: return self.line_height(family, mode, size)
    if is_builtin(family, mode): return size * 1.2 * lines
    try:
      path = self.fonts.get_path(family, mode)
      font = ImageFont.truetype(path, int(size))
      ascent, descent = font.getmetrics()
      return float(lines * (ascent + descent))
    except:
      return size * 1.2 * lines

  def box_fit(
    self,
    text: str,
    width: float,  # pt
    height: float = 0,  # pt, 0 = no height constraint
    family: str = "Helvetica",
    mode: str = "Regular",
    size: float = 12,
    autoscale: float|None = None,  # step to reduce font size
    link_char: str = "·",
    enter_in: str = "\n",
    enter_out: str = "\n",
  ) -> BoxFitResult|None:
    """Fit text into box, wrapping and optionally scaling font.

    Returns None if text cannot fit (word too wide, no autoscale).
    """
    if text is None: text = ""
    text = text.replace(link_char, "¶")
    input_lines = text.split(enter_in)
    space_width = self.text_width(" ", family, mode, size)
    output = []
    line_count = 0
    for phrase in input_lines:
      phrase = phrase.strip()
      phrase_width = self.text_width(phrase, family, mode, size)
      if phrase_width > width:
        words = phrase.split(" ")
        word_widths = [self.text_width(w, family, mode, size) for w in words]
        if any(w > width for w in word_widths):
          if autoscale and size > autoscale:
            return self.box_fit(text, width, height, family, mode,
              size - autoscale, autoscale, link_char, enter_in, enter_out)
          return None
        current_line = ""
        current_width = 0
        for i, word in enumerate(words):
          word_w = word_widths[i]
          if current_width + word_w > width and current_line:
            output.append(current_line.strip())
            line_count += 1
            current_line = word + " "
            current_width = word_w + space_width
          else:
            current_line += word + " "
            current_width += word_w + space_width
        if current_line.strip():
          output.append(current_line.strip())
          line_count += 1
      else:
        output.append(phrase)
        line_count += 1
    result_text = enter_out.join(output)
    result_height = self.lines_height(line_count, family, mode, size)
    if height > 0 and result_height > height:
      if autoscale and size > autoscale:
        return self.box_fit(text, width, height, family, mode,
          size - autoscale, autoscale, link_char, enter_in, enter_out)
      return BoxFitResult(result_text, size, result_height, line_count, overflow=True)
    return BoxFitResult(result_text, size, result_height, line_count)

  def box_fit_array(
    self,
    texts: list[list[str]]|list[str],
    widths: list[float], # pt per column
    heights: list[float]|float|None = None, # pt per row or single value
    family: str = "Helvetica",
    mode: str = "Regular",
    size: float = 12,
    autoscale: float|None = None,
  ) -> dict:
    """Fit array of texts into columns. Returns dict with text, font_size, height, lines arrays."""
    is_1d = isinstance(texts[0], str)
    if is_1d: texts = [texts]
    if heights is None: heights_list = [0] * len(texts)
    elif isinstance(heights, (int, float)): heights_list = [heights] * len(texts)
    else: heights_list = heights
    results = []
    for i, row in enumerate(texts):
      row_results = []
      for j, text in enumerate(row):
        h = heights_list[i] if i < len(heights_list) else 0
        w = widths[j] if j < len(widths) else widths[-1]
        fit = self.box_fit(text, w, h, family, mode, size, autoscale)
        row_results.append(fit)
      results.append(row_results)
    def extract(prop:str):
      return [[getattr(r, prop) if r else None for r in row] for row in results]
    out = {
      "text": extract("text"),
      "font_size": extract("font_size"),
      "height": extract("height"),
      "lines": extract("lines"),
    }
    if is_1d: out = {k: v[0] for k, v in out.items()}
    return out