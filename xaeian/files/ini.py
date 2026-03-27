# xaeian/files/ini.py

"""INI configuration file operations."""

import os
from typing import Any
from .config import get_context
from .path import PATH
from .dir import DIR
from ..xstring import ensure_suffix

#-------------------------------------------------------------------------------- INI namespace

class INI:
  """INI configuration file operations."""

  @staticmethod
  def format(value:Any) -> str:
    """Convert Python value to INI-safe string."""
    if value is None: return ""
    if isinstance(value, bool): return "true" if value else "false"
    if isinstance(value, int): return str(value)
    if isinstance(value, float): return repr(value)
    if isinstance(value, str):
      s = value.replace("\\", r"\\").replace('"', r'\"')
      return f'"{s}"'
    raise ValueError(f"Unsupported value type: {type(value).__name__}")

  @staticmethod
  def parse(text:str) -> Any:
    """Parse INI value string to Python type."""
    if not text: return None
    text = text.strip()
    if not text: return None
    if text[0] in "\"'":
      quote = text[0]
      i, chars = 1, []
      while i < len(text):
        ch = text[i]
        if ch == "\\" and i + 1 < len(text):
          nxt = text[i + 1]
          if nxt == quote: chars.append(quote); i += 2; continue
          if nxt == "\\": chars.append("\\"); i += 2; continue
        if ch == quote: break
        chars.append(ch)
        i += 1
      return "".join(chars)
    low = text.lower()
    if low == "true": return True
    if low == "false": return False
    try: return int(text, base=0)
    except ValueError: pass
    try: return float(text)
    except ValueError: pass
    return text

  @staticmethod
  def _strip_inline_comment(text:str) -> str:
    """Strip inline comment from unquoted INI value."""
    for i, ch in enumerate(text):
      if ch in ";#":
        return text[:i].rstrip()
    return text

  @staticmethod
  def load(path:str) -> dict:
    """Load an INI file into a nested dict."""
    cfg = get_context()
    path = ensure_suffix(path, ".ini")
    path = PATH.resolve(path, read=True)
    if not os.path.exists(path): return {}
    with open(path, "r", encoding=cfg.encoding) as file:
      lines = file.readlines()
    ini: dict[str, Any] = {}
    section: str|None = None
    for raw in lines:
      line = raw.strip()
      if not line or line[0] in ";#": continue
      if line.startswith("[") and "]" in line:
        section = line[1:line.index("]")].strip()
        ini[section] = {}
        continue
      if "=" not in line: continue
      key, _, rest = line.partition("=")
      key = key.strip()
      rest = rest.strip()
      if rest and rest[0] not in "\"'":
        rest = INI._strip_inline_comment(rest)
      value = INI.parse(rest)
      if section is not None: ini[section][key] = value
      else: ini[key] = value
    return ini

  @staticmethod
  def save(
    path: str,
    data: dict,
    comment_section: dict|None = None,
    comment_field: dict|None = None,
    comment_section_char: str = "# ",
    comment_field_char: str = " # ",
  ) -> None:
    """Save a dict to an INI file with optional comments."""
    cfg = get_context()
    path = ensure_suffix(path, ".ini")
    path = PATH.resolve(path, read=False)
    DIR.ensure(path, is_file=True)
    comment_section = comment_section or {}
    comment_field = comment_field or {}
    def write_comment_lines(f, text:str):
      if not text: return
      for line in str(text).splitlines():
        line = line.strip()
        if line: f.write(f"{comment_section_char}{line}\n")
    with open(path, "w", encoding=cfg.encoding) as file:
      wrote_anything = False
      top_field_comments = comment_field.get(None, {}) or {}
      for key, value in list(data.items()):
        if isinstance(value, dict): continue
        inline_comment = None
        val = value
        if isinstance(value, tuple) and len(value) == 2:
          val, inline_comment = value
        if key in top_field_comments:
          inline_comment = top_field_comments[key]
        line = f"{key} = {INI.format(val)}"
        if inline_comment:
          line += f"{comment_field_char}{inline_comment}"
        file.write(line + "\n")
        wrote_anything = True
      for section, content in data.items():
        if not isinstance(content, dict): continue
        if wrote_anything: file.write("\n")
        write_comment_lines(file, comment_section.get(section, ""))
        file.write(f"[{section}]\n")
        section_comment_map = comment_field.get(section, {}) or {}
        for key, value in content.items():
          inline_comment = None
          val = value
          if isinstance(value, tuple) and len(value) == 2:
            val, inline_comment = value
          if key in section_comment_map:
            inline_comment = section_comment_map[key]
          line = f"{key} = {INI.format(val)}"
          if inline_comment:
            line += f"{comment_field_char}{inline_comment}"
          file.write(line + "\n")
        wrote_anything = True
