# tests/test_links.py

"""
Directory links: a walker lists what lives under its root and names a link without entering it.

A junction on Windows is the link `os.path.islink` cannot see,
so each walker here meets one looping back to its root and one leading outside.
"""

import os, subprocess, sys
from pathlib import Path
import pytest
from xaeian.cli.dupes import find_dupes
from xaeian.cli.tree import tree
from xaeian.files import DIR
from xaeian.net.common import local_index

class Link:
  """A class keeps this helper out of reach of `python_functions = ["*"]` collection."""
  @staticmethod
  def to_dir(link:Path, target:Path) -> None:
    """
    The directory link this platform has: a junction on Windows, a symlink elsewhere.

    Windows gets the junction because `os.path.islink` cannot see it; a symlink is the easy half.
    """
    if sys.platform != "win32":
      os.symlink(target, link, target_is_directory=True)
      return
    done = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
      capture_output=True)
    if done.returncode: pytest.skip(f"cannot create a junction: {done.stderr!r}")

@pytest.fixture
def linked_tree(tmp_path):
  """
  `root` holds one file, a link looping back to itself, and a link to a sibling directory.

  Both files carry the same bytes, so anything that walks out of `root`
  pairs them up and says so out loud.
  """
  root, outside = tmp_path / "root", tmp_path / "outside"
  (root / "sub").mkdir(parents=True)
  outside.mkdir()
  (root / "sub" / "in.txt").write_text("same bytes", encoding="utf-8")
  (outside / "secret.txt").write_text("same bytes", encoding="utf-8")
  Link.to_dir(root / "sub" / "loop", root)
  Link.to_dir(root / "escape", outside)
  return root

def a_listing_reports_only_what_lives_under_the_path(linked_tree):
  """`os.walk` enters a junction as an ordinary directory, which would take a listing outside."""
  files = list(DIR.iter_files(str(linked_tree)))
  assert [f.rsplit("/", 1)[-1] for f in files] == ["in.txt"]
  assert [f.rsplit("/", 1)[-1] for f in DIR.folder_list(str(linked_tree), deep=True)] == ["sub"]

def a_transfer_carries_only_what_lives_under_the_path(linked_tree):
  """Indexed by `rglob`, `sync_push` would upload a file from beside the directory."""
  assert list(local_index(str(linked_tree))) == ["sub/in.txt"]

def dupes_never_pairs_a_file_from_outside_the_root(linked_tree):
  """One file inside and one identical file outside would come back as a pair to act on."""
  for follow in (False, True):
    assert find_dupes(str(linked_tree), min_size=1, follow_symlinks=follow) == []

def dupes_finds_the_duplicates_inside_the_root(tmp_path):
  for name in ("a/x.txt", "b/y.txt"):
    path = tmp_path / name
    path.parent.mkdir(exist_ok=True)
    path.write_text("same", encoding="utf-8")
  (tmp_path / "z.txt").write_text("other", encoding="utf-8")
  assert [g["count"] for g in find_dupes(str(tmp_path), min_size=1)] == [2]

def tree_shows_a_link_without_walking_into_it(linked_tree):
  """Expanding the loop would invent a tree until the path runs out of room."""
  stats = tree(str(linked_tree), color=False)
  assert stats["files"] == 1, stats["lines"]
  assert "escape/" in "".join(stats["lines"])
