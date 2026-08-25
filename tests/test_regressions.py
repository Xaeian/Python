# tests/test_regressions.py

"""Faults that shipped once: each test fails if the old behaviour comes back."""

import ftplib
import os
import subprocess
import sys
import time
import tracemalloc
import pytest
from pathlib import Path
from xaeian.cli.dupes import find_dupes
from xaeian.files import DIR
from xaeian.net.common import local_index
from xaeian.cli.tree import tree
from xaeian.cstruct import Struct, Field, Padding, Type
from xaeian.db import Database
from xaeian.db.utils import _insert_many_sql, _find_sql
from xaeian.eda.spice import _run_key, _work_id
from xaeian.media.pdf import parse_pages
from xaeian.net.ftp import FTP

#-------------------------------------------------------------------------------------- insert_many

def insert_many_binds_later_rows_by_column_name():
  """A row spelling its keys in another order used to land its values in the wrong columns."""
  sql, params = _insert_many_sql("t", [{"a": 1, "b": 2}, {"b": 20, "a": 10}])
  assert params == [(1, 2), (10, 20)]

def insert_many_refuses_a_row_missing_a_column():
  with pytest.raises(KeyError):
    _insert_many_sql("t", [{"a": 1, "b": 2}, {"a": 10}])

#-------------------------------------------------------------------------------------- parse_pages

def parse_pages_clamps_before_building_the_range():
  """"1-3000000" on a 5-page file used to allocate the whole range first."""
  tracemalloc.start()
  started = time.perf_counter()
  pages = parse_pages("1-3000000", total=5)
  peak = tracemalloc.get_traced_memory()[1]
  tracemalloc.stop()
  assert pages == [0, 1, 2, 3, 4]
  assert peak < 1_000_000, f"parse_pages allocated {peak} bytes for a 5-page document"
  assert time.perf_counter() - started < 1.0

def parse_pages_still_reads_ordinary_specs():
  assert parse_pages("1,3,5-7,!6", total=10) == [0, 2, 4, 6]
  assert parse_pages("8-", total=10) == [7, 8, 9]
  assert parse_pages("!1", total=3) == [1, 2]

#------------------------------------------------------------------------------------------ cstruct

def decoding_a_struct_short_of_its_padding_raises():
  """Padding and alignment skip bytes without reading them, so a truncated record decoded fine."""
  s = Struct(name="regression_pad")
  s.add(Field(Type.uint8, "a"), Padding(3))
  with pytest.raises(ValueError, match="Incomplete data"):
    s.decode(b"\x01")
  assert s.decode(b"\x01\x00\x00\x00") == {"a": 1}

def decoding_a_struct_that_consumes_nothing_raises():
  """An empty struct made `decode` loop forever, appending `{}` until the process died."""
  with pytest.raises(ValueError, match="consumes no bytes"):
    Struct(name="regression_empty").decode(b"\x00")

#---------------------------------------------------------------------------------------- spice ids

def a_run_key_tells_apart_every_pair_that_once_collided():
  """
  Each pair below shared one cache file, so a sweep read back another point's result.

  A dropped dot merged `2.2k` with `22k`, a dropped character merged `a+b` with `ab`,
  and joining a key straight onto its value let the value swallow the next key.
  """
  for a, b in [
    ({"RLOAD": "2.2k"}, {"RLOAD": "22k"}),
    ({"X": "a+b"}, {"X": "ab"}),
    ({"AB": "C"}, {"A": "BC"}),
    ({"R": "1k", "S": "2k"}, {"R": "1k_S2k"}),
    ({"A": "B_C"}, {"A": "B", "C": ""}),
    ({}, {"": ""}),
  ]:
    assert _run_key(a) != _run_key(b), f"{a} and {b} share a key"

def a_run_key_is_the_same_every_time_and_fits_a_filename():
  assert _run_key({"R": "1k"}) == _run_key({"R": "1k"})
  assert _run_key({"A": 1, "B": 2}) == _run_key({"B": 2, "A": 1}) # order is not identity
  assert len(_run_key({f"P{i:02}": "v" * 10 for i in range(12)})) <= 80

def parallel_runs_of_one_parameter_set_never_share_a_working_file():
  """Cache is keyed by parameters, so two identical runs met over one `.cir` ngspice held."""
  key = _run_key({"R": "1k"})
  assert len({_work_id(key) for _ in range(100)}) == 100

#---------------------------------------------------------------------------------------- FILE.save

def concurrent_saves_of_one_path_never_blend(tmp_path):
  """
  The temp name carried only the PID, so two threads wrote into one temporary file
  and the target ended up holding a mix of both. A loser may still be refused by the OS;
  what must never happen is a blended file or a stray temporary.
  """
  import threading
  from xaeian import FILE
  target = str(tmp_path / "shared.txt")
  contents = [str(i) * 20000 for i in range(8)]
  errors = []

  def save(text):
    try: FILE.save(target, text)
    except Exception as e: errors.append(e)

  threads = [threading.Thread(target=save, args=(t,)) for t in contents]
  for t in threads: t.start()
  for t in threads: t.join()
  assert all(isinstance(e, PermissionError) for e in errors), f"unexpected failure: {errors}"
  assert len(errors) < len(contents), "every writer was refused"
  assert FILE.load(target) in contents, "the file holds a blend of two writers"
  assert not list(tmp_path.glob("*.tmp")), "a temporary file was left behind"

#------------------------------------------------------------------------------------- Frame blocks

def a_block_is_read_out_of_its_declared_size():
  """A lying size header used to walk into the next block and desynchronise the stream."""
  from xaeian.cstruct import Frame, Struct, Field, Type
  temp = Struct(code=71, name="regr_temp"); temp.add(Field(Type.uint16, "v"))
  hum = Struct(code=72, name="regr_hum"); hum.add(Field(Type.uint16, "v"))
  frame = Frame(temp, hum, crc=None)
  good = frame.encode({"regr_temp": [{"v": 11}, {"v": 22}], "regr_hum": {"v": 33}})
  assert frame.decode(good) == {"regr_temp": [{"v": 11}, {"v": 22}], "regr_hum": {"v": 33}}

  over = bytearray(good); over[0] = 200
  with pytest.raises(ValueError, match="Block declares"):
    frame.decode(bytes(over))

  partial = bytearray(good); partial[0] = 5
  with pytest.raises(ValueError):
    frame.decode(bytes(partial))

#------------------------------------------------------------------------------- async transactions

def a_transaction_belongs_to_the_task_that_opened_it(tmp_path):
  """
  An unrelated task used to see `in_transaction()` True and join someone else's transaction,
  so its committed write vanished when that transaction rolled back.
  """
  import asyncio
  from xaeian.db import AsyncDatabase

  async def run():
    db = AsyncDatabase("sqlite", str(tmp_path / "tx.db"))
    await db.exec("CREATE TABLE t (id INTEGER PRIMARY KEY, tag TEXT)")
    opened = asyncio.Event()
    seen = {}

    async def writer():
      async with db.transaction():
        await db.insert("t", {"tag": "rolled-back"})
        opened.set()
        await asyncio.sleep(0.2)
        raise RuntimeError("abort")

    async def bystander():
      await opened.wait()
      seen["in_transaction"] = db.in_transaction()
      await db.insert("t", {"tag": "committed"})

    await asyncio.gather(writer(), bystander(), return_exceptions=True)
    tags = await db.get_column("SELECT tag FROM t")
    await db.close()
    return seen["in_transaction"], tags

  in_tx, tags = asyncio.run(run())
  assert in_tx is False, "an unrelated task was swept into the transaction"
  assert tags == ["committed"], f"the bystander's write did not survive: {tags}"

#---------------------------------------------------------------------------------------- blacklist

def one_blacklist_rule_answers_for_every_listing(tmp_path):
  """`"build/"` was honoured by `file_list` and silently ignored by `folder_list`."""
  from xaeian import DIR, FILE, file_context
  with file_context(root_path=str(tmp_path)):
    DIR.ensure("tree/build/")
    DIR.ensure("tree/src/")
    DIR.ensure("tree/docs/build/")
    FILE.save("tree/build/out.o", "x")
    FILE.save("tree/src/a.py", "y")
    FILE.save("tree/docs/build/d.o", "z")
    for entry in ("build", "build/"):
      assert sorted(DIR.folder_list("tree", deep=True, shape="name", blacklist=[entry])) \
        == ["docs", "src"], entry
      assert sorted(DIR.folder_list("tree", shape="name", blacklist=[entry])) \
        == ["docs", "src"], entry
      assert sorted(DIR.file_list("tree", shape="name", blacklist=[entry])) == ["a.py"], entry

def a_relative_blacklist_entry_prunes_only_that_path(tmp_path):
  from xaeian import DIR, FILE, file_context
  with file_context(root_path=str(tmp_path)):
    DIR.ensure("tree/build/")
    DIR.ensure("tree/docs/build/")
    FILE.save("tree/build/keep.o", "x")
    FILE.save("tree/docs/build/drop.o", "y")
    assert DIR.file_list("tree", shape="name", blacklist=["docs/build"]) == ["keep.o"]

def a_listing_does_not_change_its_answer_with_the_disk(tmp_path):
  """The old filter asked `isdir` while building itself, so results moved under it."""
  from xaeian import DIR, FILE, file_context
  with file_context(root_path=str(tmp_path)):
    DIR.ensure("tree/docs/")
    FILE.save("tree/docs/build", "a file, not a folder")
    before = DIR.file_list("tree", shape="rel", blacklist=["build"])
    DIR.ensure("tree/build/")
    assert DIR.file_list("tree", shape="rel", blacklist=["build"]) == before

def the_result_shape_is_one_parameter(tmp_path):
  """`basename` and `local` were two booleans encoding three mutually exclusive shapes."""
  import pytest
  from xaeian import DIR, FILE, file_context
  with file_context(root_path=str(tmp_path)):
    DIR.ensure("s/inner/")
    FILE.save("s/inner/a.txt", "x")
    assert DIR.file_list("s", shape="name") == ["a.txt"]
    assert DIR.file_list("s", shape="rel") == ["inner/a.txt"]
    assert DIR.file_list("s")[0].endswith("s/inner/a.txt")
    with pytest.raises(ValueError):
      DIR.file_list("s", shape="basename")

#--------------------------------------------------------------------------------- limits and pages

def a_limit_of_zero_asks_for_no_rows():
  """`if limit:` read `0` as "no limit given", so the query returned the whole table."""
  assert _find_sql("t", None, 0, {})[0].endswith("LIMIT 0")
  assert _find_sql("t", None, None, {})[0] == "SELECT * FROM t"

def a_negative_limit_is_refused():
  """SQLite reads `LIMIT -1` as no limit, so a negative value silently returned everything."""
  with pytest.raises(ValueError, match="negative"):
    _find_sql("t", None, -1, {})

def paginate_refuses_a_page_size_it_cannot_divide_by(tmp_path):
  """`per_page=0` reached the page-count arithmetic and raised ZeroDivisionError."""
  db = Database("sqlite", str(tmp_path / "pages.db"))
  with db.transaction():
    db.exec("CREATE TABLE t (id INTEGER PRIMARY KEY)")
    db.insert("t", {"id": 1})
  with pytest.raises(ValueError, match="per_page"):
    db.paginate("SELECT * FROM t", per_page=0)
  with pytest.raises(ValueError, match="1-based"):
    db.paginate("SELECT * FROM t", page=0)
  assert db.paginate("SELECT * FROM t")["total"] == 1

#--------------------------------------------------------------------------------------- FTP.remove

class _Refusing:
  """An FTP server that answers 550 to everything, as it does for both causes."""
  def delete(self, remote): raise ftplib.error_perm("550 Permission denied")

def removing_a_file_the_server_refuses_to_delete_raises(monkeypatch):
  """550 answers both "no such file" and "permission denied"; both were reported as success."""
  ftp = FTP.__new__(FTP)
  ftp._ftp = _Refusing()
  monkeypatch.setattr(FTP, "_require_connected", lambda self: None)
  monkeypatch.setattr(FTP, "exists", lambda self, remote: True)
  with pytest.raises(ftplib.error_perm):
    ftp.remove("locked.txt")
  monkeypatch.setattr(FTP, "exists", lambda self, remote: False)
  ftp.remove("gone.txt") # already absent: nothing to report

#------------------------------------------------------------------------------- directory boundary

class Link:
  """A class keeps this helper out of reach of `python_functions = ["*"]` collection."""
  @staticmethod
  def to_dir(link:Path, target:Path) -> None:
    """
    The directory link this platform has: a junction on Windows, a symlink elsewhere.

    Windows never gets a symlink here. The junction is the case `os.path.islink` cannot see,
    and testing a symlink there would exercise the half that was never broken.
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
  """`os.walk` enters a junction as an ordinary directory, so a listing left its own tree."""
  files = list(DIR.iter_files(str(linked_tree)))
  assert [f.rsplit("/", 1)[-1] for f in files] == ["in.txt"]
  assert [f.rsplit("/", 1)[-1] for f in DIR.folder_list(str(linked_tree), deep=True)] == ["sub"]

def a_transfer_carries_only_what_lives_under_the_path(linked_tree):
  """`sync_push` indexed by `rglob`, so it would upload a file from beside the directory."""
  assert list(local_index(str(linked_tree))) == ["sub/in.txt"]

def dupes_never_pairs_a_file_from_outside_the_root(linked_tree):
  """One file inside and one identical file outside came back as a duplicate pair to act on."""
  for follow in (False, True):
    assert find_dupes(str(linked_tree), min_size=1, follow_symlinks=follow) == []

def dupes_still_finds_real_duplicates(tmp_path):
  for name in ("a/x.txt", "b/y.txt"):
    path = tmp_path / name
    path.parent.mkdir(exist_ok=True)
    path.write_text("same", encoding="utf-8")
  (tmp_path / "z.txt").write_text("other", encoding="utf-8")
  assert [g["count"] for g in find_dupes(str(tmp_path), min_size=1)] == [2]

def tree_shows_a_link_without_walking_into_it(linked_tree):
  """A renderer names the link; expanding it invented a tree until the path ran out of room."""
  stats = tree(str(linked_tree), color=False)
  assert stats["files"] == 1, stats["lines"]
  assert "escape/" in "".join(stats["lines"])
