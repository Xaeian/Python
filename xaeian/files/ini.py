# xaeian/files/ini.py

"""INI configuration file operations."""

import io, os
from typing import Any
from .config import get_context
from .path import PATH
from .dir import DIR
from .file import FILE

#------------------------------------------------------------------------------------ INI namespace

class INI:
  """INI read/write, auto `.ini` extension, `.conf`/`.cfg` accepted."""
  EXTS = (".ini", ".conf", ".cfg")

  @staticmethod
  def _ensure_ext(path:str) -> str:
    """Keep an `EXTS` extension, else append `.ini`."""
    ext = os.path.splitext(path)[1].lower()
    if ext in INI.EXTS: return path
    return path + ".ini"

  @staticmethod
  def format(value:Any) -> str:
    """
    Convert a Python value to an INI-safe string.

    `None` → empty, bool → `true`/`false`, numbers bare, str → quoted with escapes.
    Other types raise, and so does a newline in a string: INI has no multiline syntax.
    """
    if value is None: return ""
    if isinstance(value, bool): return "true" if value else "false"
    if isinstance(value, int): return str(value)
    if isinstance(value, float): return repr(value)
    if isinstance(value, str):
      if "\n" in value or "\r" in value: raise ValueError("Newline in INI value")
      s = value.replace("\\", r"\\").replace('"', r'\"')
      return f'"{s}"'
    raise ValueError(f"Unsupported value type: {type(value).__name__}")

  @staticmethod
  def parse(text:str) -> Any:
    """
    Parse an INI value: empty → `None`, quoted text unescaped, else bool, int, float or str.

    Ints go through `base=0`, so `0x`, `0o` and `0b` prefixes are accepted.
    """
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
    """Strip a `;` or `#` inline comment from an unquoted INI value."""
    for i, ch in enumerate(text):
      if ch in ";#": return text[:i].rstrip()
    return text

  @staticmethod
  def load(path:str) -> dict:
    """
    Load an INI file into a nested dict, `{}` when missing.

    Keys before the first `[section]` land at the top level, each section becomes a sub-dict.
    Values pass through `parse`: an unquoted value loses its `;`/`#` inline comment, a quoted
    value ends at its closing quote with the rest of the line dropped.
    """
    cfg = get_context()
    path = INI._ensure_ext(path)
    path = PATH.resolve(path, read=True)
    if not os.path.isfile(path): return {}
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
    path:str,
    data:dict,
    comment_section:dict|None = None,
    comment_field:dict|None = None,
    comment_section_char:str = "# ",
    comment_field_char:str = " # ",
  ) -> None:
    """
    Save a dict as INI: scalar keys first, then dict values as `[section]` blocks.

    A value given as a `(value, comment)` pair gets a trailing comment. `comment_section` maps
    section → text written above the header, `comment_field` maps section → `{key: comment}`
    and wins over pair comments, its `None` key holding the top-level fields.
    """
    path = DIR._resolve_write(INI._ensure_ext(path), "")
    comment_section = comment_section or {}
    comment_field = comment_field or {}
    def write_comment_lines(f, text:str):
      if not text: return
      for line in str(text).splitlines():
        line = line.strip()
        if line: f.write(f"{comment_section_char}{line}\n")
    # built whole, then handed to the atomic FILE.save: a failure here cannot touch the target
    file = io.StringIO()
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
    FILE.save(path, file.getvalue())
