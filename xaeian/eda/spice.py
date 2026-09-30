# xaeian/eda/spice.py

"""
ngspice runner for template netlists: substitution, batch runs, parsing, CSV cache, sweeps.

`{name}.cir` holds the circuit, the optional `{name}.sp` its control block,
which writes the results with `wrdata {FILE} v(out) i(vcc)`.
The runner turns on `wr_singlescale` and `wr_vecnames` inside that block,
so every column comes back under the name ngspice gives it: `{"TIME": [...], "V(OUT)": [...]}`.
Requires the `ngspice` binary on PATH or an explicit path.

Example:
  >>> sim = Simulation("inverter", lib="C:/Kicad/Spice")
  >>> data = sim.run(RLOAD="2.2k")
  >>> results = sim.sweep(RLOAD=["1k", "2.2k", "4.7k"])
"""

import os, re, glob, hashlib, itertools
from concurrent.futures import ThreadPoolExecutor

from ..cmd import run as cmd_run, which
from ..files import FILE, DIR, CSV, PATH
from ..xstring import replace_map
from ..log import Print

#------------------------------------------------------------------------------------ Output parser

def parse_output(path:str) -> dict[str, list[float]]:
  """
  `wrdata` output → `{NAME: values}`, named by the header `wr_vecnames` writes, uppercased.

  A complex vector (AC) fills two columns under one name: `REAL(V(OUT))` and `IMAG(V(OUT))`.
  A header repeated further down (`appendwrite`) adds only the columns not read yet,
  so every block after the first drops its copy of the scale.
  """
  data: dict[str, list[float]] = {}
  targets: list[list[float]|None] = []
  for line in str(FILE.load(path)).splitlines():
    fields = line.split()
    if not fields: continue
    try:
      values = [float(f) for f in fields]
    except ValueError: # a header: the names of this block's columns
      targets = [None if name in data else data.setdefault(name, []) for name in _names(fields)]
      continue
    for target, value in zip(targets, values):
      if target is not None: target.append(value)
  if not data:
    raise ValueError(f"No named columns in {path}: `wrdata` names them under `wr_vecnames`")
  return data

def _names(header:list[str]) -> list[str]:
  """Column names of one header, uppercased; a name written twice in a row is complex."""
  names = [h.upper() for h in header]
  out = []
  for i, name in enumerate(names):
    if i + 1 < len(names) and names[i + 1] == name: out.append(f"REAL({name})")
    elif i and names[i - 1] == name: out.append(f"IMAG({name})")
    else: out.append(name)
  return out

#--------------------------------------------------------------------------------- Template loading

def _load_template(name:str, path:str, lib:str) -> str:
  """
  `{path}/{name}.cir` with its `.include` files inlined, then `{name}.sp` appended.

  `lib` fills `{LIB}` and `{LSM}`. An include resolves against `path`:
  the rendered netlist runs from `work_dir`, where a relative one would miss.
  A trailing `.end` goes, so the appended commands stay inside the netlist,
  and the `.control` block is told to name its `wrdata` columns and write the scale once.
  """
  cir = str(FILE.load(os.path.join(path, f"{name}.cir"))).rstrip()
  if cir.lower().endswith(".end"): cir = cir[:-4]
  cir = cir.replace("{LSM}", lib).replace("{LIB}", lib)
  for line in cir.splitlines():
    words = line.split(None, 1)
    if len(words) < 2 or words[0].lower() != ".include": continue
    inc = os.path.join(path, words[1].strip().strip("\"'"))
    if os.path.isfile(inc): cir = cir.replace(line, str(FILE.load(inc)).strip())
  sp = os.path.join(path, f"{name}.sp")
  if os.path.exists(sp): cir += "\n" + str(FILE.load(sp))
  named = r"\1\nset wr_singlescale\nset wr_vecnames"
  return re.sub(r"(?im)^(\s*\.control\b.*)$", named, cir, count=1)

#--------------------------------------------------------------------------------- Simulation class

_work_seq = itertools.count()

def _run_key(params:dict, netlist:str="") -> str:
  """
  Stable identity of one run: a readable prefix, then the digest that carries it.

  The digest covers the netlist too, so an edited `.cir` misses the cache instead of replaying.
  It reads a form where every part states its own length,
  so no two runs can serialise alike.
  A plain join gives no such promise: `{"AB": "C"}` and `{"A": "BC"}` both read `ABC`,
  and would share one cache file under it.
  The prefix only makes a listing readable, so it may drop characters and be cut short.
  """
  pairs = sorted((str(k), str(v)) for k, v in params.items())
  canon = f"{len(netlist)}:{netlist}" + "".join(f"{len(k)}:{k}:{len(v)}:{v}:" for k, v in pairs)
  digest = hashlib.sha1(canon.encode("utf-8")).hexdigest()[:12]
  prefix = re.sub(r"[^A-Za-z0-9._-]", "", "_".join(k + v for k, v in pairs))[:48] or "run"
  return f"{prefix}-{digest}"

def _work_id(key:str) -> str:
  """
  Working-file stem for one call: the run key plus a token no call in flight repeats.

  Runs of the same parameters share one cache entry by design,
  so `key` alone would point two of them at one `.cir` and one `.out`
  while ngspice still holds them open.
  """
  return f"{key}-{os.getpid()}-{next(_work_seq)}"

class Simulation:
  """
  Runner bound to one circuit template, with optional CSV caching.

  Loads `{name}.cir` + `{name}.sp` from `path`, substitutes placeholders like `{RLOAD}`,
  runs ngspice in batch mode and parses what `wrdata {FILE}` wrote.

  Args:
    name: Circuit name, the only `.cir` in `path` when `None`.
    path: Directory holding `{name}.cir` and the optional `{name}.sp`.
    lib: Spice model library path, fills `{LIB}` and `{LSM}` in the netlist.
    params: Default placeholder values, overridable per run.
    ngspice: Binary path, resolved from PATH when `None`.
    work_dir: Temp files and cache, defaults to `path`.
    rename: Column → new name, applied to every result; parsed columns are uppercase.
    scale: Per-column multipliers, applied after `rename`.
    timeout: Seconds per simulation.
  """
  def __init__(
    self,
    name:str|None = None,
    path:str = "./",
    lib:str = "",
    params:dict[str, str]|None = None,
    ngspice:str|None = None,
    work_dir:str|None = None,
    rename:dict[str, str]|None = None,
    scale:dict[str, float]|None = None,
    timeout:int = 300,
    verbose:bool = True,
  ) -> None:
    self.path = path
    self.lib = lib
    self.params = params or {}
    self.rename = rename or {}
    self.scale = scale or {}
    self.timeout = timeout
    self.verbose = verbose
    self._print = Print()
    if name is None:
      found = sorted(glob.glob(os.path.join(path, "*.cir")))
      if not found: raise FileNotFoundError(f"No .cir file in {path}")
      if len(found) > 1: raise ValueError(f"Several .cir files in {path}: pass name=")
      name = PATH.stem(found[0])
    self.name = name
    ngspice = ngspice or which("ngspice")
    if not ngspice: raise RuntimeError("ngspice not found on PATH. Install or pass ngspice= path.")
    self._ngspice = ngspice
    self.work_dir = work_dir or path
    DIR.ensure(self.work_dir)
    self._template = _load_template(name, path, lib)

  def _transform(self, data:dict[str, list[float]]) -> dict[str, list[float]]:
    """`rename`, then `scale`, over raw columns: the cache keeps them raw, so both may change."""
    for old, new in self.rename.items():
      if old.upper() in data: data[new] = data.pop(old.upper())
    for col, factor in self.scale.items():
      if col in data: data[col] = [v * factor for v in data[col]]
    return data

  #------------------------------------------------------------------------------------- Public API

  def run(self, cache:bool=False, **overrides) -> dict[str, list[float]]:
    """
    Run one simulation with `overrides` applied on top of the default params.

    `cache` both reads and writes a CSV keyed by the netlist and the merged parameter values.
    Raises `RuntimeError` when ngspice writes no output or the output cannot be parsed.
    """
    merged = {**self.params, **overrides}
    merged.pop("FILE", None) # the output path of one call, not part of what a run computes
    key = _run_key(merged, self._template)
    csv_path = os.path.join(self.work_dir, f"{self.name}_{key}.csv")
    if cache and os.path.exists(csv_path):
      rows = CSV.load(csv_path)
      if rows:
        if self.verbose: self._print.inf(f"Cache hit: {csv_path}")
        return self._transform({k: [float(r[k]) for r in rows] for k in rows[0]})
    work_id = _work_id(key)
    cir_path = os.path.join(self.work_dir, f"#{work_id}.cir")
    out_path = os.path.join(self.work_dir, f"{self.name}_{work_id}.out")
    FILE.save(cir_path, str(replace_map(self._template, {**merged, "FILE": out_path}, "{", "}")))
    if self.verbose:
      label = ", ".join(f"{k}={v}" for k, v in sorted(merged.items()))
      self._print.run(f"ngspice {self.name} ({label})")
    try: # the work files go on every way out, a timeout included
      result = cmd_run([self._ngspice, "-b", cir_path], capture=True, timeout=self.timeout)
      # ngspice returns non-zero on warnings too, so the output file decides success
      if not os.path.exists(out_path):
        raise RuntimeError(f"ngspice wrote no output (exit {result.returncode}), "
          f"does the .sp run `wrdata {{FILE}} ...`?\n{(result.stderr or '').strip()}")
      try:
        data = parse_output(out_path)
      except ValueError as e:
        raise RuntimeError(f"Failed to parse output: {e}") from e
    finally:
      FILE.remove(cir_path)
      FILE.remove(out_path)
    if self.verbose:
      self._print.ok(f"{self.name} done ({sum(len(v) for v in data.values())} values)")
    if cache:
      n = min(len(v) for v in data.values())
      # a parallel run of the same parameters aims here too, and stores the same rows
      try: CSV.save(csv_path, [{k: v[i] for k, v in data.items()} for i in range(n)])
      except OSError: pass
    return self._transform(data)

  def sweep(
    self,
    cache:bool = True,
    parallel:bool = True,
    max_workers:int|None = None,
    **param_lists,
  ) -> dict[str, dict[str, list[float]]]:
    """
    Run one simulation per value of `param_lists`, results keyed by label in job order.

    Several parameters are zipped, not combined cartesian, so the shortest list wins.
    The label is the bare value for a single parameter, `"R=1k_C=10u"` for several.
    A job that raises is stored as an empty dict, the sweep never aborts.
    `cache` is on here and off in `run()`: a repeated sweep replays CSVs instead of re-simulating,
    and an edited netlist misses them on its own.
    """
    if not param_lists: raise ValueError("No parameters to sweep")
    keys = list(param_lists)
    jobs = []
    for combo in zip(*param_lists.values()):
      overrides = dict(zip(keys, combo))
      if len(keys) == 1: label = str(combo[0])
      else: label = "_".join(f"{k}={v}" for k, v in overrides.items())
      jobs.append((label, overrides))
    if self.verbose: self._print.inf(f"Sweep: {len(jobs)} simulations")
    def attempt(job:tuple[str, dict]) -> dict[str, list[float]]:
      label, overrides = job
      try:
        return self.run(cache=cache, **overrides)
      except Exception as e:
        if self.verbose: self._print.err(f"{label}: {e}")
        return {}
    if parallel and len(jobs) > 1:
      with ThreadPoolExecutor(max_workers=max_workers) as pool:
        return dict(zip((label for label, _ in jobs), pool.map(attempt, jobs)))
    return {job[0]: attempt(job) for job in jobs}

  def __repr__(self) -> str:
    params = ", ".join(f"{k}={v}" for k, v in self.params.items())
    return f"<Simulation {self.name} ({params})>"

#--------------------------------------------------------------------------------------------- Demo

if __name__ == "__main__":
  import tempfile
  print("xaeian.eda.spice - ngspice simulation runner")
  print()
  print("Usage:")
  print('  sim = Simulation("inverter", lib="/opt/spice")')
  print('  data = sim.run(RLOAD="2.2k")')
  print('  results = sim.sweep(RLOAD=["1k", "2.2k", "4.7k"])')
  print()
  # an AC run as ngspice writes it under `wr_singlescale` and `wr_vecnames`
  sample = (
    " frequency       v(out)          v(out)          vdb(out)\n"
    " 1.00000000e+01  9.96067682e-01 -6.25847783e-02 -1.71115043e-02\n"
    " 1.00000000e+02  7.16956800e-01 -4.50477243e-01 -1.44507012e+00\n"
  )
  with tempfile.TemporaryDirectory() as tmp:
    path = os.path.join(tmp, "ac.out")
    FILE.save(path, sample)
    for column, values in parse_output(path).items():
      print(f"  {column}: {values}")
