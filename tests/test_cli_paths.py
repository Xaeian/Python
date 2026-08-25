# tests/test_cli_paths.py

"""CLI path handling: arguments coming from the command line resolve `~` and `$VAR`."""

import pytest
from xaeian.cli.tree import tree
from xaeian.cli.dupes import find_dupes

@pytest.fixture
def home(tmp_path, monkeypatch):
  """Point `~` at `tmp_path` on every platform expanduser consults."""
  monkeypatch.setenv("HOME", str(tmp_path))
  monkeypatch.setenv("USERPROFILE", str(tmp_path))
  monkeypatch.delenv("HOMEDRIVE", raising=False)
  monkeypatch.delenv("HOMEPATH", raising=False)
  return tmp_path

def tree_expands_tilde(home):
  (home / "marker.txt").write_text("x", encoding="utf-8")
  assert any("marker.txt" in line for line in tree("~")["lines"])

def tree_expands_env_var(tmp_path, monkeypatch):
  monkeypatch.setenv("XAEIAN_TEST_ROOT", str(tmp_path))
  (tmp_path / "marker.txt").write_text("x", encoding="utf-8")
  assert any("marker.txt" in line for line in tree("$XAEIAN_TEST_ROOT")["lines"])

def find_dupes_expands_tilde(home):
  (home / "a.txt").write_text("same", encoding="utf-8")
  (home / "b.txt").write_text("same", encoding="utf-8")
  assert len(find_dupes("~")) == 1

def tree_reports_a_missing_directory(tmp_path):
  with pytest.raises(FileNotFoundError):
    tree(str(tmp_path / "nie-ma-mnie"))
