# tests/files_contract.py

"""
The scenario table `test_files_async.py` runs through both layers.

It lives outside a `test_*` module because `python_functions = ["*"]` would otherwise collect
every helper here as a test case.
"""

import inspect
import pytest

async def call(fn, *args, **kwargs):
  """Invoke a namespace method, awaiting it only when the layer under test returns a coroutine."""
  out = fn(*args, **kwargs)
  return await out if inspect.isawaitable(out) else out

async def bind(fn, kw:bool, names:tuple, *args):
  """
  Invoke `fn` with `args` bound positionally or by the given parameter names.

  Both styles have to reach the same parameters. A wrapper that forwards positionally passes
  the keyword run and fails this one the moment the sync signature reorders.
  """
  if kw: return await call(fn, **dict(zip(names, args)))
  return await call(fn, *args)

async def file_round_trip(ns, root, kw):
  """save → append → read back → measure → remove."""
  FILE, DIR = ns.FILE, ns.DIR
  out = []
  await bind(DIR.ensure, kw, ("path",), f"{root}/sub/")
  await bind(FILE.save, kw, ("path", "content"), f"{root}/a.txt", "one\n")
  await bind(FILE.append, kw, ("path", "content"), f"{root}/a.txt", "two\n")
  await bind(FILE.append_line, kw, ("path", "line"), f"{root}/a.txt", "three")
  out.append(await bind(FILE.load, kw, ("path",), f"{root}/a.txt"))
  out.append(await bind(FILE.load_lines, kw, ("path",), f"{root}/a.txt"))
  out.append(await bind(FILE.size, kw, ("path",), f"{root}/a.txt"))
  out.append(await bind(FILE.hash, kw, ("path", "algo"), f"{root}/a.txt", "md5"))
  out.append(await bind(FILE.exists, kw, ("path",), f"{root}/a.txt"))
  await bind(FILE.save_lines, kw, ("path", "lines"), f"{root}/b.txt", ["x\n", "y\n"])
  out.append(await bind(FILE.load_lines, kw, ("path",), f"{root}/b.txt"))
  out.append(await bind(FILE.remove, kw, ("path",), f"{root}/b.txt"))
  out.append(await bind(FILE.exists, kw, ("path",), f"{root}/b.txt"))
  return out

async def dir_round_trip(ns, root, kw):
  """ensure → list → copy → move → zip → unzip → remove."""
  FILE, DIR = ns.FILE, ns.DIR
  out = []
  await call(DIR.ensure, f"{root}/tree/inner/")
  await call(FILE.save, f"{root}/tree/one.txt", "1")
  await call(FILE.save, f"{root}/tree/inner/two.py", "2")
  out.append(await bind(DIR.file_list, kw, ("path", "exts", "match", "blacklist", "shape"),
    f"{root}/tree", [".txt"], None, None, "name"))
  out.append(await bind(DIR.folder_list, kw, ("path", "deep", "shape"),
    f"{root}/tree", False, "name"))
  await bind(DIR.copy, kw, ("src", "dst"), f"{root}/tree", f"{root}/copy")
  out.append(sorted(await call(DIR.file_list, f"{root}/copy", shape="name")))
  await bind(DIR.move, kw, ("src", "dst"), f"{root}/copy", f"{root}/moved")
  out.append(await call(DIR.file_list, f"{root}/moved", shape="name") != [])
  zipped = await bind(DIR.zip, kw, ("path", "zip_output"), f"{root}/tree", f"{root}/tree.zip")
  out.append(zipped.endswith("tree.zip"))
  await bind(DIR.unzip, kw, ("path", "output"), f"{root}/tree.zip", f"{root}/back")
  out.append(sorted(await call(DIR.file_list, f"{root}/back", shape="name")))
  out.append(await bind(DIR.remove, kw, ("path", "force"), f"{root}/moved", True))
  return out

async def json_round_trip(ns, root, kw):
  JSON = ns.JSON
  data = {"debug": True, "port": 8080, "tags": ["a", "b"]}
  out = []
  await bind(JSON.save, kw, ("path", "content"), f"{root}/c", data)
  out.append(await bind(JSON.load, kw, ("path",), f"{root}/c"))
  out.append(await bind(JSON.load, kw, ("path", "otherwise"), f"{root}/missing", "fallback"))
  await bind(JSON.save_pretty, kw, ("path", "content", "indent"), f"{root}/p", data, 4)
  out.append(await call(JSON.load, f"{root}/p"))
  await bind(JSON.save_smart, kw, ("path", "content", "max_line"), f"{root}/s", data, 40)
  out.append(await call(JSON.load, f"{root}/s"))
  out.append(await bind(JSON.smart, kw, ("obj",), data))
  return out

async def csv_round_trip(ns, root, kw):
  CSV = ns.CSV
  rows = [{"name": "Jan", "age": 30}, {"name": "Anna", "age": 25}]
  out = []
  await bind(CSV.save, kw, ("path", "data"), f"{root}/u", rows)
  out.append(await bind(CSV.load, kw, ("path", "delimiter", "types"),
    f"{root}/u", ",", {"age": int}))
  await bind(CSV.add_row, kw, ("path", "datarow"), f"{root}/u", {"name": "Ola", "age": 41})
  out.append(await call(CSV.load, f"{root}/u"))
  out.append(await bind(CSV.load_raw, kw, ("path",), f"{root}/u"))
  out.append(await bind(CSV.load_vectors, kw, ("path",), f"{root}/u"))
  await call(CSV.save_vectors, f"{root}/v", [1, 2], [3, 4], header=["a", "b"])
  out.append(await call(CSV.load_raw, f"{root}/v"))
  return out

async def ini_round_trip(ns, root, kw):
  INI = ns.INI
  data = {"main": {"key": "value", "num": 42, "flag": True}}
  out = []
  await bind(INI.save, kw, ("path", "data"), f"{root}/cfg", data)
  out.append(await bind(INI.load, kw, ("path",), f"{root}/cfg"))
  out.append(await bind(INI.format, kw, ("value",), 42))
  out.append(await bind(INI.parse, kw, ("text",), "true"))
  return out

async def yaml_round_trip(ns, root, kw):
  YAML = getattr(ns, "YAML", None)
  if YAML is None: pytest.skip("pyyaml not installed")
  data = {"debug": True, "list": [1, 2]}
  await bind(YAML.save, kw, ("path", "content"), f"{root}/y", data)
  return [await bind(YAML.load, kw, ("path",), f"{root}/y")]

SCENARIOS = [file_round_trip, dir_round_trip, json_round_trip, csv_round_trip,
  ini_round_trip, yaml_round_trip]
