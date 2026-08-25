# tests/test_exports.py

"""Public surface: one export policy across the package, and no swallowed faults."""

import importlib
import os
import pickle
import subprocess
import sys
from pathlib import Path
import pytest
import xaeian
from xaeian import MissingExtra

PACKAGES = [
  "xaeian", "xaeian.files", "xaeian.db", "xaeian.net", "xaeian.media", "xaeian.eda",
  "xaeian.serial", "xaeian.files_async",
]

def every_exported_name_resolves():
  for name in PACKAGES:
    mod = importlib.import_module(name)
    for attr in getattr(mod, "__all__", []):
      try: value = getattr(mod, attr)
      except MissingExtra: continue # a lazy export whose extra is not installed here
      assert value is not None, f"{name}.{attr} is None instead of absent"

def no_private_name_is_exported():
  for name in PACKAGES:
    mod = importlib.import_module(name)
    private = [a for a in getattr(mod, "__all__", []) if a.startswith("_") and a != "__version__"]
    assert not private, f"{name}.__all__ exports private names: {private}"

BROKEN_DEPENDENCY = '''
import sys, importlib.abc

class Sabotage(importlib.abc.MetaPathFinder):
  """Stand in for a dependency that is installed but raises on import."""
  def find_spec(self, name, path, target=None):
    if name == "matplotlib" or name.startswith("matplotlib."):
      raise RuntimeError("matplotlib is broken")
    return None

sys.meta_path.insert(0, Sabotage())
import xaeian
print("imported")
xaeian.Plot
'''

def a_broken_optional_module_is_not_mistaken_for_a_missing_one(tmp_path):
  """A fault inside an optional stack must reach the caller, not vanish as "extra absent"."""
  script = tmp_path / "sabotage.py"
  script.write_text(BROKEN_DEPENDENCY, encoding="utf-8")
  env = dict(os.environ, PYTHONPATH=str(Path(xaeian.__file__).parent.parent))
  done = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, env=env)
  assert "imported" in done.stdout, "the core import reached into matplotlib"
  assert done.returncode != 0, "xaeian.Plot swallowed a broken optional dependency"
  assert "matplotlib is broken" in done.stderr

MISSING_TRANSITIVE = '''
import sys, importlib.abc

class Sabotage(importlib.abc.MetaPathFinder):
  """paramiko is installed; something paramiko itself imports is not."""
  def find_spec(self, name, path, target=None):
    if name == "paramiko":
      raise ModuleNotFoundError("No module named 'cryptography'", name="cryptography")
    return None

sys.meta_path.insert(0, Sabotage())
import xaeian.net.sftp
'''

def a_dependency_broken_deeper_down_is_named_for_what_is_really_missing(tmp_path):
  """
  The guard answered any `ModuleNotFoundError` with "install the extra", so a user whose
  paramiko could not find `cryptography` was sent to reinstall what they already had.
  """
  script = tmp_path / "transitive.py"
  script.write_text(MISSING_TRANSITIVE, encoding="utf-8")
  env = dict(os.environ, PYTHONPATH=str(Path(xaeian.__file__).parent.parent))
  done = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, env=env)
  assert done.returncode != 0
  assert "cryptography" in done.stderr, done.stderr[-400:]
  assert "pip install xaeian[sftp]" not in done.stderr

def missing_extra_is_an_import_error():
  assert issubclass(MissingExtra, ImportError)

def optional_guards_raise_missing_extra(monkeypatch):
  """Hiding an extra's dependency yields MissingExtra, so a package `__init__` can skip it."""
  monkeypatch.setitem(sys.modules, "yaml", None)
  for mod in list(sys.modules):
    if mod.startswith("xaeian.files.yaml"): monkeypatch.delitem(sys.modules, mod)
  with pytest.raises(ImportError):
    importlib.import_module("xaeian.files.yaml")

#----------------------------------------------------------------------------------- missing extras

HIDEABLE = ["yaml", "pytz", "serial", "matplotlib", "scipy", "paramiko", "pymysql", "PIL"]

HIDE = '''
import sys, importlib.abc

class Hide(importlib.abc.MetaPathFinder):
  """Pretend one package is not installed."""
  def find_spec(self, name, path, target=None):
    if name == {pkg!r} or name.startswith({pkg!r} + "."):
      raise ModuleNotFoundError("hidden", name={pkg!r})
    return None

sys.meta_path.insert(0, Hide())
import xaeian
print(len(xaeian.__all__))
'''

@pytest.mark.parametrize("pkg", HIDEABLE)
def importing_the_package_survives_a_missing_extra(pkg, tmp_path):
  """
  "Zero dependencies for core" is the promise on line one of the readme.

  Every optional name is served by `xaeian.__getattr__`, so hiding a package changes neither
  the import nor `__all__`. The count pins the second half: a surface that tracks whatever
  happens to be installed is a surface nobody can document.
  """
  script = tmp_path / f"hide_{pkg}.py"
  script.write_text(HIDE.format(pkg=pkg), encoding="utf-8")
  env = dict(os.environ, PYTHONPATH=str(Path(xaeian.__file__).parent.parent))
  done = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, env=env)
  assert done.returncode == 0, f"import xaeian died without {pkg}:\n{done.stderr[-600:]}"
  assert int(done.stdout.strip()) == len(xaeian.__all__), f"__all__ shrank without {pkg}"

#------------------------------------------------------------------------------------- lazy exports

# `yaml` is absent from the list on purpose: `files.bound` still imports it for `Files.YAML`
HEAVY = ("numpy", "scipy", "matplotlib", "PIL", "serial", "pytz")

CORE_ONLY = '''
import sys
import xaeian
print(",".join(m for m in {heavy!r} if m in sys.modules))
'''

def the_core_import_loads_no_heavy_dependency(tmp_path):
  """The stacks behind the extras arrive when a lazy name is first used, never before."""
  script = tmp_path / "core_only.py"
  script.write_text(CORE_ONLY.format(heavy=HEAVY), encoding="utf-8")
  env = dict(os.environ, PYTHONPATH=str(Path(xaeian.__file__).parent.parent))
  done = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, env=env)
  assert done.returncode == 0, done.stderr[-600:]
  assert not done.stdout.strip(), f"import xaeian pulled in {done.stdout.strip()}"

def a_lazy_name_is_the_real_object_not_a_proxy():
  """Pickle and `repr` read `__module__`/`__qualname__`, so the export has to be the class."""
  from xaeian.plot import Plot
  assert xaeian.Plot is Plot
  assert xaeian.Plot.__module__ == "xaeian.plot"
  assert pickle.loads(pickle.dumps(xaeian.Plot)) is Plot

def an_unknown_name_is_a_plain_attribute_error():
  """`__getattr__` must not answer for names it does not own, or submodule import breaks."""
  with pytest.raises(AttributeError):
    xaeian.no_such_name
  from xaeian import plot
  assert plot.Plot is xaeian.Plot

def dir_covers_the_whole_public_surface():
  """Completion reads `__dir__`, which sees only what has been loaded unless `__all__` joins in."""
  listed = dir(xaeian)
  missing = [name for name in xaeian.__all__ if name not in listed]
  assert not missing, f"dir(xaeian) hides {missing}"

