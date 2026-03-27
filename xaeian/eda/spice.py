# xaeian/spice.py

"""
NgSpice simulation runner with template-based netlists.

Run SPICE simulations from Python: template substitution,
batch execution, ASCII output parsing, CSV caching,
and parallel parametric sweeps.

Requires: `ngspice` binary on PATH (or explicit path).

Example:
  >>> from xaeian.spice import Simulation
  >>> sim = Simulation("inverter", lib="C:/Kicad/Spice")
  >>> data = sim.run(RLOAD="2.2k")
  >>> data["V(OUT)"]  # list[float]

  >>> results = sim.sweep(RLOAD=["1k", "2.2k", "4.7k"])
  >>> for label, d in results.items():
  ...   print(label, len(d["TIME"]))
"""

import os, re, glob
from concurrent.futures import ThreadPoolExecutor, as_completed

from ..cmd import run as cmd_run, which
from ..files import FILE, DIR, CSV
from ..xstring import replace_map
from ..log import Print

#-------------------------------------------------------------------------------- Output parser

def parse_output(path:str) -> dict[str, list[float]]:
  """Parse ngspice ASCII wrdata/print output → `{column: [values]}`.

  Handles two formats:
    - **wrdata**: two-column `index value` lines per variable
    - **print/nutmeg**: header block (Title/Date/Variables/Values)

  Args:
    path: Path to ngspice output file.

  Returns:
    Dict mapping uppercase column names to value lists.

  Raises:
    FileNotFoundError: Output file missing (simulation likely failed).
    ValueError: Cannot parse output format.

  Example:
    >>> data = parse_output("result.out")
    >>> data["V(OUT)"][:3]
    [0.0, 0.0012, 0.0025]
  """
  text = FILE.load(path)
  if not text: raise FileNotFoundError(f"Empty or missing: {path}")
  # Detect format by looking for nutmeg header
  if "Variables:" in text and "Values:" in text:
    return _parse_nutmeg(text)
  return _parse_wrdata(text)

def _parse_wrdata(text:str) -> dict[str, list[float]]:
  """Parse wrdata format: `index  value` per line, blocks separated by blanks."""
  lines = text.strip().splitlines()
  # wrdata: first column = x (sweep var), second = y
  # Multi-variable: separated by blank lines
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
    key = f"col{i}"
    vals = []
    for line in block:
      parts = line.split()
      if len(parts) >= 2:
        try: vals.append(float(parts[1]))
        except ValueError: continue
      elif len(parts) == 1:
        try: vals.append(float(parts[0]))
        except ValueError: continue
    if vals: result[key] = vals
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

#----------------------------------------------------------------------------- Template loading

def _load_template(name:str, path:str, lib:str) -> str:
  """Load .cir template, inline .include directives, append .sp commands.

  Args:
    name: Circuit base name (without extension).
    path: Directory containing circuit files.
    lib: Spice library path (replaces `{LIB}` and `{LSM}`).

  Returns:
    Complete netlist string ready for placeholder substitution.
  """
  cir_file = os.path.join(path, f"{name}.cir")
  cir = FILE.load(cir_file).rstrip()
  if cir.endswith(".end"): cir = cir[:-4]
  # Replace library path placeholders
  cir = cir.replace("{LSM}", lib).replace("{LIB}", lib)
  # Inline .include directives
  for line in cir.splitlines():
    if line.strip().lower().startswith(".include"):
      inc_path = line.split(None, 1)[1].strip('"').strip("'")
      try:
        inc = FILE.load(inc_path).strip()
        cir = cir.replace(line, inc)
      except FileNotFoundError:
        pass  # leave original .include if file not found
  # Append simulation commands (.sp file)
  sp_file = os.path.join(path, f"{name}.sp")
  if os.path.exists(sp_file):
    cir += "\n" + FILE.load(sp_file)
  return cir

#------------------------------------------------------------------------------ Simulation class

class Simulation:
  """NgSpice simulation runner with template substitution and caching.

  Loads `{name}.cir` + `{name}.sp` from `path`, substitutes
  placeholders like `{RLOAD}`, runs ngspice in batch mode,
  parses output → `dict[str, list[float]]`.

  Args:
    name: Circuit name. If `None`, auto-detected from `.cir` in `path`.
    path: Directory with `.cir` and `.sp` files.
    lib: Spice model library path (replaces `{LIB}` in netlist).
    params: Default placeholder values (overridable per run).
    ngspice: Path to ngspice binary (auto-detected if `None`).
    work_dir: Directory for temp files and cache.
    rename: Column rename mapping applied to results.
    scale: Column scale factors applied to results.
    timeout: Simulation timeout in seconds.
    verbose: Print status messages.

  Example:
    >>> sim = Simulation("buck", lib="/opt/spice/lib",
    ...   params={"RLOAD": "10", "CIN": "100u"})
    >>> data = sim.run(RLOAD="22")
    >>> sim.sweep(RLOAD=["10", "22", "47"], cache=True)
  """

  def __init__(
    self,
    name: str|None = None,
    path: str = "./",
    lib: str = "",
    params: dict[str, str]|None = None,
    ngspice: str|None = None,
    work_dir: str|None = None,
    rename: dict[str, str]|None = None,
    scale: dict[str, float]|None = None,
    timeout: int = 300,
    verbose: bool = True,
  ):
    self.path = path
    self.lib = lib
    self.params = params or {}
    self.rename = rename or {}
    self.scale = scale or {}
    self.timeout = timeout
    self.verbose = verbose
    self._print = Print()
    # Auto-detect circuit name from .cir file
    if name is None:
      cir_files = glob.glob(os.path.join(path, "*.cir"))
      if not cir_files: raise FileNotFoundError(f"No .cir files in {path}")
      name = os.path.splitext(os.path.basename(cir_files[0]))[0]
    self.name = name
    # Find ngspice binary
    self._ngspice = ngspice or which("ngspice")
    if not self._ngspice:
      raise RuntimeError("ngspice not found on PATH. Install or pass ngspice= path.")
    # Work directory for temp files
    self.work_dir = work_dir or path
    DIR.ensure(self.work_dir)
    # Load and prepare template
    self._template = _load_template(name, path, lib)

  #----------------------------------------------------------------------------- Internal methods

  def _render(self, run_id:str, **overrides) -> str:
    """Render netlist with placeholder substitution.

    Merges default params with overrides, replaces `{KEY}` patterns,
    and injects output file path as `{FILE}`.
    """
    merged = {**self.params, **overrides}
    out_path = os.path.join(self.work_dir, f"{self.name}_{run_id}.out")
    merged["FILE"] = out_path
    # Build prefix/suffix-free replacement (bare {KEY} style)
    cir = replace_map(self._template, merged, "{", "}")
    return cir

  def _cache_path(self, params:dict) -> str:
    """Deterministic CSV cache path from param values."""
    if params:
      suffix = "_".join(f"{k}={v}" for k, v in sorted(params.items())
        if k != "FILE")
    else:
      suffix = "default"
    return os.path.join(self.work_dir, f"{self.name}_{suffix}.csv")

  def _out_path(self, run_id:str) -> str:
    return os.path.join(self.work_dir, f"{self.name}_{run_id}.out")

  def _cir_path(self, run_id:str) -> str:
    return os.path.join(self.work_dir, f"#{run_id}.cir")

  def _apply_transforms(self, data:dict[str, list[float]]) -> dict[str, list[float]]:
    """Apply rename and scale transforms to result columns."""
    # Rename
    for old, new in self.rename.items():
      old_upper = old.upper()
      if old_upper in data:
        data[new] = data.pop(old_upper)
    # Scale
    for col, factor in self.scale.items():
      if col in data:
        data[col] = [v * factor for v in data[col]]
    return data

  #---------------------------------------------------------------------------------- Public API

  def run(self, cache:bool=False, **overrides) -> dict[str, list[float]]:
    """Run single simulation with given parameter overrides.

    Args:
      cache: Reuse cached CSV if available.
      **overrides: Parameter values overriding defaults.

    Returns:
      Dict mapping column names to value lists.

    Raises:
      RuntimeError: If ngspice fails or output cannot be parsed.

    Example:
      >>> data = sim.run(RLOAD="2.2k", CIN="47u")
      >>> len(data["TIME"])
      1000
    """
    merged = {**self.params, **overrides}
    csv_path = self._cache_path(merged)
    # Check cache
    if cache and os.path.exists(csv_path):
      if self.verbose: self._print.inf(f"Cache hit: {csv_path}")
      rows = CSV.load(csv_path, types={})
      if rows:
        # CSV.load → list[dict] → transpose to dict[str, list]
        result = {k: [r[k] for r in rows] for k in rows[0]}
        # Cast to float
        for k in result:
          result[k] = [float(v) for v in result[k]]
        return result
    # Generate unique run id from params
    run_id = "_".join(f"{k}{v}" for k, v in sorted(merged.items()))
    run_id = re.sub(r'[^\w]', '', run_id)[:80] or "run"
    # Render netlist
    cir_text = self._render(run_id, **overrides)
    cir_path = self._cir_path(run_id)
    out_path = self._out_path(run_id)
    # Clean previous outputs
    FILE.remove(cir_path)
    FILE.remove(out_path)
    # Write netlist
    FILE.save(cir_path, cir_text)
    if self.verbose:
      label = ", ".join(f"{k}={v}" for k, v in sorted(merged.items()) if k != "FILE")
      self._print.run(f"ngspice {self.name} ({label})")
    # Run ngspice in batch mode
    result = cmd_run(
      [self._ngspice, "-b", cir_path],
      capture=True,
    )
    if result.returncode != 0:
      stderr = (result.stderr or "").strip()
      # Don't fail on warnings — ngspice returns non-zero for warnings too
      if not os.path.exists(out_path):
        FILE.remove(cir_path)
        raise RuntimeError(f"ngspice failed (exit {result.returncode}):\n{stderr}")
    # Parse output
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
      # Cleanup temp files
      FILE.remove(cir_path)
      FILE.remove(out_path)
    data = self._apply_transforms(data)
    if self.verbose: self._print.ok(f"{self.name} done ({sum(len(v) for v in data.values())} values)")
    # Cache result
    if cache and data:
      keys = list(data.keys())
      n = len(next(iter(data.values())))
      rows = [{k: data[k][i] for k in keys} for i in range(n)]
      CSV.save(csv_path, rows)
    return data

  def sweep(
    self,
    cache: bool = True,
    parallel: bool = True,
    max_workers: int|None = None,
    **param_lists,
  ) -> dict[str, dict[str, list[float]]]:
    """Run parametric sweep over one or more parameters.

    Each parameter gets a list of values. Runs all combinations
    (single param) or zipped values (multiple params).

    Args:
      cache: Reuse cached CSV files.
      parallel: Run simulations in parallel threads.
      max_workers: Thread pool size (`None` = auto).
      **param_lists: Parameter name → list of values.

    Returns:
      Dict keyed by parameter value (or combo string) → result dict.

    Example:
      >>> results = sim.sweep(RLOAD=["1k", "2.2k", "4.7k"])
      >>> results["2.2k"]["V(OUT)"]
      [0.0, 0.12, ...]

      >>> results = sim.sweep(R=["1k", "2k"], C=["10u", "100u"])
      >>> results["R=1k_C=10u"]["V(OUT)"]
    """
    if not param_lists: raise ValueError("No parameters to sweep")
    # Build list of (label, overrides) pairs
    keys = list(param_lists.keys())
    values_lists = list(param_lists.values())
    # Single param → simple labels; multi param → combo labels
    if len(keys) == 1:
      key = keys[0]
      jobs = [(str(v), {key: v}) for v in values_lists[0]]
    else:
      # Zip values (all lists must be same length)
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

#----------------------------------------------------------------------------------------- Demo

if __name__ == "__main__":
  print("xaeian.spice — NgSpice simulation runner")
  print()
  print("Usage:")
  print('  sim = Simulation("inverter", lib="/opt/spice")')
  print('  data = sim.run(RLOAD="2.2k")')
  print('  results = sim.sweep(RLOAD=["1k", "2.2k", "4.7k"])')
  print()
  # Test parser with synthetic data
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
  # Test wrdata parser
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