# tests/test_types.py

"""
The public API as a typed client sees it, checked by mypy against the installed package.

`assert_type` is the one construct that fails on `Any`, so a dropped annotation turns a pin
red instead of quietly widening the API.

The client sits in a directory of its own, so `xaeian` resolves through site-packages
and `py.typed`, as it does for whoever installed the wheel, not through the source tree.
The library's own type debt is not this file's business, hence `--follow-imports=silent`.
"""

import subprocess
import sys
from importlib.util import find_spec
import pytest

CLIENT = '''
from datetime import timedelta
from typing import Any, Iterator, assert_type
from xaeian import CRC, CSV, DIR, FILE, INI, JSON, PATH, Files, Logger, Print, Time
from xaeian import generate_token, logger, replace_map, split_sql
from xaeian.cstruct import Field, Frame, Struct, Type
from xaeian.db import AbstractAsyncDatabase, AbstractDatabase, AsyncDatabase, Database, KeyValue
import xaeian.table as tbl

#-------------------------------------------------------------------------------------------- Files

assert_type(FILE.load("a.txt"), str|bytes)
assert_type(FILE.load_lines("a.txt"), list[str])
assert_type(FILE.iter_lines("a.txt"), Iterator[str])
assert_type(FILE.hash("a.txt"), str)
assert_type(FILE.save("a.txt", "x"), None)
assert_type(DIR.ensure("out"), str)
assert_type(DIR.file_list(".", exts=[".py"]), list[str])
assert_type(JSON.load("a.json"), Any) # payload shape is the caller's business
assert_type(CSV.load("a.csv"), list[dict[str, Any]])
assert_type(INI.load("a.ini"), dict[str, Any])
assert_type(PATH.resolve("a"), str)
assert_type(Files(root_path="/d").FILE.load("a.txt"), Any) # bound namespaces are untyped

#------------------------------------------------------------------------------------------- Binary

crc = CRC(16, 0x8005, 0xFFFF, True, True, 0x0000, True)
assert_type(crc.checksum(b"x"), int)
assert_type(crc.encode(b"x"), bytes)
assert_type(crc.decode(b"x"), bytes|None)

st = Struct(1, "sensor").add(Field(Type.uint16, "mv", scale=0.1))
assert_type(st, Struct)
assert_type(st["mv"], Field)
assert_type(st.encode({"mv": 3.3}), bytes)
assert_type(st.decode(b""), list[dict[str, Any]]|dict[str, Any])
assert_type(Frame(st).decode(b""), dict[str, dict[Any, Any]|list[dict[Any, Any]]])

#------------------------------------------------------------------------------------ Log and table

log = logger("client", file=False)
assert_type(log, Logger)
assert_type(log.inf("x"), None)
assert_type(Print().level, int)

rows: list[dict[str, Any]] = []
assert_type(tbl.where(rows, lambda r: True), list[dict[str, Any]])
assert_type(tbl.first(rows, lambda r: True), dict[str, Any]|None)
assert_type(tbl.pluck(rows, "name"), list[Any])
assert_type(tbl.markdown(rows), str)

#--------------------------------------------------------------------------------- Strings and time

assert_type(split_sql("select 1; select 2"), list[str])
assert_type(generate_token(16), str)
assert_type(replace_map("a{x}", {"x": "1"}), str|list[Any]|dict[Any, Any])

t = Time("2020-01-01")
assert_type(t + "1d", Time)
assert_type(t - t, Time|timedelta)
assert_type(t.to("iso"), float|int|str|Time)
assert_type(t.round("h"), Time)

#----------------------------------------------------------------------------------------- Database

db = Database("sqlite", ":memory:")
assert_type(db, AbstractDatabase)
assert_type(db.exec("delete from t"), int)
assert_type(db.get_dict("select 1"), dict[str, Any]|None)
assert_type(db.get_dicts("select 1"), list[dict[str, Any]])
assert_type(db.get_value("select 1"), Any)
assert_type(db.insert("t", {"name": "Jan"}), Any) # `returning` decides what comes back
assert_type(db.find_one("t", name="Jan"), dict[str, Any]|None)
assert_type(db.count("t"), int)
assert_type(db.tables(), list[str])
assert_type(KeyValue(db).get("mode"), Any)

async def use_async() -> None:
  adb = AsyncDatabase("sqlite", ":memory:")
  assert_type(adb, AbstractAsyncDatabase)
  assert_type(await adb.exec("delete from t"), int)
  assert_type(await adb.get_dicts("select 1"), list[dict[str, Any]])
  assert_type(await adb.insert("t", {"name": "Ola"}), Any)
  assert_type(await adb.find_one("t", name="Ola"), dict[str, Any]|None)
  async with adb.transaction() as tx: # what the caller holds matters, not the wrapper type
    assert_type(tx, AbstractAsyncDatabase)
'''

def a_client_sees_the_declared_types(tmp_path):
  """One mypy run over client code that names the type it expects from every call."""
  if find_spec("mypy") is None: pytest.skip("mypy is not installed")
  (tmp_path / "client.py").write_text(CLIENT, encoding="utf-8")
  run = subprocess.run(
    [sys.executable, "-m", "mypy", "--config-file=", "--follow-imports=silent", "client.py"],
    cwd=tmp_path, capture_output=True, text=True,
  )
  out = run.stdout + run.stderr
  # an editable install is invisible to mypy, so there is nothing to read and nothing to claim
  if "Cannot find implementation" in out: pytest.skip("no wheel-style xaeian install to read")
  assert run.returncode == 0, out
