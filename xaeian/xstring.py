# xaeian/xstring.py

"""
String manipulation utilities.

Line-anchored replace, placeholder mapping, quote-aware split, comment stripping for C, SQL
and Python, and cryptographically secure token/password generation.

Example:
  >>> split_str('hello "big world" here')
  ['hello', '"big world"', 'here']
"""

import re
import secrets
import string

def replace_start(text:str, find:str, replace:str, border:bool=False) -> str:
  """
  Replace `find` at every line start. `border` demands a word boundary after `find`.

  `replace` is inserted verbatim, not expanded as a regex replacement template.
  """
  if not find: return text
  pattern = rf"(?m)^{re.escape(find)}{r'\b' if border else ''}"
  return re.sub(pattern, lambda _m: replace, text)

def replace_end(text:str, find:str, replace:str, border:bool=False) -> str:
  """
  Replace `find` at every line end. `border` demands a word boundary before `find`.

  `replace` is inserted verbatim, not expanded as a regex replacement template.
  """
  if not find: return text
  pattern = rf"(?m){r'\b' if border else ''}{re.escape(find)}$"
  return re.sub(pattern, lambda _m: replace, text)

def replace_map(
  subject:str|list|dict,
  mapping:dict,
  prefix:str = "",
  suffix:str = "",
) -> str|list|dict:
  """
  Replace every `{prefix}{key}{suffix}` with its mapped value, recursing into lists and dicts.

  Dict keys are left untouched, only values are rewritten. Anything else passes through as is.

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
  """Prepend `prefix` unless `text` already starts with it."""
  if text.startswith(prefix): return text
  return prefix + text

def ensure_suffix(text:str, suffix:str) -> str:
  """Append `suffix` unless `text` already ends with it."""
  if text.endswith(suffix): return text
  return text + suffix

SQL_QUOTES = "'\""

#---------------------------------------------------------------------------------------- Tokenizer

def scan(
  text:str,
  quotes:str = "",
  esc:str|None = None,
  line:str|None = None,
  block:tuple|None = None,
  sep:str = "",
) -> list[tuple[str, str]]:
  """
  Split text into `(kind, chunk)` runs: `text`, `quote`, `unclosed`, `comment` or `sep`.

  One pass settles the precedence the three concerns need, so no caller has to repeat it: a quote
  opens only outside a comment, a comment marker is inert inside a quote, and `sep` matches only
  outside both. A quote reaching the end of the input without its closing delimiter comes back as
  `unclosed`, which lets a caller reject it or keep it. Concatenating every chunk rebuilds `text`.

  Example:
    >>> scan("a,'b,c'", quotes="'", sep=",")
    [('text', 'a'), ('sep', ','), ('quote', "'b,c'")]
  """
  out = []
  buf = []
  i, n = 0, len(text)
  def flush():
    if buf:
      out.append(("text", "".join(buf)))
      buf.clear()
  while i < n:
    ch = text[i]
    if quotes and ch in quotes:
      flush()
      start = i
      i += 1
      closed = False
      while i < n:
        c = text[i]
        i += 1
        if esc and c == esc and i < n:
          i += 1
          continue
        if c != ch: continue
        if not esc and i < n and text[i] == ch: # doubled quote escapes, the run stays open
          i += 1
          continue
        closed = True
        break
      out.append(("quote" if closed else "unclosed", text[start:i]))
      continue
    if line and text.startswith(line, i):
      flush()
      end = text.find("\n", i)
      end = n if end < 0 else end
      out.append(("comment", text[i:end]))
      i = end
      continue
    if block and text.startswith(block[0], i):
      flush()
      end = text.find(block[1], i + len(block[0]))
      end = n if end < 0 else end + len(block[1])
      out.append(("comment", text[i:end]))
      i = end
      continue
    if sep and text.startswith(sep, i):
      flush()
      out.append(("sep", sep))
      i += len(sep)
      continue
    buf.append(ch)
    i += 1
  flush()
  return out

#------------------------------------------------------------------------------------------- Splits

def split_str(text:str, sep:str=" ", quote:str='"', esc:str|None=None) -> list[str]:
  """
  Split by `sep`, keeping quoted segments whole and their quotes in the output.

  `sep` may be multi-char. `quote` may list several delimiters (`SQL_QUOTES` for SQL), each
  closed only by itself. `esc` escapes inside quotes; when `None`, a doubled quote escapes.
  An unclosed quote raises `ValueError`.

  Example:
    >>> split_str('hello "big world" here')
    ['hello', '"big world"', 'here']
  """
  if not sep: raise ValueError("Separator cannot be empty")
  parts = scan(text, quotes=quote, esc=esc, sep=sep)
  if any(kind == "unclosed" for kind, _ in parts):
    raise ValueError(f"Unclosed quote in: {text[:50]}...")
  res, buf = [], []
  for kind, chunk in parts:
    if kind == "sep":
      res.append("".join(buf))
      buf = []
    else:
      buf.append(chunk)
  res.append("".join(buf))
  return res

def _normalize_sql(sql:str) -> str:
  """Collapse whitespace and spacing around `(),=`, leaving quoted spans exactly as they are."""
  out = []
  for kind, chunk in scan(sql, quotes=SQL_QUOTES):
    if kind != "text":
      out.append(chunk)
    else:
      chunk = re.sub(r"\s+", " ", chunk)
      out.append(re.sub(r"\s*([(),=])\s*", r"\1", chunk))
  return "".join(out).strip()

def split_sql(sqls:str) -> list[str]:
  """
  Split into `;`-terminated statements, dropping comments and normalizing spacing.

  `'literals'` and `"identifiers"` are protected, so a `;` or `,` inside either one neither
  splits the statement nor loses its spacing. `--` and `/* */` comments are removed before the
  split, since collapsing newlines would otherwise let a line comment swallow what follows it.

  Example:
    >>> split_sql("SELECT 1; -- note\\nSELECT 2;")
    ['SELECT 1;', 'SELECT 2;']
  """
  out = []
  for sql in split_str(strip_comments_sql(sqls), sep=";", quote=SQL_QUOTES):
    sql = _normalize_sql(sql)
    if sql: out.append(sql + ";")
  return out

#----------------------------------------------------------------------------------------- Comments

def strip_comments(
  text:str,
  line:str|None = "//",
  block:tuple|None = ("/*", "*/"),
  quotes:str = '"',
  esc:str|None = None,
) -> str:
  """
  Remove line and block comments, leaving quoted strings untouched.

  `line` is the marker text, `block` an `(open, close)` pair, `None` disables that kind.
  `quotes` lists every character that opens a string. `esc` escapes inside quotes; when
  `None`, a doubled quote escapes.
  """
  parts = scan(text, quotes=quotes, esc=esc, line=line, block=block)
  return "".join(chunk for kind, chunk in parts if kind != "comment")

def strip_comments_c(text:str) -> str:
  """Strip C/C++/Java/JavaScript comments (`//` and `/* */`)."""
  return strip_comments(text, line="//", block=("/*", "*/"), quotes='"', esc="\\")

def strip_comments_sql(text:str) -> str:
  """Strip SQL comments (`--` and `/* */`), leaving both literals and identifiers intact."""
  return strip_comments(text, line="--", block=("/*", "*/"), quotes=SQL_QUOTES)

def strip_comments_py(text:str) -> str:
  """Strip Python comments (`#`)."""
  return strip_comments(text, line="#", block=None, quotes="\"'", esc="\\")

#------------------------------------------------------------------------------------------ Secrets

TOKEN_ALPHABET = string.ascii_letters + string.digits

def generate_token(length:int=32, alphabet:str=TOKEN_ALPHABET) -> str:
  """
  Generate a cryptographically secure random token.

  Unlike `generate_password`, no character class is forced, so the alphanumeric default
  survives a URL, an HTTP header or a filename unescaped.
  """
  if length < 1: raise ValueError("Token length must be >= 1")
  if not alphabet: raise ValueError("Token alphabet must not be empty")
  return "".join(secrets.choice(alphabet) for _ in range(length))

def generate_password(length:int=16, extend_spec:bool=False) -> str:
  """
  Generate a cryptographically secure random password, `length` at least `4`.

  At least one lowercase, uppercase, digit and special character is guaranteed.
  `extend_spec` widens the special set beyond `!@#$%^&*?`.
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

#-------------------------------------------------------------------------------------------- Tests

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
