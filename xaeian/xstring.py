# xaeian/xstring.py

"""
String manipulation utilities.

Functions for replacing, splitting, and stripping text with
quote-awareness and comment removal for various languages.

Example:
  >>> from xaeian import split_str, strip_comments_c, generate_password
  >>> split_str('hello "big world" here')
  ['hello', '"big world"', 'here']
  >>> strip_comments_c('int x = 1; // comment')
  'int x = 1; '
  >>> generate_password(12)
  'aB3$xY9!mN2@'
"""

import re
import secrets
import string

def replace_start(text:str, find:str, replace:str, border:bool=False) -> str:
  """
  Replace substring at start of each line.

  Args:
    text: Input text (possibly multiline).
    find: Substring to match at line start.
    replace: Replacement text.
    border: When `True`, require word boundary after `find`.

  Returns:
    Text with matching line prefixes replaced.

  Example:
    >>> replace_start("old_value = 1\\nold_name = 2", "old_", "new_")
    'new_value = 1\\nnew_name = 2'
  """
  if not find: return text
  pattern = rf"(?m)^{re.escape(find)}{r'\b' if border else ''}"
  return re.sub(pattern, replace, text)

def replace_end(text:str, find:str, replace:str, border:bool=False) -> str:
  """
  Replace substring at end of each line.

  Args:
    text: Input text (possibly multiline).
    find: Substring to match at line end.
    replace: Replacement text.
    border: When `True`, require word boundary before `find`.

  Returns:
    Text with matching line suffixes replaced.

  Example:
    >>> replace_end("file.txt\\ndata.txt", ".txt", ".md")
    'file.md\\ndata.md'
  """
  if not find: return text
  pattern = rf"(?m){r'\b' if border else ''}{re.escape(find)}$"
  return re.sub(pattern, replace, text)

def replace_map(
  subject: str|list|dict,
  mapping: dict,
  prefix: str = "",
  suffix: str = "",
) -> str|list|dict:
  """
  Replace mapping keys with values, recursively.

  Args:
    subject: String, list, or dict to process.
    mapping: Dict of `{key: value}` replacements.
    prefix: Prefix before each key in text.
    suffix: Suffix after each key in text.

  Returns:
    Subject with all matching patterns replaced.

  Example:
    >>> replace_map("Hello %NAME%!", {"NAME": "World"}, "%", "%")
    'Hello World!'
  """
  if isinstance(subject, str):
    for search, value in mapping.items():
      subject = subject.replace(f"{prefix}{search}{suffix}", str(value))
    return subject
  if isinstance(subject, list):
    return [replace_map(item, mapping, prefix, suffix) for item in subject]
  if isinstance(subject, dict):
    return {k: replace_map(v, mapping, prefix, suffix) for k, v in subject.items()}
  return subject

def ensure_prefix(text:str, prefix:str) -> str:
  """
  Ensure text starts with prefix (idempotent).

  Args:
    text: Input string.
    prefix: Required prefix.

  Returns:
    Text guaranteed to start with `prefix`.

  Example:
    >>> ensure_prefix("path/file", "/")
    '/path/file'
  """
  if not prefix: return text
  if text.startswith(prefix): return text
  return prefix + text

def ensure_suffix(text:str, suffix:str) -> str:
  """
  Ensure text ends with suffix (idempotent).

  Args:
    text: Input string.
    suffix: Required suffix.

  Returns:
    Text guaranteed to end with `suffix`.

  Example:
    >>> ensure_suffix("config", ".json")
    'config.json'
  """
  if not suffix: return text
  if text.endswith(suffix): return text
  return text + suffix

def split_str(string:str, sep:str=" ", quote:str='"', esc:str=None) -> list[str]:
  """
  Split string by separator, preserving quoted segments.

  Args:
    string: Input text to split.
    sep: Separator string (can be multi-char).
    quote: Quote character protecting segments.
    esc: Escape character. When `None`, doubled quotes escape (`""`).

  Returns:
    List of tokens with quotes preserved.

  Raises:
    ValueError: When `sep` is empty or quote is unclosed.

  Example:
    >>> split_str('hello "big world" here')
    ['hello', '"big world"', 'here']
    >>> split_str('a,"b,c",d', sep=",")
    ['a', '"b,c"', 'd']
  """
  if not sep: raise ValueError("Separator cannot be empty")
  res = []
  buf = []
  in_quote = False
  i = 0
  while i < len(string):
    ch = string[i]
    if in_quote:
      buf.append(ch)
      if esc and ch == esc and i + 1 < len(string):
        buf.append(string[i + 1])
        i += 2
        continue
      if not esc and ch == quote and i + 1 < len(string) and string[i + 1] == quote:
        buf.append(string[i + 1])
        i += 2
        continue
      if ch == quote: in_quote = False
      i += 1
    else:
      if ch == quote:
        in_quote = True
        buf.append(ch)
        i += 1
      elif string[i:i + len(sep)] == sep:
        res.append("".join(buf))
        buf = []
        i += len(sep)
      else:
        buf.append(ch)
        i += 1
  if in_quote: raise ValueError(f"Unclosed quote in: {string[:50]}...")
  res.append("".join(buf))
  return res

def split_sql(sqls:str) -> list[str]:
  """
  Split SQL script into normalized statements.

  Args:
    sqls: SQL text with one or more statements.

  Returns:
    List of SQL statements, each ending with `;`.

  Example:
    >>> split_sql("SELECT 1; SELECT 2;")
    ['SELECT 1;', 'SELECT 2;']
  """
  parts = split_str(sqls, sep=";", quote="'")
  out = []
  for sql in parts:
    sql = re.sub(r"\s+", " ", sql).strip()
    sql = re.sub(r"\s*([(),=])\s*", r"\1", sql)
    if sql: out.append(sql + ";")
  return out

def strip_comments(string:str, line:str="//", block:tuple=("/*", "*/"), quotes:str='"') -> str:
  """
  Remove comments while preserving quoted strings.

  Args:
    string: Input source text.
    line: Line comment marker (e.g., `"//"`, `"#"`). `None` to disable.
    block: Block comment markers as `(open, close)` tuple. `None` to disable.
    quotes: Quote character(s) protecting content.

  Returns:
    Text with comments removed.

  Example:
    >>> strip_comments('int x = 1; // comment\\nint y;')
    'int x = 1; \\nint y;'
  """
  result = []
  i = 0
  quote_char = None
  while i < len(string):
    ch = string[i]
    if quote_char:
      result.append(ch)
      if ch == quote_char and i + 1 < len(string) and string[i + 1] == quote_char:
        result.append(string[i + 1])
        i += 2
        continue
      if ch == quote_char: quote_char = None
      i += 1
    else:
      if ch in quotes:
        quote_char = ch
        result.append(ch)
        i += 1
      elif line and string[i:i + len(line)] == line:
        while i < len(string) and string[i] != "\n": i += 1
      elif block and string[i:i + len(block[0])] == block[0]:
        i += len(block[0])
        while i < len(string) and string[i:i + len(block[1])] != block[1]: i += 1
        i += len(block[1])
      else:
        result.append(ch)
        i += 1
  return "".join(result)

def strip_comments_c(string:str) -> str:
  """Strip C/C++/Java/JavaScript comments (`//` and `/* */`)."""
  return strip_comments(string, line="//", block=("/*", "*/"), quotes='"')

def strip_comments_sql(string:str) -> str:
  """Strip SQL comments (`--` and `/* */`)."""
  return strip_comments(string, line="--", block=("/*", "*/"), quotes="'")

def strip_comments_py(string:str) -> str:
  """Strip Python comments (`#`)."""
  return strip_comments(string, line="#", block=None, quotes="\"'")

def generate_password(length:int=16, extend_spec:bool=False) -> str:
  """
  Generate cryptographically secure random password.

  Guarantees at least one character from each class:
  lowercase, uppercase, digit, and special character.

  Args:
    length: Password length (minimum `4`).
    extend_spec: When `True`, use extended special character set.

  Returns:
    Random password string.

  Raises:
    ValueError: When `length < 4`.

  Example:
    >>> len(generate_password(12))
    12
  """
  if length < 4: raise ValueError("Password length must be >= 4")
  lower = string.ascii_lowercase
  upper = string.ascii_uppercase
  digits = string.digits
  spec = "~`!@#$%^&*?()_-+={[}]|\\:;\"'<,>./" if extend_spec else "!@#$%^&*?"
  all_chars = lower + upper + digits + spec
  pwd = [
    secrets.choice(lower),
    secrets.choice(upper),
    secrets.choice(digits),
    secrets.choice(spec),
  ]
  for _ in range(length - 4):
    pwd.append(secrets.choice(all_chars))
  for i in range(len(pwd) - 1, 0, -1):
    j = secrets.randbelow(i + 1)
    pwd[i], pwd[j] = pwd[j], pwd[i]
  return "".join(pwd)

#---------------------------------------------------------------------------------------- Tests

if __name__ == "__main__":
  print("split_str:", split_str('a,"b,c",d', sep=","))
  print("split_str:", split_str("key='it''s ok'", sep="=", quote="'"))
  print()
  print("replace_map:", replace_map("Hi {{NAME}}!", {"NAME": "World"}, "{{", "}}"))
  print("ensure_prefix:", ensure_prefix("path/file", "/"))
  print("ensure_suffix:", ensure_suffix("config", ".json"))
  print()
  code = 'int x = 1; // comment\nchar *s = "// not";'
  print("strip_comments_c:")
  print(" ", repr(code))
  print(" ", repr(strip_comments_c(code)))
  print()
  print("split_sql:", split_sql("SELECT 1; SELECT 'a;b';"))
  print()
  print("generate_password:", generate_password(12))
