# xaeian/eda/spice.py

"""
NgSpice simulation runner with template-based netlists.

Template substitution, batch execution, ASCII output parsing, CSV caching and parallel
parametric sweeps. Requires the `ngspice` binary on PATH or an explicit path.

Example:
  >>> sim = Simulation("inverter", lib="C:/Kicad/Spice")
  >>> data = sim.run(RLOAD="2.2k")
  >>> results = sim.sweep(RLOAD=["1k", "2.2k", "4.7k"])
"""

import os, re, glob
from concurrent.futures import ThreadPoolExecutor, as_completed

from ..cmd import run as cmd_run, which
from ..files import FILE, DIR, CSV
from ..xstring import replace_map
from ..log import Print

#------------------------------------------------------------------------------------ Output parser

def parse_output(path:str) -> dict[str, list[float]]:
  """
  Parse ngspice ASCII wrdata/print output → `{column: [values]}`.

  nutmeg carries variable names in its header → `{"TIME": [...], "V(OUT)": [...]}`.
  wrdata is positional only → `{"x": [...], "col0": [...]}`; use `Simulation.run()`
  to remap those keys onto the signal names taken from the template.
  """
  text = FILE.load(path)
  if not text: raise FileNotFoundError(f"Empty or missing: {path}")
  if "Variables:" in text and "Values:" in text:
    return _parse_nutmeg(text)
  return _parse_wrdata(text)

def _parse_wrdata(text:str) -> dict[str, list[float]]:
  """
  Parse wrdata format: `x y` per line, blocks separated by blanks.

  The x column is taken from the first block only, each block's y-values keyed `col{block}`.
  """
  lines = text.strip().splitlines()
  blocks: list[list[str]] = []
  current: list[str] = []
  for line in lines:
    stripped = line.strip()
    if not stripped:
      if current:
        blocks.append(current)
        current = []
    else:
      current.append(stripped)
  if current: blocks.append(current)
  if not blocks: raise ValueError("No data in wrdata output")
  result: dict[str, list[float]] = {}
  for i, block in enumerate(blocks):
    x_vals = []
    y_vals = []
    for line in block:
      parts = line.split()
      if len(parts) >= 2:
        try:
          x_vals.append(float(parts[0]))
          y_vals.append(float(parts[1]))
        except ValueError: continue
      elif len(parts) == 1:
        try: y_vals.append(float(parts[0]))
        except ValueError: continue
    if i == 0 and x_vals:
      result["x"] = x_vals
    if y_vals: result[f"col{i}"] = y_vals
  return result

def _parse_nutmeg(text:str) -> dict[str, list[float]]:
  """Parse nutmeg ASCII format (Title/Date/Variables/Values blocks)."""
  head: list[str] = []
  data: dict[str, list[float]] = {}
  state = "header"
  idx = 0
  for line in text.splitlines():
    if state == "header":
      if line.strip().startswith("Variables"):
        state = "variables"
    elif state == "variables":
      if line.strip().startswith("Values"):
        state = "values"
        idx = 0
      else:
        parts = line.strip().split()
        if len(parts) >= 2:
          col = parts[1].upper()
          head.append(col)
          data[col] = []
    elif state == "values":
      stripped = line.strip()
      if not stripped: continue
      if idx == 0:
        # First column line: "index  value"
        parts = stripped.split()
        val = parts[1] if len(parts) >= 2 else parts[0]
        try:
          data[head[0]].append(float(val))
          idx = 1
        except (ValueError, IndexError):
          continue
      else:
        try:
          data[head[idx]].append(float(stripped))
          idx += 1
          if idx >= len(head): idx = 0
        except (ValueError, IndexError):
          idx = 0
  return data

#--------------------------------------------------------------------------------- Template loading

def _load_template(name:str, path:str, lib:str) -> str:
  """
  Load `{path}/{name}.cir`, inline its `.include` directives, append `{name}.sp` commands.

  `lib` fills the `{LIB}` and `{LSM}` placeholders. A trailing `.end` is stripped so the
  appended commands stay inside the netlist.
  """
  cir_file = os.path.join(path, f"{name}.cir")
  cir = FILE.load(cir_file).rstrip()
  if cir.endswith(".end"): cir = cir[:-4]
  cir = cir.replace("{LSM}", lib).replace("{LIB}", lib)
  for line in cir.splitlines():
    if line.strip().lower().startswith(".include"):
      inc_path = line.split(None, 1)[1].strip('"').strip("'")
      try:
        inc = FILE.load(inc_path).strip()
        cir = cir.replace(line, inc)
      except FileNotFoundError:
        pass # missing include stays as-is, ngspice may still resolve it
  sp_file = os.path.join(path, f"{name}.sp")
  if os.path.exists(sp_file):
    cir += "\n" + FILE.load(sp_file)
  return cir

#--------------------------------------------------------------------------------- Simulation class

class Simulation:
  """
  Runner bound to one circuit template, with optional CSV caching.

  Loads `{name}.cir` + `{name}.sp` from `path`, substitutes placeholders like `{RLOAD}`,
  runs ngspice in batch mode, parses output → `dict[str, list[float]]`.

  Args:
    name: Circuit name, taken from the first `.cir` found in `path` when `None`.
    path: Directory holding `{name}.cir` and the optional `{name}.sp`.
    lib: Spice model library path, fills `{LIB}` and `{LSM}` in the netlist.
    params: Default placeholder values, overridable per run.
    ngspice: Binary path, resolved from PATH when `None`.
    work_dir: Temp files and cache, defaults to `path`.
    rename: Old → new column names applied to every result.
    scale: Per-column multipliers applied to every result.
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
  ):
    self.path = path
    self.lib = lib
    self.params = params or {}
    self.rename = rename or {}
    self.scale = scale or {}
    self.timeout = timeout
    self.verbose = verbose
    self._print = Print()
    if name is None:
      cir_files = glob.glob(os.path.join(path, "*.cir"))
      if not cir_files: raise FileNotFoundError(f"No .cir files in {path}")
      name = os.path.splitext(os.path.basename(cir_files[0]))[0]
    self.name = name
    self._ngspice = ngspice or which("ngspice")
    if not self._ngspice:
      raise RuntimeError("ngspice not found on PATH. Install or pass ngspice= path.")
    self.work_dir = work_dir or path
    DIR.ensure(self.work_dir)
    self._template = _load_template(name, path, lib)

  #------------------------------------------------------------------------------- Internal methods

  def _render(self, run_id:str, **overrides) -> str:
    """Render netlist: defaults merged with `overrides`, output path injected as `{FILE}`."""
    merged = {**self.params, **overrides}
    out_path = os.path.join(self.work_dir, f"{self.name}_{run_id}.out")
    merged["FILE"] = out_path
    cir = replace_map(self._template, merged, "{", "}")
    return cir

  def _cache_path(self, params:dict) -> str:
    """Deterministic CSV cache path from param values."""
    if params:
      suffix = "_".join(f"{k}={v}" for k, v in sorted(params.items())
        if k != "FILE")
      suffix = re.sub(r'[^\w=.]', '_', suffix)[:120]
    else:
      suffix = "default"
    return os.path.join(self.work_dir, f"{self.name}_{suffix}.csv")

  def _wrdata_vars(self) -> list[str]:
    """Extract variable names from `wrdata {FILE} var1 var2 ...` in template."""
    m = re.search(r'wrdata\s+\{FILE\}\s+(.+)', self._template, re.IGNORECASE)
    if not m: return []
    return [v.strip() for v in m.group(1).split() if v.strip()]

  def _sweep_var(self) -> str:
    """Detect sweep variable name from analysis command."""
    if re.search(r'\.tran\b', self._template, re.IGNORECASE): return "TIME"
    if re.search(r'\.ac\b', self._template, re.IGNORECASE): return "FREQUENCY"
    if re.search(r'\.dc\b', self._template, re.IGNORECASE): return "V-SWEEP"
    return "X"

  def _remap_wrdata(self, data:dict[str, list[float]]) -> dict[str, list[float]]:
    """Remap wrdata `x`/`col0`/`col1` keys to proper signal names."""
    if "col0" not in data: return data
    if "x" in data:
      data[self._sweep_var()] = data.pop("x")
    vars = self._wrdata_vars()
    for i, var_name in enumerate(vars):
      key = f"col{i}"
      if key in data:
        data[var_name.upper()] = data.pop(key)
    return data

  def _out_path(self, run_id:str) -> str:
    return os.path.join(self.work_dir, f"{self.name}_{run_id}.out")

  def _cir_path(self, run_id:str) -> str:
    return os.path.join(self.work_dir, f"#{run_id}.cir")

  def _apply_transforms(self, data:dict[str, list[float]]) -> dict[str, list[float]]:
    """Apply `rename` (its keys uppercased to match parsed columns) then `scale`."""
    for old, new in self.rename.items():
      old_upper = old.upper()
      if old_upper in data:
        data[new] = data.pop(old_upper)
    for col, factor in self.scale.items():
      if col in data:
        data[col] = [v * factor for v in data[col]]
    return data

  #------------------------------------------------------------------------------------- Public API

  def run(self, cache:bool=False, **overrides) -> dict[str, list[float]]:
    """
    Run one simulation with `overrides` applied on top of the default params.

    `cache` both reads and writes a CSV keyed by the merged parameter values.
    Raises `RuntimeError` when ngspice produces no output or the output cannot be parsed.
    """
    merged = {**self.params, **overrides}
    csv_path = self._cache_path(merged)
    if cache and os.path.exists(csv_path):
      if self.verbose: self._print.inf(f"Cache hit: {csv_path}")
      rows = CSV.load(csv_path, types={})
      if rows:
        # CSV.load → list[dict] → transpose to dict[str, list]
        result = {k: [r[k] for r in rows] for k in rows[0]}
        for k in result:
          result[k] = [float(v) for v in result[k]]
        return result
    run_id = "_".join(f"{k}{v}" for k, v in sorted(merged.items()))
    run_id = re.sub(r'[^\w]', '', run_id)[:80] or "run"
    cir_text = self._render(run_id, **overrides)
    cir_path = self._cir_path(run_id)
    out_path = self._out_path(run_id)
    FILE.remove(cir_path)
    FILE.remove(out_path)
    FILE.save(cir_path, cir_text)
    if self.verbose:
      label = ", ".join(f"{k}={v}" for k, v in sorted(merged.items()) if k != "FILE")
      self._print.run(f"ngspice {self.name} ({label})")
    result = cmd_run(
      [self._ngspice, "-b", cir_path],
      capture=True, timeout=self.timeout,
    )
    if result.returncode != 0:
      stderr = (result.stderr or "").strip()
      # ngspice returns non-zero on warnings too, so the output file decides success
      if not os.path.exists(out_path):
        FILE.remove(cir_path)
        raise RuntimeError(f"ngspice failed (exit {result.returncode}):\n{stderr}")
    if not os.path.exists(out_path):
      FILE.remove(cir_path)
      raise RuntimeError(
        f"ngspice produced no output file: {out_path}\n"
        f"Check .sp file has wrdata/write command with {{FILE}}"
      )
    try:
      data = parse_output(out_path)
    except (ValueError, FileNotFoundError) as e:
      raise RuntimeError(f"Failed to parse output: {e}")
    finally:
      FILE.remove(cir_path)
      FILE.remove(out_path)
    data = self._remap_wrdata(data)
    data = self._apply_transforms(data)
    if self.verbose:
      self._print.ok(f"{self.name} done ({sum(len(v) for v in data.values())} values)")
    if cache and data:
      keys = list(data.keys())
      n = len(next(iter(data.values())))
      rows = [{k: data[k][i] for k in keys} for i in range(n)]
      CSV.save(csv_path, rows)
    return data

  def sweep(
    self,
    cache:bool = True,
    parallel:bool = True,
    max_workers:int|None = None,
    **param_lists,
  ) -> dict[str, dict[str, list[float]]]:
    """
    Run one simulation per value of `param_lists`, results keyed by label.

    Several parameters are zipped, not combined cartesian, so the shortest list wins.
    The label is the bare value for a single parameter, `"R=1k_C=10u"` for several.
    A job that raises is stored as an empty dict, the sweep never aborts.
    `cache` is on here and off in `run()`, so a repeated sweep replays CSVs instead of
    re-simulating; pass `cache=False` after editing the netlist.
    """
    if not param_lists: raise ValueError("No parameters to sweep")
    keys = list(param_lists.keys())
    values_lists = list(param_lists.values())
    if len(keys) == 1:
      key = keys[0]
      jobs = [(str(v), {key: v}) for v in values_lists[0]]
    else:
      zipped = list(zip(*values_lists))
      jobs = []
      for combo in zipped:
        overrides = dict(zip(keys, combo))
        label = "_".join(f"{k}={v}" for k, v in overrides.items())
        jobs.append((label, overrides))
    if self.verbose:
      self._print.inf(f"Sweep: {len(jobs)} simulations")
    results: dict[str, dict[str, list[float]]] = {}
    if parallel and len(jobs) > 1:
      with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
          pool.submit(self.run, cache=cache, **overrides): label
          for label, overrides in jobs
        }
        for future in as_completed(futures):
          label = futures[future]
          try:
            results[label] = future.result()
          except Exception as e:
            if self.verbose: self._print.err(f"{label}: {e}")
            results[label] = {}
    else:
      for label, overrides in jobs:
        try:
          results[label] = self.run(cache=cache, **overrides)
        except Exception as e:
          if self.verbose: self._print.err(f"{label}: {e}")
          results[label] = {}
    return results

  def __repr__(self):
    params = ", ".join(f"{k}={v}" for k, v in self.params.items())
    return f"<Simulation {self.name} ({params})>"

#--------------------------------------------------------------------------------------------- Demo

if __name__ == "__main__":
  print("xaeian.eda.spice - NgSpice simulation runner")
  print()
  print("Usage:")
  print('  sim = Simulation("inverter", lib="/opt/spice")')
  print('  data = sim.run(RLOAD="2.2k")')
  print('  results = sim.sweep(RLOAD=["1k", "2.2k", "4.7k"])')
  print()
  test_nutmeg = """Title: Test
Date: Mon Jan 01 00:00:00 2025
Plotname: Transient
Flags: real
No. Variables: 3
No. Points: 4
Variables:
\t0\ttime\ttime
\t1\tv(out)\tvoltage
\t2\ti(vcc)\tcurrent
Values:
0\t0.000000e+00
\t1.200000e+00
\t-5.300000e-03
1\t1.000000e-04
\t2.400000e+00
\t-1.060000e-02
2\t2.000000e-04
\t3.600000e+00
\t-1.590000e-02
3\t3.000000e-04
\t4.800000e+00
\t-2.120000e-02
"""
  data = _parse_nutmeg(test_nutmeg)
  print("Parser test (nutmeg):")
  for k, v in data.items():
    print(f"  {k}: {v}")
  print()
  test_wrdata = """0  0.0
1  1.2
2  2.4
3  3.6

0  -0.0053
1  -0.0106
2  -0.0159
3  -0.0212
"""
  data2 = _parse_wrdata(test_wrdata)
  print("Parser test (wrdata):")
  for k, v in data2.items():
    print(f"  {k}: {v}")