# tests/test_readmes.py

"""
The package readmes, held against the code.

Read from the checkout beside `tests/`, never from the installed package: the wheel ships none.
Every fenced block parses, every import it shows runs, and every documented call binds.

Blocks are read with `ast`, so a `=` inside an SQL string is not mistaken for a keyword,
and a method taking `**kwargs` accepts any keyword the readme shows.
"""

import ast
import inspect
import re
from pathlib import Path
import pytest
import xaeian
import xaeian.db
import xaeian.eda
import xaeian.eda.fp
import xaeian.eda.sym
import xaeian.net
import xaeian.serial
from xaeian import MissingExtra

REPO = Path(__file__).resolve().parent.parent
if not (REPO / "xaeian" / "__init__.py").exists():
  # `publish.yml` copies `tests/` beside the wheel; `test_wheel.py` is what answers there
  pytest.skip("not a repository checkout", allow_module_level=True)

# variable name → the class its readme examples call it on; async blocks resolve separately
OBJECTS = {
  "xaeian/db/readme.md": {"db": xaeian.db.SqliteDatabase, "kv": xaeian.db.KeyValue},
  "xaeian/files/readme.md": {ns: getattr(xaeian, ns) for ns in
    ("PATH", "DIR", "FILE", "JSON", "CSV", "INI")},
  "xaeian/serial/readme.md": {"port": xaeian.serial.SerialPort, "rec": xaeian.serial.Recorder,
    "sh": xaeian.serial.Shell},
  "xaeian/net/readme.md": {"r": xaeian.net.SFTP, "sftp": xaeian.net.SFTP, "ftp": xaeian.net.FTP,
    "s3": xaeian.net.S3},
  "xaeian/eda/readme.md": {"kc": xaeian.eda.KiCad, "sim": xaeian.eda.Simulation,
    "fp": xaeian.eda.fp.Footprint, "sym": xaeian.eda.sym.Symbol, "lib": xaeian.eda.sym.SymbolLib},
  "xaeian/media/readme.md": {},
  "xaeian/cli/readme.md": {},
  "xaeian/readme.md": {},
}

ASYNC_DB = {"db": xaeian.db.SqliteAsyncDatabase, "kv": xaeian.db.AsyncKeyValue}

class Lens:
  """A class keeps these helpers out of reach of `python_functions = ["*"]` collection."""
  @staticmethod
  def blocks(doc:str) -> list[str]:
    text = (REPO / doc).read_text(encoding="utf-8")
    return re.findall(r"```py\n(.*?)```", text, re.S)

  @staticmethod
  def parse(block:str) -> ast.Module:
    """Async examples use top-level `await`, which plain `ast.parse` refuses."""
    try:
      return ast.parse(block)
    except SyntaxError:
      wrapped = "async def _doc():\n" + "".join(f"  {l}\n" for l in block.split("\n"))
      return ast.parse(wrapped)

  @staticmethod
  def imports(doc:str) -> dict[str, ast.stmt]:
    """Every distinct import the doc shows, source line → the node that runs it."""
    found = {}
    for block in Lens.blocks(doc):
      for node in ast.walk(Lens.parse(block)):
        if isinstance(node, ast.Import | ast.ImportFrom):
          found.setdefault(ast.unparse(node), node)
    return found

def every_readme_in_the_package_is_on_the_list():
  """A doc no test names is a doc nobody checks, and a missing one fails instead of skipping."""
  found = {p.relative_to(REPO).as_posix() for p in (REPO / "xaeian").rglob("readme.md")}
  assert found == set(OBJECTS), (
    f"unlisted: {sorted(found - set(OBJECTS))}, missing: {sorted(set(OBJECTS) - found)}")

@pytest.mark.parametrize("doc", sorted(OBJECTS), ids=lambda d: d.split("/")[-2])
def every_fenced_block_parses(doc):
  for n, block in enumerate(Lens.blocks(doc)):
    assert Lens.parse(block) is not None, f"{doc}, block {n}"

@pytest.mark.parametrize("doc", sorted(OBJECTS), ids=lambda d: d.split("/")[-2])
def every_documented_import_runs(doc):
  """Parsing proves the shape; only running proves the name is still there to import."""
  problems, absent = [], []
  for source, node in Lens.imports(doc).items():
    try:
      exec(compile(ast.Module(body=[node], type_ignores=[]), doc, "exec"), {})
    except MissingExtra as e:
      absent.append(f"{source} | {e}")
    except Exception as e:
      problems.append(f"{source} | {type(e).__name__}: {e}")
  assert not problems, "\n".join(problems)
  if absent: pytest.skip("; ".join(absent))

@pytest.mark.parametrize("doc", sorted(OBJECTS), ids=lambda d: d.split("/")[-2])
def every_documented_call_binds(doc):
  problems = []
  for block in Lens.blocks(doc):
    objects = dict(OBJECTS[doc])
    if "AsyncDatabase(" in block or "AsyncKeyValue(" in block or "await " in block:
      objects.update(ASYNC_DB)
    for node in ast.walk(Lens.parse(block)):
      if not isinstance(node, ast.Call): continue
      fn = node.func
      if not (isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name)): continue
      cls = objects.get(fn.value.id)
      if cls is None: continue
      method = getattr(cls, fn.attr, None)
      if method is None:
        problems.append(f"{fn.value.id}.{fn.attr}() does not exist on {cls.__name__}")
        continue
      try:
        params = inspect.signature(method).parameters
      except (TypeError, ValueError):
        continue
      takes_any = any(p.kind is p.VAR_KEYWORD for p in params.values())
      for kw in node.keywords:
        if kw.arg and not takes_any and kw.arg not in params:
          problems.append(f"{fn.value.id}.{fn.attr}({kw.arg}=...) - no such parameter")
  assert not problems, "\n".join(problems)
