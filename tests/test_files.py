# tests/test_files.py

"""File submodule: PATH/FILE/DIR + INI/CSV/JSON/YAML round-trips, in both modes
(global `file_context` and object-bound `Files`)."""

import os
import json
import pytest
from xaeian import file_context, Files, PATH, DIR, FILE, INI, CSV, JSON, YAML

@pytest.fixture(autouse=True)
def _root_context(tmp_path):
  # every test runs under a global context rooted at a fresh temp dir (restored on exit);
  # tests that need the path itself take the standard `tmp_path` fixture directly
  with file_context(root_path=str(tmp_path)):
    yield

#------------------------------------------------------------------------------------------ PATH

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
  assert PATH.exists("a.txt") and PATH.is_file("a.txt") and not PATH.is_dir("a.txt")
  assert PATH.is_dir("d") and not PATH.is_file("d")
  assert not PATH.exists("nope.txt")

#------------------------------------------------------------------------------------------ FILE

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
  assert FILE.hash("h.txt", algo="md5") == "900150983cd24fb0d6963f7d28e17f72"      # md5("abc")
  assert FILE.hash("h.txt") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad" # sha256
  assert FILE.size("h.txt") == 3 and FILE.mtime("h.txt") > 0

#------------------------------------------------------------------------------------------- DIR

def dir_ensure_creates_dirs(tmp_path):
  DIR.ensure("a/b/c/")
  assert (tmp_path / "a/b/c").is_dir()
  DIR.ensure("x/y/file.txt", is_file=True) # only the parent dir is created
  assert (tmp_path / "x/y").is_dir() and not (tmp_path / "x/y/file.txt").exists()

def dir_file_list_filters_by_ext():
  FILE.save("p/a.txt", "1"); FILE.save("p/b.py", "2"); FILE.save("p/sub/c.txt", "3")
  assert sorted(DIR.file_list("p", exts=[".txt"], local=True)) == ["a.txt", "sub/c.txt"]

def dir_file_list_match_and_blacklist():
  FILE.save("p/a.txt", "1"); FILE.save("p/sub/c.py", "2")
  assert DIR.file_list("p", match="*.py", local=True) == ["sub/c.py"]
  assert DIR.file_list("p", blacklist=["sub"], local=True) == ["a.txt"]

def dir_folder_list_and_iter_files():
  FILE.save("base/a.txt", "1"); FILE.save("base/sub/b.txt", "2")
  assert DIR.folder_list("base", basename=True) == ["sub"]
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
  assert sorted(DIR.file_list("out", local=True)) == ["a.txt", "inner/b.txt"]

#--------------------------------------------------------------------------------- INI/CSV/JSON

def ini_roundtrip_preserves_types_and_sections():
  data = {"top": 1, "main": {"k": "v", "n": 42, "flag": True, "pi": 1.5}}
  INI.save("c", data)
  assert INI.load("c") == data

def ini_load_skips_comments_and_inline():
  FILE.save("z.ini", "; comment\nk = 1 # inline\n[s]\nv = 2\n")
  assert INI.load("z") == {"k": 1, "s": {"v": 2}}

def ini_save_writes_inline_comment():
  INI.save("w", {"k": (5, "note")}) # (value, comment) tuple → trailing comment
  assert FILE.load("w.ini").strip() == "k = 5 # note"

def ini_parse_hex_and_load_missing_empty():
  assert INI.parse("0x10") == 16
  assert INI.load("none") == {}

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

def csv_load_raw_and_vectors():
  CSV.save("d", [{"a": 1, "b": 2}, {"a": 3, "b": 4}])
  assert CSV.load_raw("d") == [["a", "b"], ["1", "2"], ["3", "4"]] # raw is strings
  assert CSV.load_vectors("d", types={"a": int, "b": int}) == {"a": [1, 3], "b": [2, 4]}

def csv_load_vectors_group_by():
  CSV.save("g", [{"grp": "x", "v": 1}, {"grp": "x", "v": 2}, {"grp": "y", "v": 3}])
  assert CSV.load_vectors("g", types={"v": int}, group_by="grp") == {"x": {"v": [1, 2]}, "y": {"v": [3]}}

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

#------------------------------------------------------------------------------------ Modes

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

def files_object_independent_of_global_context(tmp_path):
  a, b = tmp_path / "A", tmp_path / "B"
  fs = Files(root_path=str(a))
  with file_context(root_path=str(b)):
    fs.FILE.save("iso.txt", "in-A") # bound to A despite active context B
    FILE.save("ctx.txt", "in-B")    # global namespace follows the context → B
  assert (a / "iso.txt").exists() and not (b / "iso.txt").exists()
  assert (b / "ctx.txt").exists()
