# tests/test_wheel.py

"""
The installed package, exercised where no repository exists.

`publish.yml` installs the wheel, copies `tests/` beside it and runs from there, so whatever
`import xaeian` answers is the artifact that ships. Nothing here reads a repository file.

What is left is the packaging: every shipped module imports, the type marker is there,
the CLI answers, and the zero-dependency core works from a bare directory.
"""

import importlib
import os
import subprocess
import sys
from pathlib import Path
import pytest
import xaeian
from xaeian import MissingExtra

PKG = Path(xaeian.__file__).parent

class Wheel:
  """A class keeps these helpers out of reach of `python_functions = ["*"]` collection."""
  @staticmethod
  def modules() -> list[str]:
    """Every module the package ships, named the way an import names it."""
    names = []
    for path in sorted(PKG.rglob("*.py")):
      parts = path.relative_to(PKG).with_suffix("").parts
      if parts[-1] == "__main__": continue # a `__main__` block is run, not imported
      if parts[-1] == "__init__": parts = parts[:-1]
      names.append(".".join(("xaeian",) + parts))
    return names

def every_shipped_module_imports():
  """A subpackage dropped by `packages.find` only surfaces when someone imports it."""
  problems, absent = [], []
  for module in Wheel.modules():
    try:
      importlib.import_module(module)
    except MissingExtra as e:
      absent.append(f"{module} | {e}")
    except Exception as e:
      problems.append(f"{module} | {type(e).__name__}: {e}")
  assert not problems, "\n".join(problems)
  if absent: pytest.skip("; ".join(absent))

def the_type_marker_ships_with_the_code():
  """`py.typed` is package data: it disappears the moment the manifest stops listing it."""
  assert (PKG / "py.typed").exists(), f"py.typed is missing from {PKG}"

def the_cli_answers(tmp_path):
  """`PYTHONPATH` pins the subprocess to the package imported here, not to what is on PATH."""
  env = dict(os.environ, PYTHONPATH=str(PKG.parent), PYTHONIOENCODING="utf-8")
  done = subprocess.run([sys.executable, "-m", "xaeian", "--help"], capture_output=True,
    text=True, env=env, cwd=str(tmp_path), timeout=60)
  assert done.returncode == 0, done.stderr[-800:]
  assert "Usage: xn" in done.stdout

def the_core_works_from_a_bare_directory(tmp_path):
  """A few real calls on the zero-dependency core, with no repository file within reach."""
  from xaeian import file_context
  from xaeian.crc import crc16_modbus
  from xaeian.db import Database
  with file_context(root_path=str(tmp_path)):
    xaeian.JSON.save("state", {"ready": True})
    assert xaeian.JSON.load("state") == {"ready": True}
  frame = crc16_modbus.encode(b"\x01\x03\x00\x00\x00\x0A")
  assert crc16_modbus.decode(frame) is not None
  db = Database("sqlite", str(tmp_path / "app.db"))
  db.exec("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)")
  db.insert("t", {"name": "Jan"})
  assert db.find_one("t", name="Jan")["name"] == "Jan"
