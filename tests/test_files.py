# tests/test_files.py

"""
File submodule: PATH/FILE/DIR + INI/CSV/JSON/YAML round-trips,
in both modes (global `file_context` and object-bound `Files`).
"""

import os, json, threading, zipfile
import pytest
from xaeian import file_context, Files, PATH, DIR, FILE, INI, CSV, JSON, YAML

@pytest.fixture(autouse=True)
def _root_context(tmp_path):
  # every test runs under a global context rooted at a fresh temp dir (restored on exit);
  # tests that need the path itself take the standard `tmp_path` fixture directly
  with file_context(root_path=str(tmp_path)):
    yield

#--------------------------------------------------------------------------------------------- PATH

@pytest.mark.parametrize("method, expected", [
  ("basename", "c.txt"),
  ("dirname", "a/b"),
  ("stem", "c"),
  ("ext", ".txt"),
])
def path_extracts_components(method, expected):
  assert getattr(PATH, method)("a/b/c.txt") == expected

def path_with_and_ensure_suffix():
  assert PATH.with_suffix("a/b.txt", ".md") == "a/b.md"
  assert PATH.ensure_suffix("a/b", ".txt") == "a/b.txt"
  assert PATH.ensure_suffix("a/b.txt", ".txt") == "a/b.txt" # idempotent

def path_normalize_posix_and_collapse():
  assert PATH.normalize("a\\b//c/./d") == "a/b/c/d"

def path_match_glob():
  assert PATH.match("src/main.py", "*.py")
  assert not PATH.match("src/main.py", "*.txt")

def path_expand_env_and_user():
  os.environ["XAEIAN_T"] = "/env/val"
  assert PATH.expand("$XAEIAN_T/y") == "/env/val/y"
  assert "~" not in PATH.expand("~/x") # ~ expands away

def path_resolve_joins_root_for_relative(tmp_path):
  resolved = PATH.resolve("data/x.txt")
  assert resolved.startswith(PATH.normalize(str(tmp_path))) and resolved.endswith("/data/x.txt")

def path_resolve_keeps_absolute(tmp_path):
  abs_in = str(tmp_path / "x.txt")
  assert PATH.resolve(abs_in) == PATH.normalize(abs_in)

def path_join_resolves():
  assert PATH.join("a", "b", "c.txt").endswith("/a/b/c.txt")

def path_rel_and_is_under(tmp_path):
  assert PATH.rel(str(tmp_path / "sub" / "f.txt")) == "sub/f.txt"
  assert PATH.rel(str(tmp_path / "p/q/f.txt"), base=str(tmp_path / "p")) == "q/f.txt"
  assert PATH.is_under("sub/f.txt")
  assert not PATH.is_under("../outside")

def path_ext_empty_for_no_extension():
  assert PATH.ext("noext") == ""

def path_exists_is_file_is_dir():
  FILE.save("a.txt", "x")
  DIR.ensure("d/")
  assert FILE.exists("a.txt") and not DIR.exists("a.txt")
  assert DIR.exists("d") and not FILE.exists("d")
  assert not FILE.exists("nope.txt")

#--------------------------------------------------------------------------------------------- FILE

def file_text_roundtrip():
  FILE.save("a.txt", "Hello!")
  assert FILE.load("a.txt") == "Hello!"

def file_binary_roundtrip():
  FILE.save("b.bin", b"\x00\x01\x02")
  assert FILE.load("b.bin", binary=True) == b"\x00\x01\x02"

def file_append_and_lines():
  FILE.save("c.txt", "a")
  FILE.append("c.txt", "b")
  FILE.append_line("c.txt", "c")
  assert FILE.load("c.txt") == "abc\n"
  FILE.save_lines("d.txt", ["x\n", "y\n"])
  assert FILE.load_lines("d.txt") == ["x\n", "y\n"]
  assert list(FILE.iter_lines("d.txt", strip=True)) == ["x", "y"]

def file_save_creates_parent_dirs():
  FILE.save("deep/nested/x.txt", "ok") # parent dirs auto-created
  assert FILE.load("deep/nested/x.txt") == "ok"

def file_exists_and_remove():
  FILE.save("e.txt", "x")
  assert FILE.exists("e.txt") and not FILE.exists(["e.txt", "missing"])
  assert FILE.remove("e.txt") and not FILE.exists("e.txt")
  assert FILE.remove("missing", missing_ok=True) is False

def file_load_missing_raises():
  with pytest.raises(FileNotFoundError):
    FILE.load("nope.txt")

def file_hash_and_size():
  FILE.save("h.txt", "abc")
  assert FILE.hash("h.txt", algo="md5") == "900150983cd24fb0d6963f7d28e17f72" # md5("abc")
  # sha256 of "abc"
  assert FILE.hash("h.txt") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
  assert FILE.size("h.txt") == 3 and FILE.mtime("h.txt") > 0

def concurrent_saves_of_one_path_never_blend(tmp_path):
  """
  Each writer gets its own temporary file: one named by the PID alone would blend two threads.

  A loser may be refused by the OS; a blended file or a stray temporary never happens.
  """
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

#---------------------------------------------------------------------------------------------- DIR

def dir_ensure_creates_dirs(tmp_path):
  DIR.ensure("a/b/c/")
  assert (tmp_path / "a/b/c").is_dir()
  DIR.ensure("x/y/file.txt", is_file=True) # only the parent dir is created
  assert (tmp_path / "x/y").is_dir() and not (tmp_path / "x/y/file.txt").exists()

def dir_file_list_filters_by_ext():
  FILE.save("p/a.txt", "1"); FILE.save("p/b.py", "2"); FILE.save("p/sub/c.txt", "3")
  assert sorted(DIR.file_list("p", exts=[".txt"], shape="rel")) == ["a.txt", "sub/c.txt"]

def dir_file_list_match_and_blacklist():
  FILE.save("p/a.txt", "1"); FILE.save("p/sub/c.py", "2")
  assert DIR.file_list("p", match="*.py", shape="rel") == ["sub/c.py"]
  assert DIR.file_list("p", blacklist=["sub"], shape="rel") == ["a.txt"]

def one_blacklist_rule_answers_for_every_listing():
  """`"build"` and `"build/"` prune the same folders from `file_list` and `folder_list` alike."""
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

def a_relative_blacklist_entry_prunes_only_that_path():
  DIR.ensure("tree/build/")
  DIR.ensure("tree/docs/build/")
  FILE.save("tree/build/keep.o", "x")
  FILE.save("tree/docs/build/drop.o", "y")
  assert DIR.file_list("tree", shape="name", blacklist=["docs/build"]) == ["keep.o"]

def a_listing_does_not_change_its_answer_with_the_disk():
  """A blacklist entry matches by name, never by asking the disk, so a new folder moves nothing."""
  DIR.ensure("tree/docs/")
  FILE.save("tree/docs/build", "a file, not a folder")
  before = DIR.file_list("tree", shape="rel", blacklist=["build"])
  DIR.ensure("tree/build/")
  assert DIR.file_list("tree", shape="rel", blacklist=["build"]) == before

def the_result_shape_is_one_parameter():
  """`shape` picks one of three exclusive results, and an unknown one is refused."""
  DIR.ensure("s/inner/")
  FILE.save("s/inner/a.txt", "x")
  assert DIR.file_list("s", shape="name") == ["a.txt"]
  assert DIR.file_list("s", shape="rel") == ["inner/a.txt"]
  assert DIR.file_list("s")[0].endswith("s/inner/a.txt")
  with pytest.raises(ValueError):
    DIR.file_list("s", shape="basename")

def dir_folder_list_and_iter_files():
  FILE.save("base/a.txt", "1"); FILE.save("base/sub/b.txt", "2")
  assert DIR.folder_list("base", shape="name") == ["sub"]
  assert sorted(PATH.rel(f) for f in DIR.iter_files("base")) == ["base/a.txt", "base/sub/b.txt"]

def dir_copy_move_remove(tmp_path):
  FILE.save("src/a.txt", "x")
  DIR.copy("src", "dst")
  assert (tmp_path / "dst/a.txt").read_text(encoding="utf-8") == "x"
  DIR.move("dst", "moved")
  assert (tmp_path / "moved/a.txt").exists() and not (tmp_path / "dst").exists()
  DIR.remove("moved")
  assert not (tmp_path / "moved").exists()

def dir_copy_single_file():
  FILE.save("f.txt", "X")
  DIR.copy("f.txt", "g.txt")
  assert FILE.load("g.txt") == "X"

def dir_remove_nonexistent_raises():
  with pytest.raises(NotADirectoryError):
    DIR.remove("missingdir")

def dir_zip_unzip_roundtrip():
  FILE.save("z/a.txt", "1"); FILE.save("z/inner/b.txt", "2")
  DIR.zip("z")
  DIR.unzip("z.zip", "out")
  assert sorted(DIR.file_list("out", shape="rel")) == ["a.txt", "inner/b.txt"]

def dir_mtime_moves_with_a_deletion(tmp_path):
  FILE.save("m/a.txt", "1"); FILE.save("m/inner/b.txt", "2")
  old = DIR.mtime("m") - 10
  for f in ("m", "m/a.txt", "m/inner", "m/inner/b.txt"): os.utime(tmp_path / f, (old, old))
  assert DIR.mtime("m") == old
  FILE.remove("m/inner/b.txt") # nothing new is written, only the parent folder moves
  assert DIR.mtime("m") > old
  assert DIR.mtime("m", blacklist=["inner"]) == old

def dir_zip_keep_fresh_skips_a_rebuild(tmp_path):
  """
  Every timestamp is pinned, the folder's included.
  `FILE.save` swaps a file in with `os.replace`, which stamps the folder "now",
  and two "now"s inside one clock tick are equal.
  """
  def archived(): return zipfile.ZipFile(tmp_path / "k.zip").read("a.txt")
  def pin(name, at): os.utime(tmp_path / name, (at, at))
  T = 1_000_000_000 # a zip entry cannot carry a date before 1980
  FILE.save("k/a.txt", "1")
  DIR.zip("k", "k.zip")
  FILE.save("k/a.txt", "2")
  pin("k", T); pin("k/a.txt", T); pin("k.zip", T + 10)
  DIR.zip("k", "k.zip", keep_fresh=True)
  assert archived() == b"1" # the tree stops before the archive: kept
  pin("k/a.txt", T + 20)
  DIR.zip("k", "k.zip", keep_fresh=True)
  assert archived() == b"2" # one file outruns the archive: rebuilt

#------------------------------------------------------------------------------------- INI/CSV/JSON

def ini_roundtrip_preserves_types_and_sections():
  data = {"top": 1, "main": {"k": "v", "n": 42, "flag": True, "pi": 1.5}}
  INI.save("c", data)
  assert INI.load("c") == data

def ini_load_skips_comments_and_inline():
  FILE.save("z.ini", "; comment\nk = 1 # inline\n[s]\nv = 2\n")
  assert INI.load("z") == {"k": 1, "s": {"v": 2}}

def ini_repeated_section_continues_instead_of_starting_over():
  FILE.save("r.ini", "[s]\na = 1\n[t]\nb = 2\n[s]\nc = 3\n")
  assert INI.load("r") == {"s": {"a": 1, "c": 3}, "t": {"b": 2}}

def ini_save_writes_inline_comment():
  INI.save("w", {"k": (5, "note")}) # (value, comment) tuple → trailing comment
  assert FILE.load("w.ini").strip() == "k = 5 # note"

def ini_parse_hex_and_load_missing_empty():
  assert INI.parse("0x10") == 16
  assert INI.load("none") == {}

@pytest.mark.parametrize("name", ["app.conf", "app.cfg", "APP.CONF"])
def ini_accepts_official_extensions(name):
  data = {"main": {"k": "v", "n": 7}}
  INI.save(name, data)
  assert FILE.exists(name) # saved as-is, no .ini appended
  assert INI.load(name) == data

def ini_appends_ini_for_other_extensions():
  INI.save("app.v2", {"k": 1})
  assert FILE.exists("app.v2.ini")
  assert INI.load("app.v2") == {"k": 1}

@pytest.mark.parametrize("value, text", [(None, ""), (True, "true"), (False, "false"), (42, "42")])
def ini_format_matches(value, text):
  assert INI.format(value) == text

@pytest.mark.parametrize("text, value", [
  ("true", True), ("false", False), ("42", 42), ("1.5", 1.5), ('"hi"', "hi"),
])
def ini_parse_matches(text, value):
  assert INI.parse(text) == value

def csv_roundtrip_with_types():
  CSV.save("d", [{"a": 1, "b": 2}, {"a": 3, "b": 4}])
  assert CSV.load("d", types={"a": int, "b": int}) == [{"a": 1, "b": 2}, {"a": 3, "b": 4}]

def csv_bool_reads_the_word_not_the_length():
  CSV.save("f", [{"on": "true"}, {"on": "0"}, {"on": "no"}, {"on": ""}])
  assert [r["on"] for r in CSV.load("f", types={"on": bool})] == [True, False, False, None]

def csv_saving_no_rows_leaves_no_old_rows_behind():
  """A filter that matched nothing must not leave the previous result reading as current."""
  CSV.save("e", [{"a": 1}])
  CSV.save("e", [])
  assert CSV.load("e") == [] and FILE.load("e.csv") == ""
  CSV.save("e", [], field_names=["a", "b"])
  assert FILE.load("e.csv").strip() == "a,b"

def csv_load_raw_and_vectors():
  CSV.save("d", [{"a": 1, "b": 2}, {"a": 3, "b": 4}])
  assert CSV.load_raw("d") == [["a", "b"], ["1", "2"], ["3", "4"]] # raw is strings
  assert CSV.load_vectors("d", types={"a": int, "b": int}) == {"a": [1, 3], "b": [2, 4]}

def csv_load_vectors_group_by():
  CSV.save("g", [{"grp": "x", "v": 1}, {"grp": "x", "v": 2}, {"grp": "y", "v": 3}])
  grouped = CSV.load_vectors("g", types={"v": int}, group_by="grp")
  assert grouped == {"x": {"v": [1, 2]}, "y": {"v": [3]}}

def csv_add_row_dict_and_list_rows():
  CSV.add_row("e", {"x": 1, "y": 2}); CSV.add_row("e", {"x": 3, "y": 4})
  assert CSV.load("e", types={"x": int, "y": int}) == [{"x": 1, "y": 2}, {"x": 3, "y": 4}]
  CSV.add_row("lst", [1, 2], header=["x", "y"]); CSV.add_row("lst", [3, 4])
  assert CSV.load("lst", types={"x": int, "y": int}) == [{"x": 1, "y": 2}, {"x": 3, "y": 4}]

def csv_save_vectors_zips_and_rejects_mismatch():
  CSV.save_vectors("v", [1, 2], [3, 4], header=["a", "b"])
  assert CSV.load("v", types={"a": int, "b": int}) == [{"a": 1, "b": 3}, {"a": 2, "b": 4}]
  with pytest.raises(ValueError):
    CSV.save_vectors("bad", [1, 2], [3]) # unequal column lengths

def csv_load_missing_returns_empty():
  assert CSV.load("none") == []

BOM = b"\xef\xbb\xbf"

def csv_reads_past_a_bom():
  """Excel's "CSV UTF-8" starts with a BOM, which stuck to the first column name."""
  FILE.save("excel.csv", BOM + b"v,i\n3.3,120\n")
  assert CSV.load("excel", types={"v": float, "i": int}) == [{"v": 3.3, "i": 120}]
  assert CSV.load_raw("excel")[0] == ["v", "i"]

def csv_add_row_appends_to_a_bom_file_and_keeps_the_bom():
  FILE.save("excel.csv", BOM + b"v,i\n3.3,120\n")
  CSV.add_row("excel", {"v": 3.4, "i": 121})
  rows = CSV.load("excel", types={"v": float, "i": int})
  assert rows == [{"v": 3.3, "i": 120}, {"v": 3.4, "i": 121}]
  assert FILE.load("excel.csv", binary=True).startswith(BOM + b"v,i")

def csv_add_row_refuses_a_dict_row_into_a_lone_bom():
  """Recorded, not endorsed: a file holding only a BOM has an empty header, so no key fits."""
  FILE.save("empty.csv", BOM)
  with pytest.raises(ValueError):
    CSV.add_row("empty", {"v": 1})

def json_roundtrip():
  data = {"a": 1, "b": [1, 2, 3], "c": {"x": True}}
  JSON.save("j", data)
  assert JSON.load("j") == data

def json_pretty_and_smart_roundtrip():
  data = {"name": "ok", "xs": [1, 2, 3]}
  JSON.save_pretty("p", data); assert JSON.load("p") == data
  JSON.save_smart("s", data); assert JSON.load("s") == data

def json_smart_stays_valid_and_ascii_escapes():
  data = {"xs": [1, 2, 3], "m": {"a": 1}}
  assert json.loads(JSON.smart(data)) == data # smart layout is still valid JSON
  JSON.save("u", {"k": "ą"}, ensure_ascii=True)
  assert "ą" not in FILE.load("u.json") # non-ascii escaped

def json_load_missing_returns_default():
  assert JSON.load("nope", otherwise={"def": 1}) == {"def": 1}

def yaml_roundtrip():
  data = {"debug": True, "port": 8080, "tags": ["a", "b"]}
  YAML.save("y", data)
  assert YAML.load("y") == data

def yaml_pretty_multi_doc_and_missing():
  YAML.save_pretty("yp", {"a": 1, "b": [1, 2]}); assert YAML.load("yp") == {"a": 1, "b": [1, 2]}
  YAML.save_all("m", [{"id": 1}, {"id": 2}]); assert YAML.load_all("m") == [{"id": 1}, {"id": 2}]
  assert YAML.load("none", otherwise=[]) == []

def yaml_yml_extension_roundtrip():
  YAML.save("app.yml", {"k": 1})
  assert FILE.exists("app.yml") # saved as-is, no .yaml appended
  assert YAML.load("app.yml") == {"k": 1}
  assert YAML.load("app") == {"k": 1} # bare name still finds .yml

#-------------------------------------------------------------------------------------------- Modes

def file_context_restores_previous_root(tmp_path):
  a, b = tmp_path / "A", tmp_path / "B"
  with file_context(root_path=str(a)):
    FILE.save("x.txt", "a")
    with file_context(root_path=str(b)):
      FILE.save("y.txt", "b")
    FILE.save("z.txt", "a2") # back to A after the inner block exits
  assert (a / "x.txt").exists() and (a / "z.txt").exists()
  assert (b / "y.txt").exists() and not (b / "z.txt").exists()

def files_object_uses_its_own_root(tmp_path):
  fs = Files(root_path=str(tmp_path / "obj"))
  fs.FILE.save("o.txt", "obj")
  assert (tmp_path / "obj" / "o.txt").read_text(encoding="utf-8") == "obj"
  assert fs.FILE.load("o.txt") == "obj"

def files_object_data_namespaces(tmp_path):
  fs = Files(root_path=str(tmp_path / "data"))
  fs.JSON.save("cfg", {"a": 1}); assert fs.JSON.load("cfg") == {"a": 1}
  fs.CSV.save("d", [{"x": 1}]); assert fs.CSV.load("d", types={"x": int}) == [{"x": 1}]
  fs.INI.save("s", {"m": {"k": "v"}}); assert fs.INI.load("s") == {"m": {"k": "v"}}

def files_object_atomic_lands_under_its_own_root(tmp_path):
  """The temp path is taken when the block runs, long after the bound call returned."""
  fs = Files(root_path=str(tmp_path / "own"))
  with fs.FILE.atomic("a.txt") as tmp:
    with open(tmp, "w", encoding="utf-8") as f: f.write("x")
  assert (tmp_path / "own" / "a.txt").read_text(encoding="utf-8") == "x"

def files_object_independent_of_global_context(tmp_path):
  a, b = tmp_path / "A", tmp_path / "B"
  fs = Files(root_path=str(a))
  with file_context(root_path=str(b)):
    fs.FILE.save("iso.txt", "in-A") # bound to A despite active context B
    FILE.save("ctx.txt", "in-B") # global namespace follows the context → B
  assert (a / "iso.txt").exists() and not (b / "iso.txt").exists()
  assert (b / "ctx.txt").exists()

#---------------------------------------------------------------------------------------- PATH.real

def real_resolves_symlinks(tmp_path):
  outside = tmp_path / "outside.txt"; outside.write_text("x")
  base = tmp_path / "base"; base.mkdir()
  link = base / "link.txt"
  try: os.symlink(outside, link)
  except OSError: pytest.skip("symlinks not permitted")
  assert PATH.real(str(link)).endswith("outside.txt")
  assert PATH.is_under(str(link), str(base)) # lexical check cannot see through the link
  assert not PATH.is_under(str(link), str(base), real=True)

def is_under_real_keeps_plain_files(tmp_path):
  f = tmp_path / "base" / "a.txt"
  f.parent.mkdir(); f.write_text("x")
  assert PATH.is_under(str(f), str(tmp_path / "base"), real=True)

#----------------------------------------------------------------------------------------- DIR deep

def file_list_deep_flag():
  FILE.save("a.log", "1"); FILE.save("sub/b.log", "2")
  assert sorted(DIR.file_list(".", shape="name")) == ["a.log", "b.log"]
  assert DIR.file_list(".", shape="name", deep=False) == ["a.log"]
  assert DIR.file_list(".", match="a.*", shape="name", deep=False) == ["a.log"]

#---------------------------------------------------------------------------------- FILE.save chmod

def file_save_chmod_sets_final_permissions(tmp_path):
  FILE.save("s.env", "K=v\n", chmod=0o600)
  FILE.save("s.env", "K=w\n", chmod=0o600) # existing file: content replaced, mode kept
  assert FILE.load("s.env") == "K=w\n"
  if os.name != "nt":
    assert oct((tmp_path / "s.env").stat().st_mode)[-3:] == "600"

@pytest.mark.skipif(os.name == "nt", reason="POSIX modes")
def file_save_again_keeps_the_mode_of_the_file_it_replaces(tmp_path):
  """The swap writes a new file: without the old mode a secret would come back world-readable."""
  secret = tmp_path / "token"
  secret.write_text("a", encoding="utf-8")
  secret.chmod(0o600)
  FILE.save("token", "b")
  assert secret.stat().st_mode & 0o777 == 0o600

@pytest.mark.skipif(os.name == "nt", reason="POSIX modes")
def file_save_sets_a_mode_the_umask_would_narrow(tmp_path):
  """`os.open` alone narrows by the umask: a shared `0o664` file would lose group write."""
  shared = tmp_path / "shared.txt"
  shared.write_text("a", encoding="utf-8")
  shared.chmod(0o664)
  umask = os.umask(0o022)
  try:
    FILE.save("shared.txt", "b")
    FILE.save("open.txt", "c", chmod=0o666)
  finally:
    os.umask(umask)
  assert shared.stat().st_mode & 0o777 == 0o664
  assert (tmp_path / "open.txt").stat().st_mode & 0o777 == 0o666

def file_save_through_a_symlink_writes_its_target(tmp_path):
  target = tmp_path / "real.txt"
  target.write_text("a", encoding="utf-8")
  link = tmp_path / "link.txt"
  try:
    link.symlink_to(target)
  except OSError:
    pytest.skip("symlinks need a privilege here")
  FILE.save("link.txt", "b")
  assert link.is_symlink() and target.read_text(encoding="utf-8") == "b"
