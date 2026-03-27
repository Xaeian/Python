# xaeian/files/__init__.py

"""
File operations with context-based path resolution.

Provides namespace classes for common file operations:
- `PATH`: path manipulation and resolution
- `DIR`: directory operations (create, remove, list, zip)
- `FILE`: file read/write/append
- `INI`: INI config files
- `CSV`: CSV data files
- `JSON`: JSON data files
- `YAML`: YAML data files (requires `pyyaml`)

Global configuration via context manager `file_context()`.
Object-oriented access via `Files(root_path=...)`.
"""

from .config import Config, get_context, set_context, file_context
from .path import PATH
from .dir import DIR
from .file import FILE
from .ini import INI
from .csv import CSV
from .json import JSON
from .bound import _BoundNamespace, _NAMESPACE_CLASSES, Files

__all__ = [
  "Config", "get_context", "set_context", "file_context",
  "PATH", "DIR", "FILE", "INI", "CSV", "JSON",
  "_BoundNamespace", "_NAMESPACE_CLASSES", "Files",
]

try:
  from .yaml import YAML
  __all__ += ["YAML"]
except ImportError:
  pass

#---------------------------------------------------------------------------------------- Tests

if __name__ == "__main__":
  import tempfile
  with tempfile.TemporaryDirectory() as tmp:
    fs = Files(root_path=tmp)
    fs.FILE.save("test.txt", "Hello!")
    print("load:", fs.FILE.load("test.txt"))
    fs.FILE.append("test.txt", " World!")
    print("append:", fs.FILE.load("test.txt"))
    print("hash:", fs.FILE.hash("test.txt", algo="md5"))
    print()
    fs.JSON.save("cfg", {"debug": True, "port": 8080})
    print("json:", fs.JSON.load("cfg"))
    print()
    fs.CSV.save("data", [{"a": 1, "b": 2}, {"a": 3, "b": 4}])
    print("csv:", fs.CSV.load("data", types={"a": int, "b": int}))
    print()
    fs.INI.save("settings", {"main": {"key": "value", "num": 42}})
    print("ini:", fs.INI.load("settings"))
    print()
    try:
      fs.YAML.save("config", {"debug": True, "port": 8080})
      print("yaml:", fs.YAML.load("config"))
    except (ImportError, AttributeError) as e:
      print(f"yaml: skipped ({e})")
    print()
    fs.DIR.ensure("sub/dir/")
    fs.FILE.save("sub/f1.txt", "1")
    fs.FILE.save("sub/f2.txt", "2")
    fs.FILE.save("sub/dir/f3.py", "3")
    print("files:", fs.DIR.file_list("sub", exts=[".txt"], basename=True))
    print()
    print("expand:", fs.PATH.expand("~/test"))
    print("exists:", fs.PATH.exists(tmp))
    print("match:", fs.PATH.match("test.py", "*.py"))
    print()
    with file_context(root_path=tmp):
      FILE.save("ctx_test.txt", "context manager works")
      print("with:", FILE.load("ctx_test.txt"))
