# tests/test_eda_spice.py

"""
`parse_output` against what ngspice really writes, `Simulation` against a stand-in for it.

The samples are `wrdata` output captured from the ngspice KiCad 10 ships,
under the `wr_singlescale` and `wr_vecnames` the runner sets: the file names its own columns.
"""

import re
import pytest
from xaeian.eda import spice

TRAN = """\
 time            v(out)          v(in)
 0.00000000e+00  0.00000000e+00  0.00000000e+00
 1.00000000e-08  9.99990000e-08  1.00000000e-02
 1.08400056e-08  1.09104574e-07  1.08400056e-02
"""

AC = """\
 frequency       v(out)          v(out)          vdb(out)
 1.00000000e+01  9.96067682e-01 -6.25847783e-02 -1.71115043e-02
 1.00000000e+02  7.16956800e-01 -4.50477243e-01 -1.44507012e+00
"""

APPENDED = """\
 v-sweep         v(out)
 0.00000000e+00  0.00000000e+00
 1.00000000e+00  5.00000000e-01
 v-sweep         v(in)
 0.00000000e+00  0.00000000e+00
 1.00000000e+00  1.00000000e+00
"""

UNNAMED = """\
 0.00000000e+00  0.00000000e+00  0.00000000e+00  0.00000000e+00
 1.00000000e-08  9.99990000e-08  1.00000000e-08  1.00000000e-02
"""

class Spice:
  """A class keeps these helpers out of reach of `python_functions = ["*"]` collection."""
  @staticmethod
  def parse(tmp_path, text:str) -> dict:
    out = tmp_path / "run.out"
    out.write_text(text, encoding="utf-8")
    return spice.parse_output(str(out))

  @staticmethod
  def simulation(path, **kw) -> spice.Simulation:
    return spice.Simulation("rc", path=str(path), ngspice="ngspice", verbose=False, **kw)

#------------------------------------------------------------------------------------------ parsing

def every_column_comes_back_under_its_ngspice_name(tmp_path):
  data = Spice.parse(tmp_path, TRAN)
  assert list(data) == ["TIME", "V(OUT)", "V(IN)"]
  assert data["V(IN)"] == [0.0, 0.01, 0.0108400056]

def a_complex_vector_splits_into_real_and_imag(tmp_path):
  data = Spice.parse(tmp_path, AC)
  assert list(data) == ["FREQUENCY", "REAL(V(OUT))", "IMAG(V(OUT))", "VDB(OUT)"]
  assert data["IMAG(V(OUT))"][0] == pytest.approx(-6.25847783e-02)

def appended_blocks_add_their_columns_once(tmp_path):
  data = Spice.parse(tmp_path, APPENDED)
  assert list(data) == ["V-SWEEP", "V(OUT)", "V(IN)"]
  assert data["V-SWEEP"] == [0.0, 1.0] and data["V(IN)"] == [0.0, 1.0]

def output_without_names_is_refused(tmp_path):
  """Unnamed, the scale repeats beside every vector, and guessing which is which loses data."""
  with pytest.raises(ValueError, match="wr_vecnames"):
    Spice.parse(tmp_path, UNNAMED)

#------------------------------------------------------------------------------------------ running

class Done:
  returncode = 0
  stderr = ""

@pytest.fixture
def circuit(tmp_path, monkeypatch):
  """`rc.cir` and `rc.sp` on disk, and an ngspice stand-in that writes `TRAN` where told."""
  (tmp_path / "models").mkdir()
  (tmp_path / "models" / "r.lib").write_text(".model RMOD R\n", encoding="utf-8")
  (tmp_path / "rc.cir").write_text(
    "* rc\n.include models/r.lib\nR1 in out {RLOAD}\nC1 out 0 1u\n.end\n", encoding="utf-8")
  (tmp_path / "rc.sp").write_text(
    ".control\ntran 1u 1m\nwrdata {FILE} v(out) v(in)\n.endc\n", encoding="utf-8")
  netlists = []
  def ngspice(args, capture=True, timeout=None):
    netlist = open(args[2], encoding="utf-8").read()
    netlists.append(netlist)
    out = re.search(r"wrdata (\S+)", netlist).group(1)
    open(out, "w", encoding="utf-8").write(TRAN)
    return Done()
  monkeypatch.setattr(spice, "cmd_run", ngspice)
  return tmp_path, netlists

def a_run_renders_the_netlist_and_reads_the_named_columns(circuit):
  path, netlists = circuit
  sim = Spice.simulation(path, rename={"v(out)": "vout"}, scale={"vout": 1000})
  data = sim.run(RLOAD="2.2k")
  assert set(data) == {"TIME", "vout", "V(IN)"}
  assert data["vout"][1] == pytest.approx(9.9999e-05)
  netlist = netlists[0]
  assert "R1 in out 2.2k" in netlist
  assert ".model RMOD R" in netlist # the include resolved against the template's directory
  assert "set wr_vecnames" in netlist.split(".control", 1)[1]
  assert list(path.glob("#*.cir")) == [] and list(path.glob("*.out")) == []

def the_cache_keeps_raw_columns_and_misses_an_edited_netlist(circuit):
  path, netlists = circuit
  sim = Spice.simulation(path)
  sim.run(cache=True, RLOAD="1k")
  sim.run(cache=True, RLOAD="1k")
  assert len(netlists) == 1 # the second one replayed the CSV
  sim.rename = {"v(out)": "vout"}
  assert "vout" in sim.run(cache=True, RLOAD="1k") # a transform set later still applies
  (path / "rc.cir").write_text("* rc\nR1 in out {RLOAD}\nC1 out 0 2u\n", encoding="utf-8")
  Spice.simulation(path).run(cache=True, RLOAD="1k")
  assert len(netlists) == 2 # an edited netlist does not replay the old result

def a_run_without_output_says_what_the_sp_lacks(circuit, monkeypatch):
  path, _ = circuit
  monkeypatch.setattr(spice, "cmd_run", lambda args, **kw: Done())
  with pytest.raises(RuntimeError, match="wrdata"):
    Spice.simulation(path).run(RLOAD="1k")
  assert list(path.glob("#*.cir")) == []

def a_sweep_keeps_job_order_and_survives_a_failing_run(circuit, monkeypatch):
  path, _ = circuit
  sim = Spice.simulation(path)
  real = sim.run
  def run(cache=False, **overrides):
    if overrides["RLOAD"] == "2k": raise RuntimeError("no convergence")
    return real(cache=cache, **overrides)
  monkeypatch.setattr(sim, "run", run)
  results = sim.sweep(cache=False, RLOAD=["1k", "2k", "3k"])
  assert list(results) == ["1k", "2k", "3k"]
  assert results["2k"] == {} and "TIME" in results["3k"]

def two_circuits_in_one_folder_need_a_name(circuit):
  path, _ = circuit
  (path / "other.cir").write_text("* other\n", encoding="utf-8")
  with pytest.raises(ValueError, match="name="):
    spice.Simulation(path=str(path), ngspice="ngspice", verbose=False)

#----------------------------------------------------------------------------------------- run keys

def a_run_key_tells_apart_pairs_a_naive_key_would_merge():
  """
  Each pair would share one cache file, and a sweep would read back another point's result.

  Dropping a dot merges `2.2k` with `22k`, dropping a character merges `a+b` with `ab`,
  and joining a key straight onto its value lets the value swallow the next key.
  """
  for a, b in [
    ({"RLOAD": "2.2k"}, {"RLOAD": "22k"}),
    ({"X": "a+b"}, {"X": "ab"}),
    ({"AB": "C"}, {"A": "BC"}),
    ({"R": "1k", "S": "2k"}, {"R": "1k_S2k"}),
    ({"A": "B_C"}, {"A": "B", "C": ""}),
    ({}, {"": ""}),
  ]:
    assert spice._run_key(a) != spice._run_key(b), f"{a} and {b} share a key"

def a_run_key_is_the_same_every_time_and_fits_a_filename():
  key = spice._run_key
  assert key({"R": "1k"}) == key({"R": "1k"})
  assert key({"A": 1, "B": 2}) == key({"B": 2, "A": 1}) # order is not identity
  assert len(key({f"P{i:02}": "v" * 10 for i in range(12)})) <= 80

def parallel_runs_of_one_parameter_set_never_share_a_working_file():
  """The cache is keyed by parameters, so two identical runs would meet over one `.cir`."""
  key = spice._run_key({"R": "1k"})
  assert len({spice._work_id(key) for _ in range(100)}) == 100
