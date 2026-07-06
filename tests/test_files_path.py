# tests/test_files_path.py

"""PATH namespace: lexical path manipulation and root-relative resolution, no disk I/O."""

import os

import pytest
from xaeian.files.path import PATH
from xaeian.files.config import file_context

WINDOWS = os.name == "nt" # different-drive paths (Z:\) only exist on Windows

# Pin a deterministic context so resolution is reproducible regardless of cwd/platform.
ROOT = "/proj/app"

@pytest.fixture(autouse=True)
def pinned_context():
  with file_context(root_path=ROOT, posix_slash=True, clean=True, auto_resolve=True) as cfg:
    yield cfg.root_path # absolute, native separators (e.g. C:\proj\app on Windows)

#------------------------------------------------------------------------------------ normalize

def normalize_uses_forward_slashes():
  assert PATH.normalize("a\\b\\c") == "a/b/c"

def normalize_collapses_redundant_segments():
  assert PATH.normalize("a//b/./c") == "a/b/c"

#----------------------------------------------------------------------------------------- stem

def stem_drops_only_the_last_extension():
  assert PATH.stem("dir/archive.tar.gz") == "archive.tar"
  assert PATH.stem("README") == "README"

#------------------------------------------------------------------------------------------ ext

def ext_returns_extension_with_dot():
  assert PATH.ext("dir/archive.tar.gz") == ".gz"

def ext_is_empty_without_extension():
  assert PATH.ext("README") == ""

#-------------------------------------------------------------------------------- ensure_suffix

def ensure_suffix_appends_when_missing():
  assert PATH.ensure_suffix("report", ".pdf") == "report.pdf"

def ensure_suffix_is_noop_when_already_present():
  assert PATH.ensure_suffix("report.pdf", ".pdf") == "report.pdf"

def ensure_suffix_empty_suffix_just_normalizes():
  assert PATH.ensure_suffix("a\\b", "") == "a/b"

#---------------------------------------------------------------------------------------- match

def match_globs_against_basename():
  assert PATH.match("src/main.py", "*.py") is True
  assert PATH.match("src/main.js", "*.py") is False

def match_supports_single_char_wildcard():
  assert PATH.match("a/b/c.txt", "c.???") is True

def match_ignores_directory_part():
  # pattern matches the basename only, never the leading directories
  assert PATH.match("src/main.py", "src/*") is False

#------------------------------------------------------------------------------------------ rel

def rel_makes_path_relative_to_root(pinned_context):
  root = pinned_context
  assert PATH.rel(f"{root}/src/main.py") == "src/main.py"

def rel_of_root_itself_is_empty(pinned_context):
  assert PATH.rel(pinned_context) == ""

def rel_escapes_root_with_dotdot(pinned_context):
  root = pinned_context
  assert PATH.rel(f"{root}/../other/x.py") == "../other/x.py"

#------------------------------------------------------------------------------------- is_under

def is_under_true_for_descendant(pinned_context):
  assert PATH.is_under(f"{pinned_context}/a/b") is True

def is_under_false_for_sibling(pinned_context):
  assert PATH.is_under(f"{pinned_context}/../other") is False

def is_under_false_for_parent(pinned_context):
  assert PATH.is_under(f"{pinned_context}/..") is False

#---------------------------------------------------------------------------------------- local

def local_returns_relative_path(pinned_context):
  assert PATH.local(f"{pinned_context}/x.py") == "x.py"

def local_prepends_prefix(pinned_context):
  assert PATH.local(f"{pinned_context}/x.py", prefix="app") == "app/x.py"

def local_trailing_slash_prefix_is_not_doubled(pinned_context):
  assert PATH.local(f"{pinned_context}/x.py", prefix="app/") == "app/x.py"

def local_of_root_with_prefix_is_the_prefix(pinned_context):
  assert PATH.local(pinned_context, prefix="app") == "app"

#--------------------------------------------------------------------------- basename / dirname

def basename_returns_final_component():
  assert PATH.basename("a/b/c.txt") == "c.txt"

def dirname_returns_parent():
  assert PATH.dirname("a/b/c.txt") == "a/b"

def with_suffix_replaces_extension():
  assert PATH.with_suffix("a/b.txt", ".md") == "a/b.md"

#----------------------------------------------------------------------------------------- join

def join_resolves_to_absolute_path(pinned_context):
  joined = PATH.join("sub", "file.txt")
  assert os.path.isabs(joined.replace("/", os.sep))
  assert joined.endswith("sub/file.txt")

def join_requires_at_least_one_part():
  with pytest.raises(ValueError):
    PATH.join()

#--------------------------------------------------------------- different drive (Windows-only)

@pytest.mark.skipif(not WINDOWS, reason="different-drive paths exist only on Windows")
def rel_falls_back_to_absolute_across_drives():
  # relpath raises ValueError across drives → rel returns the normalized absolute path
  assert PATH.rel("Z:/data/x.py") == "Z:/data/x.py"

@pytest.mark.skipif(not WINDOWS, reason="different-drive paths exist only on Windows")
def is_under_false_across_drives():
  assert PATH.is_under("Z:/data") is False

@pytest.mark.skipif(not WINDOWS, reason="different-drive paths exist only on Windows")
def local_falls_back_to_absolute_across_drives():
  assert PATH.local("Z:/x.py") == "Z:/x.py"
