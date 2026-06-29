# tests/test_xstring.py

"""String utilities: quote-aware splitting, line replace, comment stripping, passwords."""

import pytest
from xaeian import (
  replace_start, replace_end, replace_map,
  ensure_prefix, ensure_suffix,
  split_str, split_sql,
  strip_comments_c, strip_comments_sql, strip_comments_py,
  generate_password,
)

@pytest.mark.parametrize("text, sep, expected", [
  ('hello "big world" here', " ", ['hello', '"big world"', 'here']),
  ('a,"b,c",d', ",", ['a', '"b,c"', 'd']),
])
def split_str_keeps_quoted_segments(text, sep, expected):
  assert split_str(text, sep=sep) == expected

def split_str_handles_doubled_quote_escape():
  assert split_str("key='it''s ok'", sep="=", quote="'") == ["key", "'it''s ok'"]

def split_str_rejects_empty_separator():
  with pytest.raises(ValueError):
    split_str("a b", sep="")

def split_str_rejects_unclosed_quote():
  with pytest.raises(ValueError):
    split_str('a "b')

def split_str_honors_escape_char():
  assert split_str('"a\\"b" c', esc="\\") == ['"a\\"b"', "c"] # backslash escapes the quote

def split_str_absorbs_quotes_mid_token():
  assert split_str('a"b"c') == ['a"b"c'] # quote not at token start → one token

def split_sql_normalizes_whitespace():
  assert split_sql("SELECT 1;  SELECT   2 ;") == ["SELECT 1;", "SELECT 2;"]

def split_sql_preserves_string_literals():
  # regression: whitespace/punctuation collapse must not reach into quoted content
  assert split_sql("INSERT INTO t VALUES ('a , b', 'x=y')") == ["INSERT INTO t VALUES('a , b','x=y');"]
  assert split_sql("SELECT 'a;b'") == ["SELECT 'a;b';"] # ; inside a literal is not a split point

def split_sql_keeps_punctuation_inside_literals():
  # ( ) , and inner spaces survive; the = outside the literal is still collapsed
  sql = "UPDATE t SET note = '(a, b)' WHERE id = 1"
  assert split_sql(sql) == ["UPDATE t SET note='(a, b)' WHERE id=1;"]

def replace_start_end_are_line_anchored():
  assert replace_start("old_value = 1\nold_name = 2", "old_", "new_") == "new_value = 1\nnew_name = 2"
  assert replace_end("file.txt\ndata.txt", ".txt", ".md") == "file.md\ndata.md"

def replace_treats_replacement_literally():
  # regression: replacement is literal text, not a regex template
  assert replace_start("old_x", "old_", r"A\1B") == r"A\1Bx"
  assert replace_start("old_x", "old_", r"\g<name>") == r"\g<name>x"

def replace_start_border_requires_word_boundary():
  # border=True: "old" matches only before a non-word char (here the line end)
  assert replace_start("old\nold_x", "old", "new", border=True) == "new\nold_x"

def replace_map_recurses_into_lists_and_dicts():
  assert replace_map("Hi %N%!", {"N": "World"}, "%", "%") == "Hi World!"
  assert replace_map(["%A%", {"k": "%A%"}], {"A": "x"}, "%", "%") == ["x", {"k": "x"}]

def replace_map_stringifies_non_string_values():
  assert replace_map("n=%X%", {"X": 5}, "%", "%") == "n=5"

def ensure_prefix_suffix_are_idempotent():
  assert ensure_prefix("path", "/") == "/path"
  assert ensure_prefix("/path", "/") == "/path"
  assert ensure_suffix("config", ".json") == "config.json"
  assert ensure_suffix("config.json", ".json") == "config.json"

@pytest.mark.parametrize("strip, code, clean", [
  (strip_comments_c, "a /* b */ c", "a  c"),
  (strip_comments_sql, "x = 1 -- c", "x = 1 "),
  (strip_comments_py, "x = 1 # c", "x = 1 "),
])
def strip_comments_removes_comments(strip, code, clean):
  assert strip(code) == clean

def strip_comments_keeps_markers_inside_strings():
  assert strip_comments_c('s = "// not"; // real') == 's = "// not"; '

def strip_comments_respects_marker_precedence():
  assert strip_comments_c("a // /* b */ c") == "a "  # line comment swallows the block
  assert strip_comments_c("a /* // */ b") == "a  b"  # block swallows the slashes

def generate_password_covers_all_classes():
  pw = generate_password(12)
  assert len(pw) == 12
  assert any(c.islower() for c in pw)
  assert any(c.isupper() for c in pw)
  assert any(c.isdigit() for c in pw)
  assert any(c in "!@#$%^&*?" for c in pw)

def generate_password_rejects_short_length():
  with pytest.raises(ValueError):
    generate_password(3)
