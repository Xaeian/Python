# tests/conftest.py

"""
Collection rules and the import root for the whole suite.

`python_functions = ["*"]` would collect any function a test file imports,
so collection is narrowed to the ones each module defines itself.
"""

import inspect
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# A source tree beside the tests is the code under test, whatever wheel is also installed.
# The `pytest` console script leaves the cwd off `sys.path` and would import the wheel instead.
# `publish.yml` copies `tests/` away from any source tree, and there the wheel answers.
if (ROOT / "xaeian" / "__init__.py").exists():
  sys.path.insert(0, str(ROOT))

def pytest_pycollect_makeitem(collector, name, obj):
  if inspect.isfunction(obj) and obj.__module__ != collector.obj.__name__:
    return [] # ignore library functions imported into the test file

@pytest.fixture(autouse=True, scope="session")
def the_suite_leaves_no_droppings():
  """A test writing outside `tmp_path` once left `u.csv` in the repo root."""
  before = {p.name for p in ROOT.iterdir()}
  yield
  new = {p.name for p in ROOT.iterdir()} - before - {".pytest_cache", "__pycache__"}
  assert not new, f"the test run dropped files in the repo root: {sorted(new)}"
