# tests/test_readme.py

"""
The front page, executed.

`readme.md` declares the philosophy, so its claims are the ones that must not drift.
Everything checkable runs; examples needing a serial port, a display or a real PDF stay out.

Read from the checkout beside `tests/`; a wheel run has none, and `test_wheel.py` answers there.
"""

import importlib
import re
from pathlib import Path
import pytest
from xaeian import FILE, JSON, CSV, logger, split_str, generate_password
from xaeian.crc import CRC, crc16_modbus
from xaeian.db import Database
from xaeian.log import Print
from xaeian.xtime import Time

REPO = Path(__file__).resolve().parent.parent
if not (REPO / "xaeian" / "__init__.py").exists():
  # `publish.yml` copies `tests/` beside the wheel; `test_wheel.py` is what answers there
  pytest.skip("not a repository checkout", allow_module_level=True)

#-------------------------------------------------------------------------------- Zen of the readme

NAMESPACES = {"FILE": FILE, "JSON": JSON, "CSV": CSV}

def the_namespace_classes_really_are_static():
  """"`FILE`, `DIR`, `PATH`, `CSV`, `JSON` as static classes" - no `__init__`, no instances."""
  from xaeian import DIR, PATH
  for name, cls in {**NAMESPACES, "DIR": DIR, "PATH": PATH}.items():
    assert "__init__" not in vars(cls), f"{name} carries an __init__, it is not a namespace"
    assert any(isinstance(m, staticmethod) for m in vars(cls).values()), name

def crc_is_a_configured_object_not_a_namespace():
  """The readme used to list `CRC` among the static classes; it is the one that is not."""
  assert "__init__" in vars(CRC)
  assert isinstance(crc16_modbus, CRC)

def one_obvious_way_to_reach_a_level():
  """`log=` promises one vocabulary, so the readme teaches `inf`, not the stdlib spelling."""
  assert hasattr(Print(), "inf")
  assert not hasattr(Print(), "info")

#----------------------------------------------------------------------------------------- Examples

def files_take_the_extension_from_the_namespace(tmp_path):
  from xaeian import file_context
  with file_context(root_path=str(tmp_path)):
    JSON.save("config", {"debug": True, "port": 8080})
    CSV.save("users", [{"name": "Jan", "age": 30}, {"name": "Anna", "age": 25}])
    assert (tmp_path / "config.json").exists()
    assert (tmp_path / "users.csv").exists()
    assert JSON.load("config") == {"debug": True, "port": 8080}

def time_parses_anything_and_adds_strings():
  t = Time("2025-03-01") + "2w 3d"
  assert t.to("%Y-%m-%d") == "2025-03-18"
  assert t.round("w").strftime("%A") == "Monday"
  assert t.round("w").to("%Y-%m-%d") == "2025-03-17"

def crc_round_trips_a_modbus_frame():
  frame = crc16_modbus.encode(b"\x01\x03\x00\x00\x00\x0A")
  assert crc16_modbus.decode(frame) is not None
  assert crc16_modbus.decode(frame[:-1] + b"\x00") is None

def string_tools_behave_as_advertised():
  assert split_str('a,"b,c",d', sep=",") == ["a", '"b,c"', "d"]
  assert len(generate_password(16)) == 16

def the_database_example_runs(tmp_path):
  """It used to show a sync `Database` under `async with`, which raises `TypeError`."""
  db = Database("sqlite", str(tmp_path / "app.db"))
  db.exec("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, verified INT, settings TEXT)")
  db.insert("users", {"name": "Jan", "settings": {"theme": "dark"}})
  assert len(db.find("users", order="name", limit=10)) == 1
  with db.transaction():
    assert db.update("users", {"verified": True}, "id = ?", 1) == 1

def binary_structs_round_trip():
  from xaeian.cstruct import Struct, Field, Bitfield, Type, Endian
  from xaeian.crc import crc32_iso
  pkt = Struct(endian=Endian.little, crc=crc32_iso)
  pkt.add(
    Field(Type.uint32, "timestamp", "s"),
    Bitfield("flags", [("enabled", 1), ("error", 1), ("mode", 6)]),
    Field(Type.float, "temperature", "°C"),
  )
  data = {"timestamp": 1234567890, "flags": {"enabled": 1, "error": 0, "mode": 5},
    "temperature": 23.5}
  assert pkt.decode(pkt.encode(data))["timestamp"] == 1234567890

def logging_is_colored_and_rotating(tmp_path):
  log = logger("readme_example", file=str(tmp_path / "app.log"), stream=False)
  log.inf("started")
  assert "INF started" in (tmp_path / "app.log").read_text(encoding="utf-8")

#------------------------------------------------------------------------------------- Module table

def every_module_the_readme_lists_imports():
  listed = ["files", "table", "xstring", "xtime", "colors", "log", "crc", "cstruct", "cmd",
    "serial", "plot", "dsp", "db", "media", "eda", "net", "cli"]
  for name in listed:
    importlib.import_module(f"xaeian.{name}")

def the_core_really_has_zero_dependencies():
  """"Zero dependencies for core" - the promise on line one."""
  toml = (REPO / "pyproject.toml").read_text(encoding="utf-8")
  block = re.search(r"^dependencies = (\[.*?\])$", toml, re.M)
  assert block and block.group(1) == "[]"

#---------------------------------------------------------------------- The text, bound to the code

class Front:
  """A class keeps these helpers out of reach of `python_functions = ["*"]` collection."""
  path = REPO / "readme.md"

  @staticmethod
  def text() -> str:
    """Read per test, so a front page missing from the checkout fails instead of skipping."""
    return Front.path.read_text(encoding="utf-8")

def the_front_page_is_present():
  """Its absence used to skip every check below it, which is how the wheel run went quiet."""
  assert Front.path.exists(), f"the front page is missing from the checkout: {Front.path}"

def the_static_class_bullet_names_only_real_namespaces():
  """Whatever the philosophy bullet lists must actually have no `__init__`."""
  import xaeian
  line = next(l for l in Front.text().splitlines() if "as static classes" in l)
  for name in re.findall(r"`([A-Z]+)`", line):
    cls = getattr(xaeian, name)
    assert "__init__" not in vars(cls), f"readme calls {name} a static class, it is not"

def the_logging_example_calls_a_method_that_exists():
  """The readme teaches one vocabulary; a name `Print` lacks is a name `log=` cannot promise."""
  line = next(l for l in Front.text().splitlines() if l.startswith("log."))
  method = re.match(r"log\.(\w+)\(", line).group(1)
  assert hasattr(Print(), method), f"readme teaches log.{method}(), Print has no such name"

def the_time_example_states_the_value_it_produces():
  """The iso comment once carried the rounded date instead of the value on that line."""
  text = Front.text()
  expr = re.search(r'^t = Time\("([\d-]+)"\) \+ "(.+?)"$', text, re.M)
  shown = re.search(r'^t\.to\("iso"\) # "(.+?)"$', text, re.M)
  assert expr and shown, "the Time example changed shape"
  assert (Time(expr.group(1)) + expr.group(2)).to("iso") == shown.group(1)

def the_database_example_does_not_await_a_sync_object():
  """
  `async with` on a sync `Database` raises TypeError.

  It stood on the front page for four releases without anyone running it.
  """
  text = Front.text()
  block = text[text.index("db = Database("):text.index("# Serial recorders")]
  assert "async with" not in block, "the sync example uses `async with` again"
