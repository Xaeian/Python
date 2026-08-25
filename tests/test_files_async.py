# tests/test_files_async.py

"""
`files_async` against `files`: one scenario, run through both.

The async namespaces mirror the sync ones by hand, so the fault to guard against is drift
between two spellings of the same signature. Every scenario runs twice against each layer,
once with positional arguments and once with keywords, because a positionally forwarded
wrapper keeps working while silently binding the wrong parameter.
"""

import asyncio
import inspect
import pytest
import xaeian.files as sync_files
import xaeian.files_async as async_files
from xaeian.files import Files
from xaeian.files_async import AsyncFiles
from files_contract import SCENARIOS

# Called without `await`: a generator is driven by the caller, a pure helper has no IO to wait
# for. Both are still present, so one surface answers for both layers.
STAYS_SYNC = {"iter_files", "iter_lines", "format", "parse", "smart"}

NAMESPACES = ["DIR", "FILE", "INI", "CSV", "JSON", "YAML"]

#-------------------------------------------------------------------------------- surface agreement

@pytest.mark.parametrize("ns", NAMESPACES)
def the_async_surface_mirrors_the_sync_one(ns):
  s = {m for m in vars(getattr(sync_files, ns)) if not m.startswith("_")}
  a = {m for m in vars(getattr(async_files, ns)) if not m.startswith("_")}
  assert s == a, f"{ns}: only sync has {sorted(s - a)}, only async has {sorted(a - s)}"

@pytest.mark.parametrize("ns", NAMESPACES)
def everything_with_io_is_awaited_and_nothing_else_is(ns):
  cls = getattr(async_files, ns)
  for name in (m for m in vars(cls) if not m.startswith("_")):
    method = getattr(cls, name)
    if not callable(method): continue
    awaited = inspect.iscoroutinefunction(method)
    assert awaited is (name not in STAYS_SYNC), f"{ns}.{name}: awaited={awaited}"

@pytest.mark.parametrize("ns", NAMESPACES)
def the_awaited_twin_keeps_the_sync_signature(ns):
  """`functools.wraps` carries it over, so a caller reads one signature, not two."""
  sync_cls, async_cls = getattr(sync_files, ns), getattr(async_files, ns)
  for name in (m for m in vars(sync_cls) if not m.startswith("_")):
    plain = getattr(sync_cls, name)
    if not callable(plain): continue
    assert inspect.signature(plain) == inspect.signature(getattr(async_cls, name)), f"{ns}.{name}"

def the_bound_wrappers_mirror_each_other(tmp_path):
  plain = {k for k in vars(Files(root_path=str(tmp_path))) if not k.startswith("_")}
  awaited = {k for k in vars(AsyncFiles(root_path=str(tmp_path))) if not k.startswith("_")}
  assert plain == awaited
  assert AsyncFiles(root_path=str(tmp_path)).YAML is not None # bound on demand, on both sides

def the_bound_layer_offloads_by_the_same_rule(tmp_path):
  fs = AsyncFiles(root_path=str(tmp_path))
  assert inspect.iscoroutinefunction(fs.FILE.save)
  assert not inspect.iscoroutinefunction(fs.INI.format)
  assert not inspect.iscoroutinefunction(fs.DIR.iter_files)

#------------------------------------------------------------------------------------- the contract

@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s.__name__ for s in SCENARIOS])
@pytest.mark.parametrize("kw", [False, True], ids=["positional", "keyword"])
def the_async_layer_answers_like_the_sync_one(scenario, kw, tmp_path):
  plain = asyncio.run(scenario(sync_files, str(tmp_path / "sync"), kw))
  awaited = asyncio.run(scenario(async_files, str(tmp_path / "async"), kw))
  assert plain == awaited

@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s.__name__ for s in SCENARIOS])
def the_bound_layers_answer_alike(scenario, tmp_path):
  plain = asyncio.run(scenario(Files(root_path=str(tmp_path / "s")), ".", False))
  awaited = asyncio.run(scenario(AsyncFiles(root_path=str(tmp_path / "a")), ".", False))
  assert plain == awaited
